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
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import EngieApiClient, EngieAuthError, EngieError
from .const import (
    CONF_DEVICE_ID,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DOMAIN,
)
from .crypto import EngieCipher
from .models import Payment, Place, PointData
from .parser import (
    apply_index,
    parse_balance,
    parse_consumption,
    parse_divisions,
    parse_invoices,
    parse_payments,
    parse_places,
)
from .statistics import async_update_consumption_statistics

_LOGGER = logging.getLogger(__name__)

type EngieConfigEntry = ConfigEntry["EngieCoordinator"]


class EngieCoordinator(DataUpdateCoordinator[dict[str, PointData]]):
    """Fetches one MyENGIE account and exposes it keyed by place of consumption."""

    config_entry: EngieConfigEntry

    def __init__(
        self, hass: HomeAssistant, config_entry: ConfigEntry, cipher: EngieCipher
    ) -> None:
        hours = int(
            config_entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_HOURS)
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=hours),
            config_entry=config_entry,
        )
        self._interval_hours = hours
        self._cipher = cipher
        self.api: EngieApiClient | None = None

    def settings_changed(self) -> bool:
        current = int(
            self.config_entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_HOURS)
        )
        return current != self._interval_hours

    def _ensure_api(self) -> EngieApiClient:
        if self.api is None:
            try:
                password = self._cipher.decrypt(self.config_entry.data[CONF_PASSWORD])
            except ValueError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            self.api = EngieApiClient(
                self.config_entry.data[CONF_USERNAME],
                password,
                self.config_entry.data[CONF_DEVICE_ID],
                session=async_get_clientsession(self.hass),
            )
        return self.api

    async def async_shutdown(self) -> None:
        if self.api is not None:
            await self.api.close()
            self.api = None
        await super().async_shutdown()

    async def _async_update_data(self) -> dict[str, PointData]:
        api = self._ensure_api()
        try:
            places = parse_places(await api.async_get_places())
        except EngieAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except EngieError as err:
            raise UpdateFailed(str(err)) from err
        if not places:
            raise UpdateFailed("No place of consumption found on this MyENGIE account")

        previous: dict[str, PointData] = self.data or {}
        payments_by_pa: dict[str, list[Payment]] = {}
        result: dict[str, PointData] = {}
        refreshed = 0
        for place in places:
            try:
                if place.pa not in payments_by_pa:
                    payments_by_pa[place.pa] = parse_payments(
                        await api.async_get_payments(place.pa)
                    )
                point = await self._fetch_place(api, place)
            except EngieAuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except EngieError as err:
                _LOGGER.warning("MyENGIE place of consumption not refreshed: %s", err)
                if place.poc in previous:
                    result[place.poc] = previous[place.poc]
                continue
            point.payments = payments_by_pa.get(place.pa, [])
            for division, months in point.consumption.items():
                async_update_consumption_statistics(
                    self.hass, place.poc, division, point.address or place.poc, months
                )
            result[place.poc] = point
            refreshed += 1

        if not refreshed:
            raise UpdateFailed("No MyENGIE place of consumption could be refreshed")
        return result

    async def _fetch_place(self, api: EngieApiClient, place: Place) -> PointData:
        """Fetch everything for one place of consumption."""
        point = PointData(poc=place.poc, pa=place.pa, address=place.address)
        point.meters = parse_divisions(await api.async_get_divisions(place.poc, place.pa))
        for meter in point.meters:
            apply_index(
                [meter],
                await api.async_get_index(
                    place.poc, place.pa, meter.division, meter.installation_number, meter.serial
                ),
            )
        consumption: Any = await api.async_get_consumption(place.poc, place.pa)
        point.consumption = {
            m.division: parse_consumption(consumption, m.division) for m in point.meters
        }
        point.invoices = parse_invoices(await api.async_get_invoices(place.poc, place.pa))
        accounts = place.contract_accounts or sorted(
            {m.contract_account for m in point.meters if m.contract_account}
        )
        if accounts:
            point.balance, point.balance_by_division = parse_balance(
                await api.async_get_balance(accounts)
            )
        return point
