"""Persistent run state for etna-monitor.

State lives in a single JSON file. All functions here operate on plain dicts
and lists so they are trivial to test without touching disk. Disk I/O is
confined to load_state/save_state. No function in this module reads the
clock; "now" is always passed in by the caller.
"""

import json
import os
import tempfile
from datetime import datetime, timedelta

SCHEMA_VERSION = 1
MAX_RUN_RECORDS = 60
SEISMIC_RETENTION_DAYS = 45
THERMAL_RETENTION_DAYS = 45


def default_state():
    return {
        "schema_version": SCHEMA_VERSION,
        "last_run_utc": None,
        "runs": [],
        "seismic_events": [],
        "thermal_daily": [],
        "advisories_seen": [],
        "last_heartbeat_utc": None,
    }


def load_state(path):
    """Return the state dict from path, or a fresh default state if the
    file does not exist yet."""
    if not os.path.exists(path):
        return default_state()
    with open(path, "r") as f:
        return json.load(f)


def save_state(path, state):
    """Write state to path atomically: write to a temp file in the same
    directory, flush and fsync it, then rename over the target. A crash at
    any point leaves either the old file or the new file intact, never a
    partial one, because the rename is atomic on POSIX filesystems."""
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".state-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def record_run(state, timestamp, sources_reachable, alerts_emitted, dry_run):
    """Append a run record and trim to the last MAX_RUN_RECORDS. Updates
    last_run_utc unconditionally, including on dry runs."""
    state["last_run_utc"] = timestamp
    state["runs"].append(
        {
            "timestamp": timestamp,
            "sources_reachable": sources_reachable,
            "alerts_emitted": alerts_emitted,
            "dry_run": dry_run,
        }
    )
    state["runs"] = state["runs"][-MAX_RUN_RECORDS:]


def upsert_seismic_events(state, events):
    """Insert or update events by event_id. An event that reappears with a
    changed magnitude replaces the stored record rather than duplicating
    it."""
    existing = {e["event_id"]: e for e in state["seismic_events"]}
    for event in events:
        existing[event["event_id"]] = event
    state["seismic_events"] = sorted(
        existing.values(), key=lambda e: e["origin_time"]
    )


def trim_seismic_events(state, now, retention_days=SEISMIC_RETENTION_DAYS):
    """Drop seismic events older than retention_days relative to now."""
    cutoff = now - timedelta(days=retention_days)
    state["seismic_events"] = [
        e for e in state["seismic_events"] if _parse_iso(e["origin_time"]) >= cutoff
    ]


def upsert_thermal_daily(state, date, detection_count, detections_available):
    """Insert or update the thermal record for a calendar date (YYYY-MM-DD
    string). detections_available distinguishes a real zero count from a
    day the source could not be queried."""
    records = {r["date"]: r for r in state["thermal_daily"]}
    records[date] = {
        "date": date,
        "detection_count": detection_count,
        "detections_available": detections_available,
    }
    state["thermal_daily"] = sorted(records.values(), key=lambda r: r["date"])


def trim_thermal_daily(state, now, retention_days=THERMAL_RETENTION_DAYS):
    """Drop thermal daily records older than retention_days relative to
    now."""
    cutoff_date = (now - timedelta(days=retention_days)).date().isoformat()
    state["thermal_daily"] = [
        r for r in state["thermal_daily"] if r["date"] >= cutoff_date
    ]


def record_advisory_seen(state, key, published_utc, colour_code):
    """Insert or update an advisory by its key (e.g. "2026/042"). Returns
    True if this is a new advisory, False if it was already present (its
    stored fields are still refreshed, since colour code can be revised)."""
    for advisory in state["advisories_seen"]:
        if advisory["key"] == key:
            advisory["published_utc"] = published_utc
            advisory["colour_code"] = colour_code
            return False
    state["advisories_seen"].append(
        {"key": key, "published_utc": published_utc, "colour_code": colour_code}
    )
    return True


def record_heartbeat(state, timestamp):
    state["last_heartbeat_utc"] = timestamp


def _parse_iso(timestamp):
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
