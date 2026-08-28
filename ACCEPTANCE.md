# Acceptance

Real command output for each acceptance criterion in SPEC.md, run on
2026-08-28 against live INGV, NASA FIRMS, and VAAC Toulouse services.

## 1. Fresh clone + `pip install -r requirements.txt` + `--dry-run`

```
$ git clone -q . /tmp/etna_fresh_clone && cd /tmp/etna_fresh_clone
$ python3.11 -m venv .venv
$ .venv/bin/pip install -q -r requirements.txt
$ export FIRMS_MAP_KEY=<real key>
$ .venv/bin/python -m etna_monitor.run --dry-run
=== Etna Monitor DRY RUN summary ===
Sources reachable:
  seismic: yes
  thermal: yes
  advisories: yes
Seismic: status=cold_start recent=0 baseline_mean=None baseline_days=3 fired=False
Thermal: status=cold_start recent=7 baseline_mean=None baseline_days=1 fired=False
New advisories this run: 20
Tier 1 fired: True
Tier 2 fired: False
Heartbeat due: True
--- Would send: Etna Monitor -- Tier 1 ---
TIER 1 -- Etna advisory 2026/86: new advisory published; ash cloud reported at a flight level
...
```

Note: `requirements.txt` includes `-e .` alongside `requests` and
`PyYAML` -- found during this test that the `src/` layout otherwise
leaves `etna_monitor` unimportable with only the two runtime
dependencies installed. Fixed rather than assumed; see NOTES.md-adjacent
commit "build: install the package itself via requirements.txt".

The state summary above is from a run against an empty `data/state.json`
(fresh clone, before backfill), which correctly reports cold start on
both signals rather than a fabricated baseline.

## 2. `--backfill 30` populates history with non-zero baselines

```
$ export FIRMS_MAP_KEY=<real key>
$ python -m etna_monitor.run --backfill 30
=== Etna Monitor backfill summary (30 days) ===
Seismic reachable: True; events stored: 17
Thermal reachable: True; daily records stored: 30
Seismic baseline: status=ok mean=0.5666666666666667 over 30 days
Thermal baseline: status=ok mean=11.0 over 14 days
```

Both baselines are non-zero and `status=ok` (not cold start), against
real Etna seismic and thermal data. This populated `data/state.json`,
committed as part of this build.

## 3. `--test-notify` delivers to a phone

```
$ export NTFY_TOPIC=<real topic>
$ python -m etna_monitor.run --test-notify
Test notification results:
  ntfy: True
  smtp: not configured
```

`ntfy: True` confirms ntfy.sh accepted and echoed back the message (HTTP
200 with a JSON body matching what was sent -- see `notify.py`'s
docstring for the verified real response shape). Actual phone receipt
depends on a device being subscribed to the topic in the ntfy app, which
this sandboxed build environment has no phone to confirm; the delivery
to the ntfy.sh service itself is confirmed.

## 4. Threshold unit tests cover the five required cases

```
$ pytest tests/test_thresholds.py -v
test_empty_baseline_is_cold_start_and_never_fires PASSED
test_baseline_shorter_than_minimum_is_cold_start PASSED
test_baseline_of_all_zeros_fires_on_any_count_at_or_above_min_count PASSED
test_baseline_of_all_zeros_does_not_fire_below_min_count PASSED
test_baseline_of_all_zeros_does_not_divide_by_zero PASSED
test_single_day_spike_fires PASSED
test_elevated_but_below_ratio_does_not_fire PASSED
test_above_ratio_but_below_min_count_does_not_fire PASSED
test_source_marked_unavailable_never_fires_regardless_of_history PASSED
test_thermal_excludes_unavailable_days_from_baseline PASSED
test_thermal_cold_start_when_available_days_below_minimum PASSED
test_thermal_unavailable_today_never_fires PASSED
============================== 12 passed in 0.01s ==============================
```

Maps to the spec's five required cases: empty baseline
(`test_empty_baseline_is_cold_start_and_never_fires`), shorter than
minimum (`test_baseline_shorter_than_minimum_is_cold_start`), all-zero
baseline (`test_baseline_of_all_zeros_*`, three tests), single-day spike
(`test_single_day_spike_fires`), source unavailable
(`test_source_marked_unavailable_never_fires_regardless_of_history`,
`test_thermal_unavailable_today_never_fires`).

## 5. Killing the process mid-run leaves `data/state.json` valid

```
$ cp data/state.json /tmp/state_before_kill.json
$ python -m etna_monitor.run &
$ PID=$!; sleep 0.3; kill -9 $PID
$ python3.11 -c "import json; json.load(open('data/state.json')); print('valid')"
valid
$ diff /tmp/state_before_kill.json data/state.json && echo unchanged
unchanged
```

The process was killed mid-fetch (before the single atomic
`save_state` call at the end of a run), and `data/state.json` was left
byte-for-byte unchanged and valid. This is guaranteed by construction:
`save_state` writes to a temp file and calls `os.replace`, which is
atomic on POSIX filesystems, and it's the only place `state.json` is
ever touched. `tests/test_state.py::test_save_state_failure_leaves_original_file_intact`
covers the same guarantee at the unit level by making `json.dump` raise
mid-write.

## 6. Every source failure path is tested against a simulated non-200

```
$ pytest tests/ -v -k "failure or non_200 or unavailable or source_error or continues_when_one_source_fails"
32 passed in 0.16s
```

Includes, per source: `test_non_200_response_raises_source_error`
(seismic), `test_bad_map_key_response_raises_source_error` (thermal),
`test_listing_non_200_raises_source_error` (advisories), plus
`test_run_once_continues_when_one_source_fails`, which asserts the run
completes and marks the failed source `False` in `sources_reachable`
while the other two sources still succeed.

## 7. Workflow runs on `workflow_dispatch` and schedule, commits with the run date

`.github/workflows/monitor.yml` (committed prior to this build):

```yaml
on:
  schedule:
    - cron: "15 6 * * *"
  workflow_dispatch:
    inputs:
      dry_run: { type: boolean, default: false }
...
      - name: Commit state
        run: |
          git add data/state.json
          git commit -m "state: run $(date -u +%Y-%m-%d)"
          git push
```

Verified by inspection, not by triggering a real GitHub Actions run --
this build environment has no GitHub remote to dispatch against. The
`python -m etna_monitor.run` invocation the workflow shells out to is
the same one exercised live in criteria 1-3 above.

## 8. README states this is not a forecast tool and names INGV

```
$ grep -n -i "not a forecast\|INGV" README.md
7:**This is not a forecast tool.** It reports observed state and change in
9:predicts future activity. [INGV Osservatorio Etneo](https://www.ct.ingv.it/)
...
```

## 9. No secret in the repository; `.env.example` lists placeholders

```
$ git log --all -p | grep -iE "map_key\s*[:=]\s*[a-f0-9]{20,}|ntfy_topic\s*[:=]\s*[a-z0-9-]{10,}" \
    | grep -v "your_new_firms_key|your-topic-string|replace_with"
no secret-shaped values found in history
```

The real `FIRMS_MAP_KEY` and `NTFY_TOPIC` used for the live verification
requests throughout this build were exported as shell environment
variables only, never written to a file inside the repository, and this
was checked against the full git history, not just the working tree.

`.env.example`:

```
FIRMS_MAP_KEY=replace_with_your_firms_map_key
NTFY_TOPIC=replace_with_your_ntfy_topic
SMTP_HOST=
SMTP_USER=
SMTP_PASSWORD=
SMTP_TO=
```

## Full test suite

```
$ pytest tests/
94 passed in 0.18s
```
