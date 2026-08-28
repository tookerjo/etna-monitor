import smtplib

import pytest
import requests

from etna_monitor import notify


class FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


class FakeSession:
    def __init__(self, response=None, exception=None):
        self._response = response
        self._exception = exception
        self.last_call = None

    def post(self, url, data=None, headers=None, timeout=None):
        self.last_call = {"url": url, "data": data, "headers": headers, "timeout": timeout}
        if self._exception:
            raise self._exception
        return self._response


class FakeSmtpClient:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.logged_in = None
        self.sent = None
        FakeSmtpClient.instances.append(self)

    def starttls(self):
        self.started_tls = True

    def login(self, user, password):
        self.logged_in = (user, password)

    def sendmail(self, from_addr, to_addrs, message):
        self.sent = (from_addr, to_addrs, message)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class FailingSmtpClient(FakeSmtpClient):
    def login(self, user, password):
        raise smtplib.SMTPAuthenticationError(535, b"bad credentials")


def test_send_ntfy_real_shape_success():
    # Matches the verified real response: HTTP 200 JSON body.
    session = FakeSession(
        response=FakeResponse(
            200,
            '{"id":"asNsoTRD9uGS","time":1787939829,"expires":1787983029,'
            '"event":"message","topic":"etna-test","title":"Etna Monitor",'
            '"message":"hello"}',
        )
    )
    notify.send_ntfy("etna-test", "Etna Monitor", "hello", session=session)
    assert session.last_call["url"] == "https://ntfy.sh/etna-test"
    assert session.last_call["headers"]["Title"] == "Etna Monitor"
    assert session.last_call["data"] == b"hello"


def test_send_ntfy_missing_topic_raises_without_a_request():
    with pytest.raises(notify.NotifyError):
        notify.send_ntfy("", "title", "message")


def test_send_ntfy_non_200_raises_notify_error():
    session = FakeSession(
        response=FakeResponse(400, '{"code":40024,"http":400,"error":"invalid request"}')
    )
    with pytest.raises(notify.NotifyError):
        notify.send_ntfy("etna-test", "title", "message", session=session)


def test_send_ntfy_network_failure_raises_notify_error():
    session = FakeSession(exception=requests.ConnectionError("no route to host"))
    with pytest.raises(notify.NotifyError):
        notify.send_ntfy("etna-test", "title", "message", session=session)


def test_send_email_success_calls_starttls_login_sendmail():
    FakeSmtpClient.instances.clear()
    notify.send_email(
        "smtp.example.com",
        587,
        "user@example.com",
        "secret",
        "to@example.com",
        "subject",
        "body",
        smtp_client_cls=FakeSmtpClient,
    )
    client = FakeSmtpClient.instances[0]
    assert client.started_tls is True
    assert client.logged_in == ("user@example.com", "secret")
    assert client.sent[0] == "user@example.com"
    assert client.sent[1] == ["to@example.com"]


def test_send_email_missing_config_raises_without_connecting():
    with pytest.raises(notify.NotifyError):
        notify.send_email(
            "smtp.example.com", 587, "", "", "to@example.com", "s", "b",
            smtp_client_cls=FakeSmtpClient,
        )


def test_send_email_smtp_failure_raises_notify_error():
    with pytest.raises(notify.NotifyError):
        notify.send_email(
            "smtp.example.com",
            587,
            "user@example.com",
            "wrong-password",
            "to@example.com",
            "subject",
            "body",
            smtp_client_cls=FailingSmtpClient,
        )


def test_send_message_no_channels_configured():
    results = notify.send_message("title", "body")
    assert results == {"ntfy": "not configured", "smtp": "not configured"}


def test_send_message_ntfy_success_smtp_not_configured():
    session = FakeSession(response=FakeResponse(200, "{}"))
    results = notify.send_message("title", "body", ntfy_topic="etna-test", session=session)
    assert results["ntfy"] is True
    assert results["smtp"] == "not configured"


def test_send_message_reports_ntfy_failure_without_raising():
    session = FakeSession(response=FakeResponse(500, "server error"))
    results = notify.send_message("title", "body", ntfy_topic="etna-test", session=session)
    assert results["ntfy"] != True  # noqa: E712 -- must be an error string, not True
    assert isinstance(results["ntfy"], str)


def test_send_message_tries_smtp_even_if_ntfy_fails():
    FakeSmtpClient.instances.clear()
    ntfy_session = FakeSession(exception=requests.ConnectionError("down"))
    results = notify.send_message(
        "title",
        "body",
        ntfy_topic="etna-test",
        session=ntfy_session,
        smtp={
            "host": "smtp.example.com",
            "port": 587,
            "user": "user@example.com",
            "password": "secret",
            "to": "to@example.com",
        },
        smtp_client_cls=FakeSmtpClient,
    )
    assert isinstance(results["ntfy"], str)
    assert results["smtp"] is True
