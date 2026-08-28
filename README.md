# Etna Monitor

A scheduled job that reads three public data sources about Mount Etna once
per day, compares them against stored history, and sends a notification
only when something crosses a threshold. It is silent on ordinary days.

**This is not a forecast tool.** It reports observed state and change in
observed state — nothing here computes a probability of eruption or
predicts future activity. [INGV Osservatorio Etneo](https://www.ct.ingv.it/)
is the authority on Etna activity; this system defers to their published
advisories and bulletins and is not a substitute for them.

Built for a one-month window: user based in Sicily, driving, flying in and
out of a Sicilian airport.

## What it watches

| Source | What | Endpoint |
|---|---|---|
| Seismicity | Earthquake count within 15km of the summit, magnitude >= 1.0 | INGV FDSN event web service |
| Thermal | VIIRS satellite hotspot detections in a ~10km box around the summit | NASA FIRMS area API |
| Ash advisories | VAAC Toulouse aviation advisories for Etna (volcano 211060) | Scraped, no machine feed exists |

Each source is optional at runtime: if one fails, it's logged and marked
unavailable for that run, and evaluation continues with the sources that
did respond. A failed source is never silently reported as "quiet."

## Alerts

**Tier 1 (practical)** fires on every occurrence, no rate limit: a new VAAC
advisory, an aviation colour code change, or an advisory forecasting an ash
cloud at a flight level. The message includes the advisory number and the
full advisory text verbatim.

**Tier 2 (activity)** fires when the last 24 hours' seismic or thermal
count crosses its threshold relative to its own trailing baseline. At most
once per day, and suppressed entirely on any day Tier 1 also fires (Tier 1
already tells the fuller story). Thresholds are unvalidated initial
guesses from the spec (`config.yaml`) and are expected to need tuning.

**Heartbeat**, once per week regardless of activity: how many runs
completed, how many alerts were emitted, and which sources were reachable
on the most recent run. This is what distinguishes silence-because-quiet
from silence-because-dead.

## Setup

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # then fill in real values, or export them directly
```

You need:
- A free NASA FIRMS `MAP_KEY` from https://firms.modaps.eosdis.nasa.gov/api/map_key/
- An [ntfy.sh](https://ntfy.sh) topic name (any string; treat it as a shared secret)
- Optionally, SMTP credentials for a second notification channel (off by default; enable via `notify.smtp.enabled` in `config.yaml`)

For the GitHub Actions workflow, set `FIRMS_MAP_KEY`, `NTFY_TOPIC`, and
(if using email) `SMTP_HOST`/`SMTP_USER`/`SMTP_PASSWORD`/`SMTP_TO` as
repository secrets.

## Commands

```bash
python -m etna_monitor.run                 # live run: fetch, evaluate, notify, write state
python -m etna_monitor.run --dry-run       # fetch and evaluate; write and send nothing
python -m etna_monitor.run --backfill 30   # populate 30 days of trailing history
python -m etna_monitor.run --test-notify   # send one message through every configured channel
```

Run these from the repository root — `config.yaml` and `data/state.json`
are resolved relative to the current directory (override with `--config`
and `--state`).

## Configuration

Every numeric threshold in `config.yaml` is commented with whether it's a
spec-defined constant (query radius, bounding box size) or an unvalidated
guess (the count/ratio thresholds). Tuning is a config edit, not a code
change. Expect false alarms in the first week.

## State

`data/state.json` is a single JSON file, committed back to the repository
by the workflow on every run that changes it — its git history is the
observation record. It's written atomically (temp file, then rename), so
a crash mid-run can never leave it corrupted; killing the process at any
point either leaves the previous state fully intact or the new state
fully written, never a partial file.

## Architecture

```
src/etna_monitor/
  state.py            atomic JSON state store, dedup/trim helpers
  thresholds.py       pure count/ratio evaluation, no I/O, no clock reads
  advisory_format.py  reformats a raw VAAC advisory for phone readability
  notify.py           ntfy.sh push + optional SMTP email
  run.py              wires everything together; the CLI entry point
  sources/
    seismic.py     INGV FDSN event web service client
    thermal.py     NASA FIRMS VIIRS client
    advisories.py  VAAC Toulouse advisory scraper
```

Each source module's docstring records the actual verified request/response
shape from a real call made while building it — not an assumed format.
See `NOTES.md` for discrepancies found between the spec and what the
services actually return.

## Known limitations

- **Tier 2's "at most once per day"** relies on the job running once daily
  under the default cron schedule, not a same-day dedup flag in state. A
  manual `workflow_dispatch` re-run later the same day could in principle
  emit a second Tier 2 alert if conditions still cross threshold.
- **Thermal detections are lumpy and cloud-dependent.** A drop to zero can
  mean cloud cover, not quiet — every thermal number is reported alongside
  the count of days with real data in its baseline window
  (`detections_available`).
- Out of scope, per spec: SO2 retrieval, tremor amplitude, INGV bulletin
  text parsing, any model-based interpretation of the signals, a web
  interface, a map, historical analysis beyond the trailing baseline, or
  any second volcano.

## Testing

```bash
.venv/bin/pip install -r requirements-dev.txt -e .
.venv/bin/python -m pytest tests/
```

No test touches the network — every external call is behind a function
that tests replace with a fixture built from a real recorded response.
