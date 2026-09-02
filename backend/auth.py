import hashlib
import logging
import os
import re
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Header, Request
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select, update

from database import PasswordResetToken, User, AsyncSessionLocal
from emailer import send_password_reset
from rate_limit import check_auth_rate_limit, check_reset_rate_limit

log = logging.getLogger(__name__)

SECRET_KEY = os.getenv("JWT_SECRET", "dev-secret-change-in-production")
ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 7

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
router = APIRouter(prefix="/auth", tags=["auth"])

_PASSWORD_MIN = 10
_PASSWORD_MAX = 256

# How long a reset link stays usable. Short enough to limit the window if an
# inbox is exposed, long enough to survive a student getting distracted.
_RESET_TTL_MINUTES = int(os.getenv("RESET_TTL_MINUTES", "60"))


def _validate_password(v: str) -> str:
    """Shared by register and reset, so reset can never be the weaker path."""
    if len(v) < _PASSWORD_MIN:
        raise ValueError(f"Password must be at least {_PASSWORD_MIN} characters")
    if not re.search(r"[A-Za-z]", v):
        raise ValueError("Password must include at least one letter")
    if not re.search(r"\d", v):
        raise ValueError("Password must include at least one digit")
    return v


def _hash_reset_token(raw: str) -> str:
    """SHA-256 hex. Fine for a 256-bit random token - see PasswordResetToken."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _reset_link(raw_token: str) -> str:
    base = os.getenv("FRONTEND_BASE_URL", "").strip().rstrip("/") or "http://localhost:5173"
    return f"{base}/reset-password?token={raw_token}"


class RegisterRequest(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=_PASSWORD_MIN, max_length=_PASSWORD_MAX)

    @field_validator("name")
    @classmethod
    def name_stripped(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("Name cannot be empty")
        return s

    @field_validator("password")
    @classmethod
    def password_rules(cls, v: str) -> str:
        return _validate_password(v)


class LoginRequest(BaseModel):
    """email may be a full address, or the bare dev alias ``admin`` (see SEED_DEV_ADMIN_EMAIL)."""
    email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=_PASSWORD_MAX)

    @field_validator("email")
    @classmethod
    def normalize_login_email(cls, v: str) -> str:
        s = v.strip().lower()
        if "@" not in s:
            if s == "admin":
                return os.getenv("SEED_DEV_ADMIN_EMAIL", "admin@husky.local").strip().lower()
            raise ValueError("Enter a valid email address")
        return s


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    name: str
    email: str
    is_platform_admin: bool = False
    consent_research: bool = False
    research_acknowledged: bool = False


class MeResponse(BaseModel):
    user_id: str
    name: str
    email: str
    is_platform_admin: bool = False
    consent_research: bool = False
    research_acknowledged: bool = False


class UpdateMeRequest(BaseModel):
    # Settings toggle sends consent_research; the blocking acceptance gate sends
    # accept_research_notice. Both are optional so either flow can call PATCH /me.
    consent_research: bool | None = None
    accept_research_notice: bool | None = None


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=1, max_length=320)

    @field_validator("email")
    @classmethod
    def normalize(cls, v: str) -> str:
        return v.strip().lower()


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=16, max_length=512)
    password: str = Field(min_length=_PASSWORD_MIN, max_length=_PASSWORD_MAX)

    @field_validator("password")
    @classmethod
    def password_rules(cls, v: str) -> str:
        return _validate_password(v)


class SimpleMessage(BaseModel):
    message: str


def create_token(user_id: str, token_version: int = 0) -> str:
    now = datetime.utcnow()
    expire = now + timedelta(days=TOKEN_EXPIRE_DAYS)
    # tv pins the token to the account's password generation. Without it a reset
    # would leave an attacker's stolen token usable for up to 7 more days.
    return jwt.encode(
        {"sub": user_id, "exp": expire, "iat": now, "tv": int(token_version or 0)},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def _decode_payload(token: str) -> dict | None:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


async def resolve_token_user_id(token: str) -> str | None:
    """Validate a bearer token *and* honour password changes.

    Returns None when the token is malformed, expired, or was issued before the
    owner's most recent password change.
    """
    payload = _decode_payload(token)
    if not payload:
        return None
    uid = payload.get("sub")
    if not uid:
        return None
    async with AsyncSessionLocal() as db:
        u = await db.get(User, uid)
    if not u:
        return None
    # Tokens minted before this feature shipped carry no tv, which reads as 0 and
    # matches a freshly migrated account — so deploying does not log anyone out.
    if int(payload.get("tv", 0) or 0) != int(getattr(u, "token_version", 0) or 0):
        return None
    return uid


@router.post("/register", response_model=TokenResponse, dependencies=[Depends(check_auth_rate_limit)])
async def register(req: RegisterRequest):
    async with AsyncSessionLocal() as db:
        existing = await db.execute(select(User).where(User.email == str(req.email).lower()))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Email already registered")
        user = User(
            email=str(req.email).lower(),
            name=req.name,
            password_hash=pwd_context.hash(req.password),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return TokenResponse(
        access_token=create_token(user.id, getattr(user, "token_version", 0)),
        user_id=user.id,
        name=user.name,
        email=user.email,
        is_platform_admin=bool(getattr(user, "is_platform_admin", False)),
        consent_research=bool(getattr(user, "consent_research", False)),
        research_acknowledged=getattr(user, "research_ack_at", None) is not None,
    )


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(check_auth_rate_limit)])
async def login(req: LoginRequest):
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == req.email))
        user = result.scalar_one_or_none()
    if not user or not pwd_context.verify(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return TokenResponse(
        access_token=create_token(user.id, getattr(user, "token_version", 0)),
        user_id=user.id,
        name=user.name,
        email=user.email,
        is_platform_admin=bool(getattr(user, "is_platform_admin", False)),
        consent_research=bool(getattr(user, "consent_research", False)),
        research_acknowledged=getattr(user, "research_ack_at", None) is not None,
    )


@router.post("/forgot-password", response_model=SimpleMessage)
async def forgot_password(
    req: ForgotPasswordRequest,
    request: Request,
    background: BackgroundTasks,
):
    """Start a reset. Always answers identically, whether or not the account exists.

    The mail is queued as a background task so both branches return in the same
    time: doing the token write and provider round-trip inline would make an
    existing address measurably slower to respond, which leaks the same thing the
    uniform message is there to hide.
    """
    check_reset_rate_limit(request, req.email, scope="request")
    generic = SimpleMessage(
        message="If an account exists for that email, a reset link is on its way."
    )

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == req.email))
        user = result.scalar_one_or_none()
        if not user:
            return generic

        recipient = user.email
        raw = secrets.token_urlsafe(32)
        db.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=_hash_reset_token(raw),
                expires_at=datetime.utcnow() + timedelta(minutes=_RESET_TTL_MINUTES),
            )
        )
        await db.commit()

    background.add_task(send_password_reset, recipient, _reset_link(raw), _RESET_TTL_MINUTES)
    return generic


@router.post("/reset-password", response_model=SimpleMessage)
async def reset_password(req: ResetPasswordRequest, request: Request):
    """Consume a reset token and set a new password.

    On success every other outstanding token for that user is burned too, and
    `password_changed_at` is stamped so existing access tokens stop working.
    """
    check_reset_rate_limit(request, None, scope="redeem")
    token_hash = _hash_reset_token(req.token)
    now = datetime.utcnow()

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
        )
        row = result.scalar_one_or_none()
        # One message for every failure mode: not found, already used, expired.
        if not row or row.used_at is not None or row.expires_at < now:
            raise HTTPException(
                status_code=400, detail="This reset link is invalid or has expired."
            )

        user = await db.get(User, row.user_id)
        if not user:
            raise HTTPException(
                status_code=400, detail="This reset link is invalid or has expired."
            )

        reset_user_id = user.id
        user.password_hash = pwd_context.hash(req.password)
        user.password_changed_at = now.replace(microsecond=0)
        user.token_version = int(getattr(user, "token_version", 0) or 0) + 1
        row.used_at = now
        # Burn any other live links for this account - a second email sitting in
        # the inbox must not remain usable after a successful reset.
        await db.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
            )
            .values(used_at=now)
        )
        await db.commit()

    log.info("password reset completed for user %s", reset_user_id)
    return SimpleMessage(message="Your password has been reset. You can now sign in.")


async def _bearer_user_id(authorization: Optional[str] = Header(None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header required")
    token = authorization.removeprefix("Bearer ").strip()
    uid = await resolve_token_user_id(token)
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return uid


@router.get("/me", response_model=MeResponse)
async def me(user_id: str = Depends(_bearer_user_id)):
    async with AsyncSessionLocal() as db:
        u = await db.get(User, user_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        return MeResponse(
            user_id=u.id,
            name=u.name,
            email=u.email,
            is_platform_admin=bool(getattr(u, "is_platform_admin", False)),
            consent_research=bool(getattr(u, "consent_research", False)),
            research_acknowledged=getattr(u, "research_ack_at", None) is not None,
        )


@router.patch("/me", response_model=MeResponse)
async def update_me(req: UpdateMeRequest, user_id: str = Depends(_bearer_user_id)):
    """Update the caller's research settings. Two flows:
      - accept_research_notice=True: the one-time blocking acceptance. Stamps
        research_ack_at and turns consent on.
      - consent_research=<bool>: the Settings toggle, to opt out/in later.
    Consent governs FUTURE turns only — each turn snapshots it when scored
    (see _save_turn)."""
    async with AsyncSessionLocal() as db:
        u = await db.get(User, user_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        if req.accept_research_notice:
            if u.research_ack_at is None:
                u.research_ack_at = datetime.utcnow()
            u.consent_research = True
        elif req.consent_research is not None:
            u.consent_research = bool(req.consent_research)
        await db.commit()
        await db.refresh(u)
        return MeResponse(
            user_id=u.id,
            name=u.name,
            email=u.email,
            is_platform_admin=bool(getattr(u, "is_platform_admin", False)),
            consent_research=bool(u.consent_research),
            research_acknowledged=u.research_ack_at is not None,
        )
