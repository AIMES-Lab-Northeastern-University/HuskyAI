"""Transactional email for HuskyAI.

Resend is the provider (permanent free tier covers pilot-scale password resets).
Configure with:

  RESEND_API_KEY   from resend.com -> API Keys
  EMAIL_FROM       e.g. "HuskyAI <no-reply@aimeslab.org>" (domain must be verified
                   in Resend, or university spam filters will eat the mail)

With no API key set, the reset link is logged instead of sent, so the whole flow
is testable locally without a provider. Never enable that fallback in production:
the link would sit in the server log.
"""

from __future__ import annotations

import logging
import os

import httpx

log = logging.getLogger(__name__)

_RESEND_ENDPOINT = "https://api.resend.com/emails"
_TIMEOUT = httpx.Timeout(10.0)


def email_configured() -> bool:
    return bool(os.getenv("RESEND_API_KEY", "").strip())


def _from_address() -> str:
    return os.getenv("EMAIL_FROM", "").strip() or "HuskyAI <onboarding@resend.dev>"


async def _send(to: str, subject: str, html: str, text: str) -> bool:
    """Best-effort send. Returns True if accepted by the provider.

    Never raises: a provider outage must not turn into a 500 that tells the
    caller whether the address existed.
    """
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    if not api_key:
        log.warning("RESEND_API_KEY unset - email NOT sent. Body follows:\n%s", text)
        return False
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(
                _RESEND_ENDPOINT,
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "from": _from_address(),
                    "to": [to],
                    "subject": subject,
                    "html": html,
                    "text": text,
                },
            )
        if r.status_code >= 400:
            log.error("Resend rejected message (%s): %s", r.status_code, r.text[:400])
            return False
        return True
    except Exception as e:  # network error, DNS, timeout
        log.error("Resend send failed: %s: %s", type(e).__name__, e)
        return False


async def send_password_reset(to: str, reset_url: str, ttl_minutes: int) -> bool:
    subject = "Reset your HuskyAI password"
    text = (
        "You asked to reset your HuskyAI password.\n\n"
        f"Open this link within {ttl_minutes} minutes to choose a new one:\n\n"
        f"{reset_url}\n\n"
        "The link can only be used once. If you did not request this, you can\n"
        "ignore this email - your password has not changed.\n\n"
        "AIMES Lab, Northeastern University\n"
    )
    html = f"""\
<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;
            max-width:520px;margin:0 auto;color:#1A1612;line-height:1.6;">
  <h2 style="font-size:19px;margin:0 0 14px;">Reset your HuskyAI password</h2>
  <p style="margin:0 0 18px;font-size:15px;">
    You asked to reset your password. Choose a new one within
    {ttl_minutes} minutes:
  </p>
  <p style="margin:0 0 18px;">
    <a href="{reset_url}"
       style="display:inline-block;background:#C8102E;color:#fff;text-decoration:none;
              padding:11px 20px;border-radius:8px;font-size:14px;font-weight:600;">
      Set a new password
    </a>
  </p>
  <p style="margin:0 0 18px;font-size:13px;color:#6B655F;">
    The link works once. If you did not request this, ignore this email &mdash;
    your password has not changed.
  </p>
  <p style="margin:0;font-size:12px;color:#9A948E;">AIMES Lab, Northeastern University</p>
</div>
"""
    return await _send(to, subject, html, text)
