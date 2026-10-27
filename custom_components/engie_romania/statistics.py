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
from datetime import datetime

from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DIVISION_NAMES, DOMAIN
from .models import MonthlyConsumption

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
    metadata: StatisticMetaData = {
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
    return metadata


def monthly_points(months: list[MonthlyConsumption]) -> list[tuple[datetime, float, float]]:
    """``(local month start, that month's kWh, running total)``, oldest first."""
    points: list[tuple[datetime, float, float]] = []
    total = 0.0
    for month in sorted(months, key=lambda m: m.month):
        total = round(total + month.kwh, 3)
        start = dt_util.start_of_local_day(datetime.combine(month.month, datetime.min.time()))
        points.append((start, month.kwh, total))
    return points


def async_update_consumption_statistics(
    hass: HomeAssistant,
    poc: str,
    division: str,
    display_name: str,
    months: list[MonthlyConsumption],
) -> None:
    """Import one place's monthly consumption for one division."""
    points = monthly_points(months)
    if not points:
        return
    stat_id = statistic_id(poc, division)
    label = DIVISION_NAMES.get(division, division)
    try:
        async_add_external_statistics(
            hass,
            _metadata(stat_id, f"ENGIE {display_name} {label}"),
            [StatisticData(start=start, state=kwh, sum=total) for start, kwh, total in points],
        )
    except Exception:  # noqa: BLE001 - the recorder may be unavailable
        _LOGGER.debug("Could not import ENGIE statistics", exc_info=True)
