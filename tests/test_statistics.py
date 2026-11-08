"""Billed monthly consumption to long-term statistics."""

from __future__ import annotations

from datetime import date

import pytest

pytest.importorskip("homeassistant")

from datetime import datetime  # noqa: E402

from aioengieromania import MonthlyConsumption  # noqa: E402
from homeassistant.components.recorder import get_instance  # noqa: E402
from homeassistant.components.recorder.models import StatisticData  # noqa: E402
from homeassistant.components.recorder.statistics import (  # noqa: E402
    async_add_external_statistics,
    statistics_during_period,
)
from homeassistant.util import dt as dt_util  # noqa: E402

from custom_components.engie_romania.statistics import (  # noqa: E402
    _metadata,
    async_update_consumption_statistics,
    monthly_points,
    statistic_id,
)


@pytest.fixture(autouse=True)
def _auto_enable_custom_integrations():
    """Override the conftest autouse: ``recorder_mock`` must initialise before ``hass``."""
    yield


def _month(year: int, month: int) -> datetime:
    return dt_util.start_of_local_day(datetime(year, month, 1))


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


async def test_months_older_than_engies_window_keep_the_running_total(recorder_mock, hass):
    """ENGIE returns three years; the month that drops out stays the base of the total.

    The stored rows are what 0.4.0 left after July dropped out of the window:
    August restarted from zero. The next import continues from July and repairs it.
    """
    stat_id = statistic_id("p1", "gaz")
    async_add_external_statistics(
        hass,
        _metadata(stat_id, "ENGIE p1 gas"),
        [
            StatisticData(start=_month(2026, 7), state=100.0, sum=100.0),
            StatisticData(start=_month(2026, 8), state=50.0, sum=50.0),
        ],
    )
    await hass.async_block_till_done()
    await get_instance(hass).async_block_till_done()

    await async_update_consumption_statistics(
        hass,
        "p1",
        "gaz",
        "p1",
        [MonthlyConsumption(date(2026, 8, 1), 50.0), MonthlyConsumption(date(2026, 9, 1), 30.0)],
    )
    await hass.async_block_till_done()
    await get_instance(hass).async_block_till_done()

    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        dt_util.utc_from_timestamp(0),
        None,
        {stat_id},
        "hour",
        None,
        {"state", "sum"},
    )
    assert [(r["state"], r["sum"]) for r in stats[stat_id]] == [
        (100.0, 100.0),
        (50.0, 150.0),
        (30.0, 180.0),
    ]
