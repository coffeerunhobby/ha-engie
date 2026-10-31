"""Config flow for the ENGIE România integration.

MyENGIE has no second factor on this login, so setup is one step: validate the
credentials and confirm the account has at least one place of consumption.
"""

from __future__ import annotations

import uuid
from typing import Any

import voluptuous as vol
from aioengieromania import EngieAuthError, EngieClient, EngieConnectionError, EngieError
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import CONF_DEVICE_ID, DOMAIN
from .coordinator import EngieConfigEntry
from .crypto import EngieCipher

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
        }
    )


async def _validate(hass: HomeAssistant, username: str, password: str, device_id: str) -> int:
    """Log in and return the number of places of consumption found."""
    client = EngieClient(username, password, device_id, async_get_clientsession(hass))
    await client.async_login()
    return len(await client.async_get_places())


def _error_key(err: EngieError) -> str:
    if isinstance(err, EngieAuthError):
        return "invalid_auth"
    if isinstance(err, EngieConnectionError):
        return "cannot_connect"
    return "unknown"


class EngieConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle setup, re-authentication and reconfiguration."""

    VERSION = 1
    MINOR_VERSION = 2

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
                        title=f"ENGIE România — {username}",
                        data={
                            CONF_USERNAME: username,
                            CONF_PASSWORD: cipher.encrypt(user_input[CONF_PASSWORD]),
                            CONF_DEVICE_ID: device_id,
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
