# Tests: isolated DB file + env set before `main` / `database` import (see test collection order).
import os
import tempfile

_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix="_husky_test.db")
os.close(_fd)
# TEST_DATABASE_URL runs the suite against a real database instead (an empty
# Postgres, to catch what SQLite's one-writer-at-a-time hides). Never point it
# at a database you want to keep.
os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL") or (
    "sqlite+aiosqlite:///" + _TEST_DB_PATH.replace("\\", "/"))
# Skip strict auth rate limits during pytest (see rate_limit.py); override per test via AUTH_RATE_TEST_MAX.
os.environ["HUSKY_TESTING"] = "1"
