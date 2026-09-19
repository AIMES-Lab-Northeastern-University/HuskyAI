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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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


async def _ingest_corpus(corpus_id: str) -> None:
    """Upload every pending document to OpenAI and attach it to this corpus's
    own vector store.

    Runs as a background task. Never raises: a failure marks the corpus `failed`
    with the reason, and the evaluator carries on rubric-only. Breaking a
    student's turn because an instructor's PDF would not index is the wrong
    trade in every case.
    """
    import openai

    client = openai.AsyncOpenAI()
    try:
        async with AsyncSessionLocal() as db:
            corpus = await db.get(ReferenceCorpus, corpus_id)
            if corpus is None:
                return
            docs = (await db.execute(
                select(CorpusDocument).where(CorpusDocument.corpus_id == corpus_id)
            )).scalars().all()
            store_id = corpus.openai_vector_store_id
            pending = [(d.id, d.filename, d.data) for d in docs if d.status != "ready"]

        if store_id is None:
            store = await client.vector_stores.create(name=f"huskyai-corpus-{corpus_id[:8]}")
            store_id = store.id
            async with AsyncSessionLocal() as db:
                c = await db.get(ReferenceCorpus, corpus_id)
                if c:
                    c.openai_vector_store_id = store_id
                    await db.commit()

        for doc_id, filename, data in pending:
            try:
                uploaded = await client.files.create(
                    file=(filename, io.BytesIO(data)), purpose="assistants"
                )
                await client.vector_stores.files.create_and_poll(
                    vector_store_id=store_id, file_id=uploaded.id
                )
                new_status, file_id, err = "ready", uploaded.id, None
            except Exception as e:
                log.error(f"corpus {corpus_id[:8]} doc {filename!r} failed: {e}")
                new_status, file_id, err = "failed", None, str(e)[:500]
            async with AsyncSessionLocal() as db:
                d = await db.get(CorpusDocument, doc_id)
                if d:
                    d.status = new_status
                    d.openai_file_id = file_id
                    await db.commit()
            if err:
                log.warning(f"corpus {corpus_id[:8]}: continuing after {filename!r}")

        async with AsyncSessionLocal() as db:
            corpus = await db.get(ReferenceCorpus, corpus_id)
            docs = (await db.execute(
                select(CorpusDocument).where(CorpusDocument.corpus_id == corpus_id)
            )).scalars().all()
            if corpus is None:
                return
            ready = [d for d in docs if d.status == "ready"]
            # Ready if ANY document indexed: a corpus with one bad PDF is still
            # useful ground truth, and the per-document status makes the gap
            # visible to the instructor.
            corpus.status = "ready" if ready else "failed"
            if not ready:
                corpus.error = "no document could be indexed"
            await db.commit()
    except Exception as e:
        log.error(f"corpus {corpus_id[:8]} ingestion failed: {type(e).__name__}: {e}")
        try:
            async with AsyncSessionLocal() as db:
                c = await db.get(ReferenceCorpus, corpus_id)
                if c:
                    c.status = "failed"
                    c.error = str(e)[:500]
                    await db.commit()
        except Exception:
            pass


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

    asyncio.create_task(_ingest_corpus(corpus_id))
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
    await db.delete(doc)
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
