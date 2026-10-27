"""A stand-in for the HTTP client: everything downstream of it is the real code."""

from __future__ import annotations

from custom_components.engie_romania.api import EngieAuthError, EngieConnectionError

from . import payloads as P

INSTALLATIONS = {P.POC_A: 555, P.POC_B: 666}
ACCOUNTS = {P.POC_A: P.ACCOUNT_A, P.POC_B: P.ACCOUNT_B}


class StubApi:
    """Controls: ``failing_poc`` times out one place; ``reject_login`` refuses the password."""

    failing_poc: str | None = None
    reject_login = False
    everything_down = False

    def __init__(self, *args, **kwargs) -> None:
        pass

    @classmethod
    def reset(cls) -> None:
        cls.failing_poc = None
        cls.reject_login = False
        cls.everything_down = False

    def _check(self, poc: str | None = None) -> None:
        if StubApi.everything_down or (poc is not None and poc == StubApi.failing_poc):
            raise EngieConnectionError("MyENGIE did not answer in time")

    async def async_login(self):
        if StubApi.reject_login:
            raise EngieAuthError("Invalid e-mail or password")
        return "synthetic-token"

    async def async_get_places(self):
        self._check()
        return P.PLACES

    async def async_get_divisions(self, poc, pa):
        self._check(poc)
        return P.divisions(poc, ACCOUNTS[poc], INSTALLATIONS[poc])

    async def async_get_index(self, poc, pa, division, installation, serial):
        self._check(poc)
        return P.index(poc, int(installation))

    async def async_get_consumption(self, poc, pa):
        self._check(poc)
        return P.CONSUMPTION

    async def async_get_invoices(self, poc, pa):
        self._check(poc)
        return P.invoices(poc, ACCOUNTS[poc])

    async def async_get_payments(self, pa):
        return P.PAYMENTS

    async def async_get_balance(self, accounts):
        return P.BALANCE

    async def close(self):
        return None
