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
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import EngieAuthError, EngieConnectionError, EngieError, EngieRejectedError
from .const import DIVISION_NAMES, DOMAIN
from .coordinator import EngieConfigEntry, EngieCoordinator
from .entity import EngiePlaceEntity
from .models import Meter

_LOGGER = logging.getLogger(__name__)


def _today():
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

    _attr_icon = "mdi:send-clock"

    def __init__(
        self,
        coordinator: EngieCoordinator,
        config_entry: EngieConfigEntry,
        poc: str,
        division: str,
    ) -> None:
        self._name = DIVISION_NAMES.get(division, division)
        super().__init__(coordinator, config_entry, poc, f"submit_reading_{self._name}", "button")
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

    async def _async_submit(self) -> None:
        point = self._point
        meter = self._meter
        if point is None or meter is None:
            raise HomeAssistantError("This meter is not available right now")

        value = self._staged_index()
        if not value or value <= 0:
            raise HomeAssistantError(
                f"Enter the index in '{self._name.capitalize()} reading to submit' first"
            )
        index = int(value)
        if meter.last_index is not None and index < meter.last_index:
            raise HomeAssistantError(
                f"Index {index} is below the last known index ({meter.last_index:g}); "
                "a meter cannot run backwards"
            )

        if not meter.self_read_open(_today()):
            when = (
                f" (next window: {meter.window_start.isoformat()} to {meter.window_end.isoformat()})"
                if meter.window_start and meter.window_end
                else ""
            )
            raise HomeAssistantError(f"The {self._name} self-reading window is closed{when}")

        submissions = self.coordinator.submissions
        if submissions.already_submitted(self._poc, self._division, meter.window_end):
            last = submissions.last(self._poc, self._division) or {}
            raise HomeAssistantError(
                f"Index {last.get('index')} was already sent for this window; "
                "ENGIE accepts one per window (use the MyENGIE app to correct it)"
            )

        api = self.coordinator.api
        if api is None:
            raise HomeAssistantError("The MyENGIE connection is not ready yet")
        try:
            await api.async_submit_index(
                point.poc, point.pa, meter.division, meter.installation_number, meter.serial, index
            )
        except EngieRejectedError as err:
            raise HomeAssistantError(f"ENGIE refused index {index}: {err}") from err
        except EngieAuthError as err:
            raise HomeAssistantError(
                "MyENGIE rejected the session; nothing was sent. Check the account password"
            ) from err
        except EngieConnectionError as err:
            raise HomeAssistantError(
                f"MyENGIE did not confirm the reading ({err}). It may still have arrived: "
                "check the MyENGIE app before pressing again"
            ) from err
        except EngieError as err:
            raise HomeAssistantError(f"Could not send the reading: {err}") from err

        submissions.mark_submitted(
            self._poc, self._division, meter.window_end, index, dt_util.now().isoformat()
        )
        await submissions.async_save()
        _LOGGER.info("Self-reading (%s) sent to ENGIE", self._name)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
