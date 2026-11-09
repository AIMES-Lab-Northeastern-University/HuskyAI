"""Concurrency stress for team sessions: many teams at once against running workers.

Usage (from backend/, with two workers on :8101 and :8102 sharing Redis and the
database whose URL you pass; NEVER point it at a database you want to keep):

    python scripts/stress_team_sessions.py postgresql://user@host:port/db [TEAMS_PER_MODE] [frantic|class]

"class" paces each student like a person (an action every 0.5-2 s, plus bursts of
25 reads as a reconnect flushes its buffer); "frantic" sends ~22 actions/s per
student to find the breaking point. Three scenarios run side by side:
  review — writers keep editing while teammates open the final review and mark
           ready at random moments; whoever is last ends it.
  end    — writers keep editing while several members press End at once.
  timer  — a 1-minute session; writers keep going past the deadline.

Then, per team, it checks the database: completed exactly once with exactly one
submission; the submitted document equals the final revision of each section
(so no write landed after the snapshot); every acked write is stored as acked;
study_events seq is 1..N, gapless and unique; every acked read sent at least a
second before the end is stored, once; every member was told the session ended.
Reads that arrive after the end are acked but deliberately not recorded.
"""
import asyncio, json, random, sys, time, uuid
import asyncpg, httpx, websockets

W = ["http://127.0.0.1:8101", "http://127.0.0.1:8102"]
WS = [u.replace("http", "ws") for u in W]
PG = sys.argv[1]
TEAMS_PER = int(sys.argv[2]) if len(sys.argv) > 2 else 4
# "frantic": ~22 actions/s per student, far past human. "class": every 0.5-2 s,
# plus a burst of 25 reads every ~20 s, as a reconnect flushes its buffer.
PACE = sys.argv[3] if len(sys.argv) > 3 else "frantic"
SECTIONS = ["a", "b", "c"]
h = lambda t: {"Authorization": f"Bearer {t}"}
problems = []


def bad(team, msg):
    problems.append(f"[{team}] {msg}")


class Member:
    def __init__(self, tok, uid, worker):
        self.tok, self.uid, self.worker = tok, uid, worker
        self.ws = None
        self.versions = {k: 0 for k in SECTIONS}
        self.acked_writes = []      # (section, version, content)
        self.acked_reads = set()
        self.read_sent_at = {}       # event_id -> wall time sent
        self.close_info = None
        self.ended = False
        self.frames = asyncio.Queue()

    async def connect(self, tid):
        self.ws = await websockets.connect(
            f"{WS[self.worker]}/ws/coach?token={self.tok}&group_id={tid}&session_num=1", max_size=None)
        self.reader = asyncio.create_task(self._read())

    async def _read(self):
        try:
            async for raw in self.ws:
                m = json.loads(raw)
                t = m.get("type")
                if t == "artifact":
                    for s in (m.get("data") or m).get("sections", []):
                        self.versions[s["key"]] = s["version"]
                elif t == "artifact_updated":
                    self.versions[m["section_key"]] = max(self.versions[m["section_key"]], m["version"])
                elif t == "artifact_write_ok":
                    if not m.get("unchanged"):
                        self.acked_writes.append((m["section_key"], m["version"], m.get("content")))
                    self.versions[m["section_key"]] = max(self.versions[m["section_key"]], m["version"])
                elif t == "artifact_conflict":
                    self.versions[m["section_key"]] = m["version"]
                elif t == "read_ack":
                    self.acked_reads.add(m["event_id"])
                elif t == "session_ended":
                    self.ended = True
                await self.frames.put(m)
        except websockets.ConnectionClosed as e:
            self.close_info = f"rcvd={e.rcvd and (e.rcvd.code, e.rcvd.reason)} sent={e.sent and (e.sent.code, e.sent.reason)}"
        if self.close_info is None and self.ws.close_code is not None:
            self.close_info = f"closed code={self.ws.close_code}"

    async def hammer(self, stop_at, team):
        """Write and read as fast as a frantic student could, until told to stop."""
        i = 0
        while time.time() < stop_at and not self.ended:
            k = random.choice(SECTIONS)
            i += 1
            try:
                if random.random() < 0.6:
                    await self.ws.send(json.dumps({
                        "type": "artifact_write", "section_key": k, "event_id": uuid.uuid4().hex,
                        "content": f"{team} {self.uid[:6]} edit {i} " + "x" * random.randint(0, 200),
                        "expected_version": self.versions[k]}))
                else:
                    eid = uuid.uuid4().hex
                    self.read_sent_at[eid] = time.time()
                    await self.ws.send(json.dumps({
                        "type": "artifact_expand", "section_key": k, "event_id": eid,
                        "client_ts": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())}))
            except websockets.ConnectionClosed:
                return
            if PACE == "frantic":
                await asyncio.sleep(random.uniform(0.01, 0.08))
                continue
            if random.random() < 0.03:
                for _ in range(25):
                    eid = uuid.uuid4().hex
                    self.read_sent_at[eid] = time.time()
                    try:
                        await self.ws.send(json.dumps({
                            "type": "artifact_expand", "section_key": random.choice(SECTIONS), "event_id": eid,
                            "client_ts": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())}))
                    except websockets.ConnectionClosed:
                        return
            await asyncio.sleep(random.uniform(0.5, 2.0))


async def setup(c, inst, cid, mode, n):
    timer = {"time_limit_minutes": 1} if mode == "timer" else {}
    ch = (await c.post(f"{W[0]}/challenges", headers=h(inst), json={
        "classroom_id": cid, "title": f"stress {mode} {n}", "description": "d", "mode": "group",
        "sections": [{"key": k, "title": k.upper()} for k in SECTIONS], **timer})).json()["id"]
    tid = (await c.post(f"{W[0]}/classrooms/{cid}/challenges/{ch}/teams", json={}, headers=h(inst))).json()["id"]
    return ch, tid


async def run_team(c, mode, n, members, tid):
    name = f"{mode}{n}"
    for i, m in enumerate(members):
        await m.connect(tid)
    await asyncio.sleep(1.0)

    if mode == "timer":
        # Keep writing for 75 s; the deadline is at 60 s from the first connect.
        await asyncio.gather(*[m.hammer(time.time() + 75, name) for m in members])
    else:
        stop = time.time() + (random.uniform(4, 8) if PACE == "frantic" else random.uniform(20, 40))
        writers = [asyncio.create_task(m.hammer(stop + 3, name)) for m in members]
        await asyncio.sleep(stop - time.time())
        if mode == "review":
            r = await c.post(f"{W[n % 2]}/groups/{tid}/sessions/1/review", headers=h(members[0].tok))
            if r.status_code != 200:
                bad(name, f"review open {r.status_code} {r.text[:120]}")
            # Everyone marks ready, repeatedly and at random moments, while
            # writes continue; any write withdraws the marks, so keep trying.
            async def keep_marking(m, w):
                for _ in range(60):
                    if any(x.ended for x in members):
                        return
                    r = await c.post(f"{W[w]}/groups/{tid}/sessions/1/ready", json={"ready": True}, headers=h(m.tok))
                    if r.status_code not in (200, 409):
                        bad(name, f"ready {r.status_code} {r.text[:160]}")
                    if r.status_code == 200 and r.json().get("ended"):
                        return
                    await asyncio.sleep(random.uniform(0.05, 0.3))
            await asyncio.gather(*[keep_marking(m, i % 2) for i, m in enumerate(members)])
        else:
            # Several members press End at the same instant, on both workers.
            rs = await asyncio.gather(*[
                c.post(f"{W[i % 2]}/groups/{tid}/sessions/1/end", headers=h(m.tok)) for i, m in enumerate(members)])
            for r in rs:
                if r.status_code not in (200, 409):
                    bad(name, f"end {r.status_code} {r.text[:160]}")
        await asyncio.gather(*writers)
        if mode == "review" and not any(m.ended for m in members):
            # Writes outlasted every ready attempt: finish it the plain way.
            await c.post(f"{W[0]}/groups/{tid}/sessions/1/end", headers=h(members[0].tok))

    await asyncio.sleep(3)
    for m in members:
        if not m.ended:
            bad(name, f"member {m.uid[:6]} never got session_ended ({m.close_info})")
        await m.ws.close()
    return name


async def verify(pool, name, tid, members):
    async with pool.acquire() as db:
        gss = await db.fetch("select id, status, completed_at, end_reason from group_sessions where group_id=$1", tid)
        if len(gss) != 1:
            return bad(name, f"{len(gss)} group sessions")
        gs = gss[0]
        if gs["status"] != "completed":
            return bad(name, f"status {gs['status']}")
        subs = await db.fetch("select sections, submitted_at from team_submissions where group_session_id=$1", gs["id"])
        if len(subs) != 1:
            return bad(name, f"{len(subs)} submissions")
        art = await db.fetchval("select id from artifacts where group_session_id=$1", gs["id"])
        final = {r["section_key"]: r["content"] for r in await db.fetch(
            "select distinct on (section_key) section_key, content from artifact_revisions "
            "where artifact_id=$1 order by section_key, version desc", art)}
        submitted = {s["key"]: s["content"] for s in json.loads(subs[0]["sections"])}
        for k in SECTIONS:
            if (final.get(k) or "") != (submitted.get(k) or ""):
                bad(name, f"section {k}: submitted text differs from the final revision")
        revs = {(r["section_key"], r["version"]): r["content"] for r in await db.fetch(
            "select section_key, version, content from artifact_revisions where artifact_id=$1", art)}
        for m in members:
            for k, v, content in m.acked_writes:
                if revs.get((k, v)) != content:
                    bad(name, f"acked write {k} v{v} not stored as acked")
        seqs = [r["seq"] for r in await db.fetch(
            "select seq from study_events where group_session_id=$1 order by seq", gs["id"])]
        if seqs != list(range(1, len(seqs) + 1)):
            bad(name, f"event seq not gapless/unique: {len(seqs)} rows, max {seqs[-1] if seqs else None}")
        keys = [r["idempotency_key"] for r in await db.fetch(
            "select idempotency_key from study_events where group_session_id=$1 and idempotency_key is not null", gs["id"])]
        acked = set().union(*[m.acked_reads for m in members])
        sent_at = {k: v for m in members for k, v in m.read_sent_at.items()}
        # Reads that reach the server after the end are acked but not recorded
        # by design. Anything sent a full second before completion must be in.
        done = gs["completed_at"].replace(tzinfo=None)
        cutoff = time.mktime(done.timetuple()) - time.timezone + done.microsecond / 1e6 - 1.0
        missing = [k for k in acked - set(keys) if sent_at.get(k, 0) < cutoff]
        if missing:
            bad(name, f"{len(missing)} acked reads sent before the end were not stored")
        if len(keys) != len(set(keys)):
            bad(name, "an event key is stored twice")
        writes = sum(len(m.acked_writes) for m in members)
        return dict(name=name, end_reason=gs["end_reason"], writes=writes, reads=len(acked), events=len(seqs))


async def main():
    tag = uuid.uuid4().hex[:6]
    limits = httpx.Limits(max_connections=200)
    async with httpx.AsyncClient(timeout=90, limits=limits) as c:
        async def reg(nm, i):
            j = (await c.post(f"{W[i % 2]}/auth/register", json={
                "email": f"{nm}_{tag}@northeastern.edu", "password": "Passw0rd!x", "name": nm})).json()
            return j["access_token"], j["user_id"]
        inst, _ = await reg("inst", 0)
        room = (await c.post(f"{W[0]}/classrooms", json={"name": f"stress {tag}"}, headers=h(inst))).json()
        cid = room["id"]
        teams = []
        k = 0
        for mode in ("review", "end", "timer"):
            for n in range(TEAMS_PER):
                ch, tid = await setup(c, inst, cid, mode, n)
                members = []
                for j in range(3):
                    tok, uid = await reg(f"s{k}", k); k += 1
                    await c.post(f"{W[0]}/classrooms/join", json={"code": room["join_code"]}, headers=h(tok))
                    await c.patch(f"{W[0]}/auth/me", json={"accept_research_notice": True}, headers=h(tok))
                    await c.post(f"{W[0]}/classrooms/{cid}/challenges/{ch}/teams/{tid}/members", json={"user_id": uid}, headers=h(inst))
                    members.append(Member(tok, uid, j % 2))
                teams.append((mode, n, members, tid))
        print(f"{len(teams)} teams, {k} students; running…", flush=True)
        t0 = time.time()
        await asyncio.gather(*[run_team(c, mode, n, members, tid) for mode, n, members, tid in teams])
        print(f"sessions done in {time.time() - t0:.0f}s; verifying", flush=True)

    pool = await asyncpg.create_pool(PG, statement_cache_size=0)
    rows = [await verify(pool, f"{mode}{n}", tid, members) for mode, n, members, tid in teams]
    await pool.close()
    for r in rows:
        if r:
            print(f"  {r['name']:8} end={r['end_reason']:<13} acked writes={r['writes']:<4} acked reads={r['reads']:<4} events={r['events']}")
    print(f"\n{len(problems)} problems")
    for p in problems:
        print("  ", p)


asyncio.run(main())
