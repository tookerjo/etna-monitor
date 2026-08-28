"""NASA FIRMS area API client for VIIRS thermal (fire/hotspot) detections.

Verified against real requests on 2026-08-28, using a MAP_KEY registered at
https://firms.modaps.eosdis.nasa.gov/api/map_key/:

    GET https://firms.modaps.eosdis.nasa.gov/api/area/csv/[MAP_KEY]/VIIRS_SNPP_NRT/
        14.9262,37.6881,15.0398,37.7779/1

Response (HTTP 200, Content-Type text/plain), CSV with header row:

    latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,
    instrument,confidence,version,bright_ti5,frp,daynight
    37.74821,15.03866,312.87,0.42,0.38,2026-08-28,113,N,VIIRS,n,2.0NRT,299.99,1.43,N

A real zero (no detections in the box) is still HTTP 200 with only the
header row present -- confirmed against an ocean bounding box with no land.

Valid SOURCE identifiers, confirmed from the live docs page at
https://firms.modaps.eosdis.nasa.gov/api/area/ (do not assume these; NASA
adds new satellites over time): VIIRS_NOAA20_NRT, VIIRS_NOAA20_SP,
VIIRS_NOAA21_NRT, VIIRS_SNPP_NRT, VIIRS_SNPP_SP. VIIRS_SNPP_NRT is used here
-- it's the docs page's own default and has the longest continuous record.

Two discrepancies from what the spec assumes, found only by making real
requests rather than coding against the documented URL shape:

  - DAY_RANGE is capped at 5 (confirmed: requesting 10 returns HTTP 400
    "Invalid day range. Expects [1..5]."), not an open-ended lookback
    window. A 30-day backfill needs multiple 5-day-window requests, not
    one call with day_range=30.
  - The optional trailing DATE segment is the START of the window, not the
    end. Confirmed by requesting day_range=5 with date=2026-08-10 and
    observing rows spanning acq_date 2026-08-10 through 2026-08-14
    inclusive (start + day_range - 1), not the 5 days ending 2026-08-10.

Errors (bad MAP_KEY, bad source, bad day_range) are all HTTP 400 with a
short plain-text body, e.g. "Invalid MAP_KEY." or "Invalid source." --
confirmed against real bad-key and bad-source requests.
"""

import csv
import io
import math

import requests

DEFAULT_BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
DEFAULT_TIMEOUT = 30
MAX_DAY_RANGE = 5
DEFAULT_SOURCE = "VIIRS_SNPP_NRT"
VALID_SOURCES = {
    "VIIRS_NOAA20_NRT",
    "VIIRS_NOAA20_SP",
    "VIIRS_NOAA21_NRT",
    "VIIRS_SNPP_NRT",
    "VIIRS_SNPP_SP",
}

_EXPECTED_COLUMNS = {"latitude", "longitude", "acq_date", "acq_time", "frp", "confidence", "daynight"}

# Approximate degrees-per-km, used only to build a bounding box roughly
# box_km on a side. Fine for a ~10km box; not meant for precise geodesy.
_KM_PER_DEGREE_LAT = 111.32


class ThermalSourceError(Exception):
    """Raised when the FIRMS area API cannot be queried or returns a
    response that cannot be parsed. Callers must treat this as a failed
    source (unavailable), never as zero detections."""


def bounding_box(latitude, longitude, box_km):
    """Return (west, south, east, north) for a box_km-per-side box centred
    on (latitude, longitude)."""
    half_km = box_km / 2
    lat_offset = half_km / _KM_PER_DEGREE_LAT
    lon_offset = half_km / (_KM_PER_DEGREE_LAT * math.cos(math.radians(latitude)))
    return (
        longitude - lon_offset,
        latitude - lat_offset,
        longitude + lon_offset,
        latitude + lat_offset,
    )


def fetch_detections(
    map_key,
    west,
    south,
    east,
    north,
    day_range,
    user_agent,
    source=DEFAULT_SOURCE,
    start_date=None,
    base_url=DEFAULT_BASE_URL,
    timeout=DEFAULT_TIMEOUT,
    session=None,
):
    """Fetch VIIRS detections in the given bounding box.

    day_range must be between 1 and MAX_DAY_RANGE inclusive (an API limit,
    not a spec choice). If start_date ("YYYY-MM-DD") is given, the window
    is [start_date, start_date + day_range - 1]; omitted, the API returns
    the most recent day_range days.

    Returns a list of detection dicts (possibly empty -- a real zero) with
    keys: latitude, longitude, acq_date, acq_time, frp, confidence,
    daynight. Raises ThermalSourceError on any failure.
    """
    if not (1 <= day_range <= MAX_DAY_RANGE):
        raise ValueError(f"day_range must be between 1 and {MAX_DAY_RANGE}, got {day_range}")

    area = f"{west},{south},{east},{north}"
    path_parts = [base_url, map_key, source, area, str(day_range)]
    if start_date:
        path_parts.append(start_date)
    url = "/".join(path_parts)

    http = session or requests
    try:
        response = http.get(url, headers={"User-Agent": user_agent}, timeout=timeout)
    except requests.RequestException as exc:
        raise ThermalSourceError(f"request to FIRMS failed: {exc}") from exc

    if response.status_code != 200:
        raise ThermalSourceError(
            f"FIRMS returned HTTP {response.status_code}: {response.text[:500]}"
        )

    try:
        return _parse_csv(response.text)
    except ValueError as exc:
        raise ThermalSourceError(f"could not parse FIRMS response: {exc}") from exc


def _parse_csv(body):
    reader = csv.DictReader(io.StringIO(body))
    if reader.fieldnames is None:
        raise ValueError("empty response body, expected at least a header row")

    missing = _EXPECTED_COLUMNS - set(reader.fieldnames)
    if missing:
        raise ValueError(f"missing expected columns: {sorted(missing)}")

    detections = []
    for row in reader:
        detections.append(
            {
                "latitude": float(row["latitude"]),
                "longitude": float(row["longitude"]),
                "acq_date": row["acq_date"],
                "acq_time": row["acq_time"],
                "frp": float(row["frp"]),
                "confidence": row["confidence"],
                "daynight": row["daynight"],
            }
        )
    return detections


def count_by_date(detections):
    """Bucket a list of detections (as returned by fetch_detections) into
    a dict of acq_date -> count. Pure function, no I/O."""
    counts = {}
    for detection in detections:
        date = detection["acq_date"]
        counts[date] = counts.get(date, 0) + 1
    return counts
