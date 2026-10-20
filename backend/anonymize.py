"""
De-identification helpers for the research/training data export.

Two jobs:
  1. pseudonymize(): turn a real id (user id, conversation id) into a stable,
     non-reversible label like ``anon-7f3a91`` so the same student maps to the
     same label across every export (good for longitudinal analysis) without
     ever revealing who they are. Backed by HMAC-SHA256 + a secret salt.
  2. scrub(): redact PII that students type *inside* free text — emails, phone
     numbers, 9-digit NUIDs, SSNs, URLs, and (when known) the author's own name
     and email; scrub_people() does the same against a whole team's names. Replaces with placeholders like ``[EMAIL]`` / ``[NAME]``.

IMPORTANT — limits of scrub(): regex/known-term redaction is best-effort, not a
guarantee. Free text can always carry PII a pattern won't catch (a friend's
name, an address, a niche identifier). Before sharing any export externally,
spot-check a sample by hand. See docs/data-anonymization.md.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re

log = logging.getLogger("anonymize")

# Stable salt so pseudonyms are consistent across exports. MUST be set in prod
# (.env) and kept secret — without it the hashes could be brute-forced over the
# small set of known user ids. A fixed dev fallback keeps local runs working.
_DEV_FALLBACK_SALT = "huskyai-dev-anon-salt-change-me"


_warned_no_salt = False


def _salt() -> bytes:
    global _warned_no_salt
    s = os.getenv("ANONYMIZE_SALT", "").strip()
    if not s:
        if not _warned_no_salt:
            log.warning(
                "ANONYMIZE_SALT not set — using insecure dev fallback. Set ANONYMIZE_SALT "
                "in .env before exporting real data for sharing/training."
            )
            _warned_no_salt = True
        s = _DEV_FALLBACK_SALT
    return s.encode("utf-8")


def pseudonymize(value: str, prefix: str, length: int = 6) -> str:
    """Stable, non-reversible label for ``value`` (e.g. a user/conversation id)."""
    if value is None:
        value = ""
    digest = hmac.new(_salt(), str(value).encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{prefix}-{digest[:length]}"


# ── PII patterns ──────────────────────────────────────────────────────────────
# Order matters: more specific patterns run before more general ones.

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_URL_RE = re.compile(r"\b(?:https?://|www\.)\S+", re.IGNORECASE)
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
# Phone: +1 (617) 555-1234 / 617-555-1234 / 617.555.1234 / 6175551234
_PHONE_RE = re.compile(
    r"\b(?:\+?1[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}\b"
)
# Northeastern NUID is 9 digits (often zero-padded). Match a standalone 9-digit run.
_NUID_RE = re.compile(r"\b\d{9}\b")


def scrub(text: str | None, known_name: str | None = None, known_email: str | None = None) -> str | None:
    """Redact PII from free text. ``known_name``/``known_email`` are the author's
    own identifiers (from the DB) and are redacted as exact extra terms — this is
    what reliably catches 'Hi, I'm <name>' / their NU email in their own messages."""
    return scrub_people(text, [(known_name, known_email)])


def scrub_people(text: str | None, people) -> str | None:
    """scrub() against several known people at once: ``people`` is an iterable
    of (name, email). For text a team wrote together — a shared document or a
    team chat — where anyone may name anyone, so scrubbing against the author
    alone leaves every teammate's name in place.

    Every email goes before every name (one person's name can be part of
    another's address), and the generic patterns run once, at the end."""
    if not text:
        return text

    out = text
    people = [(n, e) for n, e in people if n or e]

    # 1) Known emails, then known names (exact, highest confidence).
    for _, email in people:
        if email:
            out = re.sub(re.escape(email), "[EMAIL]", out, flags=re.IGNORECASE)
    parts = {part for name, _ in people if name for part in str(name).split()
             if len(part) >= 2}  # skip single initials to avoid over-redaction
    # Longest first, so a part never pre-empts a longer one that contains it.
    for part in sorted(parts, key=len, reverse=True):
        out = re.sub(rf"\b{re.escape(part)}\b", "[NAME]", out, flags=re.IGNORECASE)

    # 2) Generic patterns.
    out = _URL_RE.sub("[URL]", out)
    out = _EMAIL_RE.sub("[EMAIL]", out)
    out = _SSN_RE.sub("[SSN]", out)
    out = _PHONE_RE.sub("[PHONE]", out)
    out = _NUID_RE.sub("[ID]", out)

    return out
