"""Files shared in team chat.

A teammate gets the file's metadata live and in replay, and fetches the bytes
from a members-only endpoint that always serves a download. Types a browser
would render as a page are refused, and the study event describes the files
without ever carrying them.
"""

import asyncio
import base64
import json

from fastapi.testclient import TestClient

from test_team_chat_logging import _chat_events, _connect, _gs_id, _team, _token, _until, app_ready  # noqa: F401

PDF = b"%PDF-1.4 tiny test file"


def _file(name, data=PDF):
    return {"filename": name, "mime_type": "application/octet-stream",
            "data": base64.b64encode(data).decode()}


def _download(client, gid, att_id, uid):
    return client.get(f"/groups/{gid}/team-chat/attachments/{att_id}",
                      headers={"Authorization": f"Bearer {_token(uid)}"})


def test_a_shared_file_reaches_the_teammate_and_downloads_for_members_only(app_ready):
    t = asyncio.run(_team())
    a, b = t["users"]
    client = TestClient(app_ready)
    with _connect(client, t["gid"], a) as ws_a, _connect(client, t["gid"], b) as ws_b:
        _until(ws_a, {"artifact"})
        _until(ws_b, {"artifact"})
        ws_a.send_text(json.dumps({"type": "team_chat", "content": "the reading",
                                   "client_id": "c1", "attachments": [_file("brief.pdf")]}))
        saved = _until(ws_a, {"team_chat_saved"})
        got = _until(ws_b, {"team_chat"})

    assert saved["client_id"] == "c1"
    (meta,) = saved["attachments"]
    # The type comes from the extension, not the client's claimed mime.
    assert meta["filename"] == "brief.pdf" and meta["mime_type"] == "application/pdf"
    assert meta["size_bytes"] == len(PDF)
    assert got["content"] == "the reading" and got["attachments"] == [meta]
    assert got["id"] == saved["id"]
    # Metadata only on the wire; the bytes are fetched on demand.
    assert "data" not in meta

    r = _download(client, t["gid"], meta["id"], b)
    assert r.status_code == 200 and r.content == PDF
    assert r.headers["content-disposition"].startswith("attachment;")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert _download(client, t["gid"], meta["id"], t["owner"]).status_code == 403

    # A member reconnecting sees the file in replay.
    with _connect(client, t["gid"], b) as ws:
        history = _until(ws, {"team_chat_history"})
    (msg,) = history["messages"]
    assert msg["attachments"] == [meta]


def test_a_file_from_another_team_is_not_served(app_ready):
    t1, t2 = asyncio.run(_team()), asyncio.run(_team())
    client = TestClient(app_ready)
    with _connect(client, t1["gid"], t1["users"][0]) as ws:
        _until(ws, {"artifact"})
        ws.send_text(json.dumps({"type": "team_chat", "content": "",
                                 "attachments": [_file("notes.txt", b"hello")]}))
        meta = _until(ws, {"team_chat_saved"})["attachments"][0]
    # A member of team 2 asking through their own team's URL gets nothing.
    assert _download(client, t2["gid"], meta["id"], t2["users"][0]).status_code == 404


def test_page_like_files_are_refused(app_ready):
    t = asyncio.run(_team())
    client = TestClient(app_ready)
    with _connect(client, t["gid"], t["users"][0]) as ws:
        _until(ws, {"artifact"})
        ws.send_text(json.dumps({"type": "team_chat", "content": "",
                                 "attachments": [_file("x.html", b"<script>alert(1)</script>"),
                                                 _file("y.svg", b"<svg/>")]}))
        rejected = _until(ws, {"team_chat_rejected"})
        # Nothing was left to send, so nothing is saved or acknowledged.
        ws.send_text(json.dumps({"type": "artifact_write", "section_key": None}))
        assert _until(ws, {"team_chat_saved", "artifact_error"})["type"] == "artifact_error"
    assert {f["name"] for f in rejected["files"]} == {"x.html", "y.svg"}


def test_the_study_event_describes_files_without_carrying_them(app_ready):
    t = asyncio.run(_team("metadata"))
    client = TestClient(app_ready)
    with _connect(client, t["gid"], t["users"][0]) as ws:
        _until(ws, {"artifact"})
        ws.send_text(json.dumps({"type": "team_chat", "content": "see attached",
                                 "attachments": [_file("brief.pdf"), _file("chart.png", b"\x89PNG..")]}))
        _until(ws, {"team_chat_saved"})
    (e,) = asyncio.run(_chat_events(asyncio.run(_gs_id(t["gid"]))))
    assert e.payload == {
        "chars": 12, "words": 2, "content_logged": False,
        "attachments": 2, "attachment_bytes": len(PDF) + 6,
        "attachment_types": ["application/pdf", "image/png"],
    }


def _docx_bytes(*paragraphs):
    import io

    import docx
    d = docx.Document()
    for p in paragraphs:
        d.add_paragraph(p)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_a_shared_word_document_can_be_previewed_as_text_by_members(app_ready):
    t = asyncio.run(_team())
    client = TestClient(app_ready)
    with _connect(client, t["gid"], t["users"][0]) as ws:
        _until(ws, {"artifact"})
        ws.send_text(json.dumps({"type": "team_chat", "content": "", "attachments": [
            _file("brief.docx", _docx_bytes("Route 7 lost 22% of riders.", "Recommend a review.")),
            _file("notes.txt", b"plain"),
        ]}))
        docx_meta, txt_meta = _until(ws, {"team_chat_saved"})["attachments"]

    def preview(att_id, uid):
        return client.get(f"/groups/{t['gid']}/team-chat/attachments/{att_id}/text",
                          headers={"Authorization": f"Bearer {_token(uid)}"})

    r = preview(docx_meta["id"], t["users"][1])
    assert r.status_code == 200
    assert r.json() == {"filename": "brief.docx",
                        "text": "Route 7 lost 22% of riders.\nRecommend a review."}
    # Other types are previewed by the browser from the file itself.
    assert preview(txt_meta["id"], t["users"][1]).status_code == 400
    assert preview(docx_meta["id"], t["owner"]).status_code == 403
