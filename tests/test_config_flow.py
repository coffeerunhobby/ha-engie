"""Config flow: setup, re-authentication and Reconfigure, HTTP client stubbed."""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("homeassistant")

from homeassistant import config_entries  # noqa: E402
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.data_entry_flow import FlowResultType  # noqa: E402

from custom_components.engie_romania.const import CONF_DEVICE_ID, DOMAIN  # noqa: E402
from custom_components.engie_romania.crypto import EngieCipher, is_encrypted  # noqa: E402

from .stub import StubApi  # noqa: E402
from .test_integration_setup import _reset_stub, entry  # noqa: E402,F401

FLOW_API = "custom_components.engie_romania.config_flow.EngieApiClient"
SETUP = "custom_components.engie_romania.async_setup_entry"


async def test_setup_creates_an_entry_with_an_encrypted_password(
    hass: HomeAssistant, enable_custom_integrations
):
    with patch(FLOW_API, StubApi), patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"}
        )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    data = result["data"]
    assert data[CONF_PASSWORD] != "secret" and is_encrypted(data[CONF_PASSWORD])
    assert (await EngieCipher.async_load(hass)).decrypt(data[CONF_PASSWORD]) == "secret"
    assert data[CONF_DEVICE_ID]


async def test_setup_rejects_bad_credentials(hass: HomeAssistant, enable_custom_integrations):
    StubApi.reject_login = True
    with patch(FLOW_API, StubApi):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "wrong"}
        )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_reconfigure_replaces_the_password_in_place(hass: HomeAssistant, entry):
    entry.add_to_hass(hass)
    device_id = entry.data[CONF_DEVICE_ID]
    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    with patch(FLOW_API, StubApi), patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "rotated"}
        )
    assert result["reason"] == "reconfigure_successful"
    assert (await EngieCipher.async_load(hass)).decrypt(entry.data[CONF_PASSWORD]) == "rotated"
    assert entry.data[CONF_DEVICE_ID] == device_id


async def test_reauth_redisplays_its_form_on_a_bad_password(hass: HomeAssistant, entry):
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    StubApi.reject_login = True
    with patch(FLOW_API, StubApi):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "wrong"}
        )
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "invalid_auth"}
