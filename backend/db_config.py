"""
Resolve DATABASE_URL for HuskyAI.

Supports:
  - DATABASE_URL (full URI from Supabase → Database → Connection string), or
  - SUPABASE_PROJECT_REF + database password (built as direct connection to db.<ref>.supabase.co:5432).

Important: the database password is from Supabase → Project Settings → Database (NOT the API
service_role JWT). If you store API keys as db_secret_key / db_publishable_key, only the
*database* password may be used to build DATABASE_URL — see .env.example.
"""

from __future__ import annotations

import os
import re
from urllib.parse import quote_plus

from dotenv import load_dotenv

load_dotenv()


def _parse_project_ref_from_supabase_url(url: str) -> str | None:
    m = re.match(r"https?://([a-z0-9]+)\.supabase\.co", url.strip(), re.I)
    return m.group(1) if m else None


def _to_asyncpg(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def _password_candidates() -> str:
    """Postgres password only — not Supabase service_role JWT."""
    for key in (
        "SUPABASE_DB_PASSWORD",
        "SUPABASE_POSTGRES_PASSWORD",
        "dbpass",
        "DBPASS",
        "DB_SECRET_KEY",
    ):
        v = os.getenv(key, "").strip().strip('"').strip("'")
        if v and not v.startswith("sb_secret_") and not v.startswith("eyJ"):
            return v
    return ""


def resolve_database_url() -> str:
    explicit = os.getenv("DATABASE_URL", "").strip()
    if explicit:
        return _to_asyncpg(explicit)

    host = os.getenv("SUPABASE_DB_HOST", "").strip()
    port = os.getenv("SUPABASE_DB_PORT", "5432").strip() or "5432"
    dbname = os.getenv("SUPABASE_DB_NAME", "postgres").strip() or "postgres"
    dbuser = os.getenv("SUPABASE_DB_USER", "postgres").strip() or "postgres"
    password = _password_candidates()

    if host and password:
        return (
            f"postgresql+asyncpg://{quote_plus(dbuser)}:{quote_plus(password)}"
            f"@{host}:{port}/{dbname}"
        )

    ref = (
        os.getenv("SUPABASE_PROJECT_REF", "").strip()
        or os.getenv("SUPABASE_PROJECT_ID", "").strip()
    )
    if not ref:
        supabase_url = os.getenv("SUPABASE_URL", "").strip()
        if supabase_url:
            ref = _parse_project_ref_from_supabase_url(supabase_url) or ""

    if ref and password:
        pwd = quote_plus(password)
        h = f"db.{ref}.supabase.co"
        return f"postgresql+asyncpg://postgres:{pwd}@{h}:5432/postgres"

    return "sqlite+aiosqlite:///./huskyai.db"


def is_transaction_pooler(url: str) -> bool:
    """Supabase's transaction pooler runs on port 6543 (session pooler = 5432).
    Transaction mode rotates server connections per transaction, so it does NOT
    pin a connection per client — which avoids the session-mode 'max clients
    reached' (EMAXCONNSESSION) cap. asyncpg must disable its prepared-statement
    cache for transaction pooling to work."""
    u = url.lower()
    return ":6543/" in u or ":6543?" in u or u.endswith(":6543")


def engine_connect_args(url: str) -> dict:
    """asyncpg connect args for Supabase: SSL, plus transaction-pooler safety."""
    args: dict = {}
    if ("supabase.co" in url.lower() or "supabase.com" in url.lower()) and url.startswith("postgresql"):
        args["ssl"] = "require"
    elif os.getenv("DATABASE_SSL_REQUIRE", "").lower() in ("1", "true", "yes"):
        args["ssl"] = "require"
    if is_transaction_pooler(url):
        # Required for asyncpg through Supavisor transaction mode (no prepared
        # statement reuse across rotated server connections).
        args["statement_cache_size"] = 0
    return args
