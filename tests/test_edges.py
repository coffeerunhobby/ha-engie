"""Failure paths and less common shapes: everything a user can hit but rarely does.

All values are SYNTHETIC; only the HTTP client is stubbed.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("homeassistant")

from aioengieromania import (  # noqa: E402
    EngieAuthError,
    EngieConnectionError,
    EngieError,
    MonthlyConsumption,
)
from homeassistant import config_entries  # noqa: E402
from homeassistant.config_entries import ConfigEntryState  # noqa: E402
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.exceptions import HomeAssistantError  # noqa: E402
from homeassistant.util import dt as dt_util  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.engie_romania import binary_sensor, button, sensor  # noqa: E402
from custom_components.engie_romania.const import DOMAIN  # noqa: E402
from custom_components.engie_romania.crypto import EngieCipher  # noqa: E402
from custom_components.engie_romania.statistics import (  # noqa: E402
    async_update_consumption_statistics,
)

from . import payloads as P  # noqa: E402
from .stub import StubApi  # noqa: E402
from .test_integration_setup import _reset_stub, entry, loaded  # noqa: E402,F401

BUTTON = f"button.{DOMAIN}_{P.POC_A}_submit_gas_reading"
FLOW_API = "custom_components.engie_romania.config_flow.EngieClient"
SETUP = "custom_components.engie_romania.async_setup_entry"


def _entity(hass: HomeAssistant, entity_id: str):
    domain = entity_id.split(".")[0]
    return hass.data["entity_components"][domain].get_entity(entity_id)


def test_today_is_the_local_date():
    today = dt_util.now().date()
    assert sensor._today() == binary_sensor._today() == button._today() == today


# ── Coordinator ─────────────────────────────────────────────────────────────


async def test_a_new_electricity_meter_appears_without_a_reload(
    hass: HomeAssistant, loaded
):
    StubApi.electricity_poc = P.POC_B
    await loaded.runtime_data.async_refresh()
    await hass.async_block_till_done()
    index = hass.states.get(f"sensor.{DOMAIN}_{P.POC_B}_electricity_meter_index")
    assert index.state == "4321.0"
    assert index.attributes["unit_of_measurement"] == "kWh"
    assert (
        hass.states.get(f"button.{DOMAIN}_{P.POC_B}_submit_electricity_reading")
        is not None
    )


async def test_a_place_that_recovers_is_published_again(
    hass: HomeAssistant, loaded, caplog
):
    coordinator = loaded.runtime_data
    StubApi.failing_poc = P.POC_B
    await coordinator.async_refresh()
    await coordinator.async_refresh()
    assert caplog.text.count("was not refreshed") == 1

    StubApi.failing_poc = None
    before = coordinator.data[P.POC_B]
    await coordinator.async_refresh()
    assert coordinator.data[P.POC_B] is not before
    assert "refreshes again" in caplog.text


async def test_every_place_failing_fails_the_update(loaded):
    StubApi.failing_poc = {P.POC_A, P.POC_B}
    await loaded.runtime_data.async_refresh()
    assert not loaded.runtime_data.last_update_success


@pytest.mark.parametrize("where", ["places", "place"])
async def test_a_rejected_session_starts_reauthentication(
    hass: HomeAssistant, loaded, where
):
    api = loaded.runtime_data.api
    method = "async_get_places" if where == "places" else "async_get_point"
    with patch.object(api, method, side_effect=EngieAuthError("rejected")):
        await loaded.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert any(
        f["context"]["source"] == "reauth"
        for f in hass.config_entries.flow.async_progress()
    )


async def test_an_account_without_places_fails_the_update(loaded):
    StubApi.no_places = True
    await loaded.runtime_data.async_refresh()
    assert not loaded.runtime_data.last_update_success


async def test_an_undecryptable_password_asks_to_sign_in_again(
    hass: HomeAssistant, entry
):
    entry.add_to_hass(hass)
    other_key = EngieCipher(EngieCipher._generate_key().encode())
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_PASSWORD: other_key.encrypt("x")}
    )
    with patch("custom_components.engie_romania.coordinator.EngieClient", StubApi):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert any(
        f["context"]["source"] == "reauth"
        for f in hass.config_entries.flow.async_progress()
    )


def test_an_untagged_password_is_refused():
    with pytest.raises(ValueError, match="not encrypted"):
        EngieCipher(EngieCipher._generate_key().encode()).decrypt("plain")


# ── Entry lifecycle ─────────────────────────────────────────────────────────


async def test_an_entry_from_a_newer_version_is_not_loaded(
    hass: HomeAssistant, enable_custom_integrations
):
    entry = MockConfigEntry(domain=DOMAIN, version=2, data={})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.MIGRATION_ERROR


async def test_removing_the_entry_forgets_its_submissions(hass: HomeAssistant, loaded):
    with patch("custom_components.engie_romania.store.Store.async_remove") as remove:
        await hass.config_entries.async_remove(loaded.entry_id)
        await hass.async_block_till_done()
    remove.assert_called_once()


# ── Config flow ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("error", "control", "key"),
    [
        (EngieConnectionError("down"), "login_error", "cannot_connect"),
        (EngieError("odd"), "login_error", "unknown"),
        (None, "no_places", "no_places"),
    ],
)
async def test_setup_errors_are_shown_on_the_form(
    hass: HomeAssistant, enable_custom_integrations, error, control, key
):
    setattr(StubApi, control, error if error is not None else True)
    with patch(FLOW_API, StubApi), patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"},
        )
    assert result["errors"] == {"base": key}


# ── Entities ────────────────────────────────────────────────────────────────


async def test_nothing_due_leaves_the_due_dates_empty(hass: HomeAssistant, loaded):
    coordinator = loaded.runtime_data
    coordinator.data[P.POC_A].invoices = []
    coordinator.async_update_listeners()
    await hass.async_block_till_done()
    assert (
        hass.states.get(f"sensor.{DOMAIN}_{P.POC_A}_due_date_relative").state
        == "unknown"
    )


async def test_a_place_without_its_meter_reports_nothing(hass: HomeAssistant, loaded):
    coordinator = loaded.runtime_data
    coordinator.data[P.POC_A].meters = []
    for entity_id in (
        f"sensor.{DOMAIN}_{P.POC_A}_gas_self_reading_window",
        f"button.{DOMAIN}_{P.POC_A}_submit_gas_reading",
    ):
        entity = _entity(hass, entity_id)
        assert entity.extra_state_attributes is None
    assert (
        _entity(hass, f"sensor.{DOMAIN}_{P.POC_A}_gas_self_reading_window").native_value
        is None
    )
    with pytest.raises(HomeAssistantError, match="not available"):
        await _entity(hass, BUTTON).async_press()
    del coordinator.data[P.POC_A]
    assert (
        _entity(
            hass, f"binary_sensor.{DOMAIN}_{P.POC_A}_overdue"
        ).extra_state_attributes
        is None
    )


# ── Submit button ───────────────────────────────────────────────────────────


async def test_an_empty_staged_index_is_refused(hass: HomeAssistant, loaded):
    hass.states.async_set(f"number.{DOMAIN}_{P.POC_A}_gas_reading_to_submit", "unknown")
    with pytest.raises(HomeAssistantError, match="reading to submit"):
        await _entity(hass, BUTTON).async_press()


async def test_a_window_without_dates_counts_as_closed(hass: HomeAssistant, loaded):
    meter = loaded.runtime_data.data[P.POC_A].meters[0]
    meter.window_start = meter.window_end = None
    with pytest.raises(HomeAssistantError, match="window is closed"):
        await _entity(hass, BUTTON).async_press()


async def test_a_press_before_the_first_connection_is_refused(
    hass: HomeAssistant, loaded
):
    loaded.runtime_data.api = None
    with pytest.raises(HomeAssistantError, match="not ready"):
        await _entity(hass, BUTTON).async_press()


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (EngieAuthError("x"), "rejected the session"),
        (EngieConnectionError("timed out"), "may still have arrived"),
        (EngieError("HTTP 500"), "Could not send"),
    ],
)
async def test_failed_sends_say_what_happened(
    hass: HomeAssistant, loaded, error, message
):
    StubApi.submit_error = error
    with pytest.raises(HomeAssistantError, match=message):
        await _entity(hass, BUTTON).async_press()
    assert loaded.runtime_data.submissions.last(P.POC_A, "gaz") is None


# ── Statistics ──────────────────────────────────────────────────────────────


def test_statistics_are_imported_with_running_totals(hass: HomeAssistant):
    months = [
        MonthlyConsumption(date(2026, 7, 1), 150.0),
        MonthlyConsumption(date(2026, 8, 1), -20.0),
    ]
    with patch(
        "custom_components.engie_romania.statistics.async_add_external_statistics"
    ) as add:
        async_update_consumption_statistics(hass, "p1", "gaz", "Acasa", months)
        async_update_consumption_statistics(hass, "p1", "gaz", "Acasa", [])
    add.assert_called_once()
    metadata, rows = add.call_args.args[1], add.call_args.args[2]
    assert metadata["statistic_id"] == f"{DOMAIN}:gas_p1"
    assert metadata["has_sum"] is True
    assert [r["sum"] for r in rows] == [150.0, 130.0]


def test_a_recorder_failure_does_not_break_the_update(hass: HomeAssistant):
    months = [MonthlyConsumption(date(2026, 7, 1), 150.0)]
    with patch(
        "custom_components.engie_romania.statistics.async_add_external_statistics",
        MagicMock(side_effect=RuntimeError("recorder down")),
    ):
        async_update_consumption_statistics(hass, "p1", "gaz", "Acasa", months)
