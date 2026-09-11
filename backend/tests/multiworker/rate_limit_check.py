"""Real multi-process check that the auth rate limit is a single shared budget.

Starts two genuinely separate server processes sharing one Redis, then spends one
IP's budget alternately across both. With per-process counters (the old
behaviour) each server would allow the full cap on its own, so 2 x cap requests
would get through. With the shared Redis window, the cap is total.

Usage (from backend/):
    python tests/multiworker/rate_limit_check.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_check import free_port, start_server, wait_healthy  # noqa: E402

CAP = 3


async def register(c: httpx.AsyncClient, port: int, fake_ip: str) -> int:
    r = await c.post(
        f"http://127.0.0.1:{port}/auth/register",
        json={
            "email": f"rl_{uuid.uuid4().hex[:12]}@example.com",
            "name": "rl",
            "password": "testpassword123",
        },
        headers={"X-Forwarded-For": fake_ip},
    )
    return r.status_code


async def main() -> int:
    redis_url = os.getenv("REDIS_URL", "").strip()
    if not redis_url:
        print("REDIS_URL is not set -- this check requires a real Redis.", file=sys.stderr)
        return 2

    # MW_DB_PATH lets a control run reuse an already-seeded DB, so the Redis
    # rate limiter can be disabled without also breaking startup seeding.
    db_path = Path(os.getenv("MW_DB_PATH") or
                   Path(tempfile.gettempdir()) / f"husky_rl_{uuid.uuid4().hex[:8]}.db")
    env = os.environ.copy()
    env.update({
        "DATABASE_URL": f"sqlite+aiosqlite:///{str(db_path).replace(os.sep, '/')}",
        "REDIS_URL": redis_url,
        "HUSKY_TESTING": "1",
        "AUTH_RATE_TEST_MAX": str(CAP),
        "JWT_SECRET": "multiworker-test-secret-key-long-enough-32",
        "PYTHONIOENCODING": "utf-8",
    })

    pa, pb = free_port(), free_port()
    procs = [start_server(pa, env), start_server(pb, env)]
    try:
        await wait_healthy(pa, timeout=120)
        await wait_healthy(pb, timeout=120)
        print(f"Two servers up on {pa} and {pb}; auth cap = {CAP}/min per IP\n")

        fake_ip = f"203.0.113.{uuid.uuid4().int % 200 + 1}"
        codes: list[tuple[int, int]] = []
        async with httpx.AsyncClient(timeout=30.0) as c:
            # Alternate between the two processes, one more than the cap allows.
            for i in range(CAP + 2):
                port = pa if i % 2 == 0 else pb
                codes.append((port, await register(c, port, fake_ip)))

        for i, (port, code) in enumerate(codes, 1):
            print(f"  request {i} -> port {port}: HTTP {code}")

        allowed = sum(1 for _, code in codes if code == 200)
        limited = sum(1 for _, code in codes if code == 429)
        ports_used = {p for p, _ in codes}

        print()
        ok = True
        if len(ports_used) < 2:
            print("FAIL  requests did not actually hit two different processes")
            ok = False
        if allowed != CAP:
            print(f"FAIL  {allowed} requests allowed, expected exactly {CAP}")
            print("      (per-process counters would have allowed up to "
                  f"{CAP * 2} across two workers)")
            ok = False
        if limited < 1:
            print("FAIL  nothing was rate limited")
            ok = False
        if ok:
            print(f"PASS  exactly {CAP} allowed / {limited} refused across 2 processes")
            print("      -> one shared budget, not one per worker")
        return 0 if ok else 1
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except Exception:
                p.kill()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
