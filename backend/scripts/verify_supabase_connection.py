#!/usr/bin/env python3
"""
Quick Postgres connectivity check (Supabase-friendly).

Supabase docs often show:
  pip install python-dotenv psycopg2
  psycopg2.connect(DATABASE_URL)

This project uses SQLAlchemy + asyncpg at runtime and psycopg3 for Alembic.
Run this script instead of adding a second main.py:

  cd backend
  pip install -r requirements.txt
  python scripts/verify_supabase_connection.py

Uses the same DATABASE_URL / SUPABASE_* resolution as the API (see db_config.py).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Load backend/.env before importing project modules
from dotenv import load_dotenv

_backend_root = Path(__file__).resolve().parents[1]
load_dotenv(_backend_root / ".env")

if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))


def main() -> int:
    try:
        import psycopg
    except ImportError:
        print(
            "Install deps: pip install -r requirements.txt  (includes psycopg for this check)",
            file=sys.stderr,
        )
        return 1

    from db_config import resolve_database_url

    url = resolve_database_url()
    if url.startswith("sqlite"):
        print("DATABASE_URL resolves to SQLite; set DATABASE_URL or SUPABASE_* for a Postgres check.")
        return 0

    sync_url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    if "supabase.co" in sync_url.lower() and "sslmode" not in sync_url.lower():
        sync_url += "&sslmode=require" if "?" in sync_url else "?sslmode=require"

    try:
        with psycopg.connect(sync_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                one = cur.fetchone()
        if one != (1,):
            print("Unexpected response:", one, file=sys.stderr)
            return 1
    except Exception as e:
        print("Connection failed:", e, file=sys.stderr)
        return 1

    print("OK: connected to Postgres (Supabase check passed).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
