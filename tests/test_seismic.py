from datetime import datetime, timezone

import pytest
import requests

from etna_monitor.sources import seismic

NOW = datetime(2026, 8, 28, 6, 15, tzinfo=timezone.utc)

REAL_SAMPLE_BODY = (
    "#EventID|Time|Latitude|Longitude|Depth/Km|Author|Catalog|Contributor|"
    "ContributorID|MagType|Magnitude|MagAuthor|EventLocationName|EventType\n"
    "46943752|2026-08-20T06:54:56.830000|37.799|15.05|0.8|SURVEY-INGV-CT#KATALOC"
    "||||ML|1.8|--|10 km SW Linguaglossa (CT)|earthquake\n"
    "46943642|2026-08-20T06:42:31.450000|37.679|15.088|2.1|SURVEY-INGV-CT#KATALOC"
    "||||ML|1.3|--|2 km SW Zafferana Etnea (CT)|earthquake\n"
)


class FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


class FakeSession:
    def __init__(self, response=None, exception=None):
        self._response = response
        self._exception = exception
        self.last_call = None

    def get(self, url, params=None, headers=None, timeout=None):
        self.last_call = {
            "url": url,
            "params": params,
            "headers": headers,
            "timeout": timeout,
        }
        if self._exception:
            raise self._exception
        return self._response


def test_parses_real_sample_response_shape():
    session = FakeSession(response=FakeResponse(200, REAL_SAMPLE_BODY))
    events = seismic.fetch_seismic_events(
        now=NOW,
        lookback_days=27,
        radius_km=15,
        min_magnitude=1.0,
        latitude=37.733,
        longitude=14.983,
        user_agent="etna-monitor-test/0.1",
        session=session,
    )
    assert len(events) == 2
    assert events[0] == {
        "event_id": "46943752",
        "origin_time": "2026-08-20T06:54:56.830000Z",
        "latitude": 37.799,
        "longitude": 15.05,
        "depth": 0.8,
        "magnitude": 1.8,
    }


def test_sends_expected_query_parameters():
    session = FakeSession(response=FakeResponse(200, ""))
    seismic.fetch_seismic_events(
        now=NOW,
        lookback_days=1,
        radius_km=15,
        min_magnitude=1.0,
        latitude=37.733,
        longitude=14.983,
        user_agent="etna-monitor-test/0.1",
        session=session,
    )
    params = session.last_call["params"]
    assert params["latitude"] == 37.733
    assert params["longitude"] == 14.983
    assert params["maxradiuskm"] == 15
    assert params["minmagnitude"] == 1.0
    assert params["format"] == "text"
    assert params["endtime"] == "2026-08-28T06:15:00"
    assert session.last_call["headers"]["User-Agent"] == "etna-monitor-test/0.1"


def test_http_204_is_a_real_empty_result_not_a_failure():
    session = FakeSession(response=FakeResponse(204, ""))
    events = seismic.fetch_seismic_events(
        now=NOW,
        lookback_days=1,
        radius_km=15,
        min_magnitude=1.0,
        latitude=37.733,
        longitude=14.983,
        user_agent="etna-monitor-test/0.1",
        session=session,
    )
    assert events == []


def test_non_200_response_raises_source_error():
    session = FakeSession(
        response=FakeResponse(400, 'Bad Request: "starttime" must be YYYY-MM-DDThh:mm:ss')
    )
    with pytest.raises(seismic.SeismicSourceError):
        seismic.fetch_seismic_events(
            now=NOW,
            lookback_days=1,
            radius_km=15,
            min_magnitude=1.0,
            latitude=37.733,
            longitude=14.983,
            user_agent="etna-monitor-test/0.1",
            session=session,
        )


def test_network_failure_raises_source_error():
    session = FakeSession(exception=requests.ConnectionError("no route to host"))
    with pytest.raises(seismic.SeismicSourceError):
        seismic.fetch_seismic_events(
            now=NOW,
            lookback_days=1,
            radius_km=15,
            min_magnitude=1.0,
            latitude=37.733,
            longitude=14.983,
            user_agent="etna-monitor-test/0.1",
            session=session,
        )


def test_unparseable_response_raises_source_error_not_empty_list():
    session = FakeSession(response=FakeResponse(200, "this is not the expected format"))
    with pytest.raises(seismic.SeismicSourceError):
        seismic.fetch_seismic_events(
            now=NOW,
            lookback_days=1,
            radius_km=15,
            min_magnitude=1.0,
            latitude=37.733,
            longitude=14.983,
            user_agent="etna-monitor-test/0.1",
            session=session,
        )
