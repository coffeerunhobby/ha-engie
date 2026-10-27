"""Diagnostics must never disclose credentials or anything identifying a place."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("homeassistant")

from homeassistant.core import HomeAssistant  # noqa: E402

from custom_components.engie_romania.diagnostics import (  # noqa: E402
    async_get_config_entry_diagnostics,
)

from . import payloads as P  # noqa: E402
from .test_integration_setup import _reset_stub, entry, loaded  # noqa: E402,F401


async def test_nothing_personal_survives(hass: HomeAssistant, loaded):
    rendered = json.dumps(await async_get_config_entry_diagnostics(hass, loaded))
    for secret in (
        "user@example.com",
        "synthetic-password",
        P.PA,
        P.POC_A,
        P.POC_B,
        str(P.ACCOUNT_A),
        "SYNTH0000000000001",
        "SYNTHPOD00000001",
        "Exemplu",
        "00000000-0000-0000-0000-000000000000",
    ):
        assert secret not in rendered, f"{secret!r} leaked into diagnostics"


async def test_still_useful(hass: HomeAssistant, loaded):
    diag = await async_get_config_entry_diagnostics(hass, loaded)
    assert diag["coordinator"]["place_count"] == 2
    assert diag["coordinator"]["places"][0]["balance"] == 123.45
