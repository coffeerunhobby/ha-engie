"""Constants for the ENGIE România integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from aioengieromania import DIVISION_ELECTRICITY, DIVISION_GAS

DOMAIN: Final = "engie_romania"

MANUFACTURER: Final = "ENGIE România"
MODEL: Final = "MyENGIE - cont online"
ATTRIBUTION: Final = "Date furnizate de MyENGIE"

# ── Config keys ─────────────────────────────────────────────────────────────
# CONF_USERNAME and CONF_PASSWORD come from homeassistant.const.
# A random id generated once per config entry and sent as the app's Device-Id,
# so the account sees one stable device instead of a new one on every restart.
CONF_DEVICE_ID: Final = "device_id"
# Removed in config entry version 1.2; still read once to migrate older entries.
CONF_UPDATE_INTERVAL: Final = "update_interval"

# ENGIE bills monthly and the meter index changes at most daily.
UPDATE_INTERVAL: Final = timedelta(hours=6)

CURRENCY_RON: Final = "RON"

# ── Local storage ───────────────────────────────────────────────────────────
STORAGE_VERSION: Final = 1
# The password-encryption key lives in its own store, deliberately separate from
# the config entry holding the ciphertext, so leaking one file is not enough.
STORAGE_KEY_SECRET: Final = f"{DOMAIN}_key"
# Which self-reading windows already had an index sent, per config entry.
STORAGE_KEY_SUBMISSIONS: Final = f"{DOMAIN}_submissions"

# English names of ENGIE's division codes, used in entity keys.
DIVISION_NAMES: Final = {DIVISION_GAS: "gas", DIVISION_ELECTRICITY: "electricity"}
