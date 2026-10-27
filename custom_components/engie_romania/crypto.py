"""At-rest encryption for the stored ENGIE password.

The integration has to log in again on its own whenever the MyENGIE token
expires, so it keeps the password — but only encrypted. There is deliberately no
plaintext code path: `cryptography` is a hard requirement of Home Assistant core,
and a password that cannot be encrypted is not stored.

## What this does and does not protect against

Home Assistant keeps config-entry data as plaintext JSON in
`.storage/core.config_entries`, and the integration must replay the password
unattended — so the key has to live on the same machine. Anyone with full
filesystem access can still recover it. **This is not a substitute for disk
encryption.** What it does buy: the key is kept in a separate store
(`.storage/engie_romania_key`), so leaking `core.config_entries` alone — a pasted
file, a single-file backup, a diagnostics dump — no longer reveals a reusable
password.

Uses Fernet (AES-128-CBC + HMAC-SHA256) from `cryptography`, which Home Assistant
core already requires, so this adds no dependency.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_KEY_SECRET, STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)

# Marks a value as produced by this module, so a plaintext value stored by an
# older version is still recognised and can be migrated in place.
PREFIX = "enc:v1:"


class EngieCipher:
    """Encrypts/decrypts stored credentials using a locally stored key."""

    def __init__(self, key: bytes) -> None:
        from cryptography.fernet import Fernet

        self._fernet = Fernet(key)

    @staticmethod
    def _generate_key() -> str:
        from cryptography.fernet import Fernet

        return Fernet.generate_key().decode()

    @classmethod
    async def async_load(cls, hass: HomeAssistant) -> EngieCipher:
        """Load the key from its own store, creating one on first use.

        One key serves every Digi entry on the instance. There is deliberately
        no plaintext fallback: `cryptography` is a hard requirement of Home
        Assistant core, and a session that cannot be encrypted is not stored.
        """
        store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_SECRET, private=True
        )
        data = await store.async_load() or {}
        key = data.get("key")
        if not key:
            key = cls._generate_key()
            await store.async_save({"key": key})
            _LOGGER.debug("Generated a new %s encryption key", DOMAIN)
        return cls(key.encode())

    def encrypt(self, value: str) -> str:
        """Return ``value`` encrypted and tagged, ready to persist."""
        return PREFIX + self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        """Return the plaintext for a stored value.

        Raises :class:`ValueError` when the value was not written by
        :meth:`encrypt` or cannot be decrypted — typically a backup restored
        without its key file — so the caller can ask the user to sign in again.
        """
        if not is_encrypted(value):
            raise ValueError("The stored ENGIE password is not encrypted")
        from cryptography.fernet import InvalidToken

        try:
            return self._fernet.decrypt(value[len(PREFIX) :].encode()).decode()
        except (InvalidToken, ValueError) as err:
            raise ValueError(
                "The stored ENGIE password could not be decrypted: the encryption "
                "key is missing or does not match. Re-authenticate to store it again."
            ) from err


def is_encrypted(value: Any) -> bool:
    """True when ``value`` was written by this module."""
    return isinstance(value, str) and value.startswith(PREFIX)
