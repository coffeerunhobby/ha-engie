"""Shared identity for entities bound to one place of consumption.

Every entity belongs to exactly one place of consumption (POC). The device is
named after the provider and ENGIE's place number, never the address: Home
Assistant builds entity ids from the device and entity names, so ids such as
``sensor.engie_romania_<poc>_amount_due`` stay free of personal data. Users can
rename the device; the address is an attribute of the Amount due sensor.
"""

from __future__ import annotations

from aioengieromania import PointData
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN, MANUFACTURER, MODEL
from .coordinator import EngieConfigEntry, EngieCoordinator


class EngiePlaceEntity(CoordinatorEntity[EngieCoordinator]):
    """An entity on one place-of-consumption device."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        coordinator: EngieCoordinator,
        config_entry: EngieConfigEntry,
        poc: str,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self._poc = poc
        self._device_id = f"{config_entry.entry_id}_{poc}"
        self._attr_unique_id = f"{self._device_id}_{key}"

    @property
    def _point(self) -> PointData | None:
        return (self.coordinator.data or {}).get(self._poc)

    @property
    def available(self) -> bool:
        return super().available and self._point is not None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=f"{MANUFACTURER} {self._poc}",
            manufacturer=MANUFACTURER,
            model=MODEL,
            entry_type=DeviceEntryType.SERVICE,
        )
