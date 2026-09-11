"""Attachment persistence: a file uploaded with a message is stored in the DB,
linked to the user message, and can be rebuilt into Gemini parts on resume."""
import base64
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from database import init_db, AsyncSessionLocal, User, Conversation, Attachment
import main

_DOCX = Path(__file__).resolve().parent.parent.parent / "evaluator_v3_overview.docx"


def _docx_attachment() -> dict:
    raw = _DOCX.read_bytes()
    return {
        "filename": "evaluator_v3_overview.docx",
        "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "data": base64.b64encode(raw).decode(),
    }


async def _make_conversation() -> str:
    async with AsyncSessionLocal() as db:
        user = User(email=f"att_{uuid4().hex}@example.com", name="Att Test", password_hash="x")
        db.add(user)
        await db.flush()
        conv = Conversation(user_id=user.id)
        db.add(conv)
        await db.commit()
        return conv.id


async def test_attachment_saved_and_linked():
    await init_db()
    conv_id = await _make_conversation()
    att = _docx_attachment()
    raw_len = len(base64.b64decode(att["data"]))

    await main._save_turn(conv_id, "Summarize the attached doc.", "Sure — it covers…",
                          {"scores": {"PEI": 50}}, 1, attachments=[att])

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Attachment).where(Attachment.conversation_id == conv_id)
        )).scalars().all()

    assert len(rows) == 1
    row = rows[0]
    assert row.filename == "evaluator_v3_overview.docx"
    assert row.message_id is not None          # linked to the user message
    assert row.size_bytes == raw_len
    assert row.data == base64.b64decode(att["data"])  # bytes round-trip intact


async def test_rehydrated_attachment_rebuilds_into_parts():
    """The base64 we'd send back on resume must rebuild into a usable Gemini part
    (for .docx that means extracted text, not raw bytes)."""
    await init_db()
    conv_id = await _make_conversation()
    att = _docx_attachment()
    await main._save_turn(conv_id, "q", "a", {"scores": {}}, 1, attachments=[att])

    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            select(Attachment).where(Attachment.conversation_id == conv_id)
        )).scalars().first()

    rebuilt = {
        "filename": row.filename,
        "mime_type": row.mime_type,
        "data": base64.b64encode(row.data).decode(),
    }
    parts = await main._build_attachment_parts([rebuilt])
    assert len(parts) == 1
    # .docx → extracted text part mentioning the filename and real content.
    assert parts[0].text is not None
    assert "evaluator_v3_overview.docx" in parts[0].text
    assert "PEI" in parts[0].text  # the doc is about the PEI evaluator
