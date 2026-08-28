import json
import os
from datetime import datetime, timezone

import pytest

from etna_monitor import state


def test_default_state_shape():
    s = state.default_state()
    assert s["schema_version"] == state.SCHEMA_VERSION
    assert s["last_run_utc"] is None
    assert s["runs"] == []
    assert s["seismic_events"] == []
    assert s["thermal_daily"] == []
    assert s["advisories_seen"] == []
    assert s["last_heartbeat_utc"] is None


def test_load_state_missing_file_returns_default(tmp_path):
    path = tmp_path / "state.json"
    loaded = state.load_state(str(path))
    assert loaded == state.default_state()


def test_save_then_load_round_trip(tmp_path):
    path = tmp_path / "state.json"
    s = state.default_state()
    s["last_run_utc"] = "2026-08-28T06:15:00Z"
    state.save_state(str(path), s)
    loaded = state.load_state(str(path))
    assert loaded == s


def test_save_state_is_atomic_no_temp_files_left(tmp_path):
    path = tmp_path / "state.json"
    state.save_state(str(path), state.default_state())
    leftovers = [f for f in os.listdir(tmp_path) if f != "state.json"]
    assert leftovers == []


def test_save_state_failure_leaves_original_file_intact(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    original = state.default_state()
    original["last_run_utc"] = "2026-08-01T00:00:00Z"
    state.save_state(str(path), original)

    def boom(*args, **kwargs):
        raise RuntimeError("simulated crash mid-write")

    monkeypatch.setattr(json, "dump", boom)

    with pytest.raises(RuntimeError):
        state.save_state(str(path), {"last_run_utc": "corrupted"})

    # original file untouched and still valid JSON
    with open(path) as f:
        recovered = json.load(f)
    assert recovered == original

    # no leftover temp file
    leftovers = [f for f in os.listdir(tmp_path) if f != "state.json"]
    assert leftovers == []


def test_record_run_appends_and_updates_last_run(tmp_path):
    s = state.default_state()
    state.record_run(s, "2026-08-28T06:15:00Z", {"seismic": True}, 0, False)
    assert s["last_run_utc"] == "2026-08-28T06:15:00Z"
    assert len(s["runs"]) == 1
    assert s["runs"][0] == {
        "timestamp": "2026-08-28T06:15:00Z",
        "sources_reachable": {"seismic": True},
        "alerts_emitted": 0,
        "dry_run": False,
    }


def test_record_run_trims_to_max_records():
    s = state.default_state()
    for i in range(state.MAX_RUN_RECORDS + 10):
        state.record_run(s, f"run-{i}", {}, 0, False)
    assert len(s["runs"]) == state.MAX_RUN_RECORDS
    assert s["runs"][0]["timestamp"] == f"run-{10}"
    assert s["runs"][-1]["timestamp"] == f"run-{state.MAX_RUN_RECORDS + 9}"


def test_upsert_seismic_events_adds_new():
    s = state.default_state()
    events = [
        {
            "event_id": "smi:1",
            "origin_time": "2026-08-27T12:00:00Z",
            "latitude": 37.7,
            "longitude": 14.98,
            "depth": 5.0,
            "magnitude": 1.5,
        }
    ]
    state.upsert_seismic_events(s, events)
    assert len(s["seismic_events"]) == 1
    assert s["seismic_events"][0]["event_id"] == "smi:1"


def test_upsert_seismic_events_updates_in_place_on_reappearance():
    s = state.default_state()
    state.upsert_seismic_events(
        s,
        [
            {
                "event_id": "smi:1",
                "origin_time": "2026-08-27T12:00:00Z",
                "latitude": 37.7,
                "longitude": 14.98,
                "depth": 5.0,
                "magnitude": 1.5,
            }
        ],
    )
    # revised magnitude for the same event id
    state.upsert_seismic_events(
        s,
        [
            {
                "event_id": "smi:1",
                "origin_time": "2026-08-27T12:00:00Z",
                "latitude": 37.7,
                "longitude": 14.98,
                "depth": 5.0,
                "magnitude": 2.1,
            }
        ],
    )
    assert len(s["seismic_events"]) == 1
    assert s["seismic_events"][0]["magnitude"] == 2.1


def test_trim_seismic_events_drops_old_events():
    s = state.default_state()
    now = datetime(2026, 8, 28, tzinfo=timezone.utc)
    state.upsert_seismic_events(
        s,
        [
            {
                "event_id": "old",
                "origin_time": "2026-06-01T00:00:00Z",
                "latitude": 37.7,
                "longitude": 14.98,
                "depth": 5.0,
                "magnitude": 1.0,
            },
            {
                "event_id": "recent",
                "origin_time": "2026-08-27T00:00:00Z",
                "latitude": 37.7,
                "longitude": 14.98,
                "depth": 5.0,
                "magnitude": 1.0,
            },
        ],
    )
    state.trim_seismic_events(s, now, retention_days=45)
    ids = [e["event_id"] for e in s["seismic_events"]]
    assert ids == ["recent"]


def test_upsert_thermal_daily_adds_and_updates():
    s = state.default_state()
    state.upsert_thermal_daily(s, "2026-08-27", 3, True)
    assert s["thermal_daily"] == [
        {"date": "2026-08-27", "detection_count": 3, "detections_available": True}
    ]
    # same date, source failed this time -> should overwrite, not duplicate
    state.upsert_thermal_daily(s, "2026-08-27", 0, False)
    assert s["thermal_daily"] == [
        {"date": "2026-08-27", "detection_count": 0, "detections_available": False}
    ]


def test_upsert_thermal_daily_distinguishes_real_zero_from_unavailable():
    s = state.default_state()
    state.upsert_thermal_daily(s, "2026-08-26", 0, True)
    state.upsert_thermal_daily(s, "2026-08-27", 0, False)
    by_date = {r["date"]: r for r in s["thermal_daily"]}
    assert by_date["2026-08-26"]["detections_available"] is True
    assert by_date["2026-08-27"]["detections_available"] is False


def test_trim_thermal_daily_drops_old_records():
    s = state.default_state()
    now = datetime(2026, 8, 28, tzinfo=timezone.utc)
    state.upsert_thermal_daily(s, "2026-06-01", 2, True)
    state.upsert_thermal_daily(s, "2026-08-27", 4, True)
    state.trim_thermal_daily(s, now, retention_days=45)
    dates = [r["date"] for r in s["thermal_daily"]]
    assert dates == ["2026-08-27"]


def test_record_advisory_seen_new_returns_true():
    s = state.default_state()
    is_new = state.record_advisory_seen(s, "2026/042", "2026-08-27T10:00:00Z", "ORANGE")
    assert is_new is True
    assert s["advisories_seen"] == [
        {
            "key": "2026/042",
            "published_utc": "2026-08-27T10:00:00Z",
            "colour_code": "ORANGE",
        }
    ]


def test_record_advisory_seen_existing_returns_false_and_updates():
    s = state.default_state()
    state.record_advisory_seen(s, "2026/042", "2026-08-27T10:00:00Z", "ORANGE")
    is_new = state.record_advisory_seen(s, "2026/042", "2026-08-27T10:00:00Z", "RED")
    assert is_new is False
    assert len(s["advisories_seen"]) == 1
    assert s["advisories_seen"][0]["colour_code"] == "RED"


def test_record_heartbeat_sets_timestamp():
    s = state.default_state()
    state.record_heartbeat(s, "2026-08-28T06:15:00Z")
    assert s["last_heartbeat_utc"] == "2026-08-28T06:15:00Z"
