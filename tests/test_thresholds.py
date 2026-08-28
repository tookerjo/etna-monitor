from etna_monitor import thresholds

MIN_BASELINE_DAYS = 7
SEISMIC_MIN_COUNT = 5
SEISMIC_MIN_RATIO = 2.5
THERMAL_MIN_COUNT = 5
THERMAL_MIN_RATIO = 3.0


def evaluate_seismic(recent_count, trailing, available=True, min_baseline_days=MIN_BASELINE_DAYS):
    return thresholds.evaluate_seismic(
        recent_count,
        available,
        trailing,
        min_baseline_days,
        SEISMIC_MIN_COUNT,
        SEISMIC_MIN_RATIO,
    )


def evaluate_thermal(recent_count, trailing, available=True, min_baseline_days=MIN_BASELINE_DAYS):
    return thresholds.evaluate_thermal(
        recent_count,
        available,
        trailing,
        min_baseline_days,
        THERMAL_MIN_COUNT,
        THERMAL_MIN_RATIO,
    )


def test_empty_baseline_is_cold_start_and_never_fires():
    result = evaluate_seismic(recent_count=20, trailing=[])
    assert result.status == "cold_start"
    assert result.fired is False
    assert result.baseline_days == 0


def test_baseline_shorter_than_minimum_is_cold_start():
    trailing = [1, 2, 3, 1, 2, 1]  # 6 days, minimum is 7
    result = evaluate_seismic(recent_count=50, trailing=trailing)
    assert result.status == "cold_start"
    assert result.fired is False
    assert result.baseline_days == 6


def test_baseline_of_all_zeros_fires_on_any_count_at_or_above_min_count():
    trailing = [0] * 30
    result = evaluate_seismic(recent_count=5, trailing=trailing)
    assert result.status == "ok"
    assert result.baseline_mean == 0.0
    assert result.fired is True


def test_baseline_of_all_zeros_does_not_fire_below_min_count():
    trailing = [0] * 30
    result = evaluate_seismic(recent_count=4, trailing=trailing)
    assert result.status == "ok"
    assert result.fired is False


def test_baseline_of_all_zeros_does_not_divide_by_zero():
    # regression guard: baseline_mean == 0 must not raise or produce inf/nan
    trailing = [0] * 10
    result = evaluate_seismic(recent_count=0, trailing=trailing)
    assert result.fired is False
    assert result.baseline_mean == 0.0


def test_single_day_spike_fires():
    trailing = [1, 2, 1, 2, 1, 2, 1, 2]  # mean = 1.5
    # 5 >= 5 and 5 >= 2.5 * 1.5 (3.75)
    result = evaluate_seismic(recent_count=5, trailing=trailing)
    assert result.status == "ok"
    assert result.fired is True
    assert result.baseline_mean == 1.5


def test_elevated_but_below_ratio_does_not_fire():
    trailing = [3, 3, 3, 3, 3, 3, 3]  # mean = 3.0, threshold = 7.5
    result = evaluate_seismic(recent_count=6, trailing=trailing)
    assert result.status == "ok"
    assert result.fired is False


def test_above_ratio_but_below_min_count_does_not_fire():
    trailing = [1, 1, 1, 1, 1, 1, 1]  # mean = 1.0, ratio threshold = 2.5
    result = evaluate_seismic(recent_count=3, trailing=trailing)
    # 3 >= 2.5*1.0 but 3 < min_count(5)
    assert result.status == "ok"
    assert result.fired is False


def test_source_marked_unavailable_never_fires_regardless_of_history():
    trailing = [1, 2, 1, 2, 1, 2, 1]
    result = evaluate_seismic(recent_count=None, trailing=trailing, available=False)
    assert result.status == "unavailable"
    assert result.fired is False
    assert result.recent_count is None


def test_thermal_excludes_unavailable_days_from_baseline():
    # 14 entries, half unavailable (cloud cover); only the 7 available
    # days with count 10 should count toward the baseline mean.
    trailing = [(10, True)] * 7 + [(0, False)] * 7
    result = evaluate_thermal(recent_count=30, trailing=trailing)
    assert result.status == "ok"
    assert result.baseline_days == 7
    assert result.baseline_mean == 10.0
    assert result.fired is True  # 30 >= 5 and 30 >= 3*10


def test_thermal_cold_start_when_available_days_below_minimum():
    # 10 raw days but only 5 have real data -> still cold start
    trailing = [(4, True)] * 5 + [(0, False)] * 5
    result = evaluate_thermal(recent_count=20, trailing=trailing)
    assert result.status == "cold_start"
    assert result.fired is False


def test_thermal_unavailable_today_never_fires():
    trailing = [(4, True)] * 10
    result = evaluate_thermal(recent_count=None, trailing=trailing, available=False)
    assert result.status == "unavailable"
    assert result.fired is False
