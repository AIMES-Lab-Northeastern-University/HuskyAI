"""Per-turn research-consent snapshot: the export must include only the turns
the student consented to at the time they were scored — even within one student."""

from database import (
    AsyncSessionLocal, Base, engine, User, Conversation, Message, EvalResult,
)
from admin import _gather_export_rows


async def _seed():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as db:
        u = User(email="stu@northeastern.edu", name="Test Student",
                 password_hash="x", consent_research=False)
        db.add(u)
        await db.flush()
        conv = Conversation(user_id=u.id, turn_count=2)
        db.add(conv)
        await db.flush()
        # Two turns: turn 1 scored while consented, turn 2 after opting out.
        for role, n in (("user", 1), ("assistant", 1), ("user", 2), ("assistant", 2)):
            db.add(Message(conversation_id=conv.id, role=role, content=f"{role} msg {n}"))
        db.add(EvalResult(conversation_id=conv.id, turn_number=1, pei=70.0,
                          full_result={"scores": {"PEI": 70}}, consent_research=True))
        db.add(EvalResult(conversation_id=conv.id, turn_number=2, pei=40.0,
                          full_result={"scores": {"PEI": 40}}, consent_research=False))
        await db.commit()
        return conv.id


async def test_export_consent_only_filters_per_turn():
    await _seed()
    async with AsyncSessionLocal() as db:
        all_rows = await _gather_export_rows(db, consent_only=False)
        consented = await _gather_export_rows(db, consent_only=True)

    # Both turns export when not filtering.
    assert {r["turn"] for r in all_rows} >= {1, 2}
    # Only the consented turn survives the filter — the same student's later,
    # post-withdrawal turn is excluded.
    consented_turns = [r for r in consented if r["pei"] in (70.0, 40.0)]
    assert all(r["turn"] == 1 for r in consented_turns)
    assert any(r["turn"] == 1 for r in consented_turns)
    assert not any(r["turn"] == 2 and r["pei"] == 40.0 for r in consented)
