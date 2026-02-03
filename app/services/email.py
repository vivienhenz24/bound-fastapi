import logging
from pathlib import Path

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "email"


def _load_template(filename: str) -> str:
    path = TEMPLATE_DIR / filename
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("Email template missing: %s", path)
        return ""


def send_verification_email(to_email: str, token: str) -> None:
    """Send an email verification link via Resend."""
    if not settings.resend_api_key or not settings.resend_from_email:
        logger.warning("Resend not configured; skipping verification email.")
        return

    verify_url = f"{settings.frontend_url.rstrip('/')}/verify-email?token={token}"
    from_address = f"{settings.resend_from_name} <{settings.resend_from_email}>"
    html_template = _load_template("verification.html")
    text_template = _load_template("verification.txt")

    html_body = (
        html_template.replace("{{verify_url}}", verify_url)
        if html_template
        else (
            "<p>Welcome to bound.</p>"
            "<p>Please verify your email by clicking the link below:</p>"
            f'<p><a href="{verify_url}">Verify email</a></p>'
            "<p>If you did not create this account, you can ignore this email.</p>"
        )
    )
    text_body = (
        text_template.replace("{{verify_url}}", verify_url)
        if text_template
        else f"Verify your email: {verify_url}"
    )

    payload = {
        "from": from_address,
        "to": [to_email],
        "subject": "Verify your email",
        "html": html_body,
        "text": text_body,
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {settings.resend_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
    except httpx.HTTPError:
        logger.exception("Failed to send verification email via Resend.")
