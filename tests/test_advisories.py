import pytest
import requests

from etna_monitor.sources import advisories

REAL_LISTING_SAMPLE = """
<li><a href="https://vaac.meteo.fr/advisory/2026/211060_20260818075433/211060_20260818075433/">
  ETNA.105 - 2026-08-18 07:54 utc

</a>
</li>

<li><a href="https://vaac.meteo.fr/advisory/2026/211060_20260818030030/211060_20260818030030/">
  ETNA.104 - 2026-08-18 03:00 utc

</a>
</li>
"""

NO_ASH_TEXT = """VA ADVISORY
DTG: 20260818/0754Z
VOLCANO: ETNA 211060
ADVISORY NR: 2026/105
AVIATION COLOUR CODE: ORANGE
ERUPTION DETAILS: ERUPTION AT 20260816/1620Z EXPLOSIVE ACTIVITY IS DECREASING
OBS VA DTG: 18/0730Z
OBS VA CLD: VA NOT IDENTIFIABLE FM SATELLITE DATA  WIND FL100 290/20KT  FL180 325/20KT
FCST VA CLD +6 HR: 18/1330Z NO VA EXP
FCST VA CLD +12 HR: 18/1930Z NO VA EXP
FCST VA CLD +18 HR: 19/0130Z NO VA EXP
RMK:  WEAK VOLCANIC ASH STILL POSSIBLE IN THE VICINITY  OF THE CRATER.
NXT ADVISORY: NO FURTHER ADVISORIES="""

WITH_ASH_TEXT = """VA ADVISORY
DTG: 20260816/2031Z
VOLCANO: ETNA 211060
ADVISORY NR: 2026/94
AVIATION COLOUR CODE: RED
ERUPTION DETAILS: ERUPTION AT 20260816/2015Z ERUPTION STARTED AT 20H15
OBS VA DTG: 16/2025Z
OBS VA CLD: SFC/FL160 N3745 E01500 - N3745 E01512 - N3738 E01509 - N3745 E01500 MOV SE 10KT
FCST VA CLD +6 HR:NOT PROVIDED
FCST VA CLD +12 HR:NOT PROVIDED
FCST VA CLD +18 HR:NOT PROVIDED
RMK:  ASH CLOUD MOVES TOWARD SE
NXT ADVISORY: NO LATER THAN 20260816/2100Z="""


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


def test_parses_real_listing_sample():
    session = FakeSession(response=FakeResponse(200, REAL_LISTING_SAMPLE))
    entries = advisories.fetch_advisory_listing(
        user_agent="etna-monitor-test/0.1", session=session
    )
    assert entries == [
        {
            "key": "2026/105",
            "text_url": (
                "https://vaac.meteo.fr/advisory/2026/211060_20260818075433/"
                "211060_20260818075433_vaa.txt"
            ),
        },
        {
            "key": "2026/104",
            "text_url": (
                "https://vaac.meteo.fr/advisory/2026/211060_20260818030030/"
                "211060_20260818030030_vaa.txt"
            ),
        },
    ]


def test_listing_sends_user_agent():
    session = FakeSession(response=FakeResponse(200, REAL_LISTING_SAMPLE))
    advisories.fetch_advisory_listing(user_agent="etna-monitor-test/0.1", session=session)
    assert session.last_call["headers"]["User-Agent"] == "etna-monitor-test/0.1"


def test_listing_non_200_raises_source_error():
    session = FakeSession(response=FakeResponse(404, "Not Found"))
    with pytest.raises(advisories.AdvisorySourceError):
        advisories.fetch_advisory_listing(user_agent="etna-monitor-test/0.1", session=session)


def test_listing_network_failure_raises_source_error():
    session = FakeSession(exception=requests.ConnectionError("no route to host"))
    with pytest.raises(advisories.AdvisorySourceError):
        advisories.fetch_advisory_listing(user_agent="etna-monitor-test/0.1", session=session)


def test_listing_unexpected_markup_raises_source_error_not_empty_list():
    session = FakeSession(response=FakeResponse(200, "<html>totally different page</html>"))
    with pytest.raises(advisories.AdvisorySourceError):
        advisories.fetch_advisory_listing(user_agent="etna-monitor-test/0.1", session=session)


def test_fetch_advisory_text_returns_body():
    session = FakeSession(response=FakeResponse(200, NO_ASH_TEXT))
    text = advisories.fetch_advisory_text(
        "https://vaac.meteo.fr/advisory/x_vaa.txt",
        user_agent="etna-monitor-test/0.1",
        session=session,
    )
    assert text == NO_ASH_TEXT


def test_fetch_advisory_text_non_200_raises_source_error():
    session = FakeSession(response=FakeResponse(500, "server error"))
    with pytest.raises(advisories.AdvisorySourceError):
        advisories.fetch_advisory_text(
            "https://vaac.meteo.fr/advisory/x_vaa.txt",
            user_agent="etna-monitor-test/0.1",
            session=session,
        )


def test_parse_no_ash_advisory():
    parsed = advisories.parse_advisory_text(NO_ASH_TEXT)
    assert parsed["advisory_nr"] == "2026/105"
    assert parsed["colour_code"] == "ORANGE"
    assert parsed["has_ash_cloud_forecast"] is False
    assert "EXPLOSIVE ACTIVITY IS DECREASING" in parsed["eruption_details"]
    assert len(parsed["forecast_lines"]) == 3


def test_parse_with_ash_advisory():
    parsed = advisories.parse_advisory_text(WITH_ASH_TEXT)
    assert parsed["advisory_nr"] == "2026/94"
    assert parsed["colour_code"] == "RED"
    assert parsed["has_ash_cloud_forecast"] is True
    assert "SFC/FL160" in parsed["obs_line"]


def test_parse_wind_flight_level_in_no_ash_line_is_not_mistaken_for_ash():
    # regression guard: "VA NOT IDENTIFIABLE ... WIND FL100" contains "FL"
    # but describes wind, not an ash cloud, and must not fire ash detection.
    text = (
        "ADVISORY NR: 2026/1\n"
        "AVIATION COLOUR CODE: ORANGE\n"
        "OBS VA CLD: VA NOT IDENTIFIABLE FM SATELLITE DATA WIND FL100 290/20KT\n"
        "FCST VA CLD +6 HR: NO VA EXP\n"
    )
    parsed = advisories.parse_advisory_text(text)
    assert parsed["has_ash_cloud_forecast"] is False


def test_parse_missing_required_fields_raises_source_error():
    with pytest.raises(advisories.AdvisorySourceError):
        advisories.parse_advisory_text("this is not a VAA at all")
