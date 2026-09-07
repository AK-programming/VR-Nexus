"""Account-lifecycle email: password reset.

Same transport as services/support_email.py (plain SMTP via smtplib, STARTTLS,
no third-party email service) but kept as its own module rather than a shared
function, because the two have an important difference: support_email.py is
"deliberately not wired to any user-supplied recipient" (its own docstring),
so it can never become an open relay. This module's whole job IS to email a
user-supplied recipient - the person who typed their email into the forgot-
password form - so that guarantee does not apply here and should not be
blurred by sharing code with the module that makes it. What they do share
(the SMTP-send mechanics) is small enough that duplicating it is cheaper than
the confusion of importing "internal" helpers across that boundary.

The send runs in a worker thread (`asyncio.to_thread`) because smtplib is
blocking and the endpoint calling this is async.
"""
from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class AccountEmailNotConfigured(Exception):
    """SMTP credentials are missing, so nothing can be sent."""


class AccountEmailFailed(Exception):
    """SMTP was configured but the send failed (auth, network, refusal)."""


def _build_reset_message(to_email: str, to_name: str, reset_url: str) -> EmailMessage:
    settings = get_settings()

    subject = "Reset your VR-Nexus password"

    # Plain text, matching support_email.py's reasoning: it renders reliably
    # everywhere and cannot carry a tracking pixel or script, and a reset link
    # does not need styling to do its job.
    body = (
        f"Hi {to_name},\n\n"
        "We received a request to reset your VR-Nexus password. Open the link "
        "below to choose a new one:\n\n"
        f"  {reset_url}\n\n"
        "This link expires in 30 minutes. If you didn't request a password "
        "reset, you can safely ignore this email - your password will not "
        "change unless you open the link above and set a new one.\n"
    )

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from
    message["To"] = to_email
    message["Date"] = formatdate(localtime=True)
    message.set_content(body)
    return message


def _send_sync(message: EmailMessage) -> None:
    settings = get_settings()

    if not settings.smtp_configured:
        raise AccountEmailNotConfigured(
            "Email sending is not configured. Set SMTP_USERNAME and SMTP_PASSWORD "
            "(a Gmail App Password) in backend/.env."
        )

    context = ssl.create_default_context()
    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as server:
            if settings.SMTP_USE_TLS:
                server.starttls(context=context)
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            server.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        raise AccountEmailFailed(
            "The mailbox rejected the login. For Gmail, SMTP_PASSWORD must be a "
            "16-character App Password (with 2-Step Verification enabled), not "
            "the account password."
        ) from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise AccountEmailFailed(f"Could not send the email: {exc}") from exc


async def send_password_reset_email(to_email: str, to_name: str, reset_url: str) -> None:
    """Raises AccountEmailNotConfigured if SMTP creds are absent, or
    AccountEmailFailed on an SMTP-level failure. The caller turns both into a
    clear HTTP error rather than a bare 500 - a sales rep who can't get a
    reset email needs to know that, not see a generic server error."""
    message = _build_reset_message(to_email, to_name, reset_url)
    await asyncio.to_thread(_send_sync, message)
    logger.info("Password reset email sent to %s", to_email)
