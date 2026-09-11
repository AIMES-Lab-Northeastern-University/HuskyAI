"""Real multi-process check for per-section artifact locks.

Two genuinely separate server processes share one Redis and one database. Alice
connects to process A, Bob to process B, and every scenario is driven over real
websockets. Only the two LLM calls are faked (see mw_app.py); the locks,
persistence, pub/sub fan-out and disconnect handling are all real.

Usage (from backend/):
    python tests/multiworker/artifact_check.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_check import (  # noqa: E402
    PASS, FAIL, drain, free_port, recv_until, record, results,
    setup_team, start_server, wait_healthy, workers_were_split, ws_url,
)

SECTIONS = [
    {"key": "design", "title": "Design"},
    {"key": "testing", "title": "Testing"},
]


def inject_sections(db_path: Path) -> None:
    """Give the harness challenge a set of artifact sections.

    There is no API for authoring sessions_data.sections yet, so rather than
    invent an endpoint purely for the test, write it straight into the DB the
    servers are already reading from. Done before any websocket connects, since
    the handler reads the challenge at connect time.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, sessions_data FROM challenges WHERE title = 'MW Group'")
        for cid, raw in cur.fetchall():
            try:
                data = json.loads(raw) if isinstance(raw, str) else raw
            except Exception:
                data = []
            # Two sessions, both with the same sections, so the carry-forward
            # check has a session 2 to move into.
            data = [
                {"title": f"S{n}", "goal": "g", "brief": "b",
                 "seed_question": "q", "sections": SECTIONS}
                for n in (1, 2)
            ]
            cur.execute(
                "UPDATE challenges SET sessions_data = ?, total_sessions = 2 WHERE id = ?",
                (json.dumps(data), cid),
            )
        conn.commit()
    finally:
        conn.close()


async def open_ws(port: int, token: str, group_id: str, session_num: int = 1):
    ws = await websockets.connect(ws_url(port, token, group_id, session_num))
    await recv_until(ws, {"session_init"})
    state = await recv_until(ws, {"artifact_state"}, timeout=10)
    return ws, state


# ---------------------------------------------------------------------------


async def check_artifact_state(pa: int, pb: int, gid: str, toks: list[str]):
    print("\nCheck 1: artifact state is delivered on connect", flush=True)
    ws, state = await open_ws(pa, toks[0], gid)
    try:
        keys = [s["key"] for s in state.get("sections", [])]
        record("sections are advertised to a joining client",
               keys == ["design", "testing"], f"got {keys}")
        record("no locks held on a fresh session",
               state.get("locks") == [], f"locks={state.get('locks')}")
    finally:
        await ws.close()


async def check_simultaneous_lock(pa: int, pb: int, gid: str, toks: list[str]):
    """Two students on DIFFERENT workers grab the same section at once."""
    print("\nCheck 2: simultaneous lock on the same section, different workers", flush=True)
    wa, _ = await open_ws(pa, toks[0], gid)
    wb, _ = await open_ws(pb, toks[1], gid)
    try:
        await drain(wa, 0.8)
        await drain(wb, 0.8)
        await asyncio.gather(
            wa.send(json.dumps({"type": "section_lock_request", "section_key": "design"})),
            wb.send(json.dumps({"type": "section_lock_request", "section_key": "design"})),
        )
        a_msgs, b_msgs = await asyncio.gather(drain(wa, 3.0), drain(wb, 3.0))

        denied = [m for m in a_msgs + b_msgs if m.get("type") == "section_lock_denied"]
        locked = [m for m in a_msgs if m.get("type") == "section_locked"]

        record("exactly one student was denied (no silent failure, no double-grant)",
               len(denied) == 1, f"{len(denied)} denials")
        record("the denial names who actually holds it",
               len(denied) == 1 and bool(denied[0].get("holder_name")),
               f"holder_name={denied[0].get('holder_name') if denied else None}")
        record("the lock was broadcast to the session",
               len(locked) >= 1, f"{len(locked)} section_locked seen by A")

        holders = {m.get("holder_user_id") for m in a_msgs + b_msgs
                   if m.get("type") == "section_locked"}
        record("all clients agree on a single holder",
               len(holders) == 1, f"holders seen: {holders}")
    finally:
        await wa.close()
        await wb.close()


async def check_cross_worker_enforcement(pa: int, pb: int, gid: str, toks: list[str]):
    """Worker B must refuse a write to a section locked on worker A."""
    print("\nCheck 3: write enforcement across workers", flush=True)
    wa, _ = await open_ws(pa, toks[0], gid)
    wb, _ = await open_ws(pb, toks[1], gid)
    try:
        await drain(wa, 0.8)
        await drain(wb, 0.8)
        await wa.send(json.dumps({"type": "section_lock_request", "section_key": "design"}))
        await recv_until(wa, {"section_locked"})
        peer = await recv_until(wb, {"section_locked"}, timeout=8)
        record("peer on the other worker is told the section is locked",
               peer.get("section_key") == "design" and bool(peer.get("holder_name")),
               f"holder={peer.get('holder_name')}")

        # Bob writes anyway -- the client is not trusted.
        await wb.send(json.dumps({
            "type": "section_write", "section_key": "design", "content": "BOB WAS HERE",
        }))
        denial = await recv_until(wb, {"section_write_denied", "section_updated"}, timeout=8)
        record("a non-holder's write is rejected, not silently applied",
               denial.get("type") == "section_write_denied", f"got {denial.get('type')}")

        # The holder's own write goes through and reaches the other worker.
        await wa.send(json.dumps({
            "type": "section_write", "section_key": "design", "content": "ALICE CONTENT",
        }))
        upd = await recv_until(wb, {"section_updated"}, timeout=8)
        record("the holder's write reaches the peer on the other worker",
               upd.get("content") == "ALICE CONTENT", f"content={upd.get('content')!r}")
    finally:
        await wa.close()
        await wb.close()


async def check_disconnect_releases(pa: int, pb: int, gid: str, toks: list[str]):
    """Alice drops mid-edit; Bob must be able to take over promptly."""
    print("\nCheck 4: disconnect releases the lock", flush=True)
    wa, _ = await open_ws(pa, toks[0], gid)
    wb, _ = await open_ws(pb, toks[1], gid)
    try:
        await drain(wa, 0.8)
        await drain(wb, 0.8)
        await wa.send(json.dumps({"type": "section_lock_request", "section_key": "testing"}))
        await recv_until(wa, {"section_locked"})
        await recv_until(wb, {"section_locked"}, timeout=8)

        t0 = time.time()
        await wa.close()  # Alice's connection drops mid-edit

        released = await recv_until(wb, {"section_unlocked"}, timeout=15)
        elapsed = time.time() - t0
        record("teammates are told the section was released",
               released.get("section_key") == "testing", f"after {elapsed:.2f}s")

        await wb.send(json.dumps({"type": "section_lock_request", "section_key": "testing"}))
        got = await recv_until(wb, {"section_locked", "section_lock_denied"}, timeout=8)
        record("a teammate can acquire it after the holder disconnects",
               got.get("type") == "section_locked",
               f"{got.get('type')} after {time.time() - t0:.2f}s")
        record("release happens promptly, not only at TTL expiry",
               elapsed < 10, f"{elapsed:.2f}s (TTL backstop is 60s)")
    finally:
        await wb.close()


async def check_independent_sections(pa: int, pb: int, gid: str, toks: list[str]):
    """Locking one section must not block a different one."""
    print("\nCheck 5: different sections do not block each other", flush=True)
    wa, _ = await open_ws(pa, toks[0], gid)
    wb, _ = await open_ws(pb, toks[1], gid)
    try:
        await drain(wa, 0.8)
        await drain(wb, 0.8)
        await wa.send(json.dumps({"type": "section_lock_request", "section_key": "design"}))
        a_got = await recv_until(wa, {"section_locked", "section_lock_denied"})
        await wb.send(json.dumps({"type": "section_lock_request", "section_key": "testing"}))
        b_got = await recv_until(wb, {"section_locked", "section_lock_denied"}, timeout=8)

        record("student A holds 'design'", a_got.get("type") == "section_locked",
               f"{a_got.get('type')}")
        record("student B concurrently holds 'testing' on another worker",
               b_got.get("type") == "section_locked", f"{b_got.get('type')}")

        # Both write concurrently; both must succeed.
        await asyncio.gather(
            wa.send(json.dumps({"type": "section_write", "section_key": "design", "content": "A1"})),
            wb.send(json.dumps({"type": "section_write", "section_key": "testing", "content": "B1"})),
        )
        a_msgs, b_msgs = await asyncio.gather(drain(wa, 3.0), drain(wb, 3.0))
        updates = {m["section_key"] for m in a_msgs + b_msgs if m.get("type") == "section_updated"}
        denials = [m for m in a_msgs + b_msgs if m.get("type") == "section_write_denied"]
        record("both concurrent writes to different sections succeeded",
               updates == {"design", "testing"} and not denials,
               f"updated={sorted(updates)}, denials={len(denials)}")
    finally:
        await wa.close()
        await wb.close()


# ---------------------------------------------------------------------------

async def check_carry_forward(pa: int, pb: int, gid: str, toks: list[str]):
    """Session 2 must start from session 1's final content, once, for everyone."""
    print("\nCheck 7: a new session starts from the previous one's content", flush=True)
    # --- Session 1: the team writes something. ---
    wa, _ = await open_ws(pa, toks[0], gid, session_num=1)
    try:
        await drain(wa, 0.8)
        await wa.send(json.dumps({"type": "section_lock_request", "section_key": "design"}))
        await recv_until(wa, {"section_locked"})
        await wa.send(json.dumps({
            "type": "section_write", "section_key": "design",
            "content": "SESSION ONE FINAL DRAFT",
        }))
        await recv_until(wa, {"section_updated"})
        await wa.send(json.dumps({"type": "section_unlock", "section_key": "design"}))
        await drain(wa, 0.8)
    finally:
        await wa.close()

    # --- Session 2: two students join at once, on different workers. ---
    (w1, s1), (w2, s2) = await asyncio.gather(
        open_ws(pa, toks[0], gid, session_num=2),
        open_ws(pb, toks[1], gid, session_num=2),
    )
    try:
        def section(state, key):
            for sec in state.get("sections", []):
                if sec.get("key") == key:
                    return sec
            return {}

        d1, d2 = section(s1, "design"), section(s2, "design")
        record("session 2 opens with session 1's content",
               d1.get("content") == "SESSION ONE FINAL DRAFT",
               f"content={d1.get('content')!r}")
        record("provenance records which session it came from",
               d1.get("carried_from_session_number") == 1,
               f"carried_from={d1.get('carried_from_session_number')}")
        record("carried content counts as unedited in the new session",
               d1.get("version") == 0, f"version={d1.get('version')}")
        record("both students on different workers see the same starting content",
               d1.get("content") == d2.get("content"),
               f"A={d1.get('content')!r} B={d2.get('content')!r}")
        record("the untouched section did not carry anything",
               section(s1, "testing").get("content") == "",
               f"testing={section(s1, 'testing').get('content')!r}")

        # Editing in session 2 must not reach back into session 1.
        await drain(w1, 0.8)
        await drain(w2, 0.8)
        await w1.send(json.dumps({"type": "section_lock_request", "section_key": "design"}))
        got = await recv_until(w1, {"section_locked", "section_lock_denied"})
        record("the carried section is editable (not left locked by session 1)",
               got.get("type") == "section_locked", f"{got.get('type')}")
        await w1.send(json.dumps({
            "type": "section_write", "section_key": "design", "content": "SESSION TWO EDIT",
        }))
        await recv_until(w2, {"section_updated"}, timeout=8)
    finally:
        await w1.close()
        await w2.close()

    # Session 1 is a separate artifact and must be untouched.
    ws1, st1 = await open_ws(pa, toks[0], gid, session_num=1)
    try:
        content = next((s.get("content") for s in st1.get("sections", [])
                        if s.get("key") == "design"), None)
        record("session 1's own artifact is unchanged by session 2 edits",
               content == "SESSION ONE FINAL DRAFT", f"content={content!r}")
    finally:
        await ws1.close()



async def _events_for(db_path: Path, gid: str) -> list[dict]:
    """Read the permanent event log straight from the DB the servers share."""
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT e.seq, e.event_type, e.actor_kind, e.actor_user_id, e.section_key,"
            " e.dwell_ms, e.surface, e.idempotency_key"
            " FROM artifact_events e"
            " JOIN group_sessions gs ON gs.id = e.group_session_id"
            " WHERE gs.group_id = ? ORDER BY e.seq", (gid,))
        cols = ["seq", "event_type", "actor_kind", "actor_user_id", "section_key",
                "dwell_ms", "surface", "idempotency_key"]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        conn.close()


async def check_read_logged_with_sequencing(db_path, pa, pb, gid, toks):
    """A real read past the dwell threshold, ordered against a write."""
    print("\nCheck 8: a qualifying read is logged and ordered against writes", flush=True)
    wa, _ = await open_ws(pa, toks[0], gid)
    wb, _ = await open_ws(pb, toks[1], gid)
    try:
        await drain(wa, 0.8)
        await drain(wb, 0.8)
        # Bob reads Alice's section BEFORE writing his own.
        await wb.send(json.dumps({
            "type": "section_read", "event_id": "ep-before", "section_key": "design",
            "event_type": "section_expand", "dwell_ms": 3400,
            "surface": "artifact_panel",
        }))
        ack = await recv_until(wb, {"read_event_ack", "read_event_rejected"}, timeout=8)
        record("a qualifying read is acked", ack.get("type") == "read_event_ack",
               f"{ack.get('type')}")

        # Bob then writes his own section.
        await wb.send(json.dumps({"type": "section_lock_request", "section_key": "testing"}))
        await recv_until(wb, {"section_locked"})
        await wb.send(json.dumps({
            "type": "section_write", "section_key": "testing", "content": "bob's work"}))
        await recv_until(wb, {"section_updated"})

        # And reads again afterwards.
        await wb.send(json.dumps({
            "type": "section_read", "event_id": "ep-after", "section_key": "design",
            "event_type": "section_expand", "dwell_ms": 5000,
            "surface": "artifact_panel",
        }))
        await recv_until(wb, {"read_event_ack"}, timeout=8)
        await asyncio.sleep(0.5)

        events = await _events_for(db_path, gid)
        reads = [e for e in events if e["event_type"] == "section_expand"]
        writes = [e for e in events if e["event_type"] == "section_write"]
        record("exactly one event per qualifying read", len(reads) == 2,
               f"{len(reads)} read events")
        record("the write shares the same seq space as the reads",
               len(writes) == 1 and reads[0]["seq"] < writes[0]["seq"] < reads[1]["seq"],
               f"reads at {[r['seq'] for r in reads]}, write at "
               f"{[w['seq'] for w in writes]}")
        record("reads carry dwell and surface",
               reads[0]["dwell_ms"] == 3400 and reads[0]["surface"] == "artifact_panel",
               f"dwell={reads[0]['dwell_ms']} surface={reads[0]['surface']}")
    finally:
        await wa.close()
        await wb.close()


async def check_below_dwell_is_not_a_read(db_path, pa, pb, gid, toks):
    print("\nCheck 9: opening and closing under the threshold logs nothing", flush=True)
    wb, _ = await open_ws(pb, toks[1], gid)
    try:
        await drain(wb, 0.8)
        await wb.send(json.dumps({
            "type": "section_read", "event_id": "ep-quick", "section_key": "design",
            "event_type": "section_expand", "dwell_ms": 900,
            "surface": "artifact_panel",
        }))
        resp = await recv_until(wb, {"read_event_ack", "read_event_rejected"}, timeout=8)
        record("a sub-threshold read is refused, not recorded",
               resp.get("type") == "read_event_rejected"
               and resp.get("reason") == "below_dwell_threshold",
               f"{resp.get('type')}/{resp.get('reason')}")
        await asyncio.sleep(0.4)
        events = await _events_for(db_path, gid)
        record("nothing was written to the permanent log",
               not [e for e in events if e["event_type"] == "section_expand"],
               f"{len(events)} events total")
    finally:
        await wb.close()


async def check_disconnect_replay_is_idempotent(db_path, pa, pb, gid, toks):
    """Drop mid-dwell, reconnect to the OTHER worker, replay the buffered event."""
    print("\nCheck 10: buffered event replays once across a disconnect", flush=True)
    wb, _ = await open_ws(pb, toks[1], gid)
    event = {
        "type": "section_read", "event_id": "ep-buffered", "section_key": "design",
        "event_type": "section_expand", "dwell_ms": 3300, "surface": "artifact_panel",
    }
    try:
        await drain(wb, 0.8)
        await wb.send(json.dumps(event))
        await recv_until(wb, {"read_event_ack"}, timeout=8)
    finally:
        await wb.close()   # connection drops before the client cleared its buffer

    # The SAME student reconnects -- landing on the other worker -- and flushes
    # the still-buffered event. It must be the same student: the idempotency key
    # is per (user, section, episode), so two different students that happened to
    # mint the same episode id are genuinely two different reads and must both be
    # kept. Replaying as a different user here would be testing the wrong thing.
    wa, _ = await open_ws(pa, toks[1], gid)
    try:
        await drain(wa, 0.8)
        await wa.send(json.dumps(event))   # same event_id -> same idempotency key
        ack = await recv_until(wa, {"read_event_ack"}, timeout=8)
        record("the replayed event is acked again (client can clear its buffer)",
               ack.get("type") == "read_event_ack", f"{ack.get('type')}")
        record("the server recognises it as a duplicate",
               ack.get("duplicate") is True, f"duplicate={ack.get('duplicate')}")
        await asyncio.sleep(0.4)
        events = await _events_for(db_path, gid)
        matching = [e for e in events if e["idempotency_key"].endswith("ep-buffered")]
        record("stored exactly once -- not lost, not duplicated",
               len(matching) == 1, f"{len(matching)} rows")
    finally:
        await wa.close()


async def check_ttl_backstop_when_a_worker_dies(procs, pa: int, pb: int, gid: str, toks: list[str]):
    """The case clean disconnect cannot cover: the worker process itself dies.

    Nothing runs in that worker -- no finally block, no release, no heartbeat --
    so the ONLY thing that frees the section is the lock's TTL lapsing. Runs last
    because it kills a server.
    """
    print("\nCheck 6: worker killed mid-edit -- TTL must free the section", flush=True)
    wa, _ = await open_ws(pa, toks[0], gid)
    wb, _ = await open_ws(pb, toks[1], gid)
    try:
        await drain(wa, 0.8)
        await drain(wb, 0.8)
        await wa.send(json.dumps({"type": "section_lock_request", "section_key": "design"}))
        await recv_until(wa, {"section_locked"})
        await recv_until(wb, {"section_locked"}, timeout=8)

        # Confirm it is genuinely held before we kill anything.
        await wb.send(json.dumps({"type": "section_lock_request", "section_key": "design"}))
        blocked = await recv_until(wb, {"section_lock_denied", "section_locked"}, timeout=8)
        record("section is held before the worker is killed",
               blocked.get("type") == "section_lock_denied", f"{blocked.get('type')}")

        t0 = time.time()
        procs[0].kill()   # hard kill: no cleanup code runs at all
        procs[0].wait(timeout=10)

        # Poll until the TTL lapses and B can take it.
        acquired_after = None
        deadline = time.time() + 25
        while time.time() < deadline:
            await asyncio.sleep(1.0)
            await wb.send(json.dumps({"type": "section_lock_request", "section_key": "design"}))
            try:
                msg = await recv_until(wb, {"section_locked", "section_lock_denied"}, timeout=5)
            except AssertionError:
                break
            if msg.get("type") == "section_locked":
                acquired_after = time.time() - t0
                break

        record("a killed worker's lock lapses via TTL and a teammate can take it",
               acquired_after is not None,
               f"acquired after {acquired_after:.1f}s (TTL=5s)" if acquired_after
               else "never freed within 25s")
    finally:
        try:
            await wb.close()
        except Exception:
            pass



async def main() -> int:
    redis_url = os.getenv("REDIS_URL", "").strip()
    if not redis_url:
        print("REDIS_URL is not set -- this check requires a real Redis.", file=sys.stderr)
        return 2

    db_path = Path(tempfile.gettempdir()) / f"husky_art_{uuid.uuid4().hex[:8]}.db"
    env = os.environ.copy()
    env.update({
        "DATABASE_URL": f"sqlite+aiosqlite:///{str(db_path).replace(os.sep, '/')}",
        "REDIS_URL": redis_url,
        "HUSKY_TESTING": "1",
        "JWT_SECRET": "multiworker-test-secret-key-long-enough-32",
        "MW_STREAM_DELAY": "0.05",
        # Short enough to exercise the TTL backstop in check 6.
        "SECTION_LOCK_TTL_SEC": "5",
        "PYTHONIOENCODING": "utf-8",
    })

    pa, pb = free_port(), free_port()
    procs = [start_server(pa, env), start_server(pb, env)]
    try:
        await wait_healthy(pa, timeout=120)
        await wait_healthy(pb, timeout=120)
        print(f"Two separate server processes on {pa} and {pb}; Redis={redis_url}")

        async with httpx.AsyncClient(timeout=30.0) as c:
            base = f"http://127.0.0.1:{pa}"
            teams = [await setup_team(c, base) for _ in range(10)]
        inject_sections(db_path)

        await check_artifact_state(pa, pb, *teams[0])
        await check_simultaneous_lock(pa, pb, *teams[1])
        await check_cross_worker_enforcement(pa, pb, *teams[2])
        await check_disconnect_releases(pa, pb, *teams[3])
        await check_independent_sections(pa, pb, *teams[4])

        split = workers_were_split(teams[1][0])
        record("the two students really were on different workers",
               bool(split), "confirmed from per-worker join counts" if split
               else "BOTH ON ONE WORKER -- cross-worker claims above are vacuous")

        await check_carry_forward(pa, pb, *teams[6])
        await check_read_logged_with_sequencing(db_path, pa, pb, *teams[7])
        await check_below_dwell_is_not_a_read(db_path, pa, pb, *teams[8])
        await check_disconnect_replay_is_idempotent(db_path, pa, pb, *teams[9])

        # Last: this kills a server process.
        await check_ttl_backstop_when_a_worker_dies(procs, pa, pb, *teams[5])
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except Exception:
                p.kill()

    print("\n" + "=" * 66)
    failed = [r for r in results if r[1] != PASS]
    for name, status, detail in results:
        print(f"{status:4}  {name}" + (f"  ({detail})" if detail else ""))
    print("=" * 66)
    print(f"{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
