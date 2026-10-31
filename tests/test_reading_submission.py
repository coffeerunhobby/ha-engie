"""Self-reading submission: the staged number and the submit button.

All values are SYNTHETIC; only the HTTP client is stubbed. The stub's window is
20-31 Oct 2026 and the fixture's today is 25 Oct, so the window is open.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

pytest.importorskip("homeassistant")

from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.exceptions import HomeAssistantError  # noqa: E402

from custom_components.engie_romania.const import DOMAIN  # noqa: E402

from . import payloads as P  # noqa: E402
from .stub import StubApi  # noqa: E402
from .test_integration_setup import _reset_stub, entry, loaded  # noqa: E402,F401

NUMBER = f"number.{DOMAIN}_{P.POC_A}_gas_reading_to_submit"
BUTTON = f"button.{DOMAIN}_{P.POC_A}_submit_gas_reading"


async def _stage_and_press(hass: HomeAssistant, value: float) -> None:
    await hass.services.async_call(
        "number", "set_value", {"entity_id": NUMBER, "value": value}, blocking=True
    )
    await hass.services.async_call("button", "press", {"entity_id": BUTTON}, blocking=True)


async def test_the_number_starts_at_the_last_index(hass: HomeAssistant, loaded):
    state = hass.states.get(NUMBER)
    assert state.state == "1234.0"
    assert state.attributes["unit_of_measurement"] == "m³"
    assert hass.states.get(BUTTON).attributes["will_submit_to_engie"] is True


async def test_a_press_in_the_window_sends_once(hass: HomeAssistant, loaded):
    await _stage_and_press(hass, 1300)
    assert [(s[2], s[3], s[5]) for s in StubApi.submitted] == [("gaz", "555", 1300)]

    attrs = hass.states.get(BUTTON).attributes
    assert attrs["already_submitted_this_window"] is True
    assert attrs["will_submit_to_engie"] is False
    with pytest.raises(HomeAssistantError, match="already sent"):
        await _stage_and_press(hass, 1310)
    assert len(StubApi.submitted) == 1


async def test_the_record_survives_a_restart(hass: HomeAssistant, loaded):
    await _stage_and_press(hass, 1300)
    assert await hass.config_entries.async_reload(loaded.entry_id)
    await hass.async_block_till_done()
    with pytest.raises(HomeAssistantError, match="already sent"):
        await _stage_and_press(hass, 1310)
    assert len(StubApi.submitted) == 1


async def test_an_index_below_the_last_one_is_refused(hass: HomeAssistant, loaded):
    with pytest.raises(HomeAssistantError, match="below the last known index"):
        await _stage_and_press(hass, 1200)
    assert StubApi.submitted == []


async def test_nothing_is_sent_outside_the_window(hass: HomeAssistant, loaded):
    with (
        patch("custom_components.engie_romania.button._today", return_value=date(2026, 11, 5)),
        pytest.raises(HomeAssistantError, match="window is closed"),
    ):
        await _stage_and_press(hass, 1300)
    assert StubApi.submitted == []


async def test_a_refusal_shows_engies_reason_and_allows_a_retry(hass: HomeAssistant, loaded):
    StubApi.reject_index = "Index prea mare"
    with pytest.raises(HomeAssistantError, match="Index prea mare"):
        await _stage_and_press(hass, 9999)
    assert hass.states.get(BUTTON).attributes["already_submitted_this_window"] is False

    StubApi.reject_index = None
    await _stage_and_press(hass, 1300)
    assert len(StubApi.submitted) == 1
