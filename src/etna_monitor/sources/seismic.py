"""INGV FDSN event web service client.

Verified against a real request on 2026-08-28:

    GET http://webservices.ingv.it/fdsnws/event/1/query
        ?starttime=2026-08-01T00:00:00&endtime=2026-08-28T00:00:00
        &latitude=37.733&longitude=14.983&maxradiuskm=15
        &minmagnitude=1.0&format=text&orderby=time

Response (HTTP 200, Content-Type text/plain), pipe-delimited, one header
line starting with "#":

    #EventID|Time|Latitude|Longitude|Depth/Km|Author|Catalog|Contributor|\
ContributorID|MagType|Magnitude|MagAuthor|EventLocationName|EventType
    46943752|2026-08-20T06:54:56.830000|37.799|15.05|0.8|SURVEY-INGV-CT#KATALOC\
||||ML|1.8|--|10 km SW Linguaglossa (CT)|earthquake

Time has no UTC suffix but is UTC per the FDSN spec. There is no JSON output
option on this deployment's application.wadl -- only "xml" and "text" -- so
"text" is the machine-readable format used here, not JSON as might be
assumed.

No results: HTTP 204 with an empty body (not HTTP 200 with an empty list).
Malformed request: HTTP 400 with a plain-text error body, e.g.:

    Error 400
    Bad Request:
     "starttime" must be YYYY-MM-DDThh:mm:ss (your value=not-a-dateT00:00:00)

maxradiuskm is an INGV extension to the FDSN spec (alongside the standard
minradius/maxradius, which are in degrees). Using it directly avoids a
degrees<->km conversion.
"""

from datetime import timedelta

import requests

DEFAULT_BASE_URL = "http://webservices.ingv.it/fdsnws/event/1/query"
DEFAULT_TIMEOUT = 30


class SeismicSourceError(Exception):
    """Raised when the INGV event service cannot be queried or returns a
    response that cannot be parsed. Callers must treat this as a failed
    source (unavailable), never as zero events."""


def fetch_seismic_events(
    now,
    lookback_days,
    radius_km,
    min_magnitude,
    latitude,
    longitude,
    user_agent,
    base_url=DEFAULT_BASE_URL,
    timeout=DEFAULT_TIMEOUT,
    session=None,
):
    """Fetch events in [now - lookback_days, now] within radius_km of
    (latitude, longitude) at or above min_magnitude.

    Returns a list of event dicts (possibly empty -- a real zero) with keys
    matching state.py's seismic event shape: event_id, origin_time,
    latitude, longitude, depth, magnitude.

    Raises SeismicSourceError on any failure: network error, non-200/204
    response, or a response that cannot be parsed in the expected shape.
    """
    start = now - timedelta(days=lookback_days)
    params = {
        "starttime": start.strftime("%Y-%m-%dT%H:%M:%S"),
        "endtime": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "latitude": latitude,
        "longitude": longitude,
        "maxradiuskm": radius_km,
        "minmagnitude": min_magnitude,
        "format": "text",
        "orderby": "time",
    }
    http = session or requests

    try:
        response = http.get(
            base_url,
            params=params,
            headers={"User-Agent": user_agent},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise SeismicSourceError(f"request to INGV failed: {exc}") from exc

    if response.status_code == 204:
        return []
    if response.status_code != 200:
        raise SeismicSourceError(
            f"INGV returned HTTP {response.status_code}: {response.text[:500]}"
        )

    try:
        return _parse_text(response.text)
    except (ValueError, IndexError) as exc:
        raise SeismicSourceError(f"could not parse INGV response: {exc}") from exc


def _parse_text(body):
    events = []
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split("|")
        events.append(
            {
                "event_id": fields[0],
                "origin_time": _to_iso_z(fields[1]),
                "latitude": float(fields[2]),
                "longitude": float(fields[3]),
                "depth": float(fields[4]),
                "magnitude": float(fields[10]) if fields[10] else None,
            }
        )
    return events


def _to_iso_z(ingv_timestamp):
    # INGV times look like "2026-08-20T06:54:56.830000" with no offset,
    # UTC per the FDSN spec. Normalise to an explicit "Z" suffix so it
    # round-trips through state.py's ISO parsing unambiguously.
    return ingv_timestamp + "Z"
