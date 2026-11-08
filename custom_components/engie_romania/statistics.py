"""Feed ENGIE's billed monthly consumption into Home Assistant long-term statistics.

MyENGIE reports consumption per billing month in kWh — gas included, which ENGIE
converts from cubic metres using the calorific value. Each month becomes one
cumulative step at local midnight on the first of that month, which the Energy
Dashboard and the Statistics Graph card show as monthly bars.

This is billed consumption: a month's value is what was invoiced for it, which
can include estimates and corrections, not metered daily truth. A correction after
an over-estimate is a negative month; it is kept, so the running total matches what
was billed, and the Energy Dashboard shows it as a negative bar for that month.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime
from typing import Any, cast

from aioengieromania import MonthlyConsumption
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    statistics_during_period,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.recorder import get_instance
from homeassistant.util import dt as dt_util

from .const import DIVISION_NAMES, DOMAIN

_LOGGER = logging.getLogger(__name__)


def statistic_id(poc: str, division: str) -> str:
    """External statistic id, e.g. ``engie_romania:gas_<poc>``."""
    return f"{DOMAIN}:{DIVISION_NAMES.get(division, division)}_{poc}"


def _metadata(stat_id: str, name: str) -> StatisticMetaData:
    """Sum-only statistic metadata, robust across Home Assistant versions.

    Newer releases replaced ``has_mean`` with ``mean_type`` and added
    ``unit_class``, which from 2026.11 is no longer derived for us. Releases before
    2025.11 reject unknown metadata keys, so it is sent only where declared.
    """
    # Built as a plain dict: which keys exist depends on the Home Assistant version.
    metadata: dict[str, Any] = {
        "has_sum": True,
        "name": name,
        "source": DOMAIN,
        "statistic_id": stat_id,
        "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
    }
    try:
        from homeassistant.components.recorder.models import StatisticMeanType

        metadata["mean_type"] = StatisticMeanType.NONE
    except ImportError:
        metadata["has_mean"] = False
    if "unit_class" in StatisticMetaData.__annotations__:
        metadata["unit_class"] = "energy"
    return cast(StatisticMetaData, metadata)


def monthly_points(
    months: list[MonthlyConsumption], stored: Iterable[tuple[datetime, float]] = ()
) -> list[tuple[datetime, float, float]]:
    """``(local month start, that month's kWh, running total)``, oldest first.

    ENGIE returns only the last three years, so each month the oldest one drops
    out. ``stored`` are the ``(start, kWh)`` rows already imported; the ones older
    than what ENGIE returned are kept at the front, so the running total keeps
    counting from the first month ever imported instead of restarting, which
    would show a wrong bar where the window used to begin.
    """
    current = [
        (dt_util.start_of_local_day(datetime.combine(m.month, datetime.min.time())), m.kwh)
        for m in sorted(months, key=lambda m: m.month)
    ]
    if not current:
        return []
    first = current[0][0]
    rows = sorted((r for r in stored if r[0] < first), key=lambda r: r[0]) + current
    points: list[tuple[datetime, float, float]] = []
    total = 0.0
    for start, kwh in rows:
        total = round(total + kwh, 3)
        points.append((start, kwh, total))
    return points


async def _async_stored_months(hass: HomeAssistant, stat_id: str) -> list[tuple[datetime, float]]:
    """The ``(start, kWh)`` rows already imported; each row's state is its month's kWh."""
    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        dt_util.utc_from_timestamp(0),
        None,
        {stat_id},
        "hour",
        None,
        {"state"},
    )
    rows: list[tuple[datetime, float]] = []
    for row in stats.get(stat_id, []):
        start, state = row.get("start"), row.get("state")
        if start is None or state is None:
            continue
        rows.append((dt_util.utc_from_timestamp(start), float(state)))
    return rows


async def async_update_consumption_statistics(
    hass: HomeAssistant,
    poc: str,
    division: str,
    display_name: str,
    months: list[MonthlyConsumption],
) -> None:
    """Import one place's monthly consumption for one division."""
    if not months:
        return
    stat_id = statistic_id(poc, division)
    label = DIVISION_NAMES.get(division, division)
    try:
        # Rewriting the older rows too repairs totals an earlier release restarted.
        points = monthly_points(months, await _async_stored_months(hass, stat_id))
        async_add_external_statistics(
            hass,
            _metadata(stat_id, f"ENGIE {display_name} {label}"),
            [StatisticData(start=start, state=kwh, sum=total) for start, kwh, total in points],
        )
    except Exception:  # noqa: BLE001 - the recorder may be unavailable
        _LOGGER.debug("Could not import ENGIE statistics", exc_info=True)
