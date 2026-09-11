"""Real multi-worker verification for the Redis-backed group rooms.

Starts genuinely separate server processes sharing one Redis and one database,
puts two students on *different* processes, and asserts the cross-worker
behaviour end to end. Nothing here is mocked except the two LLM calls (see
mw_app.py) -- the rooms, presence, pub/sub fan-out and turn lock are real.

Usage (from backend/):
    python tests/multiworker/run_check.py                # two separate ports
    python tests/multiworker/run_check.py --workers 2    # one port, --workers 2

Requires REDIS_URL. DATABASE_URL defaults to a shared temp SQLite file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx
import websockets

BACKEND = Path(__file__).resolve().parents[2]

PASS, FAIL = "PASS", "FAIL"
SERVER_LOGS: list[Path] = []
results: list[tuple[str, str, str]] = []


def record(name: str, ok: bool, detail: str = "", status: str | None = None) -> None:
    st = status or (PASS if ok else FAIL)
    results.append((name, st, detail))
    print(f"  [{st}] {name}" + (f" -- {detail}" if detail else ""), flush=True)


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------

LOG_DIR = Path(tempfile.gettempdir()) / "husky_mw_logs"


def free_port() -> int:
    """Grab a port the OS says is free. Picked per run so a leftover server (or an
    orphaned listening socket) from a previous run can never be mistaken for ours
    -- that silently pointed clients at a stale database once already."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(port: int, env: dict, workers: int = 1) -> subprocess.Popen:
    cmd = [
        sys.executable, "-m", "uvicorn", "tests.multiworker.mw_app:app",
        "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning",
    ]
    if workers > 1:
        cmd += ["--workers", str(workers)]
    # Server output goes to a file, never a pipe: the app logs at DEBUG, and an
    # unread PIPE fills its buffer and blocks the server mid-startup.
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"server-{port}-{uuid.uuid4().hex[:6]}.log"
    logf = open(path, "w", encoding="utf-8")
    SERVER_LOGS.append(path)
    return subprocess.Popen(cmd, cwd=str(BACKEND), env=env,
                            stdout=logf, stderr=subprocess.STDOUT)


def workers_were_split(group_id: str) -> bool | None:
    """Did the two students for `group_id` genuinely land on different workers?

    The handler logs "(N live on this worker)" on each join. Two joins that both
    report 1 means two different processes; a join reporting 2 means they shared
    one, and any cross-worker claim about that group would be vacuous.

    Returns True/False, or None if the log lines could not be found.
    """
    pat = re.compile(
        rf"\[WS-GROUP\] \w+ joined group={re.escape(group_id[:8])} \S+ \((\d+) live on this worker\)"
    )
    counts: list[int] = []
    for path in SERVER_LOGS:
        try:
            counts += [int(m) for m in pat.findall(path.read_text(encoding="utf-8", errors="replace"))]
        except Exception:
            continue
    if len(counts) < 2:
        return None
    # Look at the first two joins for this group (later ones are reconnects).
    return counts[0] == 1 and counts[1] == 1


async def wait_healthy(port: int, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    async with httpx.AsyncClient() as c:
        while time.time() < deadline:
            try:
                r = await c.get(f"http://127.0.0.1:{port}/health", timeout=2.0)
                if r.status_code == 200:
                    return
            except Exception:
                pass
            await asyncio.sleep(0.3)
    raise RuntimeError(f"server on port {port} never became healthy")


# ---------------------------------------------------------------------------
# Fixture setup over HTTP (mirrors tests/group_helpers.py)
# ---------------------------------------------------------------------------

async def register(c: httpx.AsyncClient, base: str, name="u") -> str:
    email = f"{name}_{uuid.uuid4().hex[:10]}@example.com"
    r = await c.post(f"{base}/auth/register",
                     json={"email": email, "name": name, "password": "testpassword123"})
    r.raise_for_status()
    return r.json()["access_token"]


async def setup_team(c: httpx.AsyncClient, base: str, n_students=2) -> tuple[str, list[str]]:
    it = await register(c, base, "ins")
    hi = {"Authorization": f"Bearer {it}"}
    cr = await c.post(f"{base}/classrooms", json={"name": "MW Sec"}, headers=hi)
    cr.raise_for_status()
    classroom_id, join_code = cr.json()["id"], cr.json()["join_code"]

    ch = await c.post(f"{base}/challenges", headers=hi, json={
        "classroom_id": classroom_id, "title": "MW Group", "description": "d",
        "category": "Test", "difficulty": "Beginner", "total_sessions": 1,
        "mode": "group", "team_min": 2, "team_max": 4,
    })
    ch.raise_for_status()
    challenge_id = ch.json()["id"]

    team = await c.post(
        f"{base}/classrooms/{classroom_id}/challenges/{challenge_id}/teams",
        json={}, headers=hi)
    team.raise_for_status()
    group_id = team.json()["id"]

    tokens = []
    for _ in range(n_students):
        st = await register(c, base, "stu")
        hs = {"Authorization": f"Bearer {st}"}
        jr = await c.post(f"{base}/classrooms/join", json={"code": join_code}, headers=hs)
        jr.raise_for_status()
        me = await c.get(f"{base}/auth/me", headers=hs)
        me.raise_for_status()
        ar = await c.post(
            f"{base}/classrooms/{classroom_id}/challenges/{challenge_id}/teams/{group_id}/members",
            json={"user_id": me.json()["user_id"]}, headers=hi)
        ar.raise_for_status()
        tokens.append(st)
    return group_id, tokens


# ---------------------------------------------------------------------------
# WS helpers
# ---------------------------------------------------------------------------

async def recv_until(ws, wanted: set[str], timeout=25.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - time.time()))
        except asyncio.TimeoutError:
            break
        msg = json.loads(raw)
        if msg.get("type") in wanted:
            return msg
    raise AssertionError(f"never received any of {wanted}")


async def drain(ws, seconds=0.6) -> list[dict]:
    out, deadline = [], time.time() + seconds
    while time.time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=max(0.05, deadline - time.time()))
        except (asyncio.TimeoutError, Exception):
            break
        out.append(json.loads(raw))
    return out


def ws_url(port: int, token: str, group_id: str, session_num: int = 1) -> str:
    return (f"ws://127.0.0.1:{port}/ws/group?token={token}"
            f"&group_id={group_id}&session_num={session_num}")


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------

async def check_cross_worker_broadcast(pa: int, pb: int, group_id: str, tokens: list[str]):
    """A message sent on worker A must reach a student connected to worker B --
    and the team_min gate must see both, which only works if presence is shared."""
    print("\nCheck 1: cross-worker broadcast + shared presence", flush=True)
    async with websockets.connect(ws_url(pa, tokens[0], group_id)) as wa, \
               websockets.connect(ws_url(pb, tokens[1], group_id)) as wb:
        await recv_until(wa, {"session_init"})
        await recv_until(wb, {"session_init"})
        await drain(wa, 1.0)
        await drain(wb, 1.0)

        await wa.send(json.dumps({"type": "message", "content": "hello from A"}))

        # If presence were per-process, A would be told to wait for a 2nd member.
        got = await recv_until(wa, {"user_message", "typing", "stream", "done", "waiting", "busy"})
        record("sender is not blocked by a stale 1-member presence count",
               got.get("type") != "waiting", f"first event: {got.get('type')}")

        peer = await recv_until(wb, {"user_message"})
        record("peer on the other worker receives user_message",
               peer.get("content") == "hello from A", f"content={peer.get('content')!r}")

        done = await recv_until(wb, {"done"})
        record("peer on the other worker receives the streamed reply",
               "FAKE" in (done.get("full_response") or ""), f"got {done.get('full_response')!r}")

        ev = await recv_until(wb, {"eval", "eval_error"})
        record("peer on the other worker receives the shared eval",
               ev.get("type") == "eval", f"type={ev.get('type')}")

    # Only meaningful if the two clients really were on different processes.
    split = workers_were_split(group_id)
    if split is None:
        record("the two students were served by different workers", False,
               "could not determine from logs", status="INCONCLUSIVE")
    else:
        record("the two students were served by different workers", split,
               "confirmed from per-worker join counts" if split
               else "BOTH LANDED ON ONE WORKER -- the checks above did not cross a process")


async def check_turn_lock_across_workers(pa: int, pb: int, group_id: str, tokens: list[str]):
    """Two students on different workers sending at once: exactly one turn runs."""
    print("\nCheck 2: turn lock is exclusive across workers", flush=True)
    async with websockets.connect(ws_url(pa, tokens[0], group_id)) as wa, \
               websockets.connect(ws_url(pb, tokens[1], group_id)) as wb:
        await recv_until(wa, {"session_init"})
        await recv_until(wb, {"session_init"})
        await drain(wa, 1.0)
        await drain(wb, 1.0)

        # Fire both as close to simultaneously as possible, on different processes.
        await asyncio.gather(
            wa.send(json.dumps({"type": "message", "content": "A races"})),
            wb.send(json.dumps({"type": "message", "content": "B races"})),
        )
        a_msgs, b_msgs = await asyncio.gather(drain(wa, 6.0), drain(wb, 6.0))

        a_busy = any(m.get("type") == "busy" for m in a_msgs)
        b_busy = any(m.get("type") == "busy" for m in b_msgs)
        # Exactly one sender must have been turned away.
        record("exactly one of the two simultaneous senders got 'busy'",
               a_busy != b_busy, f"A busy={a_busy}, B busy={b_busy}")

        # And exactly one turn actually ran.
        dones = [m for m in a_msgs if m.get("type") == "done"]
        record("exactly one AI turn ran for the session",
               len(dones) == 1, f"{len(dones)} 'done' events seen by A")


async def check_session_isolation(pa: int, pb: int, teams: list[tuple[str, list[str]]]):
    """Session A holding its lock must not delay an unrelated session B."""
    print("\nCheck 3: one session's lock does not block another", flush=True)
    (g1, t1), (g2, t2) = teams

    async def run_turn(port_x, port_y, gid, toks, label):
        async with websockets.connect(ws_url(port_x, toks[0], gid)) as w1, \
                   websockets.connect(ws_url(port_y, toks[1], gid)) as w2:
            await recv_until(w1, {"session_init"})
            await recv_until(w2, {"session_init"})
            await drain(w1, 1.0)
            await drain(w2, 1.0)
            t0 = time.time()
            await w1.send(json.dumps({"type": "message", "content": f"turn in {label}"}))
            await recv_until(w1, {"done"}, timeout=30)
            return time.time() - t0

    solo = await run_turn(pa, pb, g1, t1, "team1 (baseline)")
    both = await asyncio.gather(
        run_turn(pa, pb, g1, t1, "team1"),
        run_turn(pb, pa, g2, t2, "team2"),
    )
    slowest = max(both)
    # If the two sessions shared a lock, the second would queue behind the first
    # and take roughly twice as long. Allow generous headroom for scheduling.
    record("unrelated sessions run concurrently, not serialized",
           slowest < solo * 1.8 + 0.5,
           f"baseline={solo:.2f}s, concurrent slowest={slowest:.2f}s")


# ---------------------------------------------------------------------------

async def main_async(args) -> int:
    redis_url = os.getenv("REDIS_URL", "").strip()
    if not redis_url:
        print("REDIS_URL is not set -- this check requires a real Redis.", file=sys.stderr)
        return 2

    db_path = os.getenv("MW_DB_PATH") or (Path(tempfile.gettempdir()) / f"husky_mw_{uuid.uuid4().hex[:8]}.db")
    db_url = f"sqlite+aiosqlite:///{str(db_path).replace(os.sep, '/')}"

    env = os.environ.copy()
    env.update({
        "DATABASE_URL": db_url,
        "REDIS_URL": redis_url,
        "HUSKY_TESTING": "1",
        "JWT_SECRET": "multiworker-test-secret-key-long-enough-32",
        "MW_STREAM_DELAY": os.getenv("MW_STREAM_DELAY", "0.5"),
        "PYTHONIOENCODING": "utf-8",
    })

    p_seed, p_a, p_b = free_port(), free_port(), free_port()

    # By default the servers below start simultaneously against a COLD database.
    # That is exactly the condition that used to break startup seeding (two
    # workers racing seed_dev_platform_admin / seed_challenges); the cross-worker
    # lock in main.py's _run_startup_seeding is what makes it safe, so exercising
    # it here is the point. --preseed restores the old single-process warm-up.
    if args.preseed:
        print("Pre-seeding the shared database (single process)...", flush=True)
        warm = start_server(p_seed, env)
        try:
            await wait_healthy(p_seed, timeout=120)
        finally:
            warm.terminate()
            try:
                warm.wait(timeout=15)
            except Exception:
                warm.kill()
        await asyncio.sleep(1.0)
    else:
        print("COLD START: no pre-seed -- servers race to seed an empty DB.", flush=True)

    procs: list[subprocess.Popen] = []
    if args.workers > 1:
        print(f"Mode: ONE port, --workers {args.workers} (production-shaped)")
        ports = (p_a, p_a)
        procs.append(start_server(p_a, env, workers=args.workers))
    else:
        print("Mode: TWO separate server processes (deterministic worker split)")
        ports = (p_a, p_b)
        procs.append(start_server(p_a, env))
        procs.append(start_server(p_b, env))

    pa, pb = ports
    try:
        await wait_healthy(pa, timeout=120)
        await wait_healthy(pb, timeout=120)
        print(f"Servers healthy on {pa} and {pb}; Redis={redis_url}; DB={db_path}\n")

        async with httpx.AsyncClient(timeout=30.0) as c:
            base = f"http://127.0.0.1:{pa}"
            g1, t1 = await setup_team(c, base)
            g2, t2 = await setup_team(c, base)
            g3, t3 = await setup_team(c, base)

        await check_cross_worker_broadcast(pa, pb, g1, t1)
        await check_turn_lock_across_workers(pa, pb, g2, t2)
        await check_session_isolation(pa, pb, [(g3, t3), (g1, t1)])
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except Exception:
                p.kill()

    print("\n" + "=" * 62)
    failed = [r for r in results if r[1] != PASS]
    for name, status, detail in results:
        print(f"{status:4}  {name}" + (f"  ({detail})" if detail else ""))
    print("=" * 62)
    print(f"{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=1,
                    help="if >1, run a single port with uvicorn --workers N")
    ap.add_argument("--preseed", action="store_true",
                    help="seed with one process first instead of cold-starting")
    sys.exit(asyncio.run(main_async(ap.parse_args())))
