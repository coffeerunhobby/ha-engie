"""Number platform: the meter index staged for a self-reading.

One per metered service at a place. Changing it sends nothing to ENGIE; it only
holds the value the matching submit button will send, so the reading can be
typed in and checked before it is submitted deliberately.
"""

from __future__ import annotations

from typing import Any

from aioengieromania import DIVISION_GAS, Meter
from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DIVISION_NAMES
from .coordinator import EngieConfigEntry, EngieCoordinator
from .entity import EngiePlaceEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: EngieConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = config_entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        entities: list[EngieReadingNumber] = []
        for poc, point in (coordinator.data or {}).items():
            for meter in point.meters:
                tag = f"{poc}:{meter.division}"
                if tag not in known:
                    known.add(tag)
                    entities.append(
                        EngieReadingNumber(coordinator, config_entry, poc, meter.division)
                    )
        if entities:
            async_add_entities(entities)

    _add_new()
    config_entry.async_on_unload(coordinator.async_add_listener(_add_new))


class EngieReadingNumber(EngiePlaceEntity, RestoreNumber):
    """The index the next self-reading submission will send."""

    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = 99_999_999
    _attr_native_step = 1

    def __init__(
        self,
        coordinator: EngieCoordinator,
        config_entry: EngieConfigEntry,
        poc: str,
        division: str,
    ) -> None:
        name = DIVISION_NAMES.get(division, division)
        super().__init__(coordinator, config_entry, poc, f"reading_to_submit_{name}")
        self._division = division
        self._attr_translation_key = f"reading_to_submit_{name}"
        self._attr_native_unit_of_measurement = (
            UnitOfVolume.CUBIC_METERS if division == DIVISION_GAS else UnitOfEnergy.KILO_WATT_HOUR
        )
        self._value: float | None = None

    @property
    def _meter(self) -> Meter | None:
        point = self._point
        return point.meter(self._division) if point else None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_number_data()) is not None:
            self._value = last.native_value
        if self._value is None and (meter := self._meter) is not None:
            # Start from the last known index rather than zero.
            self._value = meter.last_index

    @property
    def native_value(self) -> float | None:
        return self._value

    async def async_set_native_value(self, value: float) -> None:
        self._value = value
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        meter = self._meter
        return {"last_known_index": meter.last_index if meter else None}
