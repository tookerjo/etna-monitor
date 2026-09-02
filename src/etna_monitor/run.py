"""Wires state, thresholds, notify, and the three sources into the job.

Commands (see README for the full contract):
    python -m etna_monitor.run                 live run
    python -m etna_monitor.run --dry-run        fetch/evaluate/print only
    python -m etna_monitor.run --backfill N     populate N days of history
    python -m etna_monitor.run --test-notify    send one message through every channel

Known simplification: Tier 2's "at most once per day" is not enforced by a
same-day dedup flag in state -- it relies entirely on run cadence. The
default schedule now runs three times a day (see .github/workflows/monitor.yml),
so a seismic or thermal signal that stays above threshold across more than
one run in the same day emits Tier 2 again at each of those runs, not just
once. See NOTES.md.
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

import yaml

from . import notify, state, thresholds
from .sources import advisories, seismic, thermal

DEFAULT_CONFIG_PATH = "config.yaml"
DEFAULT_STATE_PATH = "data/state.json"

logger = logging.getLogger("etna_monitor")


def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)


# --- gathering: one function per source, each independently fault-tolerant ---


def gather_seismic(config, state_dict, now, user_agent, session=None):
    """Fetch recent events and merge into state. Returns True if the
    source was reachable this run."""
    cfg = config["seismic"]
    try:
        events = seismic.fetch_seismic_events(
            now=now,
            lookback_days=cfg["poll_window_days"],
            radius_km=cfg["radius_km"],
            min_magnitude=cfg["min_magnitude"],
            latitude=config["location"]["summit_latitude"],
            longitude=config["location"]["summit_longitude"],
            user_agent=user_agent,
            session=session,
        )
    except seismic.SeismicSourceError as exc:
        logger.error("seismic source unavailable: %s", exc)
        return False
    state.upsert_seismic_events(state_dict, events)
    state.extend_seismic_coverage(state_dict, (now - timedelta(days=cfg["poll_window_days"])).date().isoformat())
    return True


def gather_thermal(config, state_dict, now, map_key, user_agent, session=None):
    """Fetch recent detections and merge into state as daily counts.
    Returns True if the source was reachable this run."""
    cfg = config["thermal"]
    today_str = now.date().isoformat()

    if not map_key:
        logger.error("thermal source unavailable: FIRMS_MAP_KEY is not set")
        _mark_thermal_unavailable(state_dict, today_str)
        return False

    west, south, east, north = thermal.bounding_box(
        config["location"]["summit_latitude"],
        config["location"]["summit_longitude"],
        cfg["box_km"],
    )
    try:
        detections = thermal.fetch_detections(
            map_key=map_key,
            west=west,
            south=south,
            east=east,
            north=north,
            day_range=cfg["poll_window_days"],
            user_agent=user_agent,
            source=cfg.get("source", thermal.DEFAULT_SOURCE),
            session=session,
        )
    except thermal.ThermalSourceError as exc:
        logger.error("thermal source unavailable: %s", exc)
        _mark_thermal_unavailable(state_dict, today_str)
        return False

    counts = thermal.count_by_date(detections)
    for i in range(cfg["poll_window_days"]):
        day_str = (now.date() - timedelta(days=i)).isoformat()
        state.upsert_thermal_daily(state_dict, day_str, counts.get(day_str, 0), True)
    return True


def _mark_thermal_unavailable(state_dict, today_str):
    existing = next((r for r in state_dict["thermal_daily"] if r["date"] == today_str), None)
    if not (existing and existing["detections_available"]):
        state.upsert_thermal_daily(state_dict, today_str, 0, False)


def gather_advisories(config, state_dict, user_agent, session=None):
    """Fetch the advisory listing and the text of any advisory not already
    in state. Returns (reachable, parsed_new_advisories_oldest_first)."""
    cfg = config["advisories"]
    try:
        listing = advisories.fetch_advisory_listing(
            user_agent=user_agent,
            volcano_slug=cfg["volcano_slug"],
            session=session,
        )
    except advisories.AdvisorySourceError as exc:
        logger.error("advisory source unavailable: %s", exc)
        return False, []

    known_keys = {a["key"] for a in state_dict["advisories_seen"]}
    new_entries = [entry for entry in listing if entry["key"] not in known_keys]
    new_entries.reverse()  # process oldest-first for stable colour-change detection

    parsed_new = []
    for entry in new_entries:
        try:
            text = advisories.fetch_advisory_text(entry["text_url"], user_agent=user_agent, session=session)
            parsed_new.append(advisories.parse_advisory_text(text))
        except advisories.AdvisorySourceError as exc:
            logger.error("failed to fetch/parse advisory %s: %s", entry["key"], exc)

    return True, parsed_new


# --- threshold evaluation: bridges state's stored history to thresholds.py ---


def _advisory_sort_key(entry):
    year, seq = entry["key"].split("/")
    return (int(year), int(seq))


def latest_known_colour_code(state_dict):
    seen = state_dict["advisories_seen"]
    if not seen:
        return None
    return max(seen, key=_advisory_sort_key)["colour_code"]


def latest_known_advisory_summary(state_dict):
    """The colour code, eruption id, and ash ceiling of the advisory
    already in state with the highest YEAR/NNN key, for classify_direction
    to compare the newest new advisory against. None if state has no
    advisories yet.

    An entry recorded before eruption_id/ash_ceiling_ft existed in the
    schema has neither key; .get() reads those back as None, which
    classify_direction treats as "no evidence" rather than a change."""
    seen = state_dict["advisories_seen"]
    if not seen:
        return None
    latest = max(seen, key=_advisory_sort_key)
    return {
        "colour_code": latest.get("colour_code"),
        "eruption_id": latest.get("eruption_id"),
        "ash_ceiling_ft": latest.get("ash_ceiling_ft"),
    }


# Aviation colour code scale, low to high. Anything not on this list (a
# blank field, "NOT GIVEN", a typo) ranks as None so it can never be
# compared -- classify_direction must not assert an escalation from a
# colour it can't place on the scale.
_COLOUR_ORDER = ["GREEN", "YELLOW", "ORANGE", "RED"]


def _colour_rank(colour_code):
    if not colour_code:
        return None
    code = colour_code.strip().upper()
    return _COLOUR_ORDER.index(code) if code in _COLOUR_ORDER else None


def classify_direction(previous, newest):
    """Pure comparison, no I/O. `previous` is latest_known_advisory_summary's
    return value (None if state had no advisory before this run); `newest`
    is the same shape for the batch's newest new advisory.

    Returns "escalation" if the colour code moved up, the ash ceiling
    increased, or the eruption identifier changed; otherwise
    "same_or_less". No prior advisory to compare against is SAME OR LESS,
    not escalation -- the caller is responsible for saying the baseline is
    new rather than claiming no change (see format_tier1_batch_message).
    A field missing or unparseable on either side is never treated as
    evidence of escalation; only a positively confirmed change counts."""
    if previous is None:
        return "same_or_less"

    prev_rank = _colour_rank(previous.get("colour_code"))
    new_rank = _colour_rank(newest.get("colour_code"))
    if prev_rank is not None and new_rank is not None and new_rank > prev_rank:
        return "escalation"

    prev_ceiling = previous.get("ash_ceiling_ft")
    new_ceiling = newest.get("ash_ceiling_ft")
    if prev_ceiling is not None and new_ceiling is not None and new_ceiling > prev_ceiling:
        return "escalation"

    prev_eruption = previous.get("eruption_id")
    new_eruption = newest.get("eruption_id")
    if prev_eruption is not None and new_eruption is not None and new_eruption != prev_eruption:
        return "escalation"

    return "same_or_less"


def _parse_iso(timestamp):
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


def seismic_signal(config, state_dict, now, reachable):
    cfg = config["seismic"]
    events = state_dict["seismic_events"]
    coverage_start = state_dict.get("seismic_coverage_start_date")

    recent_cutoff = now - timedelta(hours=24)
    recent_count = sum(1 for e in events if _parse_iso(e["origin_time"]) >= recent_cutoff)

    daily_counts = {}
    for event in events:
        day = _parse_iso(event["origin_time"]).date()
        daily_counts[day] = daily_counts.get(day, 0) + 1

    # A trailing day only belongs in the baseline if INGV has actually been
    # queried back that far -- otherwise a day with zero events is
    # indistinguishable from a day nobody checked, and cold start would
    # never trigger for a brand-new deployment (every unchecked day would
    # silently read as a confirmed quiet day).
    trailing = []
    if coverage_start:
        coverage_start_date = datetime.fromisoformat(coverage_start).date()
        today = now.date()
        for i in range(1, cfg["baseline_days"] + 1):
            day = today - timedelta(days=i)
            if day >= coverage_start_date:
                trailing.append(daily_counts.get(day, 0))

    return thresholds.evaluate_seismic(
        recent_count=recent_count,
        recent_available=reachable,
        trailing_daily_counts=trailing,
        min_baseline_days=cfg["min_baseline_days"],
        min_count=cfg["min_count"],
        min_ratio=cfg["min_ratio"],
    )


def thermal_signal(config, state_dict, today_str):
    cfg = config["thermal"]
    by_date = {r["date"]: r for r in state_dict["thermal_daily"]}

    today_record = by_date.get(today_str)
    recent_available = bool(today_record and today_record["detections_available"])
    recent_count = today_record["detection_count"] if today_record else None

    today = datetime.fromisoformat(today_str).date()
    trailing = []
    for i in range(1, cfg["baseline_days"] + 1):
        day_str = (today - timedelta(days=i)).isoformat()
        record = by_date.get(day_str)
        if record:
            trailing.append((record["detection_count"], record["detections_available"]))
        else:
            trailing.append((0, False))

    return thresholds.evaluate_thermal(
        recent_count=recent_count,
        recent_available=recent_available,
        trailing_daily_records=trailing,
        min_baseline_days=cfg["min_baseline_days"],
        min_count=cfg["min_count"],
        min_ratio=cfg["min_ratio"],
    )


# --- message formatting: plain text, no predictive language ---


def format_tier1_message(advisory):
    reasons = ["new advisory published"]
    if advisory["colour_changed"]:
        reasons.append(
            f"aviation colour code changed {advisory['previous_colour_code']} -> {advisory['colour_code']}"
        )
    if advisory["has_ash_cloud_forecast"]:
        reasons.append("ash cloud reported at a flight level")
    first_line = f"TIER 1 -- Etna advisory {advisory['advisory_nr']}: {'; '.join(reasons)}"
    body = notify.format_tier1_body(advisory["raw_text"])
    return first_line + "\n\n" + body


def format_tier1_batch_message(direction, has_baseline, tier1_advisories):
    """Exactly one Tier 1 message for the run, regardless of how many new
    advisories were found this run (tier1_advisories, oldest first, same
    shape as format_tier1_message expects).

    One advisory: today's single-advisory rendering, unchanged. More than
    one: a header naming the direction and the count, the newest advisory
    formatted in full, then a single line listing the other advisory
    numbers -- their full text is already in state and is not resent, so
    two advisories whose formatted output happens to be byte-identical
    still produce one message with the body shown once."""
    if len(tier1_advisories) == 1:
        return format_tier1_message(tier1_advisories[0])

    count = len(tier1_advisories)
    newest = tier1_advisories[-1]
    others = tier1_advisories[:-1]

    if not has_baseline:
        header = f"New baseline, nothing to compare against yet. {count} new advisories since last run."
    elif direction == "escalation":
        header = f"Escalation. {count} new advisories since last run."
    else:
        header = f"Still active, no change. {count} new advisories since last run."

    other_numbers = ", ".join(a["advisory_nr"] for a in others)
    return "\n\n".join(
        [header, format_tier1_message(newest), f"Other advisories this run: {other_numbers}"]
    )


def format_tier2_message(seismic_result, thermal_result):
    lines = ["TIER 2 -- activity signal crossed its threshold"]
    if seismic_result.fired:
        lines.append(
            f"Seismic: {seismic_result.recent_count} events in the last 24h "
            f"(baseline {seismic_result.baseline_mean:.2f}/day over "
            f"{seismic_result.baseline_days} days; threshold is "
            f"{seismic_result.min_count} events and {seismic_result.min_ratio}x baseline)"
        )
    if thermal_result.fired:
        lines.append(
            f"Thermal: {thermal_result.recent_count} detections today "
            f"(baseline {thermal_result.baseline_mean:.2f}/day over "
            f"{thermal_result.baseline_days} days with data; threshold is "
            f"{thermal_result.min_count} detections and {thermal_result.min_ratio}x baseline)"
        )
    return "\n".join(lines)


def format_heartbeat_message(state_dict, now, interval_days):
    cutoff = now - timedelta(days=interval_days)
    recent_runs = [r for r in state_dict["runs"] if _parse_iso(r["timestamp"]) >= cutoff]
    alert_count = sum(r["alerts_emitted"] for r in recent_runs)

    if state_dict["runs"]:
        reachable = state_dict["runs"][-1]["sources_reachable"]
        reachable_str = ", ".join(
            f"{name}: {'reachable' if ok else 'unreachable'}" for name, ok in reachable.items()
        )
    else:
        reachable_str = "no runs recorded yet"

    return (
        "HEARTBEAT -- weekly status, sent regardless of activity\n"
        f"Runs completed in the last {interval_days} days: {len(recent_runs)}\n"
        f"Alerts emitted in the last {interval_days} days: {alert_count}\n"
        f"Sources reachable on the most recent run: {reachable_str}"
    )


def _smtp_config(config):
    return {
        "host": os.environ.get("SMTP_HOST"),
        "port": config["notify"]["smtp"]["port"],
        "user": os.environ.get("SMTP_USER"),
        "password": os.environ.get("SMTP_PASSWORD"),
        "to": os.environ.get("SMTP_TO"),
        "use_tls": config["notify"]["smtp"]["use_tls"],
    }


def _deliver(config, title, body, session=None, smtp_client_cls=None):
    smtp_cfg = config["notify"]["smtp"]
    return notify.send_message(
        title,
        body,
        ntfy_topic=os.environ.get("NTFY_TOPIC"),
        ntfy_base_url=config["notify"]["ntfy"]["base_url"],
        smtp=_smtp_config(config) if smtp_cfg.get("enabled") else None,
        user_agent=config["user_agent"],
        session=session,
        smtp_client_cls=smtp_client_cls,
    )


# --- one run cycle ---


def run_once(config, state_dict, now, map_key, session=None, smtp_client_cls=None, dry_run=False):
    """Fetch every source, evaluate thresholds, and (unless dry_run) send
    and persist. Mutates state_dict in place; the caller decides whether
    to save it (a dry run never does). Returns a summary dict for
    printing."""
    user_agent = config["user_agent"]

    seismic_reachable = gather_seismic(config, state_dict, now, user_agent, session=session)
    thermal_reachable = gather_thermal(config, state_dict, now, map_key, user_agent, session=session)
    advisories_reachable, new_advisories = gather_advisories(config, state_dict, user_agent, session=session)

    sources_reachable = {
        "seismic": seismic_reachable,
        "thermal": thermal_reachable,
        "advisories": advisories_reachable,
    }

    messages = []
    previous_advisory_summary = latest_known_advisory_summary(state_dict)
    previous_colour = latest_known_colour_code(state_dict)
    tier1_advisories = []
    for parsed in new_advisories:
        colour_changed = previous_colour is not None and parsed["colour_code"] != previous_colour
        tier1_advisories.append(
            {
                **parsed,
                "colour_changed": colour_changed,
                "previous_colour_code": previous_colour,
            }
        )
        previous_colour = parsed["colour_code"]
        state.record_advisory_seen(
            state_dict,
            parsed["advisory_nr"],
            parsed["published_utc"],
            parsed["colour_code"],
            eruption_id=parsed.get("eruption_id"),
            ash_ceiling_ft=parsed.get("ash_ceiling_ft"),
        )

    if tier1_advisories:
        newest = tier1_advisories[-1]
        newest_summary = {
            "colour_code": newest["colour_code"],
            "eruption_id": newest.get("eruption_id"),
            "ash_ceiling_ft": newest.get("ash_ceiling_ft"),
        }
        direction = classify_direction(previous_advisory_summary, newest_summary)
        batch_message = format_tier1_batch_message(
            direction, previous_advisory_summary is not None, tier1_advisories
        )
        messages.append(("Etna Monitor -- Tier 1", batch_message))

    seismic_result = seismic_signal(config, state_dict, now, seismic_reachable)
    thermal_result = thermal_signal(config, state_dict, now.date().isoformat())

    tier2_body = None
    if not tier1_advisories and (seismic_result.fired or thermal_result.fired):
        tier2_body = format_tier2_message(seismic_result, thermal_result)
        messages.append(("Etna Monitor -- Tier 2", tier2_body))

    interval_days = config["heartbeat"]["interval_days"]
    last_heartbeat = state_dict.get("last_heartbeat_utc")
    heartbeat_due = last_heartbeat is None or (now - _parse_iso(last_heartbeat)) >= timedelta(days=interval_days)
    if heartbeat_due:
        messages.append(("Etna Monitor -- Heartbeat", format_heartbeat_message(state_dict, now, interval_days)))

    delivery_results = []
    if not dry_run:
        for title, body in messages:
            delivery_results.append((title, _deliver(config, title, body, session=session, smtp_client_cls=smtp_client_cls)))
        if heartbeat_due:
            state.record_heartbeat(state_dict, now.strftime("%Y-%m-%dT%H:%M:%SZ"))
        alerts_emitted = (1 if tier1_advisories else 0) + (1 if tier2_body is not None else 0)
        state.record_run(state_dict, now.strftime("%Y-%m-%dT%H:%M:%SZ"), sources_reachable, alerts_emitted, dry_run=False)
        state.trim_seismic_events(state_dict, now)
        state.trim_thermal_daily(state_dict, now)

    return {
        "sources_reachable": sources_reachable,
        "seismic": seismic_result,
        "thermal": thermal_result,
        "new_advisories": tier1_advisories,
        "tier1_fired": bool(tier1_advisories),
        "tier2_fired": tier2_body is not None,
        "heartbeat_due": heartbeat_due,
        "messages": messages,
        "delivery_results": delivery_results,
    }


def run_backfill(config, state_path, map_key, days, now, session=None):
    """Populate `days` of trailing history in one pass. Seismic needs one
    request (INGV has no day-range cap); thermal needs ceil(days/5)
    requests since FIRMS caps day_range at 5 per call."""
    state_dict = state.load_state(state_path)
    user_agent = config["user_agent"]

    try:
        events = seismic.fetch_seismic_events(
            now=now,
            lookback_days=days,
            radius_km=config["seismic"]["radius_km"],
            min_magnitude=config["seismic"]["min_magnitude"],
            latitude=config["location"]["summit_latitude"],
            longitude=config["location"]["summit_longitude"],
            user_agent=user_agent,
            session=session,
        )
        state.upsert_seismic_events(state_dict, events)
        state.extend_seismic_coverage(state_dict, (now - timedelta(days=days)).date().isoformat())
        seismic_ok = True
    except seismic.SeismicSourceError as exc:
        logger.error("backfill: seismic source unavailable: %s", exc)
        seismic_ok = False

    thermal_ok = True
    if not map_key:
        logger.error("backfill: thermal source unavailable: FIRMS_MAP_KEY is not set")
        thermal_ok = False
    else:
        west, south, east, north = thermal.bounding_box(
            config["location"]["summit_latitude"],
            config["location"]["summit_longitude"],
            config["thermal"]["box_km"],
        )
        cursor = now.date() - timedelta(days=days - 1)
        while cursor <= now.date():
            window_days = min(thermal.MAX_DAY_RANGE, (now.date() - cursor).days + 1)
            try:
                detections = thermal.fetch_detections(
                    map_key=map_key,
                    west=west,
                    south=south,
                    east=east,
                    north=north,
                    day_range=window_days,
                    user_agent=user_agent,
                    source=config["thermal"].get("source", thermal.DEFAULT_SOURCE),
                    start_date=cursor.isoformat(),
                    session=session,
                )
                counts = thermal.count_by_date(detections)
                for i in range(window_days):
                    day_str = (cursor + timedelta(days=i)).isoformat()
                    state.upsert_thermal_daily(state_dict, day_str, counts.get(day_str, 0), True)
            except thermal.ThermalSourceError as exc:
                logger.error(
                    "backfill: thermal source unavailable for window starting %s: %s", cursor, exc
                )
                thermal_ok = False
            cursor += timedelta(days=window_days)

    state.trim_seismic_events(state_dict, now)
    state.trim_thermal_daily(state_dict, now)
    state.save_state(state_path, state_dict)
    return state_dict, seismic_ok, thermal_ok


# --- CLI ---


def _print_summary(summary, dry_run):
    label = "DRY RUN" if dry_run else "RUN"
    print(f"=== Etna Monitor {label} summary ===")
    print("Sources reachable:")
    for name, ok in summary["sources_reachable"].items():
        print(f"  {name}: {'yes' if ok else 'no'}")

    for name, result in (("Seismic", summary["seismic"]), ("Thermal", summary["thermal"])):
        print(
            f"{name}: status={result.status} recent={result.recent_count} "
            f"baseline_mean={result.baseline_mean} baseline_days={result.baseline_days} "
            f"fired={result.fired}"
        )

    print(f"New advisories this run: {len(summary['new_advisories'])}")
    print(f"Tier 1 fired: {summary['tier1_fired']}")
    print(f"Tier 2 fired: {summary['tier2_fired']}")
    print(f"Heartbeat due: {summary['heartbeat_due']}")

    if dry_run:
        for title, body in summary["messages"]:
            print(f"--- Would send: {title} ---")
            print(body)
    else:
        for title, result in summary["delivery_results"]:
            print(f"Delivery [{title}]: {result}")


def _cmd_run(config, state_path, now, dry_run):
    map_key = os.environ.get("FIRMS_MAP_KEY")
    if not map_key:
        logger.warning("FIRMS_MAP_KEY is not set; thermal source will be marked unavailable")

    state_dict = state.load_state(state_path)
    summary = run_once(config, state_dict, now, map_key, dry_run=dry_run)
    if not dry_run:
        state.save_state(state_path, state_dict)
    _print_summary(summary, dry_run)
    return 0


def _cmd_backfill(config, state_path, days, now):
    map_key = os.environ.get("FIRMS_MAP_KEY")
    state_dict, seismic_ok, thermal_ok = run_backfill(config, state_path, map_key, days, now)

    seismic_result = seismic_signal(config, state_dict, now, seismic_ok)
    thermal_result = thermal_signal(config, state_dict, now.date().isoformat())

    print(f"=== Etna Monitor backfill summary ({days} days) ===")
    print(f"Seismic reachable: {seismic_ok}; events stored: {len(state_dict['seismic_events'])}")
    print(f"Thermal reachable: {thermal_ok}; daily records stored: {len(state_dict['thermal_daily'])}")
    print(
        f"Seismic baseline: status={seismic_result.status} "
        f"mean={seismic_result.baseline_mean} over {seismic_result.baseline_days} days"
    )
    print(
        f"Thermal baseline: status={thermal_result.status} "
        f"mean={thermal_result.baseline_mean} over {thermal_result.baseline_days} days"
    )
    return 0


def _cmd_test_notify(config):
    results = _deliver(
        config,
        "Etna Monitor -- test notification",
        "This is a test message from `python -m etna_monitor.run --test-notify`. "
        "If you can read this, the channel works.",
    )
    print("Test notification results:")
    for channel, outcome in results.items():
        print(f"  {channel}: {outcome}")
    failed = [c for c, outcome in results.items() if outcome not in (True, "not configured")]
    return 1 if failed else 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m etna_monitor.run")
    parser.add_argument("--dry-run", action="store_true", help="fetch and evaluate; write and send nothing")
    parser.add_argument("--backfill", type=int, metavar="DAYS", help="populate DAYS of trailing history")
    parser.add_argument("--test-notify", action="store_true", help="send one message through every channel")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--state", default=DEFAULT_STATE_PATH)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    config = load_config(args.config)
    now = datetime.now(timezone.utc)

    if args.test_notify:
        return _cmd_test_notify(config)
    if args.backfill is not None:
        return _cmd_backfill(config, args.state, args.backfill, now)
    return _cmd_run(config, args.state, now, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
