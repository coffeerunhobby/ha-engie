"""Data update coordinator for the ENGIE România integration.

One coordinator per MyENGIE account. It returns ``{poc: PointData}`` — one
entry per place of consumption, which becomes one device.

A failure on one place must not blank the whole account: whatever refreshed is
published, a place that failed keeps its last good data, and the update fails
only when nothing could be refreshed. Authentication errors still abort the
whole update, since they need the user.
"""

from __future__ import annotations

import logging

from aioengieromania import EngieAuthError, EngieClient, EngieError, Payment, PointData
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_DEVICE_ID, DOMAIN, RETRY_INTERVAL, UPDATE_INTERVAL
from .crypto import EngieCipher
from .statistics import async_update_consumption_statistics
from .store import EngieSubmissionStore

_LOGGER = logging.getLogger(__name__)

type EngieConfigEntry = ConfigEntry["EngieCoordinator"]


class EngieCoordinator(DataUpdateCoordinator[dict[str, PointData]]):
    """Fetches one MyENGIE account and exposes it keyed by place of consumption."""

    config_entry: EngieConfigEntry

    def __init__(
        self, hass: HomeAssistant, config_entry: ConfigEntry, cipher: EngieCipher
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
            config_entry=config_entry,
        )
        self._cipher = cipher
        self.api: EngieClient | None = None
        self.submissions = EngieSubmissionStore(hass, config_entry.entry_id)
        # Places whose last refresh failed, so each outage is logged once.
        self._failed_places: set[str] = set()

    def _ensure_api(self) -> EngieClient:
        if self.api is None:
            try:
                password = self._cipher.decrypt(self.config_entry.data[CONF_PASSWORD])
            except ValueError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            self.api = EngieClient(
                self.config_entry.data[CONF_USERNAME],
                password,
                self.config_entry.data[CONF_DEVICE_ID],
                async_get_clientsession(self.hass),
            )
        return self.api

    async def _async_update_data(self) -> dict[str, PointData]:
        # Retry soon after a failure or while a place is missing; the normal
        # interval returns with the first complete update. Auth errors are
        # left alone: they wait for the user.
        self.update_interval = RETRY_INTERVAL
        result = await self._async_fetch()
        if not self._failed_places:
            self.update_interval = UPDATE_INTERVAL
        return result

    async def _async_fetch(self) -> dict[str, PointData]:
        api = self._ensure_api()
        try:
            places = await api.async_get_places()
        except EngieAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except EngieError as err:
            raise UpdateFailed(str(err)) from err
        if not places:
            raise UpdateFailed("No place of consumption found on this MyENGIE account")

        previous: dict[str, PointData] = self.data or {}
        payments_by_pa: dict[str, list[Payment]] = {}
        result: dict[str, PointData] = {}
        for place in places:
            try:
                if place.pa not in payments_by_pa:
                    payments_by_pa[place.pa] = await api.async_get_payments(place.pa)
                point = await api.async_get_point(place)
            except EngieAuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except EngieError as err:
                if place.poc not in self._failed_places:
                    self._failed_places.add(place.poc)
                    _LOGGER.warning("A MyENGIE place of consumption was not refreshed: %s", err)
                if place.poc in previous:
                    result[place.poc] = previous[place.poc]
                continue
            if place.poc in self._failed_places:
                self._failed_places.discard(place.poc)
                _LOGGER.info("A MyENGIE place of consumption refreshes again")
            point.payments = payments_by_pa.get(place.pa, [])
            for division, months in point.consumption.items():
                async_update_consumption_statistics(
                    self.hass, place.poc, division, point.address or place.poc, months
                )
            result[place.poc] = point

        if not any(p.poc not in self._failed_places for p in places):
            raise UpdateFailed("No MyENGIE place of consumption could be refreshed")
        return result
