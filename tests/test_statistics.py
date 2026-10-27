"""Billed monthly consumption to long-term statistics."""

from __future__ import annotations

from datetime import date

import pytest

pytest.importorskip("homeassistant")

from custom_components.engie_romania.models import MonthlyConsumption  # noqa: E402
from custom_components.engie_romania.statistics import monthly_points  # noqa: E402


def test_corrections_are_kept_so_the_total_matches_the_bills():
    """A negative month is ENGIE correcting an over-estimate, not a glitch.

    Dropping it would leave the running total higher than what was billed.
    """
    months = [
        MonthlyConsumption(date(2026, 7, 1), 500.0),
        MonthlyConsumption(date(2026, 8, 1), -120.0),
        MonthlyConsumption(date(2026, 9, 1), 300.0),
    ]
    points = monthly_points(months)
    assert [kwh for _, kwh, _ in points] == [500.0, -120.0, 300.0]
    assert points[-1][2] == 680.0  # 500 - 120 + 300


def test_months_are_ordered_oldest_first():
    months = [MonthlyConsumption(date(2026, 9, 1), 3.0), MonthlyConsumption(date(2026, 7, 1), 1.0)]
    assert [start.month for start, _, _ in monthly_points(months)] == [7, 9]
