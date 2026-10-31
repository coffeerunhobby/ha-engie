"""Button platform: send the staged meter index to ENGIE as a self-reading.

One per metered service at a place. The value comes from the matching
"reading to submit" number entity. ENGIE accepts a self-reading only inside its
window and once per window, so a press is refused — with the reason, and
without calling ENGIE — when:

* the window is closed,
* an index was already sent from Home Assistant for this window, or
* the value is missing or below the last known index (a meter cannot run
  backwards, and a typo here becomes a wrong bill).

Nothing is ever sent automatically; only a press sends.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any

from aioengieromania import (
    EngieAuthError,
    EngieConnectionError,
    EngieError,
    EngieRejectedError,
    Meter,
)
from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DIVISION_NAMES, DOMAIN
from .coordinator import EngieConfigEntry, EngieCoordinator
from .entity import EngiePlaceEntity

_LOGGER = logging.getLogger(__name__)

# One submission at a time, across every meter of the account.
PARALLEL_UPDATES = 1


def _today() -> date:
    return dt_util.now().date()


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: EngieConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = config_entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        entities: list[EngieSubmitReadingButton] = []
        for poc, point in (coordinator.data or {}).items():
            for meter in point.meters:
                tag = f"{poc}:{meter.division}"
                if tag not in known:
                    known.add(tag)
                    entities.append(
                        EngieSubmitReadingButton(coordinator, config_entry, poc, meter.division)
                    )
        if entities:
            async_add_entities(entities)

    _add_new()
    config_entry.async_on_unload(coordinator.async_add_listener(_add_new))


class EngieSubmitReadingButton(EngiePlaceEntity, ButtonEntity):
    """Sends the staged index to ENGIE when the self-reading window allows it."""

    def __init__(
        self,
        coordinator: EngieCoordinator,
        config_entry: EngieConfigEntry,
        poc: str,
        division: str,
    ) -> None:
        self._name = DIVISION_NAMES.get(division, division)
        super().__init__(coordinator, config_entry, poc, f"submit_reading_{self._name}")
        self._division = division
        self._attr_translation_key = f"submit_reading_{self._name}"
        # Two quick presses must not both get past the once-per-window check.
        self._lock = asyncio.Lock()

    @property
    def _meter(self) -> Meter | None:
        point = self._point
        return point.meter(self._division) if point else None

    @property
    def available(self) -> bool:
        # Available outside the window too, so a press explains why it was refused.
        return super().available and self._meter is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """What the next press will do."""
        meter = self._meter
        if meter is None:
            return None
        submissions = self.coordinator.submissions
        window_open = meter.self_read_open(_today())
        submitted = submissions.already_submitted(self._poc, self._division, meter.window_end)
        last = submissions.last(self._poc, self._division) or {}
        return {
            "will_submit_to_engie": window_open and not submitted,
            "window_open": window_open,
            "window_start": meter.window_start.isoformat() if meter.window_start else None,
            "window_end": meter.window_end.isoformat() if meter.window_end else None,
            "already_submitted_this_window": submitted,
            "last_submitted_index": last.get("index"),
            "last_submitted_at": last.get("at"),
        }

    def _staged_index(self) -> float | None:
        # Resolved by unique id, so renaming the number entity does not break this.
        number_id = er.async_get(self.hass).async_get_entity_id(
            "number", DOMAIN, f"{self._device_id}_reading_to_submit_{self._name}"
        )
        state = self.hass.states.get(number_id) if number_id else None
        try:
            return float(state.state) if state else None
        except (TypeError, ValueError):
            return None

    async def async_press(self) -> None:
        async with self._lock:
            await self._async_submit()

    def _error(self, key: str, **placeholders: str) -> HomeAssistantError:
        return HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key=key,
            translation_placeholders={"service": self._name, **placeholders},
        )

    async def _async_submit(self) -> None:
        point = self._point
        meter = self._meter
        if point is None or meter is None:
            raise self._error("meter_unavailable")

        value = self._staged_index()
        if not value or value <= 0:
            raise self._error("index_missing")
        index = int(value)
        if meter.last_index is not None and index < meter.last_index:
            raise self._error("index_below_last", index=str(index), last=f"{meter.last_index:g}")

        if not meter.self_read_open(_today()):
            if meter.window_start and meter.window_end:
                raise self._error(
                    "window_closed_until",
                    start=meter.window_start.isoformat(),
                    end=meter.window_end.isoformat(),
                )
            raise self._error("window_closed")

        submissions = self.coordinator.submissions
        if submissions.already_submitted(self._poc, self._division, meter.window_end):
            last = submissions.last(self._poc, self._division) or {}
            raise self._error("already_submitted", index=str(last.get("index")))

        api = self.coordinator.api
        if api is None:
            raise self._error("not_ready")
        try:
            await api.async_submit_index(point, meter, index)
        except EngieRejectedError as err:
            raise self._error("rejected", index=str(index), reason=str(err)) from err
        except EngieAuthError as err:
            raise self._error("auth_failed") from err
        except EngieConnectionError as err:
            raise self._error("not_confirmed", error=str(err)) from err
        except EngieError as err:
            raise self._error("send_failed", error=str(err)) from err

        submissions.mark_submitted(
            self._poc, self._division, meter.window_end, index, dt_util.now().isoformat()
        )
        await submissions.async_save()
        _LOGGER.info("Self-reading (%s) sent to ENGIE", self._name)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
