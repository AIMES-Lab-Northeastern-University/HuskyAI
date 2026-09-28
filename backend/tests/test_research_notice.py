"""Research notice versioning and the optional decline (collab-study-pending #1).

Both exist so approved consent wording can ship without a code change, and both
are inert by default: version 1 and no decline is exactly the behaviour before
they existed.
"""

import asyncio
import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from database import init_db
    from main import app

    asyncio.run(init_db())
    return TestClient(app)


async def _user(ack_at=None, ack_version=None, consent=False):
    from database import AsyncSessionLocal, User
    async with AsyncSessionLocal() as db:
        u = User(email=f"rn_{uuid.uuid4().hex[:10]}@example.com", name="Notice Tester",
                 password_hash="x", consent_research=consent,
                 research_ack_at=ack_at, research_ack_version=ack_version)
        db.add(u); await db.commit()
        return u.id


async def _load(uid):
    from database import AsyncSessionLocal, User
    async with AsyncSessionLocal() as db:
        return await db.get(User, uid)


def _auth(uid):
    from auth import create_token
    return {"Authorization": f"Bearer {create_token(uid)}"}


def test_defaults_change_nothing(client, monkeypatch):
    monkeypatch.delenv("RESEARCH_NOTICE_VERSION", raising=False)
    monkeypatch.delenv("RESEARCH_NOTICE_ALLOW_DECLINE", raising=False)
    # An acknowledgement from before versioning existed.
    uid = asyncio.run(_user(ack_at=datetime.utcnow(), consent=True))

    me = client.get("/auth/me", headers=_auth(uid)).json()
    assert me["research_acknowledged"] is True
    assert me["research_notice_version"] == 1
    assert me["research_notice_allow_decline"] is False


def test_raising_the_version_re_shows_the_gate(client, monkeypatch):
    first = datetime(2026, 1, 5, 12, 0)
    uid = asyncio.run(_user(ack_at=first, consent=True))
    monkeypatch.setenv("RESEARCH_NOTICE_VERSION", "2")

    assert client.get("/auth/me", headers=_auth(uid)).json()["research_acknowledged"] is False

    r = client.patch("/auth/me", json={"accept_research_notice": True}, headers=_auth(uid))
    assert r.status_code == 200 and r.json()["research_acknowledged"] is True
    u = asyncio.run(_load(uid))
    assert u.research_ack_version == 2
    # The first acknowledgement is an audit record and is never overwritten.
    assert u.research_ack_at == first


def test_decline_is_refused_unless_enabled(client, monkeypatch):
    monkeypatch.delenv("RESEARCH_NOTICE_ALLOW_DECLINE", raising=False)
    uid = asyncio.run(_user())
    r = client.patch("/auth/me", json={"decline_research_notice": True}, headers=_auth(uid))
    assert r.status_code == 400
    assert asyncio.run(_load(uid)).research_ack_at is None


def test_decline_acknowledges_with_consent_off(client, monkeypatch):
    monkeypatch.setenv("RESEARCH_NOTICE_ALLOW_DECLINE", "1")
    monkeypatch.setenv("RESEARCH_NOTICE_VERSION", "3")
    # Previously consented under an older notice; declining the new one turns it off.
    uid = asyncio.run(_user(ack_at=datetime.utcnow(), ack_version=2, consent=True))

    assert client.get("/auth/me", headers=_auth(uid)).json()["research_notice_allow_decline"] is True
    r = client.patch("/auth/me", json={"decline_research_notice": True}, headers=_auth(uid))
    assert r.status_code == 200
    body = r.json()
    assert body["research_acknowledged"] is True and body["consent_research"] is False
    assert asyncio.run(_load(uid)).research_ack_version == 3


def test_a_bad_version_value_falls_back_to_1(client, monkeypatch):
    monkeypatch.setenv("RESEARCH_NOTICE_VERSION", "two")
    uid = asyncio.run(_user(ack_at=datetime.utcnow()))
    me = client.get("/auth/me", headers=_auth(uid)).json()
    assert me["research_notice_version"] == 1 and me["research_acknowledged"] is True


def test_login_reports_the_version_aware_state(client, monkeypatch):
    from auth import pwd_context
    from database import AsyncSessionLocal, User

    email = f"rl_{uuid.uuid4().hex[:10]}@example.com"

    async def _make():
        async with AsyncSessionLocal() as db:
            db.add(User(email=email, name="Login Tester", password_hash=pwd_context.hash("pw-123456"),
                        research_ack_at=datetime.utcnow(), research_ack_version=1))
            await db.commit()
    asyncio.run(_make())
    monkeypatch.setenv("RESEARCH_NOTICE_VERSION", "2")

    r = client.post("/auth/login", json={"email": email, "password": "pw-123456"})
    assert r.status_code == 200, r.text
    # AuthPage caches this; it must not say "acknowledged" for an older notice.
    assert r.json()["research_acknowledged"] is False
