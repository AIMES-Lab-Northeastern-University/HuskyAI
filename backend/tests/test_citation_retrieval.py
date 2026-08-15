"""Document-citation retrieval: indexing an uploaded attachment into the
conversation's OpenAI vector store, and querying it for related passages.
All OpenAI calls are mocked -- these tests must never hit the network."""
import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from database import init_db, AsyncSessionLocal, User, Conversation, Attachment
import main


async def _make_conversation() -> str:
    async with AsyncSessionLocal() as db:
        user = User(email=f"cite_{uuid4().hex}@example.com", name="Cite Test", password_hash="x")
        db.add(user)
        await db.flush()
        conv = Conversation(user_id=user.id)
        db.add(conv)
        await db.commit()
        return conv.id


def _fake_openai_client(vs_file_status="completed"):
    """A minimal stand-in for openai.AsyncOpenAI covering only the calls
    _index_attachment / _retrieve_related_passages actually make."""
    client = SimpleNamespace()
    client.vector_stores = SimpleNamespace()
    client.vector_stores.create = AsyncMock(return_value=SimpleNamespace(id="vs_123"))
    client.vector_stores.delete = AsyncMock(return_value=None)
    client.vector_stores.files = SimpleNamespace()
    client.vector_stores.files.create = AsyncMock(
        return_value=SimpleNamespace(status=vs_file_status)
    )
    client.vector_stores.files.retrieve = AsyncMock(
        return_value=SimpleNamespace(status=vs_file_status)
    )
    client.files = SimpleNamespace()
    client.files.create = AsyncMock(return_value=SimpleNamespace(id="file_abc"))
    client.vector_stores.search = AsyncMock(
        return_value=SimpleNamespace(data=[
            SimpleNamespace(
                file_id="file_abc",
                filename="notes.txt",
                score=0.9,
                content=[SimpleNamespace(type="text", text="the relevant passage")],
            ),
        ])
    )
    return client


async def test_index_attachment_success_persists_ready_status(monkeypatch):
    await init_db()
    monkeypatch.setattr(main, "openai_client", _fake_openai_client("completed"))
    conv_id = await _make_conversation()

    att = {"filename": "notes.txt", "mime_type": "text/plain",
           "data": base64.b64encode(b"hello world").decode()}
    await main._index_attachment(conv_id, att, "notes.txt", "text/plain", b"hello world")

    assert att["_index_status"] == "ready"
    assert att["_openai_file_id"] == "file_abc"

    await main._save_turn(conv_id, "q", "a", {"scores": {}}, 1, attachments=[att])

    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            select(Attachment).where(Attachment.conversation_id == conv_id)
        )).scalars().first()
    assert row.index_status == "ready"
    assert row.openai_file_id == "file_abc"

    async with AsyncSessionLocal() as db:
        conv = await db.get(Conversation, conv_id)
    assert conv.openai_vector_store_id == "vs_123"


async def test_index_attachment_failure_does_not_raise(monkeypatch):
    await init_db()
    fake = _fake_openai_client("failed")
    monkeypatch.setattr(main, "openai_client", fake)
    conv_id = await _make_conversation()

    att = {"filename": "notes.txt", "mime_type": "text/plain",
           "data": base64.b64encode(b"hello world").decode()}
    await main._index_attachment(conv_id, att, "notes.txt", "text/plain", b"hello world")

    assert att["_index_status"] == "failed"
    assert att.get("_openai_file_id") is None

    # _save_turn must still succeed and write the failed status without raising.
    await main._save_turn(conv_id, "q", "a", {"scores": {}}, 1, attachments=[att])
    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            select(Attachment).where(Attachment.conversation_id == conv_id)
        )).scalars().first()
    assert row.index_status == "failed"


async def test_index_attachment_skipped_when_openai_client_missing(monkeypatch):
    await init_db()
    monkeypatch.setattr(main, "openai_client", None)
    conv_id = await _make_conversation()

    att = {"filename": "notes.txt", "mime_type": "text/plain",
           "data": base64.b64encode(b"hello world").decode()}
    await main._index_attachment(conv_id, att, "notes.txt", "text/plain", b"hello world")

    assert att["_index_status"] == "skipped"


async def test_retrieve_related_passages_formats_results(monkeypatch):
    monkeypatch.setattr(main, "openai_client", _fake_openai_client())
    results = await main._retrieve_related_passages("vs_123", "what does it say?", "it says X")
    assert results == [{"id": 1, "filename": "notes.txt", "snippet": "the relevant passage"}]


async def test_retrieve_related_passages_empty_when_openai_client_missing(monkeypatch):
    monkeypatch.setattr(main, "openai_client", None)
    results = await main._retrieve_related_passages("vs_123", "q", "a")
    assert results == []


def test_indexable_mime_detection():
    assert main._indexable_mime({"mime_type": "application/pdf"}, "doc.pdf") == "application/pdf"
    assert main._indexable_mime({"mime_type": "application/octet-stream"}, "report.docx") == main._DOCX_MIME
    assert main._indexable_mime({"mime_type": "image/png"}, "photo.png") is None
