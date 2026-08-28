import pytest
import requests

from etna_monitor.sources import thermal

REAL_SAMPLE_BODY = (
    "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,"
    "instrument,confidence,version,bright_ti5,frp,daynight\n"
    "37.74821,15.03866,312.87,0.42,0.38,2026-08-28,113,N,VIIRS,n,2.0NRT,299.99,1.43,N\n"
    "37.74916,15.0335,302.46,0.42,0.38,2026-08-28,113,N,VIIRS,n,2.0NRT,291.72,1.43,N\n"
)

REAL_ZERO_BODY = (
    "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,"
    "instrument,confidence,version,bright_ti5,frp,daynight\n"
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

    def get(self, url, headers=None, timeout=None):
        self.last_call = {"url": url, "headers": headers, "timeout": timeout}
        if self._exception:
            raise self._exception
        return self._response


def test_bounding_box_is_centered_and_roughly_the_right_size():
    west, south, east, north = thermal.bounding_box(37.733, 14.983, box_km=10)
    assert west < 14.983 < east
    assert south < 37.733 < north
    # roughly 10km side -> each half-offset roughly 0.045 degrees latitude
    assert 0.03 < (north - south) / 2 < 0.06


def test_parses_real_sample_response_shape():
    session = FakeSession(response=FakeResponse(200, REAL_SAMPLE_BODY))
    detections = thermal.fetch_detections(
        map_key="test-key",
        west=14.9262,
        south=37.6881,
        east=15.0398,
        north=37.7779,
        day_range=1,
        user_agent="etna-monitor-test/0.1",
        session=session,
    )
    assert len(detections) == 2
    assert detections[0]["latitude"] == 37.74821
    assert detections[0]["acq_date"] == "2026-08-28"
    assert detections[0]["frp"] == 1.43


def test_real_zero_is_empty_list_not_a_failure():
    session = FakeSession(response=FakeResponse(200, REAL_ZERO_BODY))
    detections = thermal.fetch_detections(
        map_key="test-key",
        west=14.9262,
        south=37.6881,
        east=15.0398,
        north=37.7779,
        day_range=1,
        user_agent="etna-monitor-test/0.1",
        session=session,
    )
    assert detections == []


def test_builds_expected_url_with_and_without_start_date():
    session = FakeSession(response=FakeResponse(200, REAL_ZERO_BODY))
    thermal.fetch_detections(
        map_key="test-key",
        west=14.9262,
        south=37.6881,
        east=15.0398,
        north=37.7779,
        day_range=5,
        user_agent="etna-monitor-test/0.1",
        start_date="2026-08-10",
        session=session,
    )
    assert session.last_call["url"] == (
        f"{thermal.DEFAULT_BASE_URL}/test-key/{thermal.DEFAULT_SOURCE}/"
        "14.9262,37.6881,15.0398,37.7779/5/2026-08-10"
    )
    assert session.last_call["headers"]["User-Agent"] == "etna-monitor-test/0.1"

    thermal.fetch_detections(
        map_key="test-key",
        west=14.9262,
        south=37.6881,
        east=15.0398,
        north=37.7779,
        day_range=1,
        user_agent="etna-monitor-test/0.1",
        session=session,
    )
    assert session.last_call["url"] == (
        f"{thermal.DEFAULT_BASE_URL}/test-key/{thermal.DEFAULT_SOURCE}/"
        "14.9262,37.6881,15.0398,37.7779/1"
    )


def test_day_range_above_api_maximum_is_rejected_before_any_request():
    session = FakeSession(response=FakeResponse(200, REAL_ZERO_BODY))
    with pytest.raises(ValueError):
        thermal.fetch_detections(
            map_key="test-key",
            west=14.9262,
            south=37.6881,
            east=15.0398,
            north=37.7779,
            day_range=30,
            user_agent="etna-monitor-test/0.1",
            session=session,
        )
    assert session.last_call is None


def test_bad_map_key_response_raises_source_error():
    session = FakeSession(response=FakeResponse(400, "Invalid MAP_KEY."))
    with pytest.raises(thermal.ThermalSourceError):
        thermal.fetch_detections(
            map_key="bad-key",
            west=14.9262,
            south=37.6881,
            east=15.0398,
            north=37.7779,
            day_range=1,
            user_agent="etna-monitor-test/0.1",
            session=session,
        )


def test_network_failure_raises_source_error():
    session = FakeSession(exception=requests.ConnectionError("no route to host"))
    with pytest.raises(thermal.ThermalSourceError):
        thermal.fetch_detections(
            map_key="test-key",
            west=14.9262,
            south=37.6881,
            east=15.0398,
            north=37.7779,
            day_range=1,
            user_agent="etna-monitor-test/0.1",
            session=session,
        )


def test_unparseable_response_raises_source_error_not_empty_list():
    session = FakeSession(response=FakeResponse(200, "not,the,expected,columns\n1,2,3,4\n"))
    with pytest.raises(thermal.ThermalSourceError):
        thermal.fetch_detections(
            map_key="test-key",
            west=14.9262,
            south=37.6881,
            east=15.0398,
            north=37.7779,
            day_range=1,
            user_agent="etna-monitor-test/0.1",
            session=session,
        )


def test_count_by_date_buckets_detections():
    detections = [
        {"acq_date": "2026-08-27"},
        {"acq_date": "2026-08-27"},
        {"acq_date": "2026-08-28"},
    ]
    assert thermal.count_by_date(detections) == {"2026-08-27": 2, "2026-08-28": 1}


def test_count_by_date_of_empty_list_is_empty_dict():
    assert thermal.count_by_date([]) == {}
