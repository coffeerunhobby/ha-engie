"""HTTP client for the MyENGIE România mobile-app API (gwss.engie.ro).

A form POST to ``/v1/login`` returns a bearer token that authorises every other
call; the token is renewed transparently when the gateway answers 401. Every
request carries the mobile app's device headers, which the gateway requires.

The client owns its own :class:`aiohttp.ClientSession` (built on Home Assistant's
shared connector when one is supplied) so the token and headers stay isolated
from the rest of Home Assistant. This module does transport only; turning
payloads into models is ``parser.py``'s job.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import aiohttp

from .const import (
    BALANCE_URL,
    CONSUMPTION_LOOKBACK_DAYS,
    CONSUMPTION_URL,
    DEVICE_HEADERS,
    DIVISIONS_URL,
    INDEX_URL,
    INVOICE_LOOKBACK_DAYS,
    INVOICES_URL,
    LOGIN_URL,
    PAYMENT_LOOKBACK_DAYS,
    PAYMENTS_URL,
    PLACES_URL,
    REQUEST_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


class EngieError(Exception):
    """Base ENGIE exception."""


class EngieAuthError(EngieError):
    """Credentials rejected, or the session could not be renewed."""


class EngieConnectionError(EngieError):
    """The API could not be reached or did not answer in time."""


def _window(days: int) -> dict[str, str]:
    today = date.today()
    return {"startDate": (today - timedelta(days=days)).isoformat(), "endDate": today.isoformat()}


class EngieApiClient:
    """Talks to the MyENGIE API and returns raw decoded payloads."""

    def __init__(
        self,
        username: str,
        password: str,
        device_id: str,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._username = username
        self._password = password
        self._token: str | None = None
        headers = {**DEVICE_HEADERS, "Device-Id": device_id}
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        if session is not None:
            self._session = aiohttp.ClientSession(
                connector=session.connector,
                connector_owner=False,
                timeout=timeout,
                headers=headers,
            )
        else:
            self._session = aiohttp.ClientSession(timeout=timeout, headers=headers)

    async def close(self) -> None:
        if not self._session.closed:
            await self._session.close()

    # ── Auth ────────────────────────────────────────────────────────────────
    async def async_login(self) -> str:
        """Authenticate and cache the bearer token."""
        form = {"username": self._username, "password": self._password}
        try:
            async with self._session.post(LOGIN_URL, data=form) as resp:
                if resp.status >= 500:
                    raise EngieConnectionError(f"MyENGIE login failed: HTTP {resp.status}")
                body = await self._decode(resp)
                status = resp.status
        except aiohttp.ClientError as err:
            raise EngieConnectionError(str(err)) from err
        except TimeoutError as err:
            raise EngieConnectionError("MyENGIE did not answer the login in time") from err

        data = body.get("data") if isinstance(body, dict) else None
        token = data.get("token") if isinstance(data, dict) else None
        if status in (400, 401, 403, 422) or (isinstance(body, dict) and body.get("error")):
            raise EngieAuthError("Invalid e-mail or password")
        if not token:
            raise EngieAuthError("MyENGIE login returned no token")
        self._token = str(token)
        return self._token

    @staticmethod
    async def _decode(resp: aiohttp.ClientResponse) -> Any:
        """Decode JSON; the gateway serves an HTML page during maintenance."""
        try:
            return await resp.json(content_type=None)
        except (aiohttp.ContentTypeError, ValueError):
            raise EngieConnectionError(
                f"MyENGIE returned a non-JSON response (HTTP {resp.status})"
            ) from None

    # ── Core request helper ─────────────────────────────────────────────────
    async def _request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        """Issue an authenticated request, logging in again once on 401."""
        if self._token is None:
            await self.async_login()
        for attempt in (1, 2):
            try:
                async with self._session.request(
                    method,
                    url,
                    params={k: v for k, v in (params or {}).items() if v is not None},
                    json=payload,
                    headers={"Authorization": f"Bearer {self._token}"},
                ) as resp:
                    if resp.status in (401, 403) and attempt == 1:
                        self._token = None
                        await self.async_login()
                        continue
                    if resp.status in (401, 403):
                        raise EngieAuthError("Session rejected by MyENGIE")
                    if resp.status == 404:
                        return None
                    if resp.status >= 400:
                        # The path is not named: it carries account and place numbers.
                        raise EngieError(f"MyENGIE API error: HTTP {resp.status}")
                    return await self._decode(resp)
            except aiohttp.ClientError as err:
                raise EngieConnectionError(str(err)) from err
            except TimeoutError as err:
                raise EngieConnectionError("MyENGIE did not answer in time") from err
        raise EngieAuthError("Could not authenticate with MyENGIE")

    # ── Endpoints ───────────────────────────────────────────────────────────
    async def async_get_places(self) -> Any:
        """Places of consumption on the account — the entry point for everything else."""
        return await self._request("GET", PLACES_URL)

    async def async_get_divisions(self, poc: str, pa: str) -> Any:
        return await self._request("GET", DIVISIONS_URL.format(poc=poc), {"pa": pa})

    async def async_get_index(
        self, poc: str, pa: str, division: str, installation: str, serial: str | None
    ) -> Any:
        return await self._request(
            "GET",
            INDEX_URL.format(poc=poc),
            {
                "division": division,
                "pa": pa,
                "installation_number": installation,
                "serie_contor": serial,
            },
        )

    async def async_get_consumption(self, poc: str, pa: str) -> Any:
        return await self._request(
            "GET",
            CONSUMPTION_URL.format(poc=poc),
            {**_window(CONSUMPTION_LOOKBACK_DAYS), "pa": pa},
        )

    async def async_get_invoices(self, poc: str, pa: str) -> Any:
        return await self._request(
            "GET",
            INVOICES_URL.format(poc=poc),
            {**_window(INVOICE_LOOKBACK_DAYS), "pa": pa},
        )

    async def async_get_payments(self, pa: str) -> Any:
        return await self._request(
            "GET", PAYMENTS_URL.format(pa=pa), _window(PAYMENT_LOOKBACK_DAYS)
        )

    async def async_get_balance(self, contract_accounts: list[str]) -> Any:
        return await self._request(
            "POST",
            BALANCE_URL,
            payload={"contract_account": [int(c) for c in contract_accounts]},
        )
