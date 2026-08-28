"""Notification channels: ntfy.sh push (primary) and SMTP email (optional).

ntfy.sh verified against a real POST on 2026-08-28:

    POST https://ntfy.sh/<topic>
        Title: <title>
        <message body>

    -> HTTP 200, JSON body:
       {"id":"asNsoTRD9uGS","time":1787939829,"expires":1787983029,
        "event":"message","topic":"<topic>","title":"<title>","message":"<message>"}

    A malformed request (e.g. POSTing with no topic in the path) returns
    HTTP 400 with a JSON error body:
       {"code":40024,"http":400,"error":"invalid request: request body must be valid JSON"}

    No account or registration needed; any topic string is a valid, if
    unauthenticated, channel.

SMTP email goes through the standard library's smtplib against whatever
mail submission server the user configures. Unlike the three data sources,
there is no bespoke response format to discover here -- SMTP's protocol
behavior is fixed by RFC 5321, not by a particular vendor's API design --
so no live verification request was made for it, consistent with using
credential-gated services (no real SMTP secrets are available at build
time) only through their well-known protocol. It is optional and only
attempted when fully configured.
"""

import smtplib
from email.mime.text import MIMEText

import requests

from . import advisory_format

NTFY_DEFAULT_BASE_URL = "https://ntfy.sh"
NTFY_DEFAULT_TIMEOUT = 30
SMTP_DEFAULT_TIMEOUT = 30


class NotifyError(Exception):
    """Raised by a single channel sender when delivery fails."""


def format_tier1_body(raw_advisory_text):
    """Presentation only: reformats a raw VAAC advisory into a short,
    phone-readable message before it goes out over any channel. See
    advisory_format.py -- this never changes whether an alert fires."""
    return advisory_format.format_advisory(raw_advisory_text)


def send_ntfy(
    topic,
    title,
    message,
    base_url=NTFY_DEFAULT_BASE_URL,
    user_agent="etna-monitor/0.1",
    timeout=NTFY_DEFAULT_TIMEOUT,
    session=None,
):
    if not topic:
        raise NotifyError("ntfy topic is not configured")
    http = session or requests
    try:
        response = http.post(
            f"{base_url}/{topic}",
            data=message.encode("utf-8"),
            headers={"User-Agent": user_agent, "Title": title},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise NotifyError(f"ntfy request failed: {exc}") from exc

    if response.status_code != 200:
        raise NotifyError(f"ntfy returned HTTP {response.status_code}: {response.text[:500]}")


def send_email(
    smtp_host,
    smtp_port,
    smtp_user,
    smtp_password,
    to_address,
    subject,
    message,
    use_tls=True,
    timeout=SMTP_DEFAULT_TIMEOUT,
    smtp_client_cls=None,
):
    if not (smtp_host and smtp_port and smtp_user and smtp_password and to_address):
        raise NotifyError("SMTP is not fully configured")

    msg = MIMEText(message, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = to_address

    client_cls = smtp_client_cls or smtplib.SMTP
    try:
        with client_cls(smtp_host, smtp_port, timeout=timeout) as client:
            if use_tls:
                client.starttls()
            client.login(smtp_user, smtp_password)
            client.sendmail(smtp_user, [to_address], msg.as_string())
    except (smtplib.SMTPException, OSError) as exc:
        raise NotifyError(f"SMTP send failed: {exc}") from exc


def send_message(
    title,
    message,
    ntfy_topic=None,
    ntfy_base_url=NTFY_DEFAULT_BASE_URL,
    smtp=None,
    user_agent="etna-monitor/0.1",
    timeout=NTFY_DEFAULT_TIMEOUT,
    session=None,
    smtp_client_cls=None,
):
    """Attempt delivery through every configured channel independently.

    smtp, if given, is a dict with keys host, port, user, password, to,
    use_tls -- all required for the channel to be attempted.

    Never raises: a channel that fails or was not configured is recorded
    in the returned dict rather than aborting the other channel or the
    caller. A notification failure must be visible, not silent, but it
    also must not crash a run that still needs to write state.

    Returns {"ntfy": True | error message | "not configured",
             "smtp": True | error message | "not configured"}.
    """
    results = {}

    if ntfy_topic:
        try:
            send_ntfy(
                ntfy_topic,
                title,
                message,
                base_url=ntfy_base_url,
                user_agent=user_agent,
                timeout=timeout,
                session=session,
            )
            results["ntfy"] = True
        except NotifyError as exc:
            results["ntfy"] = str(exc)
    else:
        results["ntfy"] = "not configured"

    if smtp:
        try:
            send_email(
                smtp.get("host"),
                smtp.get("port"),
                smtp.get("user"),
                smtp.get("password"),
                smtp.get("to"),
                subject=title,
                message=message,
                use_tls=smtp.get("use_tls", True),
                timeout=timeout,
                smtp_client_cls=smtp_client_cls,
            )
            results["smtp"] = True
        except NotifyError as exc:
            results["smtp"] = str(exc)
    else:
        results["smtp"] = "not configured"

    return results
