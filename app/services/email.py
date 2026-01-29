import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


def send_verification_email(to_email: str, token: str) -> None:
    """Send an email verification link via Resend."""
    if not settings.resend_api_key or not settings.resend_from_email:
        logger.warning("Resend not configured; skipping verification email.")
        return

    verify_url = f"{settings.frontend_url.rstrip('/')}/verify-email?token={token}"
    from_address = f"{settings.resend_from_name} <{settings.resend_from_email}>"

    payload = {
        "from": from_address,
        "to": [to_email],
        "subject": "Verify your email",
        "html": (
            "<p>Welcome to bound.</p>"
            "<p>Please verify your email by clicking the link below:</p>"
            f'<p><a href="{verify_url}">Verify email</a></p>'
            "<p>If you did not create this account, you can ignore this email.</p>"
        ),
        "text": f"Verify your email: {verify_url}",
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
