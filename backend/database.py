import os
from datetime import datetime
from uuid import uuid4
from sqlalchemy import (
    String,
    DateTime,
    Float,
    Integer,
    ForeignKey,
    JSON,
    Text,
    Boolean,
    LargeBinary,
    UniqueConstraint,
    text,
)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped

from sqlalchemy.pool import NullPool

from db_config import resolve_database_url, engine_connect_args, is_transaction_pooler

_db_url = resolve_database_url()
_engine_kw: dict = {"echo": os.getenv("SQL_ECHO", "").lower() in ("1", "true", "yes")}
_ca = engine_connect_args(_db_url)
if _ca:
    _engine_kw["connect_args"] = _ca

if _db_url.startswith("sqlite"):
    # aiosqlite ties each connection to the event loop that opened it, and a
    # pooled connection handed to a different loop deadlocks rather than erroring.
    # That bites local dev and the test suite, where setup, a TestClient's
    # portal loop, and assertions each run their own loop. NullPool opens per
    # checkout, so a connection never crosses loops. Cheap for a local file DB.
    _engine_kw["poolclass"] = NullPool
elif is_transaction_pooler(_db_url):
    # Transaction pooler (Supavisor :6543) does its own connection pooling and
    # rotates server connections per transaction, so a client-side pool would just
    # pin connections and re-introduce the session-mode 'max clients' cap. Use
    # NullPool: open per checkout, hand back immediately. (statement_cache_size=0
    # is set in engine_connect_args — required for asyncpg in transaction mode.)
    _engine_kw["poolclass"] = NullPool
elif _db_url.startswith("postgresql"):
    # Session pooler (:5432) / direct: it caps total client connections (~15) and
    # holds one per client session. SQLAlchemy's async default (5 + 10 overflow = 15)
    # saturates that exactly, and uvicorn --reload leaves stale connections that eat
    # the cap. Keep our pool well under it, pre-ping to drop dead conns, recycle to
    # beat pooler timeouts. Overridable via env. (Prefer the :6543 transaction pooler.)
    _engine_kw.update(
        pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
        max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "2")),
        pool_pre_ping=True,
        pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "1800")),
        pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "30")),
    )

engine = create_async_engine(_db_url, **_engine_kw)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    consent_research: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # When the user accepted the research-use notice. NULL = not yet acknowledged,
    # which is what triggers the blocking acceptance gate on login.
    research_ack_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Audit only: when the password last changed. Not used for enforcement.
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Incremented on every password change; tokens embed the value current at issue
    # and are rejected when it no longer matches, so a reset immediately kills any
    # existing session. A counter rather than a timestamp on purpose: JWT `iat` has
    # whole-second resolution, so a clock comparison cannot distinguish a token
    # issued in the same second as the reset from one issued just before it.
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class PasswordResetToken(Base):
    """One row per issued password-reset link.

    Only the SHA-256 of the token is stored: the raw value goes out in the email
    once and is never needed again, so a leaked table is useless for takeover.
    SHA-256 rather than bcrypt is deliberate — the token is 256 bits of entropy
    from `secrets`, so there is nothing to brute-force and no need for a slow KDF.
    """

    __tablename__ = "password_reset_tokens"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Classroom(Base):
    __tablename__ = "classrooms"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    join_code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, index=True)
    instructor_user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    listed_in_directory: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )  # when True, section appears on Browse for any signed-in user
    is_test_section: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )  # label + auto test-as-student enrollment for creator


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    classroom_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("classrooms.id"), nullable=True, index=True
    )
    # Set when this is a shared group-challenge conversation. NULL for the normal
    # single-user flow. user_id above is still the conversation's creator/owner.
    group_session_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("group_sessions.id"), nullable=True, index=True
    )
    # What this conversation *is*:
    #   solo          - the single-user control arm (user_id set, no group session)
    #   group_shared  - the legacy one-conversation-per-team chat (/ws/group)
    #   coach_private - one student's private coach inside a group session
    # A private coach needs no new table: it is a Conversation with BOTH user_id
    # (whose coach it is) and group_session_id (which team session it belongs to).
    # Defaults to "solo" so every pre-existing row keeps its meaning.
    kind: Mapped[str] = mapped_column(String(16), default="solo", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    turn_count: Mapped[int] = mapped_column(Integer, default=0)
    # OpenAI vector store backing this conversation's document-citation search
    # (see backend/main.py's `_ensure_conversation_vector_store`). NULL until the
    # first indexable attachment is uploaded.
    openai_vector_store_id: Mapped[str | None] = mapped_column(String, nullable=True)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    conversation_id: Mapped[str] = mapped_column(String, ForeignKey("conversations.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Which group member authored a user message, so a shared transcript can
    # attribute prompts. NULL for single-user conversations and assistant turns.
    sender_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Attachment(Base):
    """A file (document/image) a user uploaded with a chat message. Bytes are
    stored inline so attachments survive reconnects/redeploys (the deploy target
    has an ephemeral filesystem). message_id links it to the user Message it was
    sent with; it's nullable only during the brief window before the turn is saved."""

    __tablename__ = "attachments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    conversation_id: Mapped[str] = mapped_column(String, ForeignKey("conversations.id"), nullable=False, index=True)
    message_id: Mapped[str | None] = mapped_column(String, ForeignKey("messages.id"), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # Document-citation indexing state (see backend/main.py's `_index_attachment`).
    # NULL/"pending" until the background index task finishes; "ready" once the
    # file is searchable in the conversation's vector store; "failed"/"skipped"
    # otherwise (e.g. unsupported mime type, upload error).
    openai_file_id: Mapped[str | None] = mapped_column(String, nullable=True)
    index_status: Mapped[str | None] = mapped_column(String(16), nullable=True)


class EvalResult(Base):
    __tablename__ = "eval_results"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    conversation_id: Mapped[str] = mapped_column(String, ForeignKey("conversations.id"), nullable=False, index=True)
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)
    pei: Mapped[float | None] = mapped_column(Float, nullable=True)
    psq: Mapped[float | None] = mapped_column(Float, nullable=True)
    ccm: Mapped[float | None] = mapped_column(Float, nullable=True)
    tsi: Mapped[float | None] = mapped_column(Float, nullable=True)
    clm: Mapped[float | None] = mapped_column(Float, nullable=True)
    ras: Mapped[float | None] = mapped_column(Float, nullable=True)
    classification: Mapped[str | None] = mapped_column(String(64), nullable=True)
    leading_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Snapshot of the user's research consent at the moment this turn was scored.
    # Consent is captured per turn (the export unit) so it is immune to mid-session
    # toggles and resumed conversations. The export's consent filter reads this.
    consent_research: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Marks the consequential post-feed revision: the scored artifact of record
    # for that session. The pre-revision score is retained as its own row, so
    # the delta between seeing the feed and acting on it stays measurable.
    is_graded_revision: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Challenge(Base):
    __tablename__ = "challenges"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(64), nullable=False)
    week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_sessions: Mapped[int] = mapped_column(Integer, default=3)
    sessions_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Timed-session settings (challenge-level, apply to all of its sessions).
    # NULL = untimed / no minimum, so existing challenges are unaffected.
    time_limit_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_turns: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="published", nullable=False)  # draft | published
    created_by_user_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=datetime.utcnow, nullable=True)


class UserChallengeSession(Base):
    __tablename__ = "user_challenge_sessions"
    __table_args__ = (
        UniqueConstraint("user_id", "challenge_id", "session_number", name="uq_user_challenge_session_num"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    challenge_id: Mapped[str] = mapped_column(String, ForeignKey("challenges.id"), nullable=False, index=True)
    session_number: Mapped[int] = mapped_column(Integer, nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(String, ForeignKey("conversations.id"), nullable=True)
    best_pei: Mapped[float | None] = mapped_column(Float, nullable=True)
    session_avg_pei: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="not_started")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # How a completed session ended, decided server-side: "manual" (user ended
    # it) or "timer_expired" (deadline hit / auto-finalized). Null until completed
    # and for sessions completed before this field existed.
    end_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Snapshot of the challenge's timer settings, captured when this session
    # starts, so later instructor edits don't disrupt an in-progress attempt.
    time_limit_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_turns: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Post-session analysis: an LLM-written synthesis of the whole session,
    # generated once in the background when the session is marked completed.
    # JSON shape: {status: "pending"|"ready"|"failed", session_pei, level,
    # dimension_averages, strongest_dimension, weakest_dimension, trend,
    # narrative, takeaways, strengths, turns_analyzed, generated_at, model}.
    session_analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ClassroomMembership(Base):
    __tablename__ = "classroom_memberships"
    __table_args__ = (UniqueConstraint("user_id", "classroom_id", name="uq_membership_user_classroom"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    classroom_id: Mapped[str] = mapped_column(String, ForeignKey("classrooms.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ClassroomChallenge(Base):
    """Which challenges are assigned to a section (students only see these after joining)."""

    __tablename__ = "classroom_challenges"
    __table_args__ = (UniqueConstraint("classroom_id", "challenge_id", name="uq_classroom_challenge"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    classroom_id: Mapped[str] = mapped_column(String, ForeignKey("classrooms.id"), nullable=False, index=True)
    challenge_id: Mapped[str] = mapped_column(String, ForeignKey("challenges.id"), nullable=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # How this challenge runs *in this section*: "solo" (the normal single-user
    # flow) or "group" (prof-assigned teams collaborate in one shared chat). Group
    # mode is an assignment-level property — the same challenge can be solo in one
    # section and group in another. team_min/team_max bound a team's size; group
    # mode is strict (a team needs >= team_min members live to run a turn).
    mode: Mapped[str] = mapped_column(String(16), default="solo", nullable=False)  # solo | group
    team_min: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    team_max: Mapped[int] = mapped_column(Integer, default=4, nullable=False)

    # ---- Collaborative-study configuration -------------------------------
    # Every flag below defaults to today's behaviour, so an assignment that
    # predates the study is unchanged and no section is silently enrolled.

    # Which arm this section runs:
    #   control_solo_feed     - the existing single-user chat + PEI feed
    #   collab_coach_artifact - per-student private coaches + one shared artifact
    study_arm: Mapped[str] = mapped_column(
        String(32), default="control_solo_feed", nullable=False
    )
    # How prominent the coach is. An experimental condition, not a product
    # choice — resolved once per session into a CoachPolicy (see main.py).
    #   ambient    - reacts to artifact changes unprompted, visible in the shared space
    #   on_request - responds only when addressed (today's behaviour)
    #   isolated   - reachable, but its output never flows into the artifact
    #                automatically; importing it takes an explicit, logged copy
    coach_prominence: Mapped[str] = mapped_column(
        String(16), default="on_request", nullable=False
    )
    # Post-feed revision rules for the control arm, e.g.
    # {"require_revision_on_turn": 3, "graded": "revision"}. NULL = no revision
    # step, which is how every existing assignment behaves.
    revision_policy: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Who reviews whose work (Phase 5): none | round_robin | random | instructor_assigned
    verification_policy: Mapped[str] = mapped_column(
        String(32), default="none", nullable=False
    )


class InstructorTestEnrollment(Base):
    """Instructor opts in to see a section's assigned challenges on the student Challenges list (try-before-class)."""

    __tablename__ = "instructor_test_enrollments"
    __table_args__ = (UniqueConstraint("user_id", "classroom_id", name="uq_instructor_test_room"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    classroom_id: Mapped[str] = mapped_column(String, ForeignKey("classrooms.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class GroupChallenge(Base):
    """A team of 2-4 students collaborating on one challenge together. The team
    persists across all of the challenge's sessions (same teammates throughout)
    and shares one conversation + one PEI per session through GroupSession.

    Instructor-driven model (2026-06-21 redesign): a team belongs to a classroom
    and is created by the instructor, who assigns members from the section roster.
    Eligibility is classroom membership — there is no student self-join. join_code
    is retired (kept nullable for back-compat with the old student-initiated rows)."""

    __tablename__ = "group_challenges"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    challenge_id: Mapped[str] = mapped_column(String, ForeignKey("challenges.id"), nullable=False, index=True)
    # The section this team belongs to. Nullable only so pre-redesign rows (created
    # before this column existed) still load; all new teams set it.
    classroom_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("classrooms.id"), nullable=True, index=True
    )
    # Optional human label for the team (e.g. "Team 1"); falls back to a default in the UI.
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Retired: the old student-initiated join code. Nullable now; new prof-assigned
    # teams leave it NULL. Kept (unique) so existing rows are undisturbed.
    join_code: Mapped[str | None] = mapped_column(String(16), unique=True, nullable=True, index=True)
    # The instructor who created the team (was the originating student pre-redesign).
    created_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)  # open | active | completed
    max_members: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class GroupMember(Base):
    """Membership of a user in a GroupChallenge team."""

    __tablename__ = "group_members"
    __table_args__ = (UniqueConstraint("group_id", "user_id", name="uq_group_member"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    group_id: Mapped[str] = mapped_column(String, ForeignKey("group_challenges.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class GroupSession(Base):
    """Group analog of UserChallengeSession: one row per (group, session_number).
    Holds the team's shared conversation and their single PEI for that session.
    Mirrors UserChallengeSession's scoring/timer/analysis fields so the existing
    per-turn and post-session logic can be reused with minimal branching."""

    __tablename__ = "group_sessions"
    __table_args__ = (
        UniqueConstraint("group_id", "session_number", name="uq_group_session_num"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    group_id: Mapped[str] = mapped_column(String, ForeignKey("group_challenges.id"), nullable=False, index=True)
    challenge_id: Mapped[str] = mapped_column(String, ForeignKey("challenges.id"), nullable=False, index=True)
    session_number: Mapped[int] = mapped_column(Integer, nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(String, ForeignKey("conversations.id"), nullable=True)
    best_pei: Mapped[float | None] = mapped_column(Float, nullable=True)
    session_avg_pei: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="not_started")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    end_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Timer settings snapshotted from the challenge when the group session starts.
    time_limit_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_turns: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Post-session analysis blob; same shape as UserChallengeSession.session_analysis.
    session_analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class GroupChatMessage(Base):
    """Team backchannel: student-to-student discussion within a group challenge,
    separate from the coach (LLM) conversation. DELIBERATELY not linked to
    Conversation/Message — this stream must never enter the Gemini prompt history,
    the PEI evaluator, or the de-identified training export. It is human-only
    deliberation, scoped to one team, and free-form (no turn lock)."""

    __tablename__ = "group_chat_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    group_id: Mapped[str] = mapped_column(String, ForeignKey("group_challenges.id"), nullable=False, index=True)
    sender_user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class StudyEvent(Base):
    """The collaborative-study event log: one ordered, append-only record of every
    action in a session — including *reads* of a teammate's work.

    Why this table exists at all: `artifact_revision` and `messages` answer who
    wrote what, but only this log answers who looked at whose work before writing,
    which is the question the study is asking. A read that goes unrecorded cannot
    be reconstructed from a database of final states, so this log is the one part
    of the design that must be right the first time.

    Three rules this schema enforces, and the reasons they are structural rather
    than conventional (see docs/collab-study-build-plan.md, "The read requirement"):

    - **Reads and writes share one sequence space.** `seq` is monotonic per
      session and assigned server-side (see events.py::log_event), so whether a
      student read a teammate's contribution *before* or *after* writing their own
      is answerable. Reads in a side table with their own clock could not answer it.
    - **No sampling.** `idempotency_key` is unique, so client delivery can be
      at-least-once and dedupe on ingest. Under-recording is not a tunable.
    - **client_ts is never trusted for ordering.** It is kept for latency analysis
      only; `seq` and `server_ts` are authoritative.

    A row is scoped to exactly one session: `group_session_id` for collaborative
    work, `user_challenge_session_id` for the solo control arm.
    """

    __tablename__ = "study_events"
    __table_args__ = (
        # One seq per session scope. Two constraints rather than one because a row
        # belongs to exactly one scope and the other column is NULL; both engines
        # treat NULLs as distinct, so the unused constraint never collides.
        UniqueConstraint("group_session_id", "seq", name="uq_study_event_group_seq"),
        UniqueConstraint("user_challenge_session_id", "seq", name="uq_study_event_solo_seq"),
        UniqueConstraint("idempotency_key", name="uq_study_event_idempotency"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))

    # Session scope: exactly one of these is set (enforced in events.py::log_event).
    group_session_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("group_sessions.id"), nullable=True, index=True
    )
    user_challenge_session_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("user_challenge_sessions.id"), nullable=True, index=True
    )
    # Denormalised for analysis-time filtering without a four-table join.
    classroom_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("classrooms.id"), nullable=True, index=True
    )
    challenge_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("challenges.id"), nullable=True, index=True
    )

    # Monotonic per session, assigned server-side under a per-session lock. The
    # total order across reads and writes is the finding, not a convenience.
    seq: Mapped[int] = mapped_column(Integer, nullable=False)

    actor_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True, index=True
    )
    # student | coach | system. A coach-mediated read is attributed to the student
    # whose prompt it entered, with actor_kind="coach" — never merged into human opens.
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    # The student's role-scoped label at the time of the event (Phase 1 roles).
    # NULL until the role taxonomy lands.
    role_label: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # coach | artifact | group_chat | feed | contested | verification
    target: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Row this event points at (a Message.id, artifact_revision.id, ...). Untyped
    # by design: targets live in different tables, so no FK.
    ref_id: Mapped[str | None] = mapped_column(String, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Client-supplied, preserved across a buffered reconnect flush. For latency
    # analysis only — never for ordering.
    client_ts: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    server_ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # Dedupe key for at-least-once client delivery. NULL for server-emitted events,
    # which cannot be double-delivered.
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Consent snapshotted per row, matching EvalResult.consent_research, so the
    # export is immune to a later toggle.
    consent_research: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Resolved experimental condition (arm, prominence, corpus id) written onto
    # every row so an exported log is self-describing.
    condition: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Artifact(Base):
    """The one shared document a team reads and writes. One per group session.

    Content lives in ArtifactSection rows, not here: a section is the unit of
    both write conflict and read granularity, and the study's central question
    ("did this student read that teammate's contribution before writing their
    own?") is only answerable if a read can name a part of the document rather
    than the whole panel. Sections are instructor-definable per assignment; an
    artifact with none defined gets a single implicit section (IMPLICIT_SECTION_KEY)
    and behaves like a free-form document.
    """

    __tablename__ = "artifacts"
    __table_args__ = (UniqueConstraint("group_session_id", name="uq_artifact_group_session"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    group_session_id: Mapped[str] = mapped_column(
        String, ForeignKey("group_sessions.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_by_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )


class ArtifactSection(Base):
    """One writable region of the shared artifact, and the unit of optimistic
    concurrency: a write carries the version it was based on, and is rejected
    with the current version if a teammate got there first, so the client can
    rebase rather than clobber."""

    __tablename__ = "artifact_sections"
    __table_args__ = (UniqueConstraint("artifact_id", "key", name="uq_artifact_section_key"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    artifact_id: Mapped[str] = mapped_column(
        String, ForeignKey("artifacts.id"), nullable=False, index=True
    )
    # Stable identifier used by read events and (later) Phase 4 subproblem pairing.
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # Bumped on every accepted write. Starts at 0 for an empty section.
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_by_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )


class ArtifactRevision(Base):
    """Append-only history of every accepted section write.

    A research record, not an undo buffer, so revisions are never pruned and
    never rewritten. `origin` distinguishes text the student typed from text
    they copied out of their coach — the difference between a student's own work
    and adopted AI output is a finding, not an implementation detail."""

    __tablename__ = "artifact_revisions"
    __table_args__ = (
        UniqueConstraint("section_id", "version", name="uq_artifact_revision_version"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    artifact_id: Mapped[str] = mapped_column(
        String, ForeignKey("artifacts.id"), nullable=False, index=True
    )
    section_id: Mapped[str] = mapped_column(
        String, ForeignKey("artifact_sections.id"), nullable=False, index=True
    )
    # Denormalised so a revision stays readable if a section is ever renamed.
    section_key: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    author_user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    # student_typed | coach_copied | verification_edit
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    bytes_added: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bytes_removed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# Columns added to already-existing tables, as (table, column, DDL type).
# `create_all` creates missing TABLES but never missing COLUMNS, and Alembic does
# not run against SQLite here — so without this, adding a column to an existing
# model leaves every SQLite database (local dev, the test suite) with an ORM that
# writes a column the file does not have. That fails at INSERT time, far from the
# cause: the first symptom of adding Conversation.kind was an empty artifact panel.
_SQLITE_ADDED_COLUMNS = [
    ("conversations", "kind", "VARCHAR(16) NOT NULL DEFAULT 'solo'"),
    ("classroom_challenges", "study_arm", "VARCHAR(32) NOT NULL DEFAULT 'control_solo_feed'"),
    ("classroom_challenges", "coach_prominence", "VARCHAR(16) NOT NULL DEFAULT 'on_request'"),
    ("classroom_challenges", "revision_policy", "JSON"),
    ("classroom_challenges", "verification_policy", "VARCHAR(32) NOT NULL DEFAULT 'none'"),
    ("eval_results", "is_graded_revision", "BOOLEAN NOT NULL DEFAULT 0"),
]


async def _ensure_sqlite_columns(conn):
    """Add any column in _SQLITE_ADDED_COLUMNS that the file is missing.

    SQLite has no ADD COLUMN IF NOT EXISTS, so existence is checked with PRAGMA
    first. Mirrors the Postgres ALTER block below; both paths exist because the
    deploy is Postgres and everything else is SQLite."""
    for table, column, ddl in _SQLITE_ADDED_COLUMNS:
        try:
            cols = {row[1] for row in (await conn.exec_driver_sql(f"PRAGMA table_info({table})")).fetchall()}
            if not cols:
                continue  # table does not exist yet; create_all will have made it
            if column not in cols:
                await conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        except Exception as e:  # never block startup on a best-effort backfill
            import logging
            logging.getLogger("database").warning(
                "could not add %s.%s on sqlite: %s", table, column, e
            )


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    if _db_url.startswith("sqlite"):
        async with engine.begin() as conn:
            await _ensure_sqlite_columns(conn)
    # Postgres: ORM expects listed_in_directory; older DBs (pre-Alembic) need the column added.
    if "postgresql" in _db_url.lower():
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "ALTER TABLE classrooms ADD COLUMN IF NOT EXISTS "
                    "listed_in_directory BOOLEAN NOT NULL DEFAULT false"
                )
            )
            await conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
                    "is_platform_admin BOOLEAN NOT NULL DEFAULT false"
                )
            )
            await conn.execute(
                text(
                    "ALTER TABLE classrooms ADD COLUMN IF NOT EXISTS "
                    "is_test_section BOOLEAN NOT NULL DEFAULT false"
                )
            )
            await conn.execute(
                text(
                    "ALTER TABLE user_challenge_sessions ADD COLUMN IF NOT EXISTS "
                    "session_avg_pei FLOAT"
                )
            )
            await conn.execute(
                text(
                    "ALTER TABLE eval_results ADD COLUMN IF NOT EXISTS "
                    "consent_research BOOLEAN NOT NULL DEFAULT false"
                )
            )
            # Existing rows are all either solo or the legacy shared group chat;
            # "solo" is the safe default and group_session_id still distinguishes them.
            await conn.execute(
                text(
                    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS "
                    "kind VARCHAR(16) NOT NULL DEFAULT 'solo'"
                )
            )
            # Study configuration. Defaults reproduce today's behaviour exactly,
            # so no existing section is enrolled into an arm by deploying this.
            for _ddl in (
                "ALTER TABLE classroom_challenges ADD COLUMN IF NOT EXISTS "
                "study_arm VARCHAR(32) NOT NULL DEFAULT 'control_solo_feed'",
                "ALTER TABLE classroom_challenges ADD COLUMN IF NOT EXISTS "
                "coach_prominence VARCHAR(16) NOT NULL DEFAULT 'on_request'",
                "ALTER TABLE classroom_challenges ADD COLUMN IF NOT EXISTS revision_policy JSONB",
                "ALTER TABLE classroom_challenges ADD COLUMN IF NOT EXISTS "
                "verification_policy VARCHAR(32) NOT NULL DEFAULT 'none'",
                "ALTER TABLE eval_results ADD COLUMN IF NOT EXISTS "
                "is_graded_revision BOOLEAN NOT NULL DEFAULT false",
            ):
                await conn.execute(text(_ddl))
            # NULL for accounts that predate password-reset support: those tokens
            # stay valid until they expire naturally, which is the safe default.
            await conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
                    "password_changed_at TIMESTAMP WITHOUT TIME ZONE"
                )
            )
            # Existing sessions carry no tv claim, which reads as 0 and matches this
            # default — so nobody is logged out by deploying the reset feature.
            await conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
                    "token_version INTEGER NOT NULL DEFAULT 0"
                )
            )
            # research_ack_at + one-time consent backfill. The backfill (make ALL
            # pre-existing data research-usable) must run exactly once, so we gate
            # it on whether the column already existed before this deploy.
            _had_ack = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name='users' AND column_name='research_ack_at'"
                    )
                )
            ).first() is not None
            await conn.execute(
                text("ALTER TABLE users ADD COLUMN IF NOT EXISTS research_ack_at TIMESTAMP")
            )
            if not _had_ack:
                await conn.execute(
                    text("UPDATE eval_results SET consent_research = true WHERE consent_research = false")
                )
                await conn.execute(
                    text("UPDATE users SET consent_research = true WHERE consent_research = false")
                )
            # Timed-session settings (nullable = untimed; existing rows unaffected).
            for _tbl in ("challenges", "user_challenge_sessions"):
                await conn.execute(
                    text(f"ALTER TABLE {_tbl} ADD COLUMN IF NOT EXISTS time_limit_minutes INTEGER")
                )
                await conn.execute(
                    text(f"ALTER TABLE {_tbl} ADD COLUMN IF NOT EXISTS min_turns INTEGER")
                )
            # Post-session analysis blob (nullable; generated lazily on completion).
            await conn.execute(
                text(
                    "ALTER TABLE user_challenge_sessions ADD COLUMN IF NOT EXISTS "
                    "session_analysis JSON"
                )
            )
            # Group-challenge links on existing tables (the new group_* tables
            # themselves are created by create_all above). Nullable = single-user
            # flow unaffected.
            await conn.execute(
                text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS group_session_id VARCHAR")
            )
            await conn.execute(
                text("ALTER TABLE messages ADD COLUMN IF NOT EXISTS sender_user_id VARCHAR")
            )
            # Instructor-driven group redesign (2026-06-21): assignment-level group
            # mode + team-scoped columns. Defaults keep every existing assignment solo.
            await conn.execute(
                text("ALTER TABLE classroom_challenges ADD COLUMN IF NOT EXISTS mode VARCHAR(16) NOT NULL DEFAULT 'solo'")
            )
            await conn.execute(
                text("ALTER TABLE classroom_challenges ADD COLUMN IF NOT EXISTS team_min INTEGER NOT NULL DEFAULT 2")
            )
            await conn.execute(
                text("ALTER TABLE classroom_challenges ADD COLUMN IF NOT EXISTS team_max INTEGER NOT NULL DEFAULT 4")
            )
            await conn.execute(
                text("ALTER TABLE group_challenges ADD COLUMN IF NOT EXISTS classroom_id VARCHAR")
            )
            await conn.execute(
                text("ALTER TABLE group_challenges ADD COLUMN IF NOT EXISTS name VARCHAR(200)")
            )
            # join_code is retired (prof-assigned teams leave it NULL) — relax NOT NULL.
            await conn.execute(
                text("ALTER TABLE group_challenges ALTER COLUMN join_code DROP NOT NULL")
            )
            # Document-citation retrieval (2026-08-15): per-conversation OpenAI
            # vector store + per-attachment indexing state. All nullable = no
            # behavior change until an attachment is uploaded.
            await conn.execute(
                text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS openai_vector_store_id VARCHAR")
            )
            await conn.execute(
                text("ALTER TABLE attachments ADD COLUMN IF NOT EXISTS openai_file_id VARCHAR")
            )
            await conn.execute(
                text("ALTER TABLE attachments ADD COLUMN IF NOT EXISTS index_status VARCHAR(16)")
            )
    if "sqlite" in _db_url.lower():
        async with engine.begin() as conn:
            # Detect whether research_ack_at already exists, to gate the one-time backfill.
            _cols = (await conn.execute(text("PRAGMA table_info(users)"))).fetchall()
            _had_ack = any(row[1] == "research_ack_at" for row in _cols)
            for stmt, ok_fragments in (
                ("ALTER TABLE users ADD COLUMN consent_research INTEGER DEFAULT 0", ("duplicate column", "already exists")),
                ("ALTER TABLE conversations ADD COLUMN classroom_id VARCHAR", ("duplicate column", "already exists")),
                ("ALTER TABLE challenges ADD COLUMN status VARCHAR(32) DEFAULT 'published'", ("duplicate column", "already exists")),
                ("ALTER TABLE challenges ADD COLUMN created_by_user_id VARCHAR", ("duplicate column", "already exists")),
                ("ALTER TABLE challenges ADD COLUMN updated_at DATETIME", ("duplicate column", "already exists")),
                ("ALTER TABLE challenges ADD COLUMN is_active INTEGER DEFAULT 1", ("duplicate column", "already exists")),
                ("ALTER TABLE classrooms ADD COLUMN listed_in_directory INTEGER DEFAULT 0", ("duplicate column", "already exists")),
                ("ALTER TABLE users ADD COLUMN is_platform_admin INTEGER DEFAULT 0", ("duplicate column", "already exists")),
                ("ALTER TABLE classrooms ADD COLUMN is_test_section INTEGER DEFAULT 0", ("duplicate column", "already exists")),
                ("ALTER TABLE user_challenge_sessions ADD COLUMN session_avg_pei REAL", ("duplicate column", "already exists")),
                ("ALTER TABLE eval_results ADD COLUMN consent_research INTEGER DEFAULT 0", ("duplicate column", "already exists")),
                ("ALTER TABLE users ADD COLUMN research_ack_at DATETIME", ("duplicate column", "already exists")),
                ("ALTER TABLE challenges ADD COLUMN time_limit_minutes INTEGER", ("duplicate column", "already exists")),
                ("ALTER TABLE challenges ADD COLUMN min_turns INTEGER", ("duplicate column", "already exists")),
                ("ALTER TABLE user_challenge_sessions ADD COLUMN time_limit_minutes INTEGER", ("duplicate column", "already exists")),
                ("ALTER TABLE user_challenge_sessions ADD COLUMN min_turns INTEGER", ("duplicate column", "already exists")),
                ("ALTER TABLE user_challenge_sessions ADD COLUMN session_analysis JSON", ("duplicate column", "already exists")),
                ("ALTER TABLE conversations ADD COLUMN group_session_id VARCHAR", ("duplicate column", "already exists")),
                ("ALTER TABLE messages ADD COLUMN sender_user_id VARCHAR", ("duplicate column", "already exists")),
                # Instructor-driven group redesign (2026-06-21).
                ("ALTER TABLE classroom_challenges ADD COLUMN mode VARCHAR(16) DEFAULT 'solo'", ("duplicate column", "already exists")),
                ("ALTER TABLE classroom_challenges ADD COLUMN team_min INTEGER DEFAULT 2", ("duplicate column", "already exists")),
                ("ALTER TABLE classroom_challenges ADD COLUMN team_max INTEGER DEFAULT 4", ("duplicate column", "already exists")),
                ("ALTER TABLE group_challenges ADD COLUMN classroom_id VARCHAR", ("duplicate column", "already exists")),
                ("ALTER TABLE group_challenges ADD COLUMN name VARCHAR(200)", ("duplicate column", "already exists")),
                # Document-citation retrieval (2026-08-15).
                ("ALTER TABLE conversations ADD COLUMN openai_vector_store_id VARCHAR", ("duplicate column", "already exists")),
                ("ALTER TABLE attachments ADD COLUMN openai_file_id VARCHAR", ("duplicate column", "already exists")),
                ("ALTER TABLE attachments ADD COLUMN index_status VARCHAR(16)", ("duplicate column", "already exists")),
            ):
                try:
                    await conn.execute(text(stmt))
                except Exception as e:
                    err = str(e).lower()
                    if not any(f in err for f in ok_fragments):
                        import logging

                        logging.getLogger("database").warning("SQLite migrate: %s — %s", stmt, e)
            # One-time backfill: make ALL pre-existing data research-usable. Runs
            # only on the first deploy that introduces research_ack_at.
            if not _had_ack:
                await conn.execute(text("UPDATE eval_results SET consent_research = 1 WHERE consent_research = 0"))
                await conn.execute(text("UPDATE users SET consent_research = 1 WHERE consent_research = 0"))
