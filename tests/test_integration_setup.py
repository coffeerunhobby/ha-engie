"""End-to-end setup inside a real Home Assistant, with only the HTTP client stubbed."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("homeassistant")

from homeassistant.config_entries import ConfigEntryState  # noqa: E402
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.engie_romania.const import (  # noqa: E402
    CONF_DEVICE_ID,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
)
from custom_components.engie_romania.crypto import EngieCipher, is_encrypted  # noqa: E402

from . import payloads as P  # noqa: E402
from .stub import StubApi  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_stub():
    StubApi.reset()
    yield


@pytest.fixture
async def entry(hass: HomeAssistant, enable_custom_integrations) -> MockConfigEntry:
    cipher = await EngieCipher.async_load(hass)
    return MockConfigEntry(
        domain=DOMAIN,
        title="ENGIE — user@example.com",
        unique_id="user@example.com",
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: cipher.encrypt("synthetic-password"),
            CONF_DEVICE_ID: "00000000-0000-0000-0000-000000000000",
            CONF_UPDATE_INTERVAL: 6,
        },
    )


@pytest.fixture
async def loaded(hass: HomeAssistant, entry: MockConfigEntry):
    entry.add_to_hass(hass)
    with (
        patch("custom_components.engie_romania.coordinator.EngieApiClient", StubApi),
        patch(
            "custom_components.engie_romania.coordinator.async_update_consumption_statistics",
            MagicMock(return_value=None),
        ),
        patch("custom_components.engie_romania.sensor._today", return_value=date(2026, 10, 25)),
        patch("custom_components.engie_romania.binary_sensor._today", return_value=date(2026, 10, 25)),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry
        if entry.state is ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(entry.entry_id)
            await hass.async_block_till_done()


async def test_the_integration_sets_up(loaded):
    assert loaded.state is ConfigEntryState.LOADED


async def test_every_place_gets_its_entities(hass: HomeAssistant, loaded):
    for poc in (P.POC_A, P.POC_B):
        for entity_id in (
            f"sensor.{DOMAIN}_{poc}_amount_due",
            f"sensor.{DOMAIN}_{poc}_last_invoice",
            f"sensor.{DOMAIN}_{poc}_due_date",
            f"sensor.{DOMAIN}_{poc}_due_date_timestamp",
            f"sensor.{DOMAIN}_{poc}_overdue",
            f"sensor.{DOMAIN}_{poc}_last_payment",
            f"sensor.{DOMAIN}_{poc}_meter_index_gas",
            f"sensor.{DOMAIN}_{poc}_self_reading_gas",
            f"binary_sensor.{DOMAIN}_{poc}_overdue",
            f"binary_sensor.{DOMAIN}_{poc}_self_reading_open_gas",
        ):
            assert hass.states.get(entity_id) is not None, f"{entity_id} was not created"


async def test_states_reflect_the_account(hass: HomeAssistant, loaded):
    poc = P.POC_A
    assert hass.states.get(f"sensor.{DOMAIN}_{poc}_amount_due").state == "123.45"
    assert hass.states.get(f"sensor.{DOMAIN}_{poc}_last_invoice").state == "123.45"
    assert hass.states.get(f"sensor.{DOMAIN}_{poc}_due_date").state == "2026-09-15"
    assert hass.states.get(f"sensor.{DOMAIN}_{poc}_last_payment").state == "200.0"
    gas = hass.states.get(f"sensor.{DOMAIN}_{poc}_meter_index_gas")
    assert gas.state == "1234.0"
    assert gas.attributes["unit_of_measurement"] == "m³"
    assert gas.attributes["device_class"] == "gas"


async def test_overdue_is_a_problem_binary_sensor(hass: HomeAssistant, loaded):
    state = hass.states.get(f"binary_sensor.{DOMAIN}_{P.POC_A}_overdue")
    assert state.state == "on"  # unpaid, due 2026-09-15, today 2026-10-25
    assert state.attributes["device_class"] == "problem"


async def test_self_reading_window_open_and_not_a_problem(hass: HomeAssistant, loaded):
    state = hass.states.get(f"binary_sensor.{DOMAIN}_{P.POC_A}_self_reading_open_gas")
    assert state.state == "on"  # window 20-31 Oct, today 25 Oct
    assert state.attributes.get("device_class") is None
    assert hass.states.get(f"sensor.{DOMAIN}_{P.POC_A}_self_reading_gas").state == "open"


async def test_each_place_is_its_own_device(hass: HomeAssistant, loaded):
    from homeassistant.helpers import device_registry as dr, entity_registry as er

    devices = {
        e.device_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), loaded.entry_id)
    }
    assert len(devices) == 2
    names = {dr.async_get(hass).async_get(d).name for d in devices}
    assert any("Exemplu" in n for n in names) and any("Model" in n for n in names)


async def test_the_password_stays_encrypted(loaded):
    assert is_encrypted(loaded.data[CONF_PASSWORD])


async def test_unload_is_clean(hass: HomeAssistant, loaded):
    assert await hass.config_entries.async_unload(loaded.entry_id)
    await hass.async_block_till_done()
    assert loaded.state is ConfigEntryState.NOT_LOADED
