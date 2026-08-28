"""Threshold evaluation for the seismic and thermal signals.

Pure functions over lists of numbers. No I/O, no clock reads: "now" and
"recent" are always computed by the caller and passed in as plain values.
This is what makes the module testable without fixtures.

A signal can be in one of three states:
  - "unavailable": the current run could not get today's count for this
    signal (source failure, or for thermal, no satellite overpass data).
    Never fires.
  - "cold_start": fewer than the minimum required days of baseline history
    exist. Never fires; the caller's message should say the baseline is
    still filling.
  - "ok": a real evaluation happened. May or may not have fired.

Firing rule: recent_count >= min_count AND recent_count >= min_ratio *
baseline_mean. When baseline_mean is 0 (e.g. an all-zero baseline), the
second condition is trivially true, so a zero baseline cannot divide by
zero and cannot suppress a real spike above min_count.
"""

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class ThresholdResult:
    fired: bool
    status: str  # "ok", "cold_start", or "unavailable"
    recent_count: Optional[int]
    baseline_mean: Optional[float]
    baseline_days: int
    min_count: int
    min_ratio: float


def _evaluate(
    recent_count: Optional[int],
    recent_available: bool,
    trailing_daily_counts: Sequence[int],
    min_baseline_days: int,
    min_count: int,
    min_ratio: float,
) -> ThresholdResult:
    baseline_days = len(trailing_daily_counts)

    if not recent_available:
        return ThresholdResult(
            fired=False,
            status="unavailable",
            recent_count=None,
            baseline_mean=None,
            baseline_days=baseline_days,
            min_count=min_count,
            min_ratio=min_ratio,
        )

    if baseline_days < min_baseline_days:
        return ThresholdResult(
            fired=False,
            status="cold_start",
            recent_count=recent_count,
            baseline_mean=None,
            baseline_days=baseline_days,
            min_count=min_count,
            min_ratio=min_ratio,
        )

    baseline_mean = sum(trailing_daily_counts) / baseline_days
    fired = recent_count >= min_count and recent_count >= min_ratio * baseline_mean
    return ThresholdResult(
        fired=fired,
        status="ok",
        recent_count=recent_count,
        baseline_mean=baseline_mean,
        baseline_days=baseline_days,
        min_count=min_count,
        min_ratio=min_ratio,
    )


def evaluate_seismic(
    recent_count: Optional[int],
    recent_available: bool,
    trailing_daily_counts: Sequence[int],
    min_baseline_days: int,
    min_count: int,
    min_ratio: float,
) -> ThresholdResult:
    """trailing_daily_counts: one entry per day in the baseline window,
    each the count of events that day. Every day in the window must be
    represented (seismic history has no per-day availability concept —
    a failed run simply does not contribute a day)."""
    return _evaluate(
        recent_count,
        recent_available,
        trailing_daily_counts,
        min_baseline_days,
        min_count,
        min_ratio,
    )


def evaluate_thermal(
    recent_count: Optional[int],
    recent_available: bool,
    trailing_daily_records: Sequence[Tuple[int, bool]],
    min_baseline_days: int,
    min_count: int,
    min_ratio: float,
) -> ThresholdResult:
    """trailing_daily_records: one (detection_count, detections_available)
    pair per day in the baseline window. Days where detections_available
    is False are excluded from both the baseline day count and the mean,
    per spec: cloud cover must not be counted as a quiet day."""
    available_counts: List[int] = [
        count for count, available in trailing_daily_records if available
    ]
    return _evaluate(
        recent_count,
        recent_available,
        available_counts,
        min_baseline_days,
        min_count,
        min_ratio,
    )
