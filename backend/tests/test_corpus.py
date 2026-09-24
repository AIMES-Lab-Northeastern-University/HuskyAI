"""Phase 2: the per-assignment reference corpus.

The highest-risk change in this phase is the evaluator refactor, because the
evaluator scores every turn in the product. So the first tests here are not
about corpora at all — they assert that an assignment WITHOUT one takes an
identical path through identical objects.
"""

import asyncio
import io
import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def app_ready():
    from database import init_db
    from main import app

    asyncio.run(init_db())
    return app


def _token(uid):
    from auth import create_token
    return create_token(uid)


async def _assignment():
    """An instructor with one section and one assigned challenge.
    Returns (instructor_id, classroom_challenge_id, classroom_id, challenge_id)."""
    from database import (AsyncSessionLocal, Challenge, Classroom, ClassroomChallenge,
                          ClassroomMembership, User)

    async with AsyncSessionLocal() as db:
        inst = User(email=f"ci_{uuid.uuid4().hex[:8]}@e.com", name="Inst", password_hash="x")
        db.add(inst); await db.flush()
        room = Classroom(name="Corpus Sec", join_code=uuid.uuid4().hex[:8].upper(),
                         instructor_user_id=inst.id)
        ch = Challenge(title="Corpus Challenge", description="d", category="c",
                       difficulty="easy", sessions_data=[{"title": "S", "goal": "g",
                                                          "brief": "b", "seed_question": "q"}])
        db.add_all([room, ch]); await db.flush()
        db.add(ClassroomMembership(user_id=inst.id, classroom_id=room.id, role="instructor"))
        cc = ClassroomChallenge(classroom_id=room.id, challenge_id=ch.id)
        db.add(cc); await db.commit()
        return inst.id, cc.id, room.id, ch.id


# ── The regression that matters most ─────────────────────────────────────────

def test_without_a_corpus_the_panel_is_the_untouched_module_agents():
    """Not equivalent copies — the SAME objects. If this ever returns clones,
    every historical score becomes incomparable with new ones for reasons no
    one will think to look for."""
    import evaluator_v3 as ev

    panel = ev._agents_for(None)
    assert panel["psq"] is ev.psq_judge
    assert panel["ccm"] is ev.ccm_judge
    assert panel["tsi"] is ev.tsi_judge
    assert panel["clm"] is ev.clm_judge
    assert panel["ras"] is ev.ras_judge
    assert panel["domain"] is ev.domain_detector
    assert panel["feedback"] is ev.feedback_writer
    assert panel["grounding"] is None, "no grounding judge without ground truth"


def test_with_a_corpus_the_judges_search_both_stores():
    """The rubric still defines what good prompting looks like; the corpus adds
    what the answer should contain."""
    import evaluator_v3 as ev

    panel = ev._agents_for("vs_test_corpus")
    stores = panel["psq"].tools[0].vector_store_ids
    assert ev._VECTOR_STORE_ID in stores
    assert "vs_test_corpus" in stores
    assert panel["psq"] is not ev.psq_judge, "must not mutate the shared judge"
    assert ev.psq_judge.tools[0].vector_store_ids == [ev._VECTOR_STORE_ID], \
        "the module-level judge must be left alone"


def test_the_grounding_judge_searches_only_the_corpus():
    """Mixing the rubric in would let a rhetorically well-formed answer score
    well on grounding without matching the source material."""
    import evaluator_v3 as ev

    panel = ev._agents_for("vs_only_me")
    assert panel["grounding"].tools[0].vector_store_ids == ["vs_only_me"]


def test_the_panel_is_memoised_per_corpus():
    """Clone cost is paid once per process, not once per turn."""
    import evaluator_v3 as ev

    a = ev._agents_for("vs_memo")
    b = ev._agents_for("vs_memo")
    assert a is b
    assert ev._agents_for("vs_other") is not a


# ── Resolution: a corpus is only used when it is ready ───────────────────────

def test_no_corpus_resolves_to_none(app_ready):
    from corpus import resolve_corpus_store

    _, _, room_id, ch_id = asyncio.run(_assignment())
    assert asyncio.run(resolve_corpus_store(room_id, ch_id)) is None


def test_a_building_corpus_is_not_used_for_scoring(app_ready):
    """A half-indexed corpus degrades to rubric-only rather than silently
    grading students against a partial set of documents."""
    from corpus import resolve_corpus_store
    from database import AsyncSessionLocal, ClassroomChallenge, ReferenceCorpus

    inst, cc_id, room_id, ch_id = asyncio.run(_assignment())

    async def attach(status):
        async with AsyncSessionLocal() as db:
            c = ReferenceCorpus(classroom_challenge_id=cc_id, name="C",
                                created_by_user_id=inst, status=status,
                                openai_vector_store_id="vs_partial")
            db.add(c); await db.flush()
            cc = await db.get(ClassroomChallenge, cc_id)
            cc.reference_corpus_id = c.id
            await db.commit()
            return c.id

    cid = asyncio.run(attach("building"))
    assert asyncio.run(resolve_corpus_store(room_id, ch_id)) is None

    async def mark(status):
        async with AsyncSessionLocal() as db:
            c = await db.get(ReferenceCorpus, cid)
            c.status = status
            await db.commit()

    asyncio.run(mark("failed"))
    assert asyncio.run(resolve_corpus_store(room_id, ch_id)) is None

    asyncio.run(mark("ready"))
    assert asyncio.run(resolve_corpus_store(room_id, ch_id)) == "vs_partial"


# ── The API ──────────────────────────────────────────────────────────────────

def test_only_a_section_instructor_can_manage_a_corpus(app_ready):
    from database import AsyncSessionLocal, User

    _, cc_id, _, _ = asyncio.run(_assignment())

    async def outsider():
        async with AsyncSessionLocal() as db:
            u = User(email=f"o_{uuid.uuid4().hex[:8]}@e.com", name="O", password_hash="x")
            db.add(u); await db.commit()
            return u.id

    stranger = asyncio.run(outsider())
    client = TestClient(app_ready)
    r = client.post(f"/corpus/assignments/{cc_id}",
                    headers={"Authorization": f"Bearer {_token(stranger)}"})
    assert r.status_code == 403


def test_creating_a_corpus_attaches_it_to_the_assignment(app_ready):
    from database import AsyncSessionLocal, ClassroomChallenge

    inst, cc_id, _, _ = asyncio.run(_assignment())
    client = TestClient(app_ready)

    r = client.post(f"/corpus/assignments/{cc_id}?name=Ground+truth",
                    headers={"Authorization": f"Bearer {_token(inst)}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "building"
    assert body["documents"] == []

    async def linked():
        async with AsyncSessionLocal() as db:
            cc = await db.get(ClassroomChallenge, cc_id)
            return cc.reference_corpus_id

    assert asyncio.run(linked()) == body["id"]

    # Idempotent: a second create returns the same corpus rather than orphaning one.
    again = client.post(f"/corpus/assignments/{cc_id}",
                        headers={"Authorization": f"Bearer {_token(inst)}"})
    assert again.json()["id"] == body["id"]


def test_unindexable_uploads_are_rejected_not_silently_skipped(app_ready):
    """Accepting a file the ingester cannot read would show the instructor a
    corpus that looks complete and scores against less than they uploaded."""
    inst, cc_id, _, _ = asyncio.run(_assignment())
    client = TestClient(app_ready)
    hdr = {"Authorization": f"Bearer {_token(inst)}"}
    corpus_id = client.post(f"/corpus/assignments/{cc_id}", headers=hdr).json()["id"]

    r = client.post(f"/corpus/{corpus_id}/documents", headers=hdr,
                    files={"file": ("slides.pptx", io.BytesIO(b"binary"),
                                    "application/vnd.openxmlformats-officedocument.presentationml.presentation")})
    assert r.status_code == 415
    assert "cannot be indexed" in r.json()["detail"]


def test_an_empty_upload_is_rejected(app_ready):
    inst, cc_id, _, _ = asyncio.run(_assignment())
    client = TestClient(app_ready)
    hdr = {"Authorization": f"Bearer {_token(inst)}"}
    corpus_id = client.post(f"/corpus/assignments/{cc_id}", headers=hdr).json()["id"]

    r = client.post(f"/corpus/{corpus_id}/documents", headers=hdr,
                    files={"file": ("empty.txt", io.BytesIO(b""), "text/plain")})
    assert r.status_code == 400


def test_detaching_keeps_the_rows_and_falls_back_to_rubric_only(app_ready):
    """Past EvalResults cite grounding scores that came from this corpus;
    deleting it would orphan the evidence behind a published number."""
    from corpus import resolve_corpus_store
    from database import AsyncSessionLocal, ReferenceCorpus

    inst, cc_id, room_id, ch_id = asyncio.run(_assignment())
    client = TestClient(app_ready)
    hdr = {"Authorization": f"Bearer {_token(inst)}"}
    corpus_id = client.post(f"/corpus/assignments/{cc_id}", headers=hdr).json()["id"]

    async def mark_ready():
        async with AsyncSessionLocal() as db:
            c = await db.get(ReferenceCorpus, corpus_id)
            c.status = "ready"
            c.openai_vector_store_id = "vs_live"
            await db.commit()

    asyncio.run(mark_ready())
    assert asyncio.run(resolve_corpus_store(room_id, ch_id)) == "vs_live"

    r = client.delete(f"/corpus/{corpus_id}", headers=hdr)
    assert r.status_code == 200
    assert asyncio.run(resolve_corpus_store(room_id, ch_id)) is None

    async def still_there():
        async with AsyncSessionLocal() as db:
            return await db.get(ReferenceCorpus, corpus_id)

    assert asyncio.run(still_there()) is not None, "the corpus row must survive detaching"
