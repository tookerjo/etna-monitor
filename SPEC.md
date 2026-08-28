# Etna Monitor: build specification

## What this is

A scheduled job that reads three public data sources about Mount Etna once per
day, compares them against stored history, and sends a notification only when
something crosses a threshold. It is silent on ordinary days.

It is not a forecast tool. It reports observed state and change in observed
state. INGV Osservatorio Etneo is the authority on Etna activity and this
system defers to their published advisories. The README must say this.

Operating window: one month, user based in Sicily, driving, flying in and out
of a Sicilian airport.

## Two alert tiers

The system emits at two different levels with different urgency.

### Tier 1, practical

Fires on anything that could affect air travel or outdoor plans.

- A new VAAC Toulouse advisory is published for Etna that was not in state.
- The aviation colour code changes in either direction.
- An advisory forecasts an ash cloud at any flight level.

Tier 1 emits on every occurrence, no rate limit. Message includes the advisory
number, the colour code, the eruption detail line, and the observed and
forecast ash cloud lines verbatim from the advisory text.

### Tier 2, activity

Fires when the underlying signals move relative to their own recent history.

- Seismic event count in the last 24 hours crosses the seismic threshold.
- Thermal anomaly count in the last 24 hours crosses the thermal threshold.

Tier 2 emits at most once per day and is suppressed entirely on any day where
Tier 1 also fires, since Tier 1 already tells the fuller story.

### Heartbeat

Once per week, regardless of activity, send a message stating how many runs
completed in the last seven days, how many alerts were emitted, and which
sources were reachable on the most recent run. This distinguishes silence
because quiet from silence because dead.

## Data sources

Each source is optional at runtime. A source that fails is marked unavailable
for that run, logged, and excluded from threshold evaluation. A run with a
failed source must not be reported as quiet for that signal.

### Seismicity: INGV FDSN event web service

Base: `http://webservices.ingv.it/fdsnws/event/1/query`

Standard FDSN event parameters. Query a circular region around the summit with
a time window and a minimum magnitude, request a machine-readable output
format, and count events. Verify the exact parameter names and supported output
formats against the service documentation before writing the client. Do not
guess parameter names.

Summit reference position: 37.733 N, 14.983 E. This is the position VAAC
Toulouse states in its own Etna advisories.

Query radius: 15 km. Minimum magnitude: 1.0.

Store per event: origin time, latitude, longitude, depth, magnitude, event id.
Event id is the deduplication key. Events get revised, so an event already in
state may reappear with a changed magnitude. On reappearance, update in place
rather than inserting a duplicate.

### Thermal: NASA FIRMS area API

Base: `https://firms.modaps.eosdis.nasa.gov/api/area/csv/[MAP_KEY]/[SOURCE]/[AREA]/[DAY_RANGE]`

Requires a free MAP_KEY, requested at
`https://firms.modaps.eosdis.nasa.gov/api/map_key/`. Rate limit is documented
as 5000 transactions per 10 minute interval, which this job will not approach.

AREA is a bounding box in `west,south,east,north` order. Use a box roughly
10 km on a side centred on the summit. SOURCE should be a VIIRS product.
Confirm the current valid source identifiers from the API documentation rather
than assuming.

These are fire detections, not a volcano product. At Etna they pick up lava and
hot vents, which is the intended signal. Two consequences that must be handled
rather than ignored:

- Cloud cover suppresses detection. A drop to zero can mean cloud, not quiet.
- Detection depends on satellite overpass timing, so daily counts are lumpy.

Every stored daily thermal count must carry a `detections_available` boolean.
When the API returns successfully with zero rows, that is a real zero. When the
call fails, that is unavailable. These are different and must not be conflated.

### Ash advisories: VAAC Toulouse

Advisory index: `https://vaac.meteo.fr/advisory/`

Individual Etna advisories appear under a per-volcano path with a text version
linked from each advisory page. Etna's volcano number is 211060.

Determine the correct listing or feed URL for Etna advisories by inspecting the
site during the build. If no stable machine-readable listing exists, parse the
advisory index page for Etna entries. Store the advisory number and the raw
advisory text.

Advisory numbers are sequential within a calendar year, formatted as
`YEAR/NNN`. Use the full string as the key, not the integer.

## State

A single JSON file at `data/state.json`, committed back to the repository by
the workflow on every run that changes it. The git history of this file is the
observation record.

Required top-level keys:

- `schema_version`, integer, incremented on any breaking change to this shape.
- `last_run_utc`, ISO 8601 timestamp.
- `runs`, list of the last 60 run records: timestamp, sources reachable,
  alerts emitted, and whether the run was a dry run.
- `seismic_events`, list of events within the last 45 days, deduplicated on
  event id.
- `thermal_daily`, list of per-day records: date, detection count,
  `detections_available`.
- `advisories_seen`, list of advisory keys with their publication timestamp and
  colour code.
- `last_heartbeat_utc`.

Trim on write so the file does not grow without bound. Forty-five days of
seismic history and sixty run records is enough.

State must be written atomically: write to a temp file, then move. A run that
crashes mid-write must not corrupt state.

## Thresholds

These initial values are guesses. They will produce false alarms in the first
week and are expected to be tuned twice. They live in `config.yaml`, not in
code, so tuning is a config edit and not a code change.

Seismic: fire when the count of events in the last 24 hours is at least 5 and
at least 2.5 times the trailing 30-day daily mean.

Thermal: fire when the count of detections in the last 24 hours is at least 5
and at least 3 times the trailing 14-day daily mean, counting only days where
`detections_available` is true.

Both rules require a minimum baseline length. If fewer than 7 days of history
exist for a signal, that signal does not fire and the message says the baseline
is still filling. This is the cold start case and it must be handled explicitly,
not by dividing by zero.

## Notification

Primary channel: ntfy.sh push to a topic held in a repository secret. Works on
a phone abroad with no account.

Optional second channel: SMTP email, enabled by config, credentials in secrets.

Message format is plain text. First line states the tier and the reason. Body
gives the numbers with their baselines, so the message is interpretable without
opening anything. Advisory text is included verbatim for Tier 1.

No message body may contain a probability of eruption, a forecast of future
activity, or any language implying prediction.

## Repository shape

```
etna-monitor/
  README.md
  config.yaml
  requirements.txt
  data/state.json
  src/etna_monitor/
    __init__.py
    run.py
    state.py
    notify.py
    thresholds.py
    sources/
      seismic.py
      thermal.py
      advisories.py
  tests/
  .github/workflows/monitor.yml
  .env.example
```

## Commands

- `python -m etna_monitor.run` performs a live run.
- `python -m etna_monitor.run --dry-run` fetches, evaluates, prints what it
  would send, and writes nothing and sends nothing.
- `python -m etna_monitor.run --backfill 30` populates history for the trailing
  30 days in one pass, so the baseline is not empty on day one.
- `python -m etna_monitor.run --test-notify` sends one message through every
  configured channel and exits.

## Acceptance criteria

The build is done when all of these are true, verified by running them.

1. A fresh clone with `pip install -r requirements.txt` and a MAP_KEY in the
   environment runs `--dry-run` successfully and prints a state summary.
2. `--backfill 30` populates seismic and thermal history and the printed
   baselines are non-zero.
3. `--test-notify` delivers a message to a phone.
4. Unit tests cover threshold logic against synthetic series, including: empty
   baseline, baseline shorter than the minimum, a baseline of all zeros, a
   single-day spike, and a source marked unavailable.
5. Killing the process mid-run leaves `data/state.json` valid and parseable.
6. Every source failure path is exercised by a test that simulates a non-200
   response and asserts the run completes and marks the source unavailable.
7. The workflow runs on `workflow_dispatch` and on a daily schedule, and
   commits state changes back with a message containing the run date.
8. The README states that this is not a forecast tool and names INGV as the
   authority.
9. Nothing in the repository contains a secret. `.env.example` lists required
   variables with placeholder values.

## Out of scope

Do not build: SO2 retrieval, tremor amplitude, INGV bulletin text parsing, any
model-based interpretation of the signals, a web interface, a map, historical
analysis beyond the trailing baseline, or any second volcano.

If a source turns out to be unavailable or undocumented, drop that source and
note it in the README. Do not substitute a different source without saying so.

## Known risks

Cloud cover suppresses thermal detection, so a quiet thermal signal is
ambiguous. Every thermal number reported must be accompanied by the count of
days with data available in the baseline window.

Initial thresholds are unvalidated and will misfire. This is expected. The
config file exists so tuning does not require a code change.

A scheduled job that breaks fails silently and looks identical to quiet. The
weekly heartbeat is the mitigation and is not optional.

INGV and VAAC endpoints may change format without notice. Parsing must fail
loudly to the log and mark the source unavailable rather than returning an
empty result that reads as quiet.
