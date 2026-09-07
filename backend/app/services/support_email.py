"""Send a tender failure to the technical support team.

Why this exists: VR-Nexus is handed to non-technical procurement teams. When a
tender fails, a Python traceback on screen helps no one who cannot read it and
alarms everyone who can't. The error log's "Contact technical support" button
routes that traceback to the people who CAN act on it, and leaves the user with
a calm message instead of a stack trace.

Transport is plain SMTP (smtplib) with STARTTLS — no third-party email service,
so the only dependency is the Python standard library and one set of SMTP
credentials in the environment. Defaults target Gmail; see core/config for the
App Password note. The send runs in a worker thread (`asyncio.to_thread`)
because smtplib is blocking and the endpoint calling this is async.

This module never sends marketing or user-facing mail — only an internal
failure report to a single configured support address. It is deliberately not
wired to any user-supplied recipient, so it cannot be turned into an open relay
by anything a tender or a form contains.
"""
from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate

from app.core.config import get_settings
from app.models.tender import Tender

logger = logging.getLogger(__name__)


class SupportEmailNotConfigured(Exception):
    """SMTP credentials are missing, so nothing can be sent."""


class SupportEmailFailed(Exception):
    """SMTP was configured but the send failed (auth, network, refusal)."""


def _build_message(tender: Tender, reporter_email: str | None) -> EmailMessage:
    settings = get_settings()

    stage = tender.failed_stage or "unknown stage"
    reason = tender.progress_message or "No reason was recorded."
    detail = tender.error_detail or "No technical detail was recorded."
    failed_at = tender.failed_at.isoformat() if tender.failed_at else "unknown"

    subject = f"[VR-Nexus] Tender analysis failed: {tender.name}"

    # Plain text only. A support inbox reads a failure report faster as text than
    # as styled HTML, and text cannot carry a tracking pixel or a script.
    body = (
        "A VR-Nexus user reported a failed tender analysis from the app.\n\n"
        "WHAT THE USER SEES\n"
        f"  Tender:      {tender.name}\n"
        f"  File:        {tender.original_filename}\n"
        f"  Failed at:   {stage}\n"
        f"  When:        {failed_at}\n"
        f"  Reported by: {reporter_email or 'unknown'}\n\n"
        "REASON SHOWN TO THE USER\n"
        f"  {reason}\n\n"
        "TECHNICAL DETAIL (exception + stack tail)\n"
        f"{detail}\n\n"
        "REFERENCE\n"
        f"  Tender ID:   {tender.id}\n\n"
        "The user has been told the support team will look into it within a few "
        "days. Please follow up with them if you need the source file.\n"
    )

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from
    message["To"] = settings.SUPPORT_EMAIL
    message["Date"] = formatdate(localtime=True)
    # So a support reply goes to the person who reported it, when we know them.
    if reporter_email:
        message["Reply-To"] = reporter_email
    message.set_content(body)
    return message


def _send_sync(message: EmailMessage) -> None:
    settings = get_settings()

    if not settings.support_email_configured:
        raise SupportEmailNotConfigured(
            "Support email is not configured. Set SMTP_USERNAME and SMTP_PASSWORD "
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
        # The single most common failure: an account password used where Gmail
        # requires an App Password, or 2-Step Verification not enabled.
        raise SupportEmailFailed(
            "The support mailbox rejected the login. For Gmail, SMTP_PASSWORD must "
            "be a 16-character App Password (with 2-Step Verification enabled), not "
            "the account password."
        ) from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise SupportEmailFailed(f"Could not send the support email: {exc}") from exc


async def send_failure_report(tender: Tender, reporter_email: str | None) -> None:
    """Email the tender's failure to the support team.

    Raises SupportEmailNotConfigured if SMTP creds are absent (the caller turns
    this into a clear "not configured" response so the UI can offer a mailto:
    fallback), or SupportEmailFailed on an SMTP-level failure. On success it
    returns None; the caller records support_requested_at.
    """
    message = _build_message(tender, reporter_email)
    await asyncio.to_thread(_send_sync, message)
    logger.info("Support failure report sent for tender %s", tender.id)
