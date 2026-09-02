from datetime import datetime, timedelta, timezone

from etna_monitor import notify, run, state
from etna_monitor.sources import advisories, seismic, thermal

NOW = datetime(2026, 8, 28, 6, 15, tzinfo=timezone.utc)

CONFIG = {
    "location": {"summit_latitude": 37.733, "summit_longitude": 14.983},
    "seismic": {
        "radius_km": 15,
        "min_magnitude": 1.0,
        "poll_window_days": 3,
        "baseline_days": 30,
        "min_baseline_days": 7,
        "min_count": 5,
        "min_ratio": 2.5,
    },
    "thermal": {
        "box_km": 10,
        "source": "VIIRS_SNPP_NRT",
        "poll_window_days": 2,
        "baseline_days": 14,
        "min_baseline_days": 7,
        "min_count": 5,
        "min_ratio": 3.0,
    },
    "advisories": {"volcano_slug": "etna"},
    "heartbeat": {"interval_days": 7},
    "notify": {
        "ntfy": {"base_url": "https://ntfy.sh"},
        "smtp": {"enabled": False, "use_tls": True, "port": 587},
    },
    "user_agent": "etna-monitor-test/0.1",
}

INGV_SAMPLE = (
    "#EventID|Time|Latitude|Longitude|Depth/Km|Author|Catalog|Contributor|"
    "ContributorID|MagType|Magnitude|MagAuthor|EventLocationName|EventType\n"
    "1|2026-08-28T02:00:00.000000|37.799|15.05|0.8|X||||ML|1.8|--|loc|earthquake\n"
)

FIRMS_SAMPLE = (
    "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,"
    "instrument,confidence,version,bright_ti5,frp,daynight\n"
    "37.748,15.038,312.87,0.42,0.38,2026-08-28,113,N,VIIRS,n,2.0NRT,299.99,1.43,N\n"
)

VAAC_LISTING_SAMPLE = """
<li><a href="https://vaac.meteo.fr/advisory/2026/211060_20260828060000/211060_20260828060000/">
  ETNA.200 - 2026-08-28 06:00 utc
</a>
</li>
"""

VAAC_TEXT_SAMPLE = """VA ADVISORY
DTG: 20260828/0600Z
VOLCANO: ETNA 211060
ADVISORY NR: 2026/200
AVIATION COLOUR CODE: ORANGE
ERUPTION DETAILS: ERUPTION CONTINUES
OBS VA CLD: VA NOT IDENTIFIABLE FM SATELLITE DATA WIND FL100 290/20KT
FCST VA CLD +6 HR: NO VA EXP
NXT ADVISORY: NO FURTHER ADVISORIES="""

# Real advisories fetched from vaac.meteo.fr on 2026-09-02, the run that
# produced four Tier 1 alerts in one morning and motivated batching. 107
# and 108 are identical apart from the advisory number -- their formatted
# output is byte-identical. 109 carries a new eruption identifier
# (20260901 vs 20260831 on 107/108); 110 repeats 109's eruption id with no
# ceiling change. State's real prior entry at the time (2026/106) only
# recorded a colour code, not eruption_id/ash_ceiling_ft, so these are
# used below to prove the batch classifies as SAME OR LESS despite the
# eruption id change on 109 -- state has nothing to compare 109 against.
ADVISORY_107 = """VA ADVISORY
DTG: 20260902/0220Z
VAAC: TOULOUSE
VOLCANO: ETNA 211060
PSN: N3744 E01459
AREA: SICILY VOLCANIC PROVINCE
SOURCE ELEV: 3357M
ADVISORY NR: 2026/107
INFO SOURCE: SAT IMAGERY
AVIATION COLOUR CODE: ORANGE
ERUPTION DETAILS: ERUPTION AT 20260831/2100Z ASH EMISSION ONGOING
OBS VA DTG: 02/0215Z
OBS VA CLD: SFC/FL120 N3742 E01454 - N3753 E01500 - N3706 E01557 - N3653 E01548 - N3742 E01454 MOV SE 10KT
FCST VA CLD +6 HR:NOT PROVIDED
FCST VA CLD +12 HR:NOT PROVIDED
FCST VA CLD +18 HR:NOT PROVIDED
RMK:  THIN ASH CLOUD DETECTABLE ON SAT IMAGERY.
NXT ADVISORY: NO LATER THAN 20260902/0300Z="""

ADVISORY_108 = ADVISORY_107.replace("ADVISORY NR: 2026/107", "ADVISORY NR: 2026/108")

ADVISORY_109 = """VA ADVISORY
DTG: 20260902/0320Z
VAAC: TOULOUSE
VOLCANO: ETNA 211060
PSN: N3744 E01459
AREA: SICILY VOLCANIC PROVINCE
SOURCE ELEV: 3357M
ADVISORY NR: 2026/109
INFO SOURCE: WEBCAM INGV, SAT IMAGERY
AVIATION COLOUR CODE: ORANGE
ERUPTION DETAILS: ERUPTION AT 20260901/2100Z ASH EMISSION ONGOING
OBS VA DTG: 02/0304Z
OBS VA CLD: SFC/FL120 N3748 E01457 - N3753 E01503 - N3700 E01606 - N3642 E01554 - N3748 E01457 MOV SE 10KT
FCST VA CLD +6 HR: 02/0904Z SFC/FL120 N3745 E01500 - N3721 E01515 - N3723 E01503 - N3745 E01457 - N3745 E01500
FCST VA CLD +12 HR: 02/1504Z SFC/FL120 N3745 E01457 - N3748 E01500 - N3738 E01515 - N3730 E01509 - N3745 E01457
FCST VA CLD +18 HR: 02/2104Z SFC/FL120 N3745 E01457 - N3748 E01500 - N3738 E01515 - N3730 E01509 - N3745 E01457
RMK:  ASH CLOUD DETECTABLE ON SAT IMAGERY AND WEBCAMS. DUE TO THE LOW INTENSITY  OF THIS ERUPTIVE EVENT, QVA NOT PROVIDED.
NXT ADVISORY: NO LATER THAN 20260902/0900Z="""

ADVISORY_110 = """VA ADVISORY
DTG: 20260902/0900Z
VAAC: TOULOUSE
VOLCANO: ETNA 211060
PSN: N3744 E01459
AREA: SICILY VOLCANIC PROVINCE
SOURCE ELEV: 3357M
ADVISORY NR: 2026/110
INFO SOURCE: WEBCAM INGV, SAT IMAGERY
AVIATION COLOUR CODE: ORANGE
ERUPTION DETAILS: ERUPTION AT 20260901/2100Z WEAK ASH EMISSION
OBS VA DTG: 02/0900Z
OBS VA CLD: SFC/FL120 N3748 E01454 - N3751 E01503 - N3721 E01521 - N3712 E01512 - N3748 E01454 MOV SE 25KT
FCST VA CLD +6 HR: 02/1500Z NO VA EXP
FCST VA CLD +12 HR: 02/2100Z NO VA EXP
FCST VA CLD +18 HR: 03/0300Z NO VA EXP
RMK:  THIN PLUME DETECTABLE ON WEBCAM. WEAK ASH  EMISSION IN THE VICINITY OF THE VOLCANO. DUE TO  THE LOW INTENSITY OF THIS ERUPTIVE EVENT, QVA DO  NOT SHOW ANY SIGNIFICANT ASH CLOUD AND WILL NOT  BE PROVIDED.
NXT ADVISORY: WILL BE ISSUED BY 20260902/1500Z="""


def _build_tier1_advisories(state_dict, raw_texts):
    """Mirror run_once's own loop: parse each raw text and stamp on the
    colour_changed/previous_colour_code fields format_tier1_message needs,
    tracking previous colour sequentially exactly as run_once does."""
    previous_colour = run.latest_known_colour_code(state_dict)
    built = []
    for raw in raw_texts:
        parsed = advisories.parse_advisory_text(raw)
        colour_changed = previous_colour is not None and parsed["colour_code"] != previous_colour
        built.append({**parsed, "colour_changed": colour_changed, "previous_colour_code": previous_colour})
        previous_colour = parsed["colour_code"]
    return built


class FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


class RoutingSession:
    """Routes .get/.post by URL prefix to a canned response, for exercising
    run.py's orchestration without touching the network."""

    def __init__(self):
        self.responses = {}
        self.calls = []

    def set(self, prefix, response):
        self.responses[prefix] = response

    def _resolve(self, url):
        for prefix, response in self.responses.items():
            if url.startswith(prefix):
                return response
        raise AssertionError(f"no canned response for {url}")

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"method": "GET", "url": url, "params": params})
        return self._resolve(url)

    def post(self, url, data=None, headers=None, timeout=None):
        self.calls.append({"method": "POST", "url": url, "data": data})
        return self._resolve(url)


def fresh_session_all_ok():
    session = RoutingSession()
    session.set(seismic.DEFAULT_BASE_URL, FakeResponse(200, INGV_SAMPLE))
    session.set(thermal.DEFAULT_BASE_URL, FakeResponse(200, FIRMS_SAMPLE))
    session.set("https://vaac.meteo.fr/volcanoes/", FakeResponse(200, VAAC_LISTING_SAMPLE))
    session.set("https://vaac.meteo.fr/advisory/", FakeResponse(200, VAAC_TEXT_SAMPLE))
    session.set("https://ntfy.sh/", FakeResponse(200, "{}"))
    return session


# --- gather_seismic ---


def test_gather_seismic_success_updates_state_and_returns_true():
    session = RoutingSession()
    session.set(seismic.DEFAULT_BASE_URL, FakeResponse(200, INGV_SAMPLE))
    state_dict = state.default_state()
    ok = run.gather_seismic(CONFIG, state_dict, NOW, "ua", session=session)
    assert ok is True
    assert len(state_dict["seismic_events"]) == 1


def test_gather_seismic_failure_returns_false_and_state_unchanged():
    session = RoutingSession()
    session.set(seismic.DEFAULT_BASE_URL, FakeResponse(500, "server error"))
    state_dict = state.default_state()
    ok = run.gather_seismic(CONFIG, state_dict, NOW, "ua", session=session)
    assert ok is False
    assert state_dict["seismic_events"] == []


# --- gather_thermal ---


def test_gather_thermal_success_updates_state_and_returns_true():
    session = RoutingSession()
    session.set(thermal.DEFAULT_BASE_URL, FakeResponse(200, FIRMS_SAMPLE))
    state_dict = state.default_state()
    ok = run.gather_thermal(CONFIG, state_dict, NOW, "test-map-key", "ua", session=session)
    assert ok is True
    by_date = {r["date"]: r for r in state_dict["thermal_daily"]}
    assert by_date["2026-08-28"]["detection_count"] == 1
    assert by_date["2026-08-28"]["detections_available"] is True
    # poll_window_days=2 also covers yesterday, with a real zero
    assert by_date["2026-08-27"]["detection_count"] == 0
    assert by_date["2026-08-27"]["detections_available"] is True


def test_gather_thermal_missing_map_key_marks_unavailable_without_a_request():
    session = RoutingSession()
    state_dict = state.default_state()
    ok = run.gather_thermal(CONFIG, state_dict, NOW, None, "ua", session=session)
    assert ok is False
    assert session.calls == []
    by_date = {r["date"]: r for r in state_dict["thermal_daily"]}
    assert by_date["2026-08-28"]["detections_available"] is False


def test_gather_thermal_source_failure_marks_unavailable():
    session = RoutingSession()
    session.set(thermal.DEFAULT_BASE_URL, FakeResponse(400, "Invalid MAP_KEY."))
    state_dict = state.default_state()
    ok = run.gather_thermal(CONFIG, state_dict, NOW, "bad-key", "ua", session=session)
    assert ok is False
    by_date = {r["date"]: r for r in state_dict["thermal_daily"]}
    assert by_date["2026-08-28"]["detections_available"] is False


def test_gather_thermal_failure_does_not_clobber_earlier_success_same_day():
    session = RoutingSession()
    state_dict = state.default_state()
    state.upsert_thermal_daily(state_dict, "2026-08-28", 7, True)
    session.set(thermal.DEFAULT_BASE_URL, FakeResponse(500, "error"))
    run.gather_thermal(CONFIG, state_dict, NOW, "key", "ua", session=session)
    by_date = {r["date"]: r for r in state_dict["thermal_daily"]}
    assert by_date["2026-08-28"] == {
        "date": "2026-08-28",
        "detection_count": 7,
        "detections_available": True,
    }


# --- gather_advisories ---


def test_gather_advisories_new_entry_parsed():
    session = RoutingSession()
    session.set("https://vaac.meteo.fr/volcanoes/", FakeResponse(200, VAAC_LISTING_SAMPLE))
    session.set("https://vaac.meteo.fr/advisory/", FakeResponse(200, VAAC_TEXT_SAMPLE))
    state_dict = state.default_state()
    ok, new_advisories = run.gather_advisories(CONFIG, state_dict, "ua", session=session)
    assert ok is True
    assert len(new_advisories) == 1
    assert new_advisories[0]["advisory_nr"] == "2026/200"


def test_gather_advisories_already_seen_is_skipped():
    session = RoutingSession()
    session.set("https://vaac.meteo.fr/volcanoes/", FakeResponse(200, VAAC_LISTING_SAMPLE))
    session.set("https://vaac.meteo.fr/advisory/", FakeResponse(200, VAAC_TEXT_SAMPLE))
    state_dict = state.default_state()
    state.record_advisory_seen(state_dict, "2026/200", "2026-08-28T06:00:00Z", "ORANGE")
    ok, new_advisories = run.gather_advisories(CONFIG, state_dict, "ua", session=session)
    assert ok is True
    assert new_advisories == []


def test_gather_advisories_listing_failure_returns_false_empty():
    session = RoutingSession()
    session.set("https://vaac.meteo.fr/volcanoes/", FakeResponse(404, "not found"))
    state_dict = state.default_state()
    ok, new_advisories = run.gather_advisories(CONFIG, state_dict, "ua", session=session)
    assert ok is False
    assert new_advisories == []


# --- signal bridging ---


def test_seismic_signal_cold_start_with_no_history():
    state_dict = state.default_state()
    result = run.seismic_signal(CONFIG, state_dict, NOW, reachable=True)
    assert result.status == "cold_start"


def test_seismic_signal_is_still_cold_start_with_a_single_days_events_and_no_coverage_marker():
    # Regression guard: a handful of real events with no recorded
    # observation coverage must not be zero-filled into a fake 30-day
    # baseline. Without seismic_coverage_start_date, one real event two
    # days ago must not look like "29 confirmed quiet days + 1 active day."
    state_dict = state.default_state()
    state.upsert_seismic_events(
        state_dict,
        [
            {
                "event_id": "e1",
                "origin_time": (NOW - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S.000000Z"),
                "latitude": 37.7,
                "longitude": 15.0,
                "depth": 1.0,
                "magnitude": 1.2,
            }
        ],
    )
    result = run.seismic_signal(CONFIG, state_dict, NOW, reachable=True)
    assert result.status == "cold_start"
    assert result.baseline_days == 0


def test_seismic_signal_counts_recent_24h_and_baseline():
    state_dict = state.default_state()
    events = []
    # 8 days of baseline history, 2 events/day, plus 6 events in the last 24h
    for day_offset in range(1, 9):
        day = NOW - timedelta(days=day_offset, hours=1)
        events.append(
            {
                "event_id": f"base-{day_offset}-a",
                "origin_time": day.strftime("%Y-%m-%dT%H:%M:%S.000000Z"),
                "latitude": 37.7,
                "longitude": 15.0,
                "depth": 1.0,
                "magnitude": 1.2,
            }
        )
    for i in range(6):
        recent = NOW - timedelta(hours=1 + i)
        events.append(
            {
                "event_id": f"recent-{i}",
                "origin_time": recent.strftime("%Y-%m-%dT%H:%M:%S.000000Z"),
                "latitude": 37.7,
                "longitude": 15.0,
                "depth": 1.0,
                "magnitude": 1.2,
            }
        )
    state.upsert_seismic_events(state_dict, events)
    state.extend_seismic_coverage(state_dict, (NOW - timedelta(days=10)).date().isoformat())
    result = run.seismic_signal(CONFIG, state_dict, NOW, reachable=True)
    assert result.status == "ok"
    assert result.baseline_days == 10
    assert result.recent_count == 6
    assert result.fired is True  # 6 >= 5 and 6 >= 2.5 * baseline_mean(0.8)


def test_seismic_signal_unavailable_when_source_unreachable():
    state_dict = state.default_state()
    result = run.seismic_signal(CONFIG, state_dict, NOW, reachable=False)
    assert result.status == "unavailable"


def test_thermal_signal_uses_todays_record_and_excludes_unavailable_days():
    state_dict = state.default_state()
    today = "2026-08-28"
    for i in range(1, 10):
        day = (NOW.date() - timedelta(days=i)).isoformat()
        state.upsert_thermal_daily(state_dict, day, 10, True)
    state.upsert_thermal_daily(state_dict, today, 40, True)
    result = run.thermal_signal(CONFIG, state_dict, today)
    assert result.status == "ok"
    assert result.recent_count == 40
    assert result.fired is True  # 40 >= 5 and 40 >= 3 * 10


def test_thermal_signal_unavailable_today_never_fires():
    state_dict = state.default_state()
    result = run.thermal_signal(CONFIG, state_dict, "2026-08-28")
    assert result.status == "unavailable"


# --- latest_known_colour_code ---


def test_latest_known_colour_code_empty_state():
    assert run.latest_known_colour_code(state.default_state()) is None


def test_latest_known_colour_code_picks_highest_key():
    state_dict = state.default_state()
    state.record_advisory_seen(state_dict, "2026/5", "t", "GREEN")
    state.record_advisory_seen(state_dict, "2026/12", "t", "ORANGE")
    assert run.latest_known_colour_code(state_dict) == "ORANGE"


# --- message formatting ---


def test_format_tier1_message_includes_formatted_body():
    # Body formatting itself is advisory_format.py's job (see
    # tests/test_advisory_format.py); this only checks run.py wires the
    # first line and the formatted body together correctly.
    advisory = {
        "advisory_nr": "2026/200",
        "colour_code": "RED",
        "eruption_details": "x",
        "obs_line": "",
        "forecast_lines": [],
        "has_ash_cloud_forecast": True,
        "raw_text": VAAC_TEXT_SAMPLE,
        "colour_changed": True,
        "previous_colour_code": "ORANGE",
    }
    message = run.format_tier1_message(advisory)
    assert message.startswith("TIER 1")
    assert "2026/200" in message
    assert "ORANGE -> RED" in message
    assert "Colour code ORANGE" in message  # from the formatted body, not the raw text
    assert "N3744 E01459" not in message  # coordinate polygons must not leak through


def test_latest_known_advisory_summary_empty_state():
    assert run.latest_known_advisory_summary(state.default_state()) is None


def test_latest_known_advisory_summary_reads_missing_fields_as_none():
    # An entry written before eruption_id/ash_ceiling_ft existed in the
    # schema (e.g. the real 2026/106 in state at the time of the 107-110
    # batch) has neither key.
    state_dict = state.default_state()
    state.record_advisory_seen(state_dict, "2026/106", "2026-09-01T09:06:00Z", "ORANGE")
    assert run.latest_known_advisory_summary(state_dict) == {
        "colour_code": "ORANGE",
        "eruption_id": None,
        "ash_ceiling_ft": None,
    }


# --- classify_direction ---


def test_classify_direction_escalates_on_colour_code_increase():
    previous = {"colour_code": "YELLOW", "eruption_id": None, "ash_ceiling_ft": None}
    newest = {"colour_code": "RED", "eruption_id": None, "ash_ceiling_ft": None}
    assert run.classify_direction(previous, newest) == "escalation"


def test_classify_direction_same_or_less_on_colour_code_decrease():
    previous = {"colour_code": "RED", "eruption_id": None, "ash_ceiling_ft": None}
    newest = {"colour_code": "ORANGE", "eruption_id": None, "ash_ceiling_ft": None}
    assert run.classify_direction(previous, newest) == "same_or_less"


def test_classify_direction_escalates_on_new_eruption_id():
    previous = {"colour_code": "ORANGE", "eruption_id": "20260831/2100Z", "ash_ceiling_ft": None}
    newest = {"colour_code": "ORANGE", "eruption_id": "20260901/2100Z", "ash_ceiling_ft": None}
    assert run.classify_direction(previous, newest) == "escalation"


def test_classify_direction_escalates_on_ash_ceiling_increase():
    # Synthetic: no real advisory currently in state exercises this branch.
    previous = {"colour_code": "ORANGE", "eruption_id": "20260901/2100Z", "ash_ceiling_ft": 12000}
    newest = {"colour_code": "ORANGE", "eruption_id": "20260901/2100Z", "ash_ceiling_ft": 18000}
    assert run.classify_direction(previous, newest) == "escalation"


def test_classify_direction_no_ceiling_change_is_same_or_less():
    previous = {"colour_code": "ORANGE", "eruption_id": "20260901/2100Z", "ash_ceiling_ft": 12000}
    newest = {"colour_code": "ORANGE", "eruption_id": "20260901/2100Z", "ash_ceiling_ft": 12000}
    assert run.classify_direction(previous, newest) == "same_or_less"


def test_classify_direction_no_prior_advisory_is_same_or_less():
    newest = {"colour_code": "ORANGE", "eruption_id": "20260901/2100Z", "ash_ceiling_ft": 12000}
    assert run.classify_direction(None, newest) == "same_or_less"


def test_classify_direction_missing_colour_code_on_either_side_never_crashes_or_escalates():
    previous = {"colour_code": None, "eruption_id": "X", "ash_ceiling_ft": None}
    newest = {"colour_code": "RED", "eruption_id": "X", "ash_ceiling_ft": None}
    assert run.classify_direction(previous, newest) == "same_or_less"

    previous = {"colour_code": "GREEN", "eruption_id": "X", "ash_ceiling_ft": None}
    newest = {"colour_code": "", "eruption_id": "X", "ash_ceiling_ft": None}
    assert run.classify_direction(previous, newest) == "same_or_less"


def test_classify_direction_unparseable_colour_code_never_escalates():
    previous = {"colour_code": "ORANGE", "eruption_id": "X", "ash_ceiling_ft": None}
    newest = {"colour_code": "UNKNOWN COLOUR", "eruption_id": "X", "ash_ceiling_ft": None}
    assert run.classify_direction(previous, newest) == "same_or_less"


def test_classify_direction_on_the_real_107_110_batch_is_same_or_less():
    # State at the time only knew 2026/106's colour code -- not an
    # eruption_id or ash_ceiling_ft to compare against -- so even though
    # 109 carries a new eruption id relative to 107/108, there is nothing
    # in *state* for it to be new relative to.
    state_dict = state.default_state()
    state.record_advisory_seen(state_dict, "2026/106", "2026-09-01T09:06:00Z", "ORANGE")
    tier1_advisories = _build_tier1_advisories(
        state_dict, [ADVISORY_107, ADVISORY_108, ADVISORY_109, ADVISORY_110]
    )
    assert tier1_advisories[1]["eruption_id"] == "20260831/2100Z"  # 108
    assert tier1_advisories[2]["eruption_id"] == "20260901/2100Z"  # 109: new id

    previous = run.latest_known_advisory_summary(state_dict)
    newest = tier1_advisories[-1]
    direction = run.classify_direction(
        previous,
        {
            "colour_code": newest["colour_code"],
            "eruption_id": newest["eruption_id"],
            "ash_ceiling_ft": newest["ash_ceiling_ft"],
        },
    )
    assert direction == "same_or_less"


# --- format_tier1_batch_message ---


def test_format_tier1_batch_message_single_advisory_matches_todays_rendering():
    advisory = {
        "advisory_nr": "2026/200",
        "colour_code": "RED",
        "eruption_details": "x",
        "obs_line": "",
        "forecast_lines": [],
        "has_ash_cloud_forecast": True,
        "raw_text": VAAC_TEXT_SAMPLE,
        "colour_changed": True,
        "previous_colour_code": "ORANGE",
    }
    assert run.format_tier1_batch_message("escalation", True, [advisory]) == run.format_tier1_message(advisory)


def test_format_tier1_batch_message_byte_identical_advisories_still_one_message():
    # 107 and 108 differ only in the ADVISORY NR line, which
    # advisory_format never renders -- their formatted *bodies* are
    # byte-identical (their full run.format_tier1_message output still
    # differs by advisory number, since that's stated in the header line
    # format_tier1_message adds on top of the formatted body).
    state_dict = state.default_state()
    tier1_advisories = _build_tier1_advisories(state_dict, [ADVISORY_107, ADVISORY_108])
    assert notify.format_tier1_body(ADVISORY_107) == notify.format_tier1_body(ADVISORY_108)

    message = run.format_tier1_batch_message("same_or_less", True, tier1_advisories)
    assert message.count("TIER 1 -- Etna advisory") == 1  # the formatted body appears once, not twice
    assert "2026/108" in message  # the newest, formatted in full
    assert "Other advisories this run: 2026/107" in message
    assert message.startswith("Still active, no change. 2 new advisories since last run.")


def test_format_tier1_batch_message_escalation_header():
    state_dict = state.default_state()
    tier1_advisories = _build_tier1_advisories(state_dict, [ADVISORY_107, ADVISORY_109])
    message = run.format_tier1_batch_message("escalation", True, tier1_advisories)
    assert message.startswith("Escalation. 2 new advisories since last run.")


def test_format_tier1_batch_message_no_baseline_says_new_not_no_change():
    state_dict = state.default_state()
    tier1_advisories = _build_tier1_advisories(state_dict, [ADVISORY_109, ADVISORY_110])
    message = run.format_tier1_batch_message("same_or_less", False, tier1_advisories)
    assert "no change" not in message.lower()
    assert message.startswith("New baseline, nothing to compare against yet. 2 new advisories since last run.")


def test_format_tier2_message_only_mentions_fired_signals():
    seismic_result = thresholds_result(fired=True, recent_count=6, baseline_mean=1.0, baseline_days=10, min_count=5, min_ratio=2.5)
    thermal_result = thresholds_result(fired=False, recent_count=1, baseline_mean=10.0, baseline_days=10, min_count=5, min_ratio=3.0)
    message = run.format_tier2_message(seismic_result, thermal_result)
    assert "Seismic" in message
    assert "Thermal" not in message


def thresholds_result(**kwargs):
    from etna_monitor.thresholds import ThresholdResult

    defaults = dict(status="ok")
    defaults.update(kwargs)
    return ThresholdResult(**defaults)


def test_format_heartbeat_message_counts_runs_in_window():
    state_dict = state.default_state()
    state.record_run(state_dict, "2026-08-27T06:00:00Z", {"seismic": True}, 2, False)
    state.record_run(state_dict, "2026-01-01T06:00:00Z", {"seismic": False}, 5, False)  # outside window
    message = run.format_heartbeat_message(state_dict, NOW, interval_days=7)
    assert "Runs completed in the last 7 days: 1" in message
    assert "Alerts emitted in the last 7 days: 2" in message


# --- run_once orchestration ---


def test_run_once_dry_run_sends_nothing_and_persists_nothing():
    session = fresh_session_all_ok()
    state_dict = state.default_state()
    summary = run.run_once(CONFIG, state_dict, NOW, "test-map-key", session=session, dry_run=True)

    assert not any(call["method"] == "POST" for call in session.calls)
    assert state_dict["runs"] == []
    assert state_dict["last_heartbeat_utc"] is None
    # tier 1 fires (new advisory) and heartbeat is due on an empty state
    assert summary["tier1_fired"] is True
    assert summary["heartbeat_due"] is True
    assert len(summary["messages"]) == 2  # tier1 + heartbeat, tier2 suppressed by tier1


def test_run_once_live_records_run_and_sends():
    session = fresh_session_all_ok()
    state_dict = state.default_state()
    run.run_once(CONFIG, state_dict, NOW, "test-map-key", session=session, dry_run=False)

    assert any(call["method"] == "POST" for call in session.calls)
    assert len(state_dict["runs"]) == 1
    assert state_dict["runs"][0]["sources_reachable"] == {
        "seismic": True,
        "thermal": True,
        "advisories": True,
    }
    assert state_dict["last_heartbeat_utc"] is not None


def test_run_once_continues_when_one_source_fails():
    session = fresh_session_all_ok()
    session.set(seismic.DEFAULT_BASE_URL, FakeResponse(500, "server error"))
    state_dict = state.default_state()
    summary = run.run_once(CONFIG, state_dict, NOW, "test-map-key", session=session, dry_run=False)

    assert summary["sources_reachable"]["seismic"] is False
    assert summary["sources_reachable"]["thermal"] is True
    assert summary["sources_reachable"]["advisories"] is True
    assert len(state_dict["runs"]) == 1  # the run still completes and is recorded


def _seed_seismic_spike(state_dict):
    """8 quiet baseline days plus a same-day spike, with observation
    coverage recorded -- enough for evaluate_seismic to fire on its own."""
    events = []
    for day_offset in range(1, 9):
        day = NOW - timedelta(days=day_offset, hours=1)
        events.append(
            {
                "event_id": f"base-{day_offset}",
                "origin_time": day.strftime("%Y-%m-%dT%H:%M:%S.000000Z"),
                "latitude": 37.7,
                "longitude": 15.0,
                "depth": 1.0,
                "magnitude": 1.2,
            }
        )
    for i in range(6):
        recent = NOW - timedelta(hours=1 + i)
        events.append(
            {
                "event_id": f"recent-{i}",
                "origin_time": recent.strftime("%Y-%m-%dT%H:%M:%S.000000Z"),
                "latitude": 37.7,
                "longitude": 15.0,
                "depth": 1.0,
                "magnitude": 1.2,
            }
        )
    state.upsert_seismic_events(state_dict, events)
    state.extend_seismic_coverage(state_dict, (NOW - timedelta(days=10)).date().isoformat())


def test_run_once_suppresses_tier2_when_tier1_fires():
    session = fresh_session_all_ok()
    state_dict = state.default_state()
    _seed_seismic_spike(state_dict)
    summary = run.run_once(CONFIG, state_dict, NOW, "test-map-key", session=session, dry_run=True)
    assert summary["tier1_fired"] is True
    assert summary["tier2_fired"] is False


def _two_new_advisory_session():
    """A session whose listing carries two new advisories (the real,
    byte-identical-once-formatted 2026/107 and 2026/108) so run_once has
    something to batch."""
    session = RoutingSession()
    session.set(seismic.DEFAULT_BASE_URL, FakeResponse(200, INGV_SAMPLE))
    session.set(thermal.DEFAULT_BASE_URL, FakeResponse(200, FIRMS_SAMPLE))
    session.set("https://ntfy.sh/", FakeResponse(200, "{}"))
    listing = """
<li><a href="https://vaac.meteo.fr/advisory/2026/211060_20260902022019/211060_20260902022019/">
  ETNA.108 - 2026-09-02 02:20 utc
</a>
</li>
<li><a href="https://vaac.meteo.fr/advisory/2026/211060_20260902022016/211060_20260902022016/">
  ETNA.107 - 2026-09-02 02:20 utc
</a>
</li>
"""
    session.set("https://vaac.meteo.fr/volcanoes/", FakeResponse(200, listing))
    session.set(
        "https://vaac.meteo.fr/advisory/2026/211060_20260902022019/211060_20260902022019_vaa.txt",
        FakeResponse(200, ADVISORY_108),
    )
    session.set(
        "https://vaac.meteo.fr/advisory/2026/211060_20260902022016/211060_20260902022016_vaa.txt",
        FakeResponse(200, ADVISORY_107),
    )
    return session


def test_run_once_batches_multiple_new_advisories_into_one_tier1_message():
    session = _two_new_advisory_session()
    state_dict = state.default_state()
    summary = run.run_once(CONFIG, state_dict, NOW, "test-map-key", session=session, dry_run=True)

    assert len(summary["new_advisories"]) == 2
    tier1_messages = [body for title, body in summary["messages"] if title == "Etna Monitor -- Tier 1"]
    assert len(tier1_messages) == 1  # one message, not one per advisory
    message = tier1_messages[0]
    assert message.startswith("New baseline, nothing to compare against yet. 2 new advisories since last run.")
    assert "2026/108" in message  # newest, formatted in full
    assert "Other advisories this run: 2026/107" in message
    assert message.count("TIER 1 -- Etna advisory") == 1  # 107 and 108's bodies are byte-identical; shown once


def test_run_once_alerts_emitted_counts_messages_not_advisories():
    session = _two_new_advisory_session()
    state_dict = state.default_state()
    run.run_once(CONFIG, state_dict, NOW, "test-map-key", session=session, dry_run=False)
    assert state_dict["runs"][-1]["alerts_emitted"] == 1


def test_run_once_no_new_advisories_allows_tier2():
    session = fresh_session_all_ok()
    session.set(
        "https://vaac.meteo.fr/volcanoes/",
        FakeResponse(
            200,
            '<li><a href="https://vaac.meteo.fr/advisory/2026/x/2026x/">ETNA.1 - 2026-01-01 00:00 utc</a></li>',
        ),
    )
    state_dict = state.default_state()
    state.record_advisory_seen(state_dict, "2026/1", "2026-01-01T00:00:00Z", "GREEN")
    _seed_seismic_spike(state_dict)
    summary = run.run_once(CONFIG, state_dict, NOW, "test-map-key", session=session, dry_run=True)
    assert summary["tier1_fired"] is False
    assert summary["tier2_fired"] is True
