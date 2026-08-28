"""Formats a raw VAAC advisory into a short, phone-readable plain-text
message. Pure function: no I/O, no clock reads, no network. Presentation
only -- this module has no say in whether an alert fires, only in how its
text reads. Called from notify.py.

Field mapping (see the real advisory samples in tests/test_advisory_format.py):

    AVIATION COLOUR CODE  -> headline, e.g. "Colour code RED"
    DTG                   -> UTC converted to Europe/Rome ("Sicily"),
                              e.g. "Tue 18 Aug, 9:54 AM Sicily"
    ERUPTION DETAILS      -> one plain-text line
    OBS VA CLD            -> one line per ash layer: height range in feet
                              (flight level x 100), direction, speed;
                              coordinate polygons are dropped entirely
    FCST VA CLD +6 HR     -> one summary line ("NO VA EXP" -> no ash
                              expected); +12/+18 HR are ignored
    RMK                   -> included verbatim (whitespace-collapsed)
    NXT ADVISORY          -> any embedded timestamp converted to Sicily
                              time; otherwise passed through as-is

A field that's missing or doesn't parse is simply omitted from the
output -- never rendered as the word "None", never a crash. If nothing
at all can be extracted (empty input, or text unlike any advisory this
parser recognizes), the raw text is returned with a note that formatting
failed, so an alert is never dropped for a presentation-layer reason.
"""

import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

SICILY_TZ = ZoneInfo("Europe/Rome")

_DTG_RE = re.compile(r"^DTG:\s*(\d{8})/(\d{4})Z\s*$", re.MULTILINE)
_COLOUR_RE = re.compile(r"^AVIATION COLOUR CODE:\s*(.+)$", re.MULTILINE)
_ERUPTION_RE = re.compile(r"^ERUPTION DETAILS:\s*(.+)$", re.MULTILINE)
_OBS_RE = re.compile(r"^OBS VA CLD:\s*(.*)$", re.MULTILINE)
_FCST6_RE = re.compile(r"^FCST VA CLD \+6 HR:\s*(.*)$", re.MULTILINE)
_RMK_RE = re.compile(r"^RMK:\s*(.+)$", re.MULTILINE)
_NXT_RE = re.compile(r"^NXT ADVISORY:\s*(.+?)=?\s*$", re.MULTILINE)

# A layer header is "SFC/FL160" or "FL050/200" (second number implicitly
# a flight level too). Requires the literal "/" right after the first
# token, which is what keeps this from matching wind data like
# "WIND FL100 290/20KT" (a space, not a slash, follows FL100 there).
_LAYER_HEADER_RE = re.compile(r"\b(SFC|FL\d{3})/(?:FL)?(\d{3})\b")
_MOV_RE = re.compile(r"MOV\s+([NSEW]{1,3})\s+(\d+)\s*KT")
_EMBEDDED_DTG_RE = re.compile(r"(\d{8})/(\d{4})Z")

_FALLBACK_NOTE = "[Could not format this advisory -- showing the raw text]"


def format_advisory(raw_text):
    raw_text = raw_text or ""
    try:
        lines = _build_lines(raw_text)
    except Exception:
        lines = None

    if not lines:
        return _fallback(raw_text)
    return "\n".join(lines)


def _fallback(raw_text):
    if raw_text:
        return _FALLBACK_NOTE + "\n\n" + raw_text
    return _FALLBACK_NOTE


def _build_lines(raw_text):
    lines = []

    colour = _first_match(_COLOUR_RE, raw_text)
    if colour:
        lines.append(f"Colour code {colour.strip()}")

    dtg_line = _format_dtg_line(raw_text)
    if dtg_line:
        lines.append(dtg_line)

    eruption = _first_match(_ERUPTION_RE, raw_text)
    if eruption:
        lines.append(f"Eruption: {eruption.strip()}")

    obs_line = _format_obs_line(raw_text)
    if obs_line:
        lines.append(obs_line)

    forecast_line = _format_forecast_line(raw_text)
    if forecast_line:
        lines.append(forecast_line)

    rmk = _first_match(_RMK_RE, raw_text)
    if rmk:
        lines.append(f"Remarks: {_collapse_whitespace(rmk)}")

    nxt_line = _format_nxt_line(raw_text)
    if nxt_line:
        lines.append(nxt_line)

    return lines


def _first_match(pattern, text):
    m = pattern.search(text)
    if not m:
        return None
    value = m.group(1)
    return value if value and value.strip() else None


def _collapse_whitespace(text):
    return " ".join(text.split())


def _format_dtg_line(text):
    m = _DTG_RE.search(text)
    if not m:
        return None
    return _dtg_to_sicily(m.group(1), m.group(2))


def _dtg_to_sicily(date_part, time_part):
    try:
        dt_utc = datetime(
            int(date_part[0:4]),
            int(date_part[4:6]),
            int(date_part[6:8]),
            int(time_part[0:2]),
            int(time_part[2:4]),
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    return _format_sicily_datetime(dt_utc)


def _format_sicily_datetime(dt_utc):
    local = dt_utc.astimezone(SICILY_TZ)
    hour12 = local.strftime("%I").lstrip("0") or "12"
    return f"{local.strftime('%a')} {local.day} {local.strftime('%b')}, {hour12}:{local.strftime('%M')} {local.strftime('%p')} Sicily"


def _parse_ash_layers(text):
    headers = list(_LAYER_HEADER_RE.finditer(text))
    layers = []
    for i, m in enumerate(headers):
        start = m.start()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        segment = text[start:end]
        bottom_token, top_token = m.group(1), m.group(2)
        bottom_ft = 0 if bottom_token == "SFC" else int(bottom_token[2:]) * 100
        top_ft = int(top_token) * 100
        mov = _MOV_RE.search(segment)
        direction, speed = (mov.group(1), mov.group(2)) if mov else (None, None)
        layers.append((bottom_ft, top_ft, direction, speed))
    return layers


def _describe_layer(bottom_ft, top_ft, direction, speed):
    height = f"surface to {top_ft:,} ft" if bottom_ft == 0 else f"{bottom_ft:,}-{top_ft:,} ft"
    if direction and speed:
        return f"{height}, moving {direction} at {speed} kt"
    return height


def _format_obs_line(text):
    obs = _first_match(_OBS_RE, text)
    if obs is None:
        return None
    layers = _parse_ash_layers(obs)
    if not layers:
        return "Ash: none observed"
    return "Ash: " + "; ".join(_describe_layer(*layer) for layer in layers)


def _format_forecast_line(text):
    fcst = _first_match(_FCST6_RE, text)
    if fcst is None:
        return None
    layers = _parse_ash_layers(fcst)
    if not layers:
        return "6hr forecast: no ash expected"
    return "6hr forecast: ash expected, " + "; ".join(_describe_layer(*layer) for layer in layers)


def _format_nxt_line(text):
    nxt = _first_match(_NXT_RE, text)
    if nxt is None:
        return None
    nxt = nxt.strip()

    embedded = _EMBEDDED_DTG_RE.search(nxt)
    if embedded:
        sicily = _dtg_to_sicily(embedded.group(1), embedded.group(2))
        if sicily:
            prefix = nxt[: embedded.start()].strip()
            return f"Next advisory: {prefix.lower()} {sicily}" if prefix else f"Next advisory: {sicily}"

    if "NO FURTHER ADVISORIES" in nxt.upper():
        return "Next advisory: none expected"

    return f"Next advisory: {_collapse_whitespace(nxt)}"
