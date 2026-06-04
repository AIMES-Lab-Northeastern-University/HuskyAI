import os
import re
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Request
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select

from database import User, AsyncSessionLocal
from rate_limit import check_auth_rate_limit

SECRET_KEY = os.getenv("JWT_SECRET", "dev-secret-change-in-production")
ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 7

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
router = APIRouter(prefix="/auth", tags=["auth"])

_PASSWORD_MIN = 10
_PASSWORD_MAX = 256


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
        if len(v) < _PASSWORD_MIN:
            raise ValueError(f"Password must be at least {_PASSWORD_MIN} characters")
        if not re.search(r"[A-Za-z]", v):
            raise ValueError("Password must include at least one letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must include at least one digit")
        return v


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


class MeResponse(BaseModel):
    user_id: str
    name: str
    email: str
    is_platform_admin: bool = False
    consent_research: bool = False


class UpdateMeRequest(BaseModel):
    consent_research: bool


def create_token(user_id: str) -> str:
    expire = datetime.utcnow() + timedelta(days=TOKEN_EXPIRE_DAYS)
    return jwt.encode({"sub": user_id, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


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
        access_token=create_token(user.id),
        user_id=user.id,
        name=user.name,
        email=user.email,
        is_platform_admin=bool(getattr(user, "is_platform_admin", False)),
        consent_research=bool(getattr(user, "consent_research", False)),
    )


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(check_auth_rate_limit)])
async def login(req: LoginRequest):
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == req.email))
        user = result.scalar_one_or_none()
    if not user or not pwd_context.verify(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return TokenResponse(
        access_token=create_token(user.id),
        user_id=user.id,
        name=user.name,
        email=user.email,
        is_platform_admin=bool(getattr(user, "is_platform_admin", False)),
        consent_research=bool(getattr(user, "consent_research", False)),
    )


async def _bearer_user_id(authorization: Optional[str] = Header(None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header required")
    token = authorization.removeprefix("Bearer ").strip()
    uid = decode_token(token)
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
        )


@router.patch("/me", response_model=MeResponse)
async def update_me(req: UpdateMeRequest, user_id: str = Depends(_bearer_user_id)):
    """Update the caller's research-consent flag. Governs FUTURE turns only —
    each turn snapshots this value when it is scored (see _save_turn)."""
    async with AsyncSessionLocal() as db:
        u = await db.get(User, user_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        u.consent_research = bool(req.consent_research)
        await db.commit()
        await db.refresh(u)
        return MeResponse(
            user_id=u.id,
            name=u.name,
            email=u.email,
            is_platform_admin=bool(getattr(u, "is_platform_admin", False)),
            consent_research=bool(u.consent_research),
        )
