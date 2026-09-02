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

Updated after this was written: both triggers were exercised for real
against the actual GitHub remote (`tookerjo/etna-monitor`, private).

```
$ gh workflow run etna-monitor -f dry_run=true
$ gh run watch 33201503559
✓ main etna-monitor · 33201503559
  ✓ Run monitor
  - Commit state          # skipped correctly: dry_run=true

$ gh workflow run etna-monitor
$ gh run watch 33201714536
✓ main etna-monitor · 33201714536
  ✓ Run monitor
  ✓ Commit state
    [main e7e55a9] state: run 2026-08-28
     1 file changed, 116 insertions(+), 4 deletions(-)
    7275165..e7e55a9  main -> main
```

The live run's own log shows 20 real Tier 1 deliveries plus the weekly
heartbeat, each `{'ntfy': True, 'smtp': 'not configured'}`, and the
workflow's own commit-and-push happened autonomously using its
`etna-monitor` bot identity -- not something this build session did
directly. Secrets were correctly masked in the job log
(`FIRMS_MAP_KEY: ***`, `NTFY_TOPIC: ***`).

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

## Advisory formatter: output for every advisory currently in state

Added after the initial build: `advisory_format.py` reformats a raw VAAC
advisory into a short, phone-readable message (Sicily local time, ash
layers in feet, coordinate polygons dropped) and is called from
`notify.py`. Presentation only -- no firing condition, threshold, or
config value changed.

`data/state.json`'s `advisories_seen` only stores `key`/`published_utc`/
`colour_code`, not raw text, so the raw text for each of the 20 real
advisories currently in state was re-fetched live from VAAC (same source
already used at runtime) and run through the formatter:

```
$ python3 -c "
import json
from etna_monitor import advisory_format
from etna_monitor.sources import advisories

state = json.load(open('data/state.json'))
keys_in_state = [a['key'] for a in state['advisories_seen']]
listing = advisories.fetch_advisory_listing(user_agent='etna-monitor-acceptance/0.1')
by_key = {e['key']: e['text_url'] for e in listing}
for key in keys_in_state:
    raw = advisories.fetch_advisory_text(by_key[key], user_agent='etna-monitor-acceptance/0.1')
    print(f'=== {key} ===')
    print(advisory_format.format_advisory(raw))
    print()
"
=== 2026/86 ===
Colour code RED
Sat 15 Aug, 6:00 AM Sicily
Eruption: ERUPTION AT 20260808/0018Z ONGOING ERUPTION
Ash: surface to 16,000 ft, moving S at 20 kt
6hr forecast: ash expected, surface to 16,000 ft
Remarks: QVA NOT PROVIDED DUE TO LOW INTENSITY OF THE EVENT.
Next advisory: no later than Sat 15 Aug, 12:00 PM Sicily

=== 2026/87 ===
Colour code ORANGE
Sat 15 Aug, 9:25 AM Sicily
Eruption: ERUPTION AT 20260808/0018Z ERUPTION ENDED, ASH CLOUD ONGOING
Ash: surface to 16,000 ft, moving S at 15 kt
6hr forecast: ash expected, surface to 10,000 ft
Remarks: NON SIGNIFICATIV ERUPTION, QVA WILL NOT BE PROVIDED
Next advisory: no later than Sat 15 Aug, 3:00 PM Sicily

=== 2026/88 ===
Colour code ORANGE
Sat 15 Aug, 2:58 PM Sicily
Eruption: ERUPTION AT 20260807/0018Z ERUPTION STOPED, ASH CLOUD ONGOING
Ash: surface to 14,000 ft, moving N at 15 kt
6hr forecast: no ash expected
Remarks: ERUPTION NOT SIGNIFICANT, THEREFORE QVA ARE NOT PROVIDED.
Next advisory: no later than Sat 15 Aug, 9:00 PM Sicily

=== 2026/89 ===
Colour code ORANGE
Sat 15 Aug, 8:01 PM Sicily
Eruption: ERUPTION AT 20260805/0018Z ACTIVITY HAS DECREASED.
Ash: surface to 12,000 ft, moving S at 10 kt
6hr forecast: no ash expected
Remarks: THIN ASH CLOUD NEAR LYBIAN COAST, MOVING SOUTH AND DISSIPATING. QVA NOT PROVIDED DUE TO LOW INTENSITY OF THE EVENT.
Next advisory: no later than Sun 16 Aug, 2:00 AM Sicily

=== 2026/90 ===
Colour code ORANGE
Sat 15 Aug, 8:01 PM Sicily
Eruption: ERUPTION AT 20260805/0018Z ACTIVITY HAS DECREASED.
Ash: surface to 12,000 ft, moving S at 10 kt
6hr forecast: no ash expected
Remarks: THIN ASH CLOUD NEAR LYBIAN COAST, MOVING SOUTH AND DISSIPATING. QVA NOT PROVIDED DUE TO LOW INTENSITY OF THE EVENT.
Next advisory: no later than Sun 16 Aug, 2:00 AM Sicily

=== 2026/91 ===
Colour code ORANGE
Sat 15 Aug, 11:59 PM Sicily
Eruption: ERUPTION AT 20260808/0018Z NO MORE ASH EMISSION.
Ash: surface to 12,000 ft, moving S at 10 kt
6hr forecast: no ash expected
Remarks: THIN ASH CLOUD IN NORTH OF LYBIA, DISSIPATING. QVA NOT PROVIDED DUE TO LOW INTENSITY OF THE EVENT.
Next advisory: no later than Sun 16 Aug, 6:00 AM Sicily

=== 2026/92 ===
Colour code ORANGE
Sun 16 Aug, 6:00 AM Sicily
Eruption: ERUPTION AT 20260808/0018Z EXPLOSIVE ACTIVITY HAS CEASED
Ash: none observed
6hr forecast: no ash expected
Remarks: VA NOT DETECTABLE IN SPITE OF GOOD VISIBILITY
Next advisory: none expected

=== 2026/93 ===
Colour code ORANGE
Sun 16 Aug, 11:18 AM Sicily
Eruption: ERUPTION AT 20260808/0018Z WEAK ERUPTION
Ash: 10,000-20,000 ft
6hr forecast: no ash expected
Remarks: WEAK ERUPTION, POSSIBLE ASH IN THE VICINITY OF THE SUMMIT. WEAK PLUME MAINLY COMPOSED OF WATER AND SO2 DRIFTING SOUTHEAST.
Next advisory: none expected

=== 2026/94 ===
Colour code RED
Sun 16 Aug, 10:31 PM Sicily
Eruption: ERUPTION AT 20260816/2015Z ERUPTION STARTED AT 20H15
Ash: surface to 16,000 ft, moving SE at 10 kt
6hr forecast: no ash expected
Remarks: ASH CLOUD MOVES TOWARD SE
Next advisory: no later than Sun 16 Aug, 11:00 PM Sicily

=== 2026/95 ===
Colour code RED
Sun 16 Aug, 11:00 PM Sicily
Eruption: ERUPTION AT 20260816/2015Z ONGOING EURPTION
Ash: surface to 16,000 ft, moving SE at 10 kt
6hr forecast: ash expected, surface to 16,000 ft
Remarks: WEAK EMISSION, ASH CLOUD MOVING SOUTHEAST DIRECTION. QVA NOT PROVIDED DUE TO THE LOW INTENSITY OF THE EVENT
Next advisory: no later than Mon 17 Aug, 5:00 AM Sicily

=== 2026/96 ===
Colour code RED
Mon 17 Aug, 5:00 AM Sicily
Eruption: ERUPTION AT 20260816/2015Z ONGOING ERUPTION
Ash: surface to 16,000 ft, moving SE at 15 kt
6hr forecast: ash expected, surface to 16,000 ft
Remarks: WEAK EMISSION, ASH CLOUD MOVING SOUTHEAST DIRECTION. QVA NOT PROVIDED DUE TO THE LOW INTENSITY OF THE EVENT
Next advisory: no later than Mon 17 Aug, 11:00 AM Sicily

=== 2026/97 ===
Colour code RED
Mon 17 Aug, 5:05 AM Sicily
Eruption: ERUPTION AT 20260816/2015Z ONGOING ERUPTION
Ash: surface to 16,000 ft, moving SE at 15 kt
6hr forecast: ash expected, surface to 16,000 ft
Remarks: WEAK EMISSION, ASH CLOUD MOVING SOUTHEAST DIRECTION. QVA NOT PROVIDED DUE TO THE LOW INTENSITY OF THE EVENT
Next advisory: no later than Mon 17 Aug, 11:00 AM Sicily

=== 2026/98 ===
Colour code RED
Mon 17 Aug, 11:10 AM Sicily
Eruption: ERUPTION AT 20260816/1620Z STRONG ERUPTION ONGOING.
Ash: surface to 23,000 ft, moving SE at 20 kt
6hr forecast: ash expected, surface to 16,000 ft; 8,000-23,000 ft
Remarks: ASH CLOUD HEIGT ESTIMATED AROUND 7000 M AMSL. PLUME IS MOVING SE. HIGHEST CONCENTRATION WITHIN 100KM OF THE VOLCANO. QVA WILL BE PROVIDED SOON.
Next advisory: no later than Mon 17 Aug, 5:00 PM Sicily

=== 2026/99 ===
Colour code RED
Mon 17 Aug, 5:12 PM Sicily
Eruption: ERUPTION AT 20260816/1620Z STRONG ERUPTION ONGOING.
Ash: surface to 16,000 ft, moving SE at 20 kt; surface to 23,000 ft, moving SE at 30 kt
6hr forecast: ash expected, surface to 16,000 ft; 8,000-23,000 ft
Remarks: ASH CLOUD HEIGT ESTIMATED AROUND 7000 M AMSL. PLUME IS MOVING SE.
Next advisory: no later than Mon 17 Aug, 11:00 PM Sicily

=== 2026/100 ===
Colour code RED
Mon 17 Aug, 5:28 PM Sicily
Eruption: ERUPTION AT 20260816/1620Z STRONG ERUPTION ONGOING.
Ash: surface to 16,000 ft, moving SE at 20 kt; surface to 23,000 ft, moving SE at 30 kt
6hr forecast: ash expected, surface to 16,000 ft; 8,000-23,000 ft
Remarks: ASH CLOUD HEIGT ESTIMATED AROUND 7000 M AMSL. PLUME IS MOVING SE.
Next advisory: no later than Mon 17 Aug, 11:00 PM Sicily

=== 2026/101 ===
Colour code RED
Mon 17 Aug, 6:35 PM Sicily
Eruption: ERUPTION AT 20260816/1620Z STRONG ERUPTION ONGOING.
Ash: surface to 16,000 ft, moving SE at 20 kt; surface to 23,000 ft, moving SE at 30 kt
6hr forecast: ash expected, surface to 16,000 ft; 8,000-23,000 ft
Remarks: ASH CLOUD HEIGT ESTIMATED AROUND 7000 M AMSL. PLUME IS MOVING SE. DUE TO THE LOW RELIABITY OF THE MODEL, QVA AND CONCENTRATION CHARTS WILL NOT BE PROVIDED.
Next advisory: no later than Mon 17 Aug, 11:00 PM Sicily

=== 2026/102 ===
Colour code RED
Mon 17 Aug, 11:06 PM Sicily
Eruption: ERUPTION AT 20260816/1620Z ONGOING ERUPTION
Ash: surface to 16,000 ft, moving SE at 20 kt; surface to 24,000 ft, moving SE at 30 kt
6hr forecast: ash expected, surface to 16,000 ft; surface to 24,000 ft
Remarks: ASH CLOUD HEIGT ESTIMATED AROUND 7000 M AMSL. PLUME IS MOVING SOUTHEAST.
Next advisory: no later than Tue 18 Aug, 5:00 AM Sicily

=== 2026/103 ===
Colour code RED
Tue 18 Aug, 5:00 AM Sicily
Eruption: ERUPTION AT 20260816/1620Z ONGOING ERUPTION DECREASING
Ash: surface to 15,000 ft, moving SE at 25 kt; 5,000-20,000 ft, moving SE at 20 kt
6hr forecast: ash expected, surface to 15,000 ft; 5,000-20,000 ft
Remarks: ASH EMISSION DECREASING. ASH CLOUD MAINLY COMPOSED OF WATER AND SO2 AND EASTERN CLOUD DISSIPATING. QVA NOT PROVIDED DUE TO THE LOW INTENSITY OF THE EVENT.
Next advisory: no later than Tue 18 Aug, 11:00 AM Sicily

=== 2026/104 ===
Colour code RED
Tue 18 Aug, 5:00 AM Sicily
Eruption: ERUPTION AT 20260816/1620Z ONGOING ERUPTION DECREASING
Ash: surface to 15,000 ft, moving SE at 25 kt; 5,000-20,000 ft, moving SE at 20 kt
6hr forecast: ash expected, surface to 15,000 ft; 5,000-20,000 ft
Remarks: ASH EMISSION DECREASING. ASH CLOUD MAINLY COMPOSED OF WATER AND SO2 AND EASTERN CLOUD DISSIPATING. QVA NOT PROVIDED DUE TO THE LOW INTENSITY OF THE EVENT.
Next advisory: no later than Tue 18 Aug, 11:00 AM Sicily

=== 2026/105 ===
Colour code ORANGE
Tue 18 Aug, 9:54 AM Sicily
Eruption: ERUPTION AT 20260816/1620Z EXPLOSIVE ACTIVITY IS DECREASING
Ash: none observed
6hr forecast: no ash expected
Remarks: WEAK VOLCANIC ASH STILL POSSIBLE IN THE VICINITY OF THE CRATER.
Next advisory: none expected
```

All 20 advisories currently in state are formatted above -- none omitted.
Every advisory number and colour code line is present, "Ash: none
observed" appears exactly where the real "VA NOT IDENTIFIABLE" / "NO VA
EXP" boilerplate does (2026/92, 2026/105), and no line contains a
coordinate token like "N3744" or "E01459" (confirmed:
`grep -E "N[0-9]{4}|E[0-9]{5}"` over this output matches nothing).

Edge cases (`tests/test_advisory_format.py`, using the real 2026/86 and
2026/105 text above as fixtures, since state.json doesn't persist raw
text to pull from directly):

```
$ pytest tests/test_advisory_format.py -v
test_ash_present_advisory PASSED
test_no_ash_advisory_says_so_plainly PASSED
test_empty_string_falls_back_without_crashing PASSED
test_none_input_falls_back_without_crashing PASSED
test_truncated_advisory_omits_missing_fields_without_crashing PASSED
test_completely_unrecognizable_text_falls_back PASSED
test_garbage_dtg_is_omitted_not_crashed_on PASSED
test_mixed_ash_and_no_ash_layers_in_one_line PASSED
========================== 8 passed in 0.02s ==========================
```

## Full test suite

```
$ pytest tests/
102 passed in 0.21s
```

## Change: three runs a day, Tier 1 batched into one message per run

Verified 2026-09-02, using the four real advisories from that morning's
run (2026/107 through 2026/110, fetched live from vaac.meteo.fr) as the
fixture, per the task's instruction. State at the time had 2026/106
(colour ORANGE) as the only prior advisory, recorded before eruption_id
and ash_ceiling_ft existed in the schema.

```
$ python -c "..." # batching logic run directly over the 107-110 set
direction = same_or_less
---
Still active, no change. 4 new advisories since last run.

TIER 1 -- Etna advisory 2026/110: new advisory published; ash cloud reported at a flight level

Colour code ORANGE
Wed 2 Sep, 11:00 AM Sicily
Eruption: ERUPTION AT 20260901/2100Z WEAK ASH EMISSION
Ash: surface to 12,000 ft, moving SE at 25 kt
6hr forecast: no ash expected
Remarks: THIN PLUME DETECTABLE ON WEBCAM. WEAK ASH EMISSION IN THE VICINITY OF THE VOLCANO. DUE TO THE LOW INTENSITY OF THIS ERUPTIVE EVENT, QVA DO NOT SHOW ANY SIGNIFICANT ASH CLOUD AND WILL NOT BE PROVIDED.
Next advisory: will be issued by Wed 2 Sep, 5:00 PM Sicily

Other advisories this run: 2026/107, 2026/108, 2026/109
```

One message for four new advisories, as required. Direction is SAME OR
LESS even though 2026/109 carries a new eruption identifier
(`20260901/2100Z` vs `20260831/2100Z` on 107/108) -- state's one prior
advisory (2026/106) predates eruption_id/ash_ceiling_ft tracking, so
there is nothing in state for that change to be new *against*. This is
the behaviour the task asked to verify, not a bug: the escalation check
compares the newest advisory to what state actually recorded, not to
earlier advisories within the same run.

```
$ pytest tests/ -v -k "classify_direction or format_tier1_batch or record_advisory_seen or parse_extracts_eruption_id or parse_ash_ceiling"
tests/test_advisories.py::test_parse_extracts_eruption_id_from_eruption_at_timestamp PASSED
tests/test_advisories.py::test_parse_ash_ceiling_ft_from_real_ash_layer PASSED
tests/test_advisories.py::test_parse_ash_ceiling_ft_none_when_no_real_ash_observed PASSED
tests/test_advisories.py::test_parse_ash_ceiling_ft_ignores_wind_flight_levels_in_no_ash_line PASSED
tests/test_run.py::test_classify_direction_escalates_on_colour_code_increase PASSED
tests/test_run.py::test_classify_direction_same_or_less_on_colour_code_decrease PASSED
tests/test_run.py::test_classify_direction_escalates_on_new_eruption_id PASSED
tests/test_run.py::test_classify_direction_escalates_on_ash_ceiling_increase PASSED
tests/test_run.py::test_classify_direction_no_ceiling_change_is_same_or_less PASSED
tests/test_run.py::test_classify_direction_no_prior_advisory_is_same_or_less PASSED
tests/test_run.py::test_classify_direction_missing_colour_code_on_either_side_never_crashes_or_escalates PASSED
tests/test_run.py::test_classify_direction_unparseable_colour_code_never_escalates PASSED
tests/test_run.py::test_classify_direction_on_the_real_107_110_batch_is_same_or_less PASSED
tests/test_run.py::test_format_tier1_batch_message_single_advisory_matches_todays_rendering PASSED
tests/test_run.py::test_format_tier1_batch_message_byte_identical_advisories_still_one_message PASSED
tests/test_run.py::test_format_tier1_batch_message_escalation_header PASSED
tests/test_run.py::test_format_tier1_batch_message_no_baseline_says_new_not_no_change PASSED
tests/test_state.py::test_record_advisory_seen_new_returns_true PASSED
tests/test_state.py::test_record_advisory_seen_existing_returns_false_and_updates PASSED
tests/test_state.py::test_record_advisory_seen_stores_eruption_id_and_ash_ceiling PASSED
====================== 20 passed, 105 deselected in 0.15s ======================
```

```
$ pytest tests/
125 passed in 0.23s
```
