"""Binary sensor platform for the ENGIE România integration.

A device-class ``problem`` entity is shown in red when ``on`` (with
``state_color: true`` on a card) — the native way to make an overdue invoice
stand out. The self-reading window is deliberately not a problem class: an open
window is useful information, not a fault.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DIVISION_NAMES
from .coordinator import EngieConfigEntry, EngieCoordinator
from .entity import EngiePlaceEntity


def _today():
    return dt_util.now().date()


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: EngieConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = config_entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        entities: list[BinarySensorEntity] = []
        for poc, point in (coordinator.data or {}).items():
            if poc not in known:
                known.add(poc)
                entities.append(EngieOverdueBinarySensor(coordinator, config_entry, poc))
            for meter in point.meters:
                tag = f"{poc}:self_reading_open_{meter.division}"
                if tag not in known:
                    known.add(tag)
                    entities.append(
                        EngieSelfReadingBinarySensor(
                            coordinator, config_entry, poc, meter.division
                        )
                    )
        if entities:
            async_add_entities(entities)

    _add_new()
    config_entry.async_on_unload(coordinator.async_add_listener(_add_new))


class EngieOverdueBinarySensor(EngiePlaceEntity, BinarySensorEntity):
    """On when an invoice is unpaid past its due date."""

    _attr_translation_key = "overdue"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self, coordinator: EngieCoordinator, config_entry: EngieConfigEntry, poc: str
    ) -> None:
        super().__init__(coordinator, config_entry, poc, "overdue", "binary_sensor")
        self._attr_unique_id = f"{self._device_id}_overdue_binary"

    @property
    def is_on(self) -> bool | None:
        point = self._point
        return bool(point.overdue_invoices(_today())) if point else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        point = self._point
        if point is None:
            return None
        overdue = point.overdue_invoices(_today())
        return {
            "amount_due": point.amount_due,
            "overdue_invoices": len(overdue),
            "oldest_due_date": min(i.due_date for i in overdue).isoformat() if overdue else None,
        }


class EngieSelfReadingBinarySensor(EngiePlaceEntity, BinarySensorEntity):
    """On while the self-reading window for one metered service is open."""

    _attr_icon = "mdi:calendar-check"

    def __init__(
        self,
        coordinator: EngieCoordinator,
        config_entry: EngieConfigEntry,
        poc: str,
        division: str,
    ) -> None:
        name = DIVISION_NAMES.get(division, division)
        super().__init__(
            coordinator, config_entry, poc, f"self_reading_open_{name}", "binary_sensor"
        )
        self._attr_unique_id = f"{self._device_id}_self_reading_open_{name}_binary"
        self._attr_translation_key = f"self_reading_open_{name}"
        self._division = division

    @property
    def available(self) -> bool:
        point = self._point
        return super().available and point is not None and point.meter(self._division) is not None

    @property
    def is_on(self) -> bool | None:
        point = self._point
        meter = point.meter(self._division) if point else None
        return meter.self_read_open(_today()) if meter else None
