"""Sensor platform for the ENGIE România integration.

The config entry is the MyENGIE account and each place of consumption is a
device. Money and invoice sensors are per place; the meter index and the
self-reading window are per metered service (gas, electricity), so a bundled
contract gets one of each.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import CURRENCY_RON, DIVISION_GAS, DIVISION_NAMES
from .coordinator import EngieConfigEntry, EngieCoordinator
from .entity import EngiePlaceEntity
from .models import Meter, PointData


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _today() -> date:
    return dt_util.now().date()


def _next_due_date(point: PointData) -> date | None:
    """The earliest unpaid invoice's due date; ``None`` once everything is paid."""
    dated = [i.due_date for i in point.unpaid_invoices if i.due_date]
    return min(dated) if dated else None


def _due_datetime(point: PointData) -> datetime | None:
    """Reported as a timestamp so Home Assistant shows "in 3 days" / "5 days ago"."""
    due = _next_due_date(point)
    if due is None:
        return None
    return datetime.combine(due, time.min).replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)


def _due_icon(point: PointData) -> str:
    return "mdi:calendar-alert" if point.overdue_invoices(_today()) else "mdi:calendar-clock"


def _invoice_attrs(point: PointData) -> dict[str, Any]:
    latest = point.latest_invoice
    return {
        "address": point.address,
        "credit": point.balance is not None and point.balance < 0,
        "balance_by_service": {
            DIVISION_NAMES.get(k, k): v for k, v in point.balance_by_division.items()
        },
        "issue_date": _iso(latest.issue_date) if latest else None,
        "due_date": _iso(latest.due_date) if latest else None,
        "unpaid_invoices": len(point.unpaid_invoices),
        "history": [
            {
                "issue_date": _iso(inv.issue_date),
                "due_date": _iso(inv.due_date),
                "total": inv.total,
                "unpaid": inv.unpaid,
                "service": DIVISION_NAMES.get(inv.division or "", inv.division),
                "consumption_kwh": inv.consumption_kwh,
            }
            for inv in point.invoices[:12]
        ],
    }


def _payment_attrs(point: PointData) -> dict[str, Any]:
    latest = point.latest_payment
    return {
        "payment_date": _iso(latest.paid_at) if latest else None,
        "method": latest.method if latest else None,
        "history": [
            {"date": _iso(p.paid_at), "amount": p.amount, "method": p.method}
            for p in point.payments[:12]
        ],
    }


@dataclass(frozen=True, kw_only=True)
class EngieSensorDescription(SensorEntityDescription):
    value_fn: Callable[[PointData], Any]
    attrs_fn: Callable[[PointData], dict[str, Any]] | None = None
    icon_fn: Callable[[PointData], str] | None = None


PLACE_SENSORS: tuple[EngieSensorDescription, ...] = (
    EngieSensorDescription(
        key="amount_due",
        translation_key="amount_due",
        icon="mdi:cash-multiple",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_RON,
        value_fn=lambda p: p.amount_due,
        attrs_fn=_invoice_attrs,
    ),
    EngieSensorDescription(
        key="last_invoice",
        translation_key="last_invoice",
        icon="mdi:file-document-outline",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_RON,
        value_fn=lambda p: p.latest_invoice.total if p.latest_invoice else None,
    ),
    EngieSensorDescription(
        key="due_date",
        translation_key="due_date",
        icon="mdi:calendar-clock",
        value_fn=lambda p: _iso(_next_due_date(p)),
        icon_fn=_due_icon,
    ),
    EngieSensorDescription(
        key="due_date_timestamp",
        translation_key="due_date_timestamp",
        icon="mdi:calendar-clock",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_due_datetime,
        icon_fn=_due_icon,
    ),
    EngieSensorDescription(
        key="overdue",
        translation_key="overdue",
        icon="mdi:alert-circle-outline",
        value_fn=lambda p: "yes" if p.overdue_invoices(_today()) else "no",
    ),
    EngieSensorDescription(
        key="last_payment",
        translation_key="last_payment",
        icon="mdi:cash-check",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_RON,
        value_fn=lambda p: p.latest_payment.amount if p.latest_payment else None,
        attrs_fn=_payment_attrs,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: EngieConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """One device per place of consumption; entities appear as places and meters do."""
    coordinator = config_entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        entities: list[SensorEntity] = []
        for poc, point in (coordinator.data or {}).items():
            if poc not in known:
                known.add(poc)
                entities.extend(
                    EngieSensor(coordinator, config_entry, poc, d) for d in PLACE_SENSORS
                )
            for meter in point.meters:
                name = DIVISION_NAMES.get(meter.division, meter.division)
                for kind in ("meter_index", "self_reading"):
                    tag = f"{poc}:{kind}_{name}"
                    if tag not in known:
                        known.add(tag)
                        cls = EngieMeterIndexSensor if kind == "meter_index" else EngieSelfReadingSensor
                        entities.append(cls(coordinator, config_entry, poc, meter.division))
        if entities:
            async_add_entities(entities)

    _add_new()
    config_entry.async_on_unload(coordinator.async_add_listener(_add_new))


class EngieSensor(EngiePlaceEntity, SensorEntity):
    """A per-place sensor described by :class:`EngieSensorDescription`."""

    entity_description: EngieSensorDescription

    def __init__(
        self,
        coordinator: EngieCoordinator,
        config_entry: EngieConfigEntry,
        poc: str,
        description: EngieSensorDescription,
    ) -> None:
        super().__init__(coordinator, config_entry, poc, description.key, "sensor")
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        point = self._point
        return self.entity_description.value_fn(point) if point else None

    @property
    def icon(self) -> str | None:
        point = self._point
        if point is not None and self.entity_description.icon_fn is not None:
            return self.entity_description.icon_fn(point)
        return super().icon

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        point = self._point
        if point is None or self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(point)


class _MeterSensor(EngiePlaceEntity, SensorEntity):
    """Base for sensors bound to one metered service at a place."""

    _kind: str

    def __init__(
        self,
        coordinator: EngieCoordinator,
        config_entry: EngieConfigEntry,
        poc: str,
        division: str,
    ) -> None:
        name = DIVISION_NAMES.get(division, division)
        super().__init__(coordinator, config_entry, poc, f"{self._kind}_{name}", "sensor")
        self._division = division
        self._attr_translation_key = f"{self._kind}_{name}"

    @property
    def _meter(self) -> Meter | None:
        point = self._point
        return point.meter(self._division) if point else None

    @property
    def available(self) -> bool:
        return super().available and self._meter is not None


class EngieMeterIndexSensor(_MeterSensor):
    """The last meter index: cubic metres for gas, kWh for electricity."""

    _kind = "meter_index"
    _attr_icon = "mdi:counter"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, *args: Any) -> None:
        super().__init__(*args)
        if self._division == DIVISION_GAS:
            self._attr_device_class = SensorDeviceClass.GAS
            self._attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
        else:
            self._attr_device_class = SensorDeviceClass.ENERGY
            self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    @property
    def native_value(self) -> float | None:
        meter = self._meter
        return meter.last_index if meter else None


class EngieSelfReadingSensor(_MeterSensor):
    """Whether the self-reading window is open, with its dates."""

    _kind = "self_reading"
    _attr_icon = "mdi:calendar-check"

    @property
    def native_value(self) -> str | None:
        meter = self._meter
        if meter is None:
            return None
        return "open" if meter.self_read_open(_today()) else "closed"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        meter = self._meter
        if meter is None:
            return None
        return {
            "window_start": _iso(meter.window_start),
            "window_end": _iso(meter.window_end),
            "index_allowed": meter.index_allowed,
        }
