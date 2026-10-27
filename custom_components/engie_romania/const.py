"""Constants for the ENGIE România integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "engie_romania"

MANUFACTURER: Final = "ENGIE România"
MODEL: Final = "MyENGIE - cont online"
ATTRIBUTION: Final = "Date furnizate de MyENGIE"

# ── Config / option keys ────────────────────────────────────────────────────
# CONF_USERNAME and CONF_PASSWORD come from homeassistant.const.
CONF_UPDATE_INTERVAL: Final = "update_interval"
# A random id generated once per config entry and sent as the app's Device-Id,
# so the account sees one stable device instead of a new one on every restart.
CONF_DEVICE_ID: Final = "device_id"

# ── Defaults / bounds ───────────────────────────────────────────────────────
# ENGIE bills monthly and the meter index changes at most daily.
DEFAULT_UPDATE_INTERVAL_HOURS: Final = 6
MIN_UPDATE_INTERVAL_HOURS: Final = 1
MAX_UPDATE_INTERVAL_HOURS: Final = 24

CURRENCY_RON: Final = "RON"

# ── Local storage ───────────────────────────────────────────────────────────
STORAGE_VERSION: Final = 1
# The password-encryption key lives in its own store, deliberately separate from
# the config entry holding the ciphertext, so leaking one file is not enough.
STORAGE_KEY_SECRET: Final = f"{DOMAIN}_key"

# ── MyENGIE API ─────────────────────────────────────────────────────────────
# The mobile app's JSON gateway. A form POST to /v1/login returns a bearer token;
# every request must also carry the app's device headers or the gateway refuses it.
BASE_URL: Final = "https://gwss.engie.ro/myservices"
LOGIN_URL: Final = f"{BASE_URL}/v1/login"
PLACES_URL: Final = f"{BASE_URL}/v1/placesofconsumption"
DIVISIONS_URL: Final = f"{BASE_URL}/v1/placesofconsumption/divisions/{{poc}}"
INDEX_URL: Final = f"{BASE_URL}/v1/index/{{poc}}"
CONSUMPTION_URL: Final = f"{BASE_URL}/v1/index/consumption/{{poc}}"
INVOICES_URL: Final = f"{BASE_URL}/v1/invoices/history/{{poc}}"
PAYMENTS_URL: Final = f"{BASE_URL}/v1/invoices/payment/history/{{pa}}"
# "ballance" is ENGIE's own spelling in the endpoint path.
BALANCE_URL: Final = f"{BASE_URL}/v1/invoices/ballance-details"

# The server rejects invoice-history windows longer than twelve months.
INVOICE_LOOKBACK_DAYS: Final = 364
PAYMENT_LOOKBACK_DAYS: Final = 730
CONSUMPTION_LOOKBACK_DAYS: Final = 1095

REQUEST_TIMEOUT: Final = 30

APP_VERSION: Final = "2.1.11"
APP_BUILD: Final = "177"
DEVICE_HEADERS: Final = {
    "source": "android",
    "App-Version": APP_VERSION,
    "App-Build": APP_BUILD,
    "OS-Version": "14",
    "OS-Platform": "android",
    "Device-Type": "phone",
    "Device-Manufacturer": "Google",
    "Device-Model": "Pixel 8",
    "Screen-Height": "2400",
    "Screen-Width": "1080",
    "User-Agent": f"MyEngie/{APP_VERSION} (Android; ro.engie.agentia; build {APP_BUILD})",
    "Accept": "application/json",
}

# ENGIE's division codes, and the English names used in entity keys.
DIVISION_GAS: Final = "gaz"
DIVISION_ELECTRICITY: Final = "elec"
DIVISION_NAMES: Final = {DIVISION_GAS: "gas", DIVISION_ELECTRICITY: "electricity"}
