from etna_monitor import advisory_format

# Real advisory text, fetched live from VAAC Toulouse for two advisories
# that are genuinely present (by key) in the committed data/state.json:
# advisories_seen contains "2026/86" and "2026/105". Raw text itself isn't
# persisted in state.json (only key/published_utc/colour_code are), so
# these were re-fetched from the same live source for use as fixtures.

REAL_ASH_PRESENT = (
    "VA ADVISORY\n"
    "DTG: 20260815/0400Z\n"
    "VAAC: TOULOUSE\n"
    "VOLCANO: ETNA 211060\n"
    "PSN: N3744 E01459\n"
    "AREA: SICILY VOLCANIC PROVINCE\n"
    "SOURCE ELEV: 3357M\n"
    "ADVISORY NR: 2026/86\n"
    "INFO SOURCE: VONA, INGV WEBCAMS, SAT IMAGERY\n"
    "AVIATION COLOUR CODE: RED\n"
    "ERUPTION DETAILS: ERUPTION AT 20260808/0018Z ONGOING ERUPTION\n"
    "OBS VA DTG: 15/0400Z\n"
    "OBS VA CLD: SFC/FL160 N3748 E01454 - N3745 E01512 - N3653 E01530 - N3518 E01536 - N3518 E01400 - N3748 E01454 MOV S 20KT\n"
    "FCST VA CLD +6 HR: 15/1000Z SFC/FL160 N3745 E01451 - N3745 E01512 - N3700 E01536 - N3430 E01545 - N3430 E01351 - N3636 E01421 - N3745 E01451 \n"
    "FCST VA CLD +12 HR: 15/1600Z SFC/FL170 N3745 E01451 - N3745 E01512 - N3718 E01554 - N3408 E01621 - N3408 E01445 - N3548 E01500 - N3745 E01451 \n"
    "FCST VA CLD +18 HR: 15/2200Z SFC/FL170 N3745 E01451 - N3745 E01512 - N3748 E01524 - N3612 E01633 - N3418 E01648 - N3418 E01500 - N3553 E01518 - N3745 E01451 \n"
    "RMK:  QVA NOT PROVIDED DUE TO LOW INTENSITY OF THE  EVENT.\n"
    "NXT ADVISORY: NO LATER THAN 20260815/1000Z="
)

REAL_NO_ASH = (
    "VA ADVISORY\n"
    "DTG: 20260818/0754Z\n"
    "VAAC: TOULOUSE\n"
    "VOLCANO: ETNA 211060\n"
    "PSN: N3744 E01459\n"
    "AREA: SICILY VOLCANIC PROVINCE\n"
    "SOURCE ELEV: 3357M\n"
    "ADVISORY NR: 2026/105\n"
    "INFO SOURCE: VONA, INGV WEBCAMS, SAT IMAGERY\n"
    "AVIATION COLOUR CODE: ORANGE\n"
    "ERUPTION DETAILS: ERUPTION AT 20260816/1620Z EXPLOSIVE ACTIVITY IS DECREASING\n"
    "OBS VA DTG: 18/0730Z\n"
    "OBS VA CLD: VA NOT IDENTIFIABLE FM SATELLITE DATA  WIND FL100 290/20KT  FL180 325/20KT\n"
    "FCST VA CLD +6 HR: 18/1330Z NO VA EXP\n"
    "FCST VA CLD +12 HR: 18/1930Z NO VA EXP\n"
    "FCST VA CLD +18 HR: 19/0130Z NO VA EXP\n"
    "RMK:  WEAK VOLCANIC ASH STILL POSSIBLE IN THE VICINITY  OF THE CRATER. \n"
    "NXT ADVISORY: NO FURTHER ADVISORIES="
)


def test_ash_present_advisory():
    message = advisory_format.format_advisory(REAL_ASH_PRESENT)
    lines = message.splitlines()

    assert "Colour code RED" in lines
    assert "Sat 15 Aug, 6:00 AM Sicily" in lines
    assert "Eruption: ERUPTION AT 20260808/0018Z ONGOING ERUPTION" in lines
    assert "Ash: surface to 16,000 ft, moving S at 20 kt" in lines
    assert "6hr forecast: ash expected, surface to 16,000 ft" in "\n".join(lines)
    assert any(line.startswith("Remarks:") for line in lines)
    assert "Next advisory: no later than Sat 15 Aug, 12:00 PM Sicily" in lines

    # coordinate polygons must never leak into the formatted output
    assert "N3748" not in message
    assert "E01454" not in message


def test_no_ash_advisory_says_so_plainly():
    message = advisory_format.format_advisory(REAL_NO_ASH)
    lines = message.splitlines()

    assert "Colour code ORANGE" in lines
    assert "Tue 18 Aug, 9:54 AM Sicily" in lines
    assert "Ash: none observed" in lines
    assert "6hr forecast: no ash expected" in lines
    assert "Next advisory: none expected" in lines

    # the "no ash" line still contains "FL100"/"FL180" as wind data --
    # must not be misread as an ash layer
    ash_line = next(l for l in lines if l.startswith("Ash:"))
    assert "moving" not in ash_line


def test_empty_string_falls_back_without_crashing():
    message = advisory_format.format_advisory("")
    assert message == "[Could not format this advisory -- showing the raw text]"
    assert "None" not in message


def test_none_input_falls_back_without_crashing():
    message = advisory_format.format_advisory(None)
    assert "Could not format" in message
    assert "None" not in message


def test_truncated_advisory_omits_missing_fields_without_crashing():
    # Cut off right after the colour code -- no eruption details, no ash
    # lines, no RMK, no NXT ADVISORY.
    truncated = (
        "VA ADVISORY\n"
        "DTG: 20260818/0754Z\n"
        "VAAC: TOULOUSE\n"
        "VOLCANO: ETNA 211060\n"
        "ADVISORY NR: 2026/105\n"
        "AVIATION COLOUR CODE: ORANGE\n"
    )
    message = advisory_format.format_advisory(truncated)
    assert "Colour code ORANGE" in message
    assert "Tue 18 Aug, 9:54 AM Sicily" in message
    assert "None" not in message
    assert "Eruption:" not in message
    assert "Ash:" not in message
    assert "Remarks:" not in message
    assert "Next advisory:" not in message


def test_completely_unrecognizable_text_falls_back():
    message = advisory_format.format_advisory("the quick brown fox jumps over the lazy dog")
    assert "Could not format" in message
    assert "the quick brown fox" in message  # raw text preserved, not dropped


def test_garbage_dtg_is_omitted_not_crashed_on():
    text = "DTG: not-a-real-dtg\nAVIATION COLOUR CODE: GREEN\n"
    message = advisory_format.format_advisory(text)
    assert "Colour code GREEN" in message
    assert "Sicily" not in message  # no valid timestamp to convert


def test_mixed_ash_and_no_ash_layers_in_one_line():
    # Real shape seen in advisory 2026/103: two layers in one OBS line,
    # one with ash, effectively testing multi-layer parsing.
    text = (
        "AVIATION COLOUR CODE: RED\n"
        "OBS VA CLD: SFC/FL150 N3748 E01503 - N3645 E01841 MOV SE 25KT "
        "FL050/200 N3536 E01800 - N3645 E01839 MOV SE 20KT\n"
    )
    message = advisory_format.format_advisory(text)
    assert "surface to 15,000 ft, moving SE at 25 kt" in message
    assert "5,000-20,000 ft, moving SE at 20 kt" in message
    assert "N3748" not in message
