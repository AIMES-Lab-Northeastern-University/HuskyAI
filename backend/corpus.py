"""Per-assignment reference corpus: upload, ingest, and resolve.

An instructor attaches ground-truth material to one assignment; the evaluator
then scores student work against it (see evaluator_v3._agents_for).

Two properties are load-bearing:

- **A corpus is only used once `status == "ready"`.** A half-indexed corpus
  degrades to rubric-only scoring rather than silently grading students against
  a partial set of documents, which would look like a scoring change rather than
  an ingestion bug.
- **Bytes are kept in the database**, mirroring the Attachment table. The deploy
  target has an ephemeral filesystem, and keeping them means a corpus can be
  re-ingested into a fresh vector store without asking the instructor to
  re-upload.
"""

from __future__ import annotations

import asyncio
import io
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import coordination
from challenges import get_current_user, get_db
from classrooms import _assert_can_manage_classroom
from database import (AsyncSessionLocal, Classroom, ClassroomChallenge, CorpusDocument,
                      ReferenceCorpus)

log = logging.getLogger("corpus")

router = APIRouter(prefix="/corpus", tags=["corpus"])

# Same caps as chat attachments, for the same reason: an instructor uploading a
# 200MB scan should get a clear error, not a silent timeout during ingestion.
MAX_DOC_BYTES = 20 * 1024 * 1024
MAX_DOCS_PER_CORPUS = 40

# What the OpenAI file-search ingester can actually read. Anything else is
# rejected at upload rather than accepted and quietly skipped at index time.
INDEXABLE_MIME_PREFIXES = ("text/", "application/pdf", "application/json")
INDEXABLE_EXTENSIONS = (".txt", ".md", ".pdf", ".json", ".csv", ".docx")


def _is_indexable(filename: str, mime: str) -> bool:
    lower = (filename or "").lower()
    return (
        any(mime.startswith(p) for p in INDEXABLE_MIME_PREFIXES)
        or lower.endswith(INDEXABLE_EXTENSIONS)
    )


async def _assert_can_manage_assignment(db: AsyncSession, user_id: str, cc_id: str
                                        ) -> ClassroomChallenge:
    cc = await db.get(ClassroomChallenge, cc_id)
    if cc is None:
        raise HTTPException(status_code=404, detail="Assignment not found")
    room = await db.get(Classroom, cc.classroom_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Section not found")
    await _assert_can_manage_classroom(db, user_id, room)
    return cc


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


def _openai_client():
    """One place to build the client, so tests can stub every OpenAI call."""
    import openai

    return openai.AsyncOpenAI()


# Strong references to running ingests (asyncio keeps only weak ones, so an
# un-referenced task can be collected mid-upload), and at most one per corpus
# in this process. An upload that arrives while one is running just asks it to
# go round again rather than starting a second job over the same documents.
_ingest_tasks: dict[str, asyncio.Task] = {}
_ingest_again: set[str] = set()


def schedule_ingest(corpus_id: str) -> None:
    running = _ingest_tasks.get(corpus_id)
    if running is not None and not running.done():
        _ingest_again.add(corpus_id)
        return
    task = asyncio.create_task(_ingest_loop(corpus_id))
    _ingest_tasks[corpus_id] = task

    def _done(t, cid=corpus_id):
        if _ingest_tasks.get(cid) is t:
            _ingest_tasks.pop(cid, None)

    task.add_done_callback(_done)


async def _ingest_loop(corpus_id: str) -> None:
    while True:
        _ingest_again.discard(corpus_id)
        await _ingest_corpus(corpus_id)
        if corpus_id not in _ingest_again:
            return


async def _ensure_store(client, corpus_id: str) -> str | None:
    """The corpus's vector store id, creating it at most once.

    The id is set with a conditional UPDATE (only while still NULL), so if two
    ingests race — two uploads, or two workers — exactly one store is kept and
    the loser deletes the one it made instead of orphaning it and splitting the
    corpus's documents across two stores."""
    async with AsyncSessionLocal() as db:
        c = await db.get(ReferenceCorpus, corpus_id)
        if c is None:
            return None
        if c.openai_vector_store_id:
            return c.openai_vector_store_id
    store = await client.vector_stores.create(name=f"huskyai-corpus-{corpus_id[:8]}")
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            update(ReferenceCorpus)
            .where(ReferenceCorpus.id == corpus_id, ReferenceCorpus.openai_vector_store_id.is_(None))
            .values(openai_vector_store_id=store.id)
        )
        await db.commit()
        if res.rowcount == 1:
            return store.id
        winner = (await db.get(ReferenceCorpus, corpus_id)).openai_vector_store_id
    try:
        await client.vector_stores.delete(store.id)
    except Exception as e:
        log.warning(f"corpus {corpus_id[:8]}: could not delete duplicate store {store.id}: {e}")
    return winner


async def _claim(doc_id: str) -> bool:
    """Take one document for indexing. The status moves pending/failed ->
    indexing in a single conditional UPDATE, so no two ingests (in this process
    or another worker) upload the same file."""
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            update(CorpusDocument)
            .where(CorpusDocument.id == doc_id, CorpusDocument.status.in_(("pending", "failed")))
            .values(status="indexing")
        )
        await db.commit()
        return res.rowcount == 1


async def _refresh_corpus_status(db, corpus_id: str) -> None:
    corpus = await db.get(ReferenceCorpus, corpus_id)
    if corpus is None:
        return
    docs = (await db.execute(
        select(CorpusDocument.status).where(CorpusDocument.corpus_id == corpus_id)
    )).scalars().all()
    if any(st == "ready" for st in docs):
        # Ready if ANY document indexed: a corpus with one bad PDF is still
        # useful ground truth, and the per-document status makes the gap
        # visible to the instructor.
        corpus.status, corpus.error = "ready", None
    elif any(st in ("pending", "indexing") for st in docs) or not docs:
        # Still settling, or empty (an empty corpus waits at "building" for
        # its first upload, and is never used for scoring).
        corpus.status = "building"
    else:
        corpus.status, corpus.error = "failed", "no document could be indexed"


async def _ingest_corpus(corpus_id: str) -> None:
    """Upload every pending document to OpenAI and attach it to this corpus's
    own vector store.

    Runs as a background task. Never raises: a failure marks the corpus `failed`
    with the reason, and the evaluator carries on rubric-only. Breaking a
    student's turn because an instructor's PDF would not index is the wrong
    trade in every case.
    """
    client = _openai_client()
    claimed: list[str] = []
    try:
        async with AsyncSessionLocal() as db:
            if await db.get(ReferenceCorpus, corpus_id) is None:
                return
            candidates = [d for (d,) in (await db.execute(
                select(CorpusDocument.id).where(
                    CorpusDocument.corpus_id == corpus_id,
                    CorpusDocument.status.in_(("pending", "failed")),
                )
            )).all()]
        if not candidates:
            async with AsyncSessionLocal() as db:
                await _refresh_corpus_status(db, corpus_id)
                await db.commit()
            return

        store_id = await _ensure_store(client, corpus_id)
        if store_id is None:
            return

        for doc_id in candidates:
            # The lease is taken BEFORE the status moves to "indexing", so a
            # document at "indexing" whose lease has lapsed really was
            # abandoned -- which is what release_stranded_claims relies on to
            # leave a live worker's ingest alone.
            lease = await coordination.acquire(f"corpus_doc:{doc_id}")
            if lease is None:
                continue        # a live worker is indexing it
            try:
                if not await _claim(doc_id):
                    continue        # another ingest has it
                claimed.append(doc_id)
                async with AsyncSessionLocal() as db:
                    d = await db.get(CorpusDocument, doc_id)
                    if d is None:
                        continue    # deleted after the claim
                    filename, data = d.filename, d.data
                try:
                    uploaded = await client.files.create(
                        file=(filename, io.BytesIO(data)), purpose="assistants"
                    )
                    await client.vector_stores.files.create_and_poll(
                        vector_store_id=store_id, file_id=uploaded.id
                    )
                    new_status, file_id = "ready", uploaded.id
                except Exception as e:
                    log.error(f"corpus {corpus_id[:8]} doc {filename!r} failed: {e}")
                    new_status, file_id = "failed", None
                async with AsyncSessionLocal() as db:
                    d = await db.get(CorpusDocument, doc_id)
                    if d:
                        d.status = new_status
                        d.openai_file_id = file_id
                        await db.commit()
            finally:
                await lease.release()

        async with AsyncSessionLocal() as db:
            await _refresh_corpus_status(db, corpus_id)
            await db.commit()
    except Exception as e:
        log.error(f"corpus {corpus_id[:8]} ingestion failed: {type(e).__name__}: {e}")
        try:
            async with AsyncSessionLocal() as db:
                # Documents THIS run had claimed and not finished go back to
                # failed, so the next upload (or a retry) can pick them up
                # instead of them sitting at "indexing" forever. Only ours: a
                # document another worker is indexing right now is left alone.
                if claimed:
                    await db.execute(
                        update(CorpusDocument)
                        .where(CorpusDocument.id.in_(claimed), CorpusDocument.status == "indexing")
                        .values(status="failed")
                    )
                c = await db.get(ReferenceCorpus, corpus_id)
                if c:
                    c.status = "failed"
                    c.error = str(e)[:500]
                await db.commit()
        except Exception:
            pass


async def release_stranded_claims() -> int:
    """Startup: documents left at "indexing" by a process that died mid-ingest
    (a redeploy) go back to failed, so they can be retried or deleted and the
    corpus stops showing as building forever.

    Only documents no live worker holds the lease for: with several workers, a
    sibling may be indexing right now, and a restarting worker must not fail
    its document out from under it. Without Redis there is one worker and no
    lease can be live, so every "indexing" row is released, as before. If
    Redis cannot be asked, nothing is released -- a document wrongly marked
    failed is worse than one left at "indexing" until the next check."""
    try:
        async with AsyncSessionLocal() as db:
            stuck = [d for (d,) in (await db.execute(
                select(CorpusDocument.id).where(CorpusDocument.status == "indexing")
            )).all()]
        if not stuck:
            return 0
        abandoned: list[str] = []
        for doc_id in stuck:
            held = await coordination.is_held(f"corpus_doc:{doc_id}")
            if held is None:
                log.error(f"could not check corpus leases; leaving {len(stuck)} document(s) "
                          "at 'indexing' for now")
                return 0
            if not held:
                abandoned.append(doc_id)
        if not abandoned:
            return 0
        async with AsyncSessionLocal() as db:
            res = await db.execute(
                update(CorpusDocument)
                .where(CorpusDocument.id.in_(abandoned), CorpusDocument.status == "indexing")
                .values(status="failed")
            )
            ids = [c for (c,) in (await db.execute(
                select(CorpusDocument.corpus_id).where(CorpusDocument.id.in_(abandoned)).distinct()
            )).all()] if res.rowcount else []
            for cid in ids:
                await _refresh_corpus_status(db, cid)
            await db.commit()
            if res.rowcount:
                log.warning(f"released {res.rowcount} corpus document(s) stranded at 'indexing'")
            return res.rowcount or 0
    except Exception as e:
        log.error(f"could not release stranded corpus claims: {e}")
        return 0


_recheck_tasks: set = set()


def schedule_stranded_recheck() -> None:
    """Startup, with several workers: check again once every lease a dead
    process could have left behind has lapsed. On a redeploy the old workers'
    leases are still live for up to LEASE_TTL_SEC when the new ones boot, so
    the first check leaves their documents alone; this one releases them."""
    if not coordination.enabled():
        return

    async def _later():
        await asyncio.sleep(coordination.LEASE_TTL_SEC + 5)
        await release_stranded_claims()

    task = asyncio.create_task(_later())
    _recheck_tasks.add(task)
    task.add_done_callback(_recheck_tasks.discard)


def cancel_stranded_recheck() -> None:
    """Shutdown: drop a recheck that has not run yet (the next boot does its own)."""
    for task in list(_recheck_tasks):
        task.cancel()


# ---------------------------------------------------------------------------
# Resolution (used by the turn paths)
# ---------------------------------------------------------------------------


async def resolve_corpus_store(classroom_id: str | None, challenge_id: str | None) -> str | None:
    """The vector store the evaluator should additionally search, or None.

    Returns None unless a corpus is attached AND ready, so a building or failed
    corpus degrades to exactly today's behaviour."""
    if not classroom_id or not challenge_id:
        return None
    try:
        async with AsyncSessionLocal() as db:
            cc = (await db.execute(
                select(ClassroomChallenge).where(
                    ClassroomChallenge.classroom_id == classroom_id,
                    ClassroomChallenge.challenge_id == challenge_id,
                )
            )).scalar_one_or_none()
            if cc is None or not cc.reference_corpus_id:
                return None
            corpus = await db.get(ReferenceCorpus, cc.reference_corpus_id)
            if corpus is None or corpus.status != "ready":
                return None
            return corpus.openai_vector_store_id
    except Exception as e:
        log.error(f"could not resolve corpus: {e}")
        return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/assignments/{classroom_challenge_id}")
async def create_corpus(
    classroom_challenge_id: str,
    name: str = "Reference corpus",
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create (or return) this assignment's corpus."""
    cc = await _assert_can_manage_assignment(db, user_id, classroom_challenge_id)
    if cc.reference_corpus_id:
        existing = await db.get(ReferenceCorpus, cc.reference_corpus_id)
        if existing is not None:
            return _corpus_payload(existing, [])

    corpus = ReferenceCorpus(
        classroom_challenge_id=cc.id, name=name[:200],
        created_by_user_id=user_id, status="building",
    )
    db.add(corpus)
    await db.flush()
    cc.reference_corpus_id = corpus.id
    await db.commit()
    return _corpus_payload(corpus, [])


@router.post("/{corpus_id}/documents")
async def upload_document(
    corpus_id: str,
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    corpus = await db.get(ReferenceCorpus, corpus_id)
    if corpus is None:
        raise HTTPException(status_code=404, detail="Corpus not found")
    await _assert_can_manage_assignment(db, user_id, corpus.classroom_challenge_id)

    count = len((await db.execute(
        select(CorpusDocument.id).where(CorpusDocument.corpus_id == corpus_id)
    )).all())
    if count >= MAX_DOCS_PER_CORPUS:
        raise HTTPException(status_code=413, detail=f"At most {MAX_DOCS_PER_CORPUS} documents")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > MAX_DOC_BYTES:
        raise HTTPException(status_code=413, detail="File too large (20MB max)")
    mime = file.content_type or "application/octet-stream"
    if not _is_indexable(file.filename or "", mime):
        raise HTTPException(
            status_code=415,
            detail=f"{file.filename!r} cannot be indexed. Use text, markdown, PDF, CSV, JSON or DOCX.",
        )

    doc = CorpusDocument(
        corpus_id=corpus_id, filename=(file.filename or "file")[:512],
        mime_type=mime[:255], size_bytes=len(data), data=data,
        uploaded_by_user_id=user_id, status="pending",
    )
    db.add(doc)
    corpus.status = "building"
    corpus.error = None
    await db.commit()

    schedule_ingest(corpus_id)
    return {"id": doc.id, "filename": doc.filename, "status": doc.status}


@router.get("/{corpus_id}")
async def get_corpus(
    corpus_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    corpus = await db.get(ReferenceCorpus, corpus_id)
    if corpus is None:
        raise HTTPException(status_code=404, detail="Corpus not found")
    await _assert_can_manage_assignment(db, user_id, corpus.classroom_challenge_id)
    docs = (await db.execute(
        select(CorpusDocument).where(CorpusDocument.corpus_id == corpus_id)
        .order_by(CorpusDocument.created_at)
    )).scalars().all()
    return _corpus_payload(corpus, docs)


@router.delete("/{corpus_id}/documents/{document_id}")
async def delete_document(
    corpus_id: str,
    document_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    corpus = await db.get(ReferenceCorpus, corpus_id)
    if corpus is None:
        raise HTTPException(status_code=404, detail="Corpus not found")
    await _assert_can_manage_assignment(db, user_id, corpus.classroom_challenge_id)
    doc = await db.get(CorpusDocument, document_id)
    if doc is None or doc.corpus_id != corpus_id:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.status == "indexing":
        raise HTTPException(status_code=409, detail="This document is being indexed. Try again in a moment.")

    # Remove it from the search index FIRST. Deleting the row first used to
    # leave the file in the vector store, so the evaluator kept grading
    # students against a document the instructor had removed and could no
    # longer see. If OpenAI cannot be reached the row stays listed, so the
    # instructor sees it is still in use and can try again.
    if doc.openai_file_id:
        import openai

        client = _openai_client()
        try:
            if corpus.openai_vector_store_id:
                try:
                    await client.vector_stores.files.delete(
                        doc.openai_file_id, vector_store_id=corpus.openai_vector_store_id)
                except openai.NotFoundError:
                    pass    # already gone from the store: the goal state
            try:
                await client.files.delete(doc.openai_file_id)
            except openai.NotFoundError:
                pass
        except Exception as e:
            log.error(f"corpus {corpus_id[:8]}: could not remove {doc.filename!r} from OpenAI: {e}")
            raise HTTPException(
                status_code=502,
                detail="Could not remove this document from the search index, so it is still "
                       "being used for scoring. Nothing was deleted; please try again.",
            )

    await db.delete(doc)
    await db.flush()
    # A corpus whose last indexed document just went is no longer ready: the
    # evaluator must not keep searching an empty store as "ground truth".
    await _refresh_corpus_status(db, corpus_id)
    await db.commit()
    return {"deleted": document_id}


@router.delete("/{corpus_id}")
async def detach_corpus(
    corpus_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Detach a corpus from its assignment.

    The rows are kept, not dropped: past EvalResults cite grounding scores that
    came from this corpus, and deleting it would orphan the evidence for a
    published number. Scoring falls back to rubric-only immediately."""
    corpus = await db.get(ReferenceCorpus, corpus_id)
    if corpus is None:
        raise HTTPException(status_code=404, detail="Corpus not found")
    cc = await _assert_can_manage_assignment(db, user_id, corpus.classroom_challenge_id)
    cc.reference_corpus_id = None
    await db.commit()
    return {"detached": corpus_id}


def _corpus_payload(corpus: ReferenceCorpus, docs: list) -> dict:
    return {
        "id": corpus.id,
        "name": corpus.name,
        "status": corpus.status,
        "error": corpus.error,
        "vector_store_id": corpus.openai_vector_store_id,
        "documents": [
            {
                "id": d.id, "filename": d.filename, "size_bytes": d.size_bytes,
                "status": d.status,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in docs
        ],
    }
