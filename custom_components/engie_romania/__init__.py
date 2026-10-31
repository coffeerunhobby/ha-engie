"""The ENGIE România integration."""

from __future__ import annotations

import logging

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_UPDATE_INTERVAL
from .coordinator import EngieConfigEntry, EngieCoordinator
from .crypto import EngieCipher
from .store import EngieSubmissionStore

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.BUTTON,
]


async def async_setup_entry(hass: HomeAssistant, entry: EngieConfigEntry) -> bool:
    """Set up ENGIE România from a config entry."""
    coordinator = EngieCoordinator(hass, entry, await EngieCipher.async_load(hass))
    await coordinator.submissions.async_load()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EngieConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, entry: EngieConfigEntry) -> bool:
    """1.1 → 1.2: the update interval is no longer a setting."""
    if entry.version > 1:
        return False
    if entry.minor_version < 2:
        data = {k: v for k, v in entry.data.items() if k != CONF_UPDATE_INTERVAL}
        hass.config_entries.async_update_entry(entry, data=data, minor_version=2)
        _LOGGER.debug("Migrated the ENGIE entry to version 1.2")
    return True


async def async_remove_entry(hass: HomeAssistant, entry: EngieConfigEntry) -> None:
    """Forget the submission record of a removed account."""
    await EngieSubmissionStore(hass, entry.entry_id).async_remove()
