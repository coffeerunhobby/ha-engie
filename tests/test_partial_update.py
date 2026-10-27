"""One place failing must not take the whole account down."""

from __future__ import annotations

import pytest

pytest.importorskip("homeassistant")

from homeassistant.core import HomeAssistant  # noqa: E402

from custom_components.engie_romania.const import DOMAIN  # noqa: E402

from . import payloads as P  # noqa: E402
from .stub import StubApi  # noqa: E402
from .test_integration_setup import _reset_stub, entry, loaded  # noqa: E402,F401


async def test_a_failing_place_keeps_its_last_data(hass: HomeAssistant, loaded):
    coordinator = loaded.runtime_data
    before = coordinator.data[P.POC_B]
    StubApi.failing_poc = P.POC_B

    await coordinator.async_refresh()

    assert coordinator.last_update_success
    assert coordinator.data[P.POC_B] is before
    assert coordinator.data[P.POC_A] is not before
    state = hass.states.get(f"sensor.{DOMAIN}_{P.POC_B}_amount_due")
    assert state.state != "unavailable"


async def test_the_update_fails_only_when_nothing_refreshed(loaded):
    coordinator = loaded.runtime_data
    StubApi.everything_down = True

    await coordinator.async_refresh()

    assert not coordinator.last_update_success
