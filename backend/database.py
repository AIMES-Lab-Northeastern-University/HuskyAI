import asyncio
import logging
import os
from datetime import datetime
from uuid import uuid4
from sqlalchemy import (
    CheckConstraint,
    Index,
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
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped

from sqlalchemy.pool import NullPool

from db_config import resolve_database_url, engine_connect_args, is_transaction_pooler

_db_url = resolve_database_url()
_engine_kw: dict = {"echo": os.getenv("SQL_ECHO", "").lower() in ("1", "true", "yes")}
_ca = engine_connect_args(_db_url)
if _ca:
    _engine_kw["connect_args"] = _ca

if is_transaction_pooler(_db_url):
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

IS_POSTGRES = _db_url.startswith("postgresql")

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


# A conversation's kind. Needed because a group session now holds more than one
# conversation: the team's shared coach thread, plus one PRIVATE thread per
# student. Without a discriminator, (group_session_id, user_id) would collide for
# the team creator, who owns the shared thread and also needs their own private one.
CONVERSATION_SOLO = "solo"
CONVERSATION_GROUP_SHARED = "group_shared"
CONVERSATION_GROUP_PRIVATE = "group_private"


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        # A unique INDEX rather than a table constraint: SQLite cannot add a
        # constraint to an existing table, but CREATE UNIQUE INDEX IF NOT EXISTS
        # works on both backends, so the same guarantee reaches an already
        # populated production database. NULL group_session_id (solo chats) is
        # distinct in both engines, so solo conversations are unconstrained.
        Index(
            "uq_conversation_group_user_kind",
            "group_session_id", "user_id", "kind",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    # solo | group_shared | group_private
    kind: Mapped[str] = mapped_column(String(24), default=CONVERSATION_SOLO, nullable=False, index=True)
    # The student's role in the group session, for role-split coaching
    # (e.g. "backend" / "frontend"). NULL when roles aren't in use.
    role_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    classroom_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("classrooms.id"), nullable=True, index=True
    )
    # Set when this is a shared group-challenge conversation. NULL for the normal
    # single-user flow. user_id above is still the conversation's creator/owner.
    group_session_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("group_sessions.id"), nullable=True, index=True
    )
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
    # Study condition: 'control' | 'treatment'. Assigned once, when the session
    # row is created, and never written again -- see _assign_study_arm in
    # main.py for why it is a TEAM-level draw stored per session.
    #
    # Nullable because rows created before this column existed have no arm and
    # must not be back-filled with a guess: a fabricated condition is worse than
    # a missing one, and analysis has to be able to exclude them.
    arm: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)


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


class ArtifactEvent(Base):
    """Append-only research log of what happened to a team's artifact.

    Reads and writes share ONE monotonic `seq` per group session. That is the
    whole point: the research question is whether a student read a teammate's
    section *before or after* writing their own, which is unanswerable if the two
    live on separate timelines. Never sampled, never pruned.

    Coach reads are kept structurally distinct from human reads, not merely
    distinguished by a string:
      - actor_kind is 'student' | 'coach' | 'system'
      - a CHECK constraint enforces that a coach/system event carries no user and
        a student event always does
      - the append helpers in artifact_events.py are separate functions, each
        hard-coding its own actor_kind and rejecting the other's event types
    so a coach read cannot be recorded as a human one even by a direct insert.
    """

    __tablename__ = "artifact_events"
    __table_args__ = (
        UniqueConstraint("group_session_id", "seq", name="uq_artifact_event_seq"),
        UniqueConstraint(
            "group_session_id", "idempotency_key", name="uq_artifact_event_idem"
        ),
        CheckConstraint(
            "(actor_kind = 'student' AND actor_user_id IS NOT NULL) OR "
            "(actor_kind IN ('coach', 'system') AND actor_user_id IS NULL)",
            name="ck_artifact_event_actor",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    group_session_id: Mapped[str] = mapped_column(
        String, ForeignKey("group_sessions.id"), nullable=False, index=True
    )
    # Monotonic within the session, shared by reads and writes.
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    # section_open | section_expand | section_write | section_read_by_coach | heartbeat_shed
    event_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    actor_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True, index=True
    )
    # NULL only for session-wide events such as heartbeat_shed.
    section_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Client clock is untrusted and kept only for skew analysis; server_ts orders.
    client_ts: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    server_ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    # Visible dwell time the client accumulated before the read qualified.
    dwell_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Which UI surface produced this. The coverage test uses it to prove every
    # surface that can show a teammate's section actually reports reads.
    surface: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ArtifactReadHeartbeat(Base):
    """Raw dwell samples. Low value individually, and the ONLY thing load
    shedding is ever allowed to drop. Prunable; ArtifactEvent is not."""

    __tablename__ = "artifact_read_heartbeats"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    group_session_id: Mapped[str] = mapped_column(
        String, ForeignKey("group_sessions.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    section_key: Mapped[str] = mapped_column(String(128), nullable=False)
    visible_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)


def _is_already_exists(exc: BaseException) -> bool:
    """True when a DDL/insert failed only because another worker got there first."""
    msg = str(exc).lower()
    return any(
        f in msg
        for f in ("already exists", "duplicate table", "duplicate column", "duplicate key")
    )


async def run_seed_step(name: str, step) -> None:
    """Run one idempotent startup seed step, tolerating a concurrent worker.

    Every seed step is a check-then-insert, so with several workers booting at
    once two can both see "missing" and both insert. The unique constraints in
    the schema are the arbiter: the loser gets an IntegrityError, and simply
    re-running the step then finds the winner's committed rows and does nothing.

    This is what makes startup safe without needing a distributed lock -- and so
    without needing Redis to be reachable at boot.
    """
    for attempt in range(3):
        try:
            await step()
            return
        except (IntegrityError, ProgrammingError, OperationalError) as e:
            if not _is_already_exists(e) and not isinstance(e, IntegrityError):
                raise
            if attempt == 2:
                logging.getLogger("database").warning(
                    "Seed step %r still conflicting after %d attempts; assuming another "
                    "worker completed it. Last error: %s", name, attempt + 1, e,
                )
                return
            logging.getLogger("database").info(
                "Seed step %r lost a race with another worker; re-running it.", name
            )
            await asyncio.sleep(0.2 * (attempt + 1))


class GroupArtifactSection(Base):
    """One editable section of a team's shared artifact, for one group session.

    The artifact is divided into fixed sections (one per subproblem, defined by
    the challenge). Students take a per-section lock to edit, so two people can
    work on different subproblems at once but never on the same one. There is no
    per-keystroke merging: a section is held by one editor until they release it.

    Scoped to the GroupSession, matching how rooms, turn locks and the pub/sub
    fan-out are already keyed. `version` increments on every committed write, so
    a client can tell whether the content it is looking at is still current.
    """

    __tablename__ = "group_artifact_sections"
    __table_args__ = (
        UniqueConstraint("group_session_id", "section_key", name="uq_artifact_section"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    group_session_id: Mapped[str] = mapped_column(
        String, ForeignKey("group_sessions.id"), nullable=False, index=True
    )
    # Stable identifier for the subproblem, from the challenge's sessions_data.
    section_key: Mapped[str] = mapped_column(String(128), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_by_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True, index=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 0 = the content here has not been edited during THIS session. Combined with
    # carried_from_session_number that distinguishes "carried over from last
    # session, untouched" from "the team wrote this here".
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Which earlier session this section's starting content was copied from, if
    # any. Records the provenance of the *initial* text only; `version` says
    # whether it has been edited since, so this is never cleared on write.
    carried_from_session_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


async def init_db():
    # create_all checks-then-creates, so two workers starting against an empty
    # database can collide. Whoever loses just sees "already exists".
    for attempt in range(3):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            break
        except Exception as e:
            if not _is_already_exists(e) or attempt == 2:
                raise
            await asyncio.sleep(0.2 * (attempt + 1))
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
            # Private per-student coach conversations inside a group session
            # (2026-09-11). Existing rows are classified by whether they belong
            # to a group session; the unique index is created after the backfill
            # so it cannot trip on un-classified rows.
            await conn.execute(
                text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS kind VARCHAR(24) NOT NULL DEFAULT 'solo'")
            )
            await conn.execute(
                text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS role_label VARCHAR(64)")
            )
            await conn.execute(
                text("UPDATE conversations SET kind = 'group_shared' "
                     "WHERE group_session_id IS NOT NULL AND kind = 'solo'")
            )
            await conn.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS uq_conversation_group_user_kind "
                     "ON conversations (group_session_id, user_id, kind)")
            )
            await conn.execute(
                text("ALTER TABLE group_sessions ADD COLUMN IF NOT EXISTS arm VARCHAR(16)")
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
                # Private per-student coach conversations (2026-09-11).
                ("ALTER TABLE conversations ADD COLUMN kind VARCHAR(24) DEFAULT 'solo'", ("duplicate column", "already exists")),
                ("ALTER TABLE conversations ADD COLUMN role_label VARCHAR(64)", ("duplicate column", "already exists")),
                ("UPDATE conversations SET kind = 'group_shared' WHERE group_session_id IS NOT NULL AND (kind IS NULL OR kind = 'solo')", ()),
                ("UPDATE conversations SET kind = 'solo' WHERE kind IS NULL", ()),
                ("CREATE UNIQUE INDEX IF NOT EXISTS uq_conversation_group_user_kind ON conversations (group_session_id, user_id, kind)", ()),
                # Team-level study arm (2026-09-11).
                ("ALTER TABLE group_sessions ADD COLUMN arm VARCHAR(16)", ("duplicate column", "already exists")),
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
