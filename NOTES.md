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
