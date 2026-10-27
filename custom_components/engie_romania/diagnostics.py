"""Diagnostics for the ENGIE România integration.

Everything that identifies the customer or the place is redacted: place and
client numbers, contract accounts, addresses, meter serials and POD codes are
personal data under GDPR. Diagnostics downloads are routinely pasted into issue
reports, so the account e-mail and password never appear either.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import CONF_DEVICE_ID
from .coordinator import EngieConfigEntry

TO_REDACT_ENTRY = {CONF_USERNAME, CONF_PASSWORD, CONF_DEVICE_ID}
TO_REDACT_DATA = {
    "poc",
    "pa",
    "address",
    "installation_number",
    "serial",
    "pod",
    "contract_account",
    "invoice_number",
}


def _plain(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {k: _plain(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: EngieConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    points = _plain(coordinator.data or {})
    return {
        "entry": {
            # The title is "ENGIE — <e-mail>", so it is personal data too.
            "title": "<redacted>",
            "data": async_redact_data(dict(entry.data), TO_REDACT_ENTRY),
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "place_count": len(points),
            # Keyed by place number, so only the redacted values are emitted.
            "places": [async_redact_data(p, TO_REDACT_DATA) for p in points.values()],
        },
    }
