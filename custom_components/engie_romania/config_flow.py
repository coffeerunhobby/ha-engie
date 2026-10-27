"""Config and options flow for the ENGIE România integration.

MyENGIE has no second factor on this login, so setup is one step: validate the
credentials and confirm the account has at least one place of consumption.
"""

from __future__ import annotations

import uuid
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import EngieApiClient, EngieAuthError, EngieConnectionError, EngieError
from .const import (
    CONF_DEVICE_ID,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DOMAIN,
    MAX_UPDATE_INTERVAL_HOURS,
    MIN_UPDATE_INTERVAL_HOURS,
)
from .coordinator import EngieConfigEntry
from .crypto import EngieCipher
from .parser import parse_places

_INTERVAL_SELECTOR = NumberSelector(
    NumberSelectorConfig(
        min=MIN_UPDATE_INTERVAL_HOURS,
        max=MAX_UPDATE_INTERVAL_HOURS,
        step=1,
        mode=NumberSelectorMode.BOX,
    )
)
_PASSWORD_SCHEMA = vol.Schema(
    {vol.Required(CONF_PASSWORD): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))}
)


def _user_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): TextSelector(
                TextSelectorConfig(type=TextSelectorType.EMAIL)
            ),
            vol.Required(CONF_PASSWORD): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
            vol.Optional(
                CONF_UPDATE_INTERVAL,
                default=defaults.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_HOURS),
            ): _INTERVAL_SELECTOR,
        }
    )


async def _validate(hass: HomeAssistant, username: str, password: str, device_id: str) -> int:
    """Log in and return the number of places of consumption found."""
    client = EngieApiClient(username, password, device_id, session=async_get_clientsession(hass))
    try:
        await client.async_login()
        return len(parse_places(await client.async_get_places()))
    finally:
        await client.close()


def _error_key(err: EngieError) -> str:
    if isinstance(err, EngieAuthError):
        return "invalid_auth"
    if isinstance(err, EngieConnectionError):
        return "cannot_connect"
    return "unknown"


class EngieConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle setup, re-authentication and reconfiguration."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            await self.async_set_unique_id(username.lower())
            self._abort_if_unique_id_configured()
            device_id = str(uuid.uuid4())
            try:
                places = await _validate(self.hass, username, user_input[CONF_PASSWORD], device_id)
            except EngieError as err:
                errors["base"] = _error_key(err)
            else:
                if not places:
                    errors["base"] = "no_places"
                else:
                    cipher = await EngieCipher.async_load(self.hass)
                    return self.async_create_entry(
                        title=f"ENGIE — {username}",
                        data={
                            CONF_USERNAME: username,
                            CONF_PASSWORD: cipher.encrypt(user_input[CONF_PASSWORD]),
                            CONF_DEVICE_ID: device_id,
                            CONF_UPDATE_INTERVAL: int(
                                user_input.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_HOURS)
                            ),
                        },
                    )
        return self.async_show_form(
            step_id="user", data_schema=_user_schema(user_input), errors=errors
        )

    # Re-auth is Home Assistant asking after a refresh failed; reconfigure is the
    # user opening the same form from the entry's menu. Both replace the password
    # on the existing entry and keep everything else.
    async def _async_replace_password(
        self, step_id: str, entry: EngieConfigEntry, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await _validate(
                    self.hass,
                    entry.data[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                    entry.data[CONF_DEVICE_ID],
                )
            except EngieError as err:
                errors["base"] = _error_key(err)
            else:
                cipher = await EngieCipher.async_load(self.hass)
                return self.async_update_reload_and_abort(
                    entry,
                    data={**entry.data, CONF_PASSWORD: cipher.encrypt(user_input[CONF_PASSWORD])},
                )
        return self.async_show_form(step_id=step_id, data_schema=_PASSWORD_SCHEMA, errors=errors)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_replace_password(
            "reauth_confirm", self._get_reauth_entry(), user_input
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_replace_password(
            "reconfigure", self._get_reconfigure_entry(), user_input
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: EngieConfigEntry) -> EngieOptionsFlow:
        return EngieOptionsFlow()


class EngieOptionsFlow(OptionsFlow):
    """Change the update interval without re-adding the integration."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self.config_entry
        if user_input is not None:
            self.hass.config_entries.async_update_entry(
                entry,
                data={**entry.data, CONF_UPDATE_INTERVAL: int(user_input[CONF_UPDATE_INTERVAL])},
            )
            return self.async_create_entry(title="", data={})
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_UPDATE_INTERVAL,
                        default=entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_HOURS),
                    ): _INTERVAL_SELECTOR
                }
            ),
        )
