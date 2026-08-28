"""VAAC Toulouse ash advisory client for Etna.

Verified against real requests on 2026-08-28. There is no machine-readable
feed; the site is scraped, per spec, since no stable listing/feed exists.

1. GET https://vaac.meteo.fr/volcanoes/etna/  (HTTP 200, text/html)

   Contains a plain <ul> of every advisory ever issued for the volcano,
   newest first, each entry shaped like:

       <li><a href="https://vaac.meteo.fr/advisory/2026/211060_20260818075433/211060_20260818075433/">
         ETNA.105 - 2026-08-18 07:54 utc
       </a></li>

   The "ETNA.105" sequence number matches the "ADVISORY NR" field inside
   that advisory's own text (confirmed: ETNA.105 <-> "ADVISORY NR: 2026/105",
   ETNA.94 <-> "2026/94", ETNA.93 <-> "2026/93"), so the YEAR/NNN key from
   the spec can be read directly off the listing page without fetching each
   advisory's text -- only genuinely new advisories need a follow-up fetch.
   An unknown volcano slug (or a dead link) returns HTTP 404.

2. Each entry's landing-page URL derives its raw text URL by stripping the
   trailing slash and appending "_vaa.txt":

       https://vaac.meteo.fr/advisory/2026/211060_20260818075433/211060_20260818075433_vaa.txt

   (HTTP 200, text/plain). Confirmed shape:

       VA ADVISORY
       DTG: 20260818/0754Z
       VAAC: TOULOUSE
       VOLCANO: ETNA 211060
       PSN: N3744 E01459
       AREA: SICILY VOLCANIC PROVINCE
       SOURCE ELEV: 3357M
       ADVISORY NR: 2026/105
       INFO SOURCE: VONA, INGV WEBCAMS, SAT IMAGERY
       AVIATION COLOUR CODE: ORANGE
       ERUPTION DETAILS: ERUPTION AT 20260816/1620Z EXPLOSIVE ACTIVITY IS DECREASING
       OBS VA DTG: 18/0730Z
       OBS VA CLD: VA NOT IDENTIFIABLE FM SATELLITE DATA  WIND FL100 290/20KT  FL180 325/20KT
       FCST VA CLD +6 HR: 18/1330Z NO VA EXP
       FCST VA CLD +12 HR: 18/1930Z NO VA EXP
       FCST VA CLD +18 HR: 19/0130Z NO VA EXP
       RMK:  WEAK VOLCANIC ASH STILL POSSIBLE IN THE VICINITY  OF THE CRATER.
       NXT ADVISORY: NO FURTHER ADVISORIES=

   A real ash cloud (confirmed on advisory 2026/94, issued during an active
   eruption) replaces "NO VA EXP" / "NOT PROVIDED" / "VA NOT IDENTIFIABLE
   FM SATELLITE DATA" with a flight-level polygon, e.g.:

       OBS VA CLD: SFC/FL160 N3745 E01500 - N3745 E01512 - N3738 E01509 - N3745 E01500 MOV SE 10KT

   Distinguishing the two requires checking for those three no-ash phrases
   rather than just searching for "FL", since the no-ash wind line above
   also contains "FL100"/"FL180" -- as wind levels, not ash.
"""

import re

import requests

DEFAULT_BASE_URL = "https://vaac.meteo.fr"
DEFAULT_TIMEOUT = 30

_LISTING_ENTRY_RE = re.compile(
    r'<li><a href="(?P<url>https://vaac\.meteo\.fr/advisory/\d+/[^"]+/)">\s*'
    r"ETNA\.(?P<seq>\d+)\s*-\s*(?P<year>\d{4})-\d{2}-\d{2}\s+\d{2}:\d{2}\s+utc",
    re.IGNORECASE,
)

_NO_ASH_MARKERS = ("NO VA EXP", "NOT PROVIDED", "VA NOT IDENTIFIABLE")


class AdvisorySourceError(Exception):
    """Raised when the VAAC advisory listing or an individual advisory's
    text cannot be fetched or parsed as expected."""


def fetch_advisory_listing(
    user_agent,
    base_url=DEFAULT_BASE_URL,
    volcano_slug="etna",
    timeout=DEFAULT_TIMEOUT,
    session=None,
):
    """Fetch the Etna advisory listing page. Returns a list of dicts,
    newest first: {"key": "2026/105", "text_url": "..."}.

    Raises AdvisorySourceError on any failure: network error, non-200
    response, or a page that does not contain the expected listing
    markup (site format changed).
    """
    url = f"{base_url}/volcanoes/{volcano_slug}/"
    http = session or requests

    try:
        response = http.get(url, headers={"User-Agent": user_agent}, timeout=timeout)
    except requests.RequestException as exc:
        raise AdvisorySourceError(f"request to VAAC listing failed: {exc}") from exc

    if response.status_code != 200:
        raise AdvisorySourceError(
            f"VAAC listing returned HTTP {response.status_code}: {response.text[:500]}"
        )

    matches = list(_LISTING_ENTRY_RE.finditer(response.text))
    if not matches:
        raise AdvisorySourceError(
            "VAAC listing page did not match the expected advisory entry markup"
        )

    return [
        {
            "key": f"{m.group('year')}/{m.group('seq')}",
            "text_url": m.group("url").rstrip("/") + "_vaa.txt",
        }
        for m in matches
    ]


def fetch_advisory_text(text_url, user_agent, timeout=DEFAULT_TIMEOUT, session=None):
    """Fetch the raw VAA text for one advisory. Raises AdvisorySourceError
    on failure."""
    http = session or requests
    try:
        response = http.get(text_url, headers={"User-Agent": user_agent}, timeout=timeout)
    except requests.RequestException as exc:
        raise AdvisorySourceError(f"request to VAAC advisory text failed: {exc}") from exc

    if response.status_code != 200:
        raise AdvisorySourceError(
            f"VAAC advisory text returned HTTP {response.status_code}: {response.text[:500]}"
        )
    return response.text


def parse_advisory_text(raw_text):
    """Parse a raw VAA text body into a dict with the fields Tier 1 needs:
    advisory_nr, published_utc, colour_code, eruption_details, obs_line,
    forecast_lines, has_ash_cloud_forecast, raw_text.

    Raises AdvisorySourceError if the expected fields are missing (format
    changed) -- callers must not fall back to a silently empty result.
    """
    fields = {}
    forecast_lines = []
    obs_line = None

    for line in raw_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("ADVISORY NR:"):
            fields["advisory_nr"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("DTG:"):
            fields["dtg"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("AVIATION COLOUR CODE:"):
            fields["colour_code"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("ERUPTION DETAILS:"):
            fields["eruption_details"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("OBS VA CLD:"):
            obs_line = stripped
        elif stripped.startswith("FCST VA CLD"):
            forecast_lines.append(stripped)

    if "advisory_nr" not in fields or "colour_code" not in fields or "dtg" not in fields:
        raise AdvisorySourceError(
            "VAAC advisory text is missing ADVISORY NR, DTG, or AVIATION COLOUR "
            "CODE -- format may have changed"
        )

    ash_lines = ([obs_line] if obs_line else []) + forecast_lines
    has_ash_cloud_forecast = any(_line_indicates_ash(line) for line in ash_lines)

    return {
        "advisory_nr": fields["advisory_nr"],
        "published_utc": _parse_dtg(fields["dtg"]),
        "colour_code": fields["colour_code"],
        "eruption_details": fields.get("eruption_details", ""),
        "obs_line": obs_line or "",
        "forecast_lines": forecast_lines,
        "has_ash_cloud_forecast": has_ash_cloud_forecast,
        "raw_text": raw_text,
    }


def _line_indicates_ash(line):
    upper = line.upper()
    if any(marker in upper for marker in _NO_ASH_MARKERS):
        return False
    return "FL" in upper or "SFC" in upper


def _parse_dtg(dtg):
    # "20260818/0754Z" -> "2026-08-18T07:54:00Z". Confirmed shape against
    # the real advisory sample above; DTG is always UTC ("Z").
    match = re.match(r"^(\d{4})(\d{2})(\d{2})/(\d{2})(\d{2})Z$", dtg)
    if not match:
        raise AdvisorySourceError(f"could not parse DTG {dtg!r} -- format may have changed")
    year, month, day, hour, minute = match.groups()
    return f"{year}-{month}-{day}T{hour}:{minute}:00Z"
