#!/usr/bin/env python3
"""
Pre-pilot HTTP flow (CI-friendly): register → create section → POST challenge →
student join → GET challenges → start session → challenge detail.

Runs: pytest tests/test_e2e_http_flow.py

For chat + Gemini + OpenAI eval over WebSocket (requires API keys + Postgres in
the existing script), use: python scripts/e2e_website_flow.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]


def main() -> int:
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(_root / "tests" / "test_e2e_http_flow.py"),
        "-v",
        "--tb=short",
    ]
    return subprocess.run(cmd, cwd=str(_root)).returncode


if __name__ == "__main__":
    raise SystemExit(main())
