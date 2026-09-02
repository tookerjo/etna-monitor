# Build notes: discrepancies and decisions

Recorded per CLAUDE.md's instruction to write down anything a service does
that the spec doesn't describe, rather than working around it silently.

## NASA FIRMS: DAY_RANGE is capped at 5, not open-ended

The spec's URL shape (`/api/area/csv/[MAP_KEY]/[SOURCE]/[AREA]/[DAY_RANGE]`)
doesn't say DAY_RANGE has a maximum. A real request with `day_range=10`
returns HTTP 400: `Invalid day range. Expects [1..5].` Confirmed against
the live docs page and by testing the boundary directly.

Consequence: `--backfill 30` cannot fetch 30 days of thermal history in one
call. `run_backfill` in `run.py` pages backward in <=5-day windows.

## NASA FIRMS: the optional DATE segment is the start of the window, not the end

Untested, this would have been a plausible but wrong assumption. Requesting
`.../5/2026-08-10` returns detections with `acq_date` spanning
2026-08-10 through 2026-08-14 inclusive — the window is
`[DATE, DATE + DAY_RANGE - 1]`, not the DAY_RANGE days ending at DATE.
Confirmed by inspecting the actual `acq_date` values in a real response.
`run_backfill`'s paging logic depends on this being right; getting it
backwards would have silently produced gaps or overlaps in backfilled
history.

## NASA FIRMS: valid VIIRS source identifiers

Taken from the live docs page (`https://firms.modaps.eosdis.nasa.gov/api/area/`)
rather than assumed: `VIIRS_NOAA20_NRT`, `VIIRS_NOAA20_SP`,
`VIIRS_NOAA21_NRT`, `VIIRS_SNPP_NRT`, `VIIRS_SNPP_SP`. `VIIRS_SNPP_NRT` is
used (the docs page's own default, longest continuous record).

## INGV FDSN: no JSON output option

The spec says "request a machine-readable output format" without
specifying which. The live `application.wadl` lists only two: `xml`
(QuakeML) and `text` (pipe-delimited plain text). There is no JSON option
on this deployment. `text` is used as the machine-readable format.

## INGV FDSN: no-results is HTTP 204, not an empty HTTP 200 body

A query with zero matching events returns HTTP 204 with an empty body, not
HTTP 200 with just a header line (which is how NASA FIRMS represents a real
zero). `seismic.py` treats 204 as a real empty result and anything other
than 200/204 as a source failure.

## VAAC Toulouse: no machine-readable feed exists

Confirmed by inspecting the site: there is no RSS/Atom/JSON feed for
advisories. The spec anticipated this ("If no stable machine-readable
listing exists, parse the advisory index page"). The per-volcano page
(`https://vaac.meteo.fr/volcanoes/etna/`) is scraped instead of the global
index, since it's already filtered to Etna and stable.

## VAAC Toulouse: the listing's sequence number matches the advisory's own key

Not guaranteed by anything documented, but confirmed against three real
advisories: the listing page's "ETNA.105" label matches "ADVISORY NR:
2026/105" inside that advisory's own text (also true for ETNA.94 <-> 2026/94
and ETNA.93 <-> 2026/93). This means which advisories are new (not yet in
state) can be determined from the listing page alone, without fetching
every advisory's text — only genuinely new advisories need a follow-up
request. If this correspondence ever breaks, new-advisory detection would
need to fall back to fetching every advisory's text every run.

## VAAC Toulouse: distinguishing a real ash cloud from a "no ash" wind line

A "no ash" observation line still contains a flight-level token, e.g.:

    OBS VA CLD: VA NOT IDENTIFIABLE FM SATELLITE DATA WIND FL100 290/20KT

Searching for "FL" alone would misclassify this as an ash-cloud-at-flight-
level forecast. A real ash cloud replaces the line with a flight-level
polygon instead, e.g.:

    OBS VA CLD: SFC/FL160 N3745 E01500 - N3745 E01512 - ... MOV SE 10KT

`advisories.py` checks for the specific no-ash phrases (`NO VA EXP`,
`NOT PROVIDED`, `VA NOT IDENTIFIABLE`) before treating a line as ash
evidence, confirmed against real advisories from both a quiet period and
an active eruption. Covered by a regression test.

## Design decision beyond the spec's literal state schema: `seismic_coverage_start_date`

The spec lists six required top-level keys for `data/state.json`. A
seventh, `seismic_coverage_start_date`, was added during the `run.py`
build. Reason: `seismic_events` is a flat list with no per-day ledger, so
a calendar day with zero events is indistinguishable from a day INGV was
never queried for. Without this field, cold-start detection (spec: "fewer
than 7 days of history exist... must be handled explicitly") was silently
defeated — a brand-new deployment with a single real event two days ago
computed a fake, zero-padded 30-day baseline and evaluated as fully warmed
up. Thermal doesn't need an equivalent field because `thermal_daily`
already carries `detections_available` per day. This is additive and
non-breaking (nothing reads the schema expecting exactly six keys); found
and fixed with a regression test in `tests/test_run.py` before this build
reached its own acceptance testing.

## Not a discrepancy, but worth stating: "one request per source per run"

CLAUDE.md's verify-before-write section names INGV and NASA specifically
for "reasonable request volume." Advisories genuinely need more than one
request when there's new content: one to fetch the listing, then one more
per newly-published advisory to get its full text (typically 0-1 per day;
VAAC doesn't publish machine-readable summaries any denser than that). The
listing-then-selective-fetch design minimizes this to the smallest number
of requests that can still deliver Tier 1's verbatim advisory text
requirement.


## Deliberate deviation from spec: Tier 1's body is no longer verbatim

SPEC.md says Tier 1's message includes "the observed and forecast ash
cloud lines verbatim from the advisory text." As of the advisory
formatter (`advisory_format.py`), this is no longer literally true: the
body is reformatted for phone readability (Sicily local time instead of
UTC, feet instead of flight levels, coordinate polygons dropped
entirely) rather than pasted in unchanged. This was an explicit, scoped
request ("presentation only... do not change any firing condition,
threshold, or config value") -- the firing logic and message *content*
(which advisory, which colour code, whether ash is present) are
unchanged; only how that content is typeset changed. If formatting
fails for any reason, the raw text is still sent verbatim as a
fallback, so the original spec behavior is the safety net, not the
default.

## Finding: the seismic ratio rule never binds

INGV's public FDSN catalog for the Etna region has a completeness floor at
magnitude 1.0. Querying 1 Jun to 29 Aug 2026, 15 km radius around
37.733 N 14.983 E, returned 74 events at `minmagnitude=1.0` and the
identical 74 at `minmagnitude=0.5`, with the smallest magnitude in the set
being 1.0. `minmagnitude=2.0` returned 9, confirming the parameter is
applied correctly rather than ignored -- the catalog itself simply has
nothing below M1.0 for this region.

Mean is 0.82 events per day. At that density the minimum-count floor of 5
is already six to eight times the mean, so the 2.5x ratio can never be the
binding condition at any baseline window length. The rule is effectively
"five or more events in 24 hours."

Daily distribution over those 90 days: one day at 14 events (13 Jun), one
at 6 (20 Aug), one at 5 (15 Aug), two at 4, one at 3, and the rest at 1 or
2. The floor of 5 would have fired three times in 90 days.

Config is intentionally left unchanged. The ratio costs nothing to keep,
and lowering the floor below 5 would fire on ordinary weeks. Verified
1 Sep 2026.

Increasing seismic sensitivity would require a different INGV data
product, not a different query against this endpoint.

## Risk surfaced by moving to three runs a day: Tier 2 can now repeat same-day

The schedule changed from one run a day to three (05:15/11:15/17:15 UTC).
Tier 2's "at most once per day" was always enforced only by run cadence, not
a same-day dedup flag in state (`run.py`'s own docstring called this out as
a known simplification, previously only reachable via a manual
`workflow_dispatch` re-run). At three runs a day, a seismic or thermal
signal that stays above threshold across consecutive runs will now emit
Tier 2 at each of those runs in the ordinary course of the schedule, not
just on a rare manual re-run.

Not fixed here -- out of scope for this change, which only touched the
cron schedule and Tier 1 batching. Recorded so it isn't mistaken for new
code doing something unintended.

## Deliberate deviation from spec: Tier 1 no longer emits one message per advisory

SPEC.md says "Tier 1 emits on every occurrence, no rate limit." As of this
change, a run that finds several new advisories still evaluates every one
of them against the same firing conditions, but sends exactly one message
for the run instead of one per advisory -- an explicit, scoped request
("today a run that finds four new advisories sends four notifications. It
should send one"). The firing condition itself is unchanged: any new
advisory still counts, and every one of them is still recorded in state
and named in the message (the newest in full, the rest by number). Only
delivery volume changed, for the same reason the three-times-daily
schedule exists: this repeats the earlier body-formatting deviation's
shape (see "Deliberate deviation... Tier 1's body is no longer verbatim"
above) -- content and firing logic untouched, only how it's delivered.

The escalation/no-change framing added to the batched message
("Escalation. N new advisories..." / "Still active, no change. N new
advisories...") compares only the newest new advisory in the run against
the most recent advisory *already in state before the run* -- not against
other advisories within the same batch. Two consequences worth remembering
when reading a real batched message:

- `advisories_seen` entries written before this change only ever recorded
  a colour code, never an eruption id or ash ceiling. A batch's direction
  can come out SAME OR LESS even when an eruption id changes partway
  through the batch (see the real 2026/107-110 fixture in
  `tests/test_run.py`, where 109 introduces a new eruption id but state's
  prior entry, 2026/106, has nothing to compare it against) -- there is
  nothing in state for the change to be new *relative to*, only within the
  batch itself, which this comparison intentionally does not scan.
- No real advisory in state currently exercises the ash-ceiling-increase
  escalation branch; it's covered by a synthetic fixture instead
  (`test_classify_direction_escalates_on_ash_ceiling_increase`).
