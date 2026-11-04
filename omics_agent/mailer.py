"""Outgoing email for sign-in codes. Plain SMTP with STARTTLS (Brevo's relay by default), configured by environment:

    LOCUS_SMTP_HOST, LOCUS_SMTP_PORT (587), LOCUS_SMTP_USER, LOCUS_SMTP_PASSWORD, LOCUS_MAIL_FROM

With none of these set, email sign-in is off (the routes answer 404). For local trials without a provider,
LOCUS_MAIL_DEV_LOG=1 appends each message to data/dev-mail.log instead of sending it; never set it on a public server.
"""

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

log = logging.getLogger(__name__)
DEV_LOG = Path(__file__).resolve().parent.parent / "data" / "dev-mail.log"


def dev_log() -> bool:
    return os.environ.get("LOCUS_MAIL_DEV_LOG") == "1"


def configured() -> bool:
    smtp = all(os.environ.get(k) for k in ("LOCUS_SMTP_HOST", "LOCUS_SMTP_USER", "LOCUS_SMTP_PASSWORD", "LOCUS_MAIL_FROM"))
    return smtp or dev_log()


class MailError(Exception):
    pass


def send(to: str, subject: str, text: str) -> None:
    """Sends one plain-text message; raises MailError when the relay refuses or cannot be reached."""
    if dev_log() and not os.environ.get("LOCUS_SMTP_HOST"):
        with DEV_LOG.open("a") as f:
            f.write(f"To: {to}\nSubject: {subject}\n\n{text}\n----\n")
        return
    msg = EmailMessage()
    msg["From"] = f"locus <{os.environ['LOCUS_MAIL_FROM']}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    try:
        with smtplib.SMTP(os.environ["LOCUS_SMTP_HOST"], int(os.environ.get("LOCUS_SMTP_PORT") or 587), timeout=20) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(os.environ["LOCUS_SMTP_USER"], os.environ["LOCUS_SMTP_PASSWORD"])
            smtp.send_message(msg)
    except (OSError, smtplib.SMTPException) as e:
        log.warning("sign-in email to a %s address failed: %s", to.rsplit("@", 1)[-1], e)
        raise MailError(str(e)) from e
