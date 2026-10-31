"""On-disk record of which self-reading windows already had an index sent.

ENGIE accepts one self-reading per window. Remembering the window (by its end
date) per place and metered service lets the submit button refuse a second
send — a double press, or a press after a restart — instead of sending again.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY_SUBMISSIONS, STORAGE_VERSION


class EngieSubmissionStore:
    """``{poc: {division: {"window_end", "index", "at"}}}`` for one config entry."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{STORAGE_KEY_SUBMISSIONS}.{entry_id}"
        )
        self._data: dict[str, dict[str, dict[str, Any]]] = {}

    async def async_load(self) -> None:
        self._data = await self._store.async_load() or {}

    async def async_save(self) -> None:
        await self._store.async_save(self._data)

    async def async_remove(self) -> None:
        await self._store.async_remove()

    def last(self, poc: str, division: str) -> dict[str, Any] | None:
        return self._data.get(poc, {}).get(division)

    def already_submitted(self, poc: str, division: str, window_end: date | None) -> bool:
        last = self.last(poc, division)
        return bool(last and window_end and last.get("window_end") == window_end.isoformat())

    def mark_submitted(
        self, poc: str, division: str, window_end: date | None, index: int, at: str
    ) -> None:
        self._data.setdefault(poc, {})[division] = {
            "window_end": window_end.isoformat() if window_end else None,
            "index": index,
            "at": at,
        }
