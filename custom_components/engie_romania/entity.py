"""Shared identity for entities bound to one place of consumption.

Every entity belongs to exactly one place of consumption (POC). The device
identifiers, the lookup through the coordinator and the entity_id shape are
defined once here, so the platforms cannot drift apart and split one place
across two devices.
"""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN, MANUFACTURER, MODEL
from .coordinator import EngieConfigEntry, EngieCoordinator
from .models import PointData


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
        platform: str,
    ) -> None:
        super().__init__(coordinator)
        self._poc = poc
        self._device_id = f"{config_entry.entry_id}_{poc}"
        self._attr_unique_id = f"{self._device_id}_{key}"
        # Keyed on ENGIE's place number, so the address never appears in an id.
        self.entity_id = f"{platform}.{DOMAIN}_{poc}_{key}"

    @property
    def _point(self) -> PointData | None:
        return (self.coordinator.data or {}).get(self._poc)

    @property
    def available(self) -> bool:
        return super().available and self._point is not None

    @property
    def device_info(self) -> DeviceInfo:
        point = self._point
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=point.address if point and point.address else f"POC {self._poc}",
            manufacturer=MANUFACTURER,
            model=MODEL,
            entry_type=DeviceEntryType.SERVICE,
        )
