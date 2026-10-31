"""A stand-in for the MyENGIE client: everything downstream of it is the real code.

It answers with the library's own parsers applied to synthetic payloads, so the
models the integration sees are exactly what the real client would build.
"""

from __future__ import annotations

from aioengieromania import (
    EngieAuthError,
    EngieConnectionError,
    EngieRejectedError,
    Meter,
    PointData,
)
from aioengieromania.parser import (
    apply_index,
    parse_balance,
    parse_consumption,
    parse_divisions,
    parse_invoices,
    parse_payments,
    parse_places,
)

from . import payloads as P

INSTALLATIONS = {P.POC_A: 555, P.POC_B: 666}
ACCOUNTS = {P.POC_A: P.ACCOUNT_A, P.POC_B: P.ACCOUNT_B}


class StubApi:
    """Controls: ``failing_poc`` times out one place (or a set of them);
    ``reject_login`` refuses the password; ``login_error`` raises any error at
    login; ``no_places`` empties the account; ``electricity_poc`` adds an
    electricity meter to one place; ``submit_error`` fails a submission.
    """

    failing_poc: str | set[str] | None = None
    reject_login = False
    login_error: Exception | None = None
    no_places = False
    everything_down = False
    electricity_poc: str | None = None
    submit_error: Exception | None = None
    # Self-readings sent, as (poc, pa, division, installation, serial, index).
    submitted: list[tuple] = []
    reject_index: str | None = None

    def __init__(self, *args, **kwargs) -> None:
        pass

    @classmethod
    def reset(cls) -> None:
        cls.failing_poc = None
        cls.reject_login = False
        cls.login_error = None
        cls.no_places = False
        cls.everything_down = False
        cls.electricity_poc = None
        cls.submit_error = None
        cls.submitted = []
        cls.reject_index = None

    def _check(self, poc: str | None = None) -> None:
        failing = StubApi.failing_poc
        if StubApi.everything_down or (
            poc is not None and (poc == failing or (isinstance(failing, set) and poc in failing))
        ):
            raise EngieConnectionError("MyENGIE did not answer in time")

    async def async_login(self):
        if StubApi.reject_login:
            raise EngieAuthError("Invalid e-mail or password")
        if StubApi.login_error:
            raise StubApi.login_error

    async def async_get_places(self):
        self._check()
        return [] if StubApi.no_places else parse_places(P.PLACES)

    async def async_get_point(self, place):
        self._check(place.poc)
        point = PointData(poc=place.poc, pa=place.pa, address=place.address)
        point.meters = parse_divisions(
            P.divisions(place.poc, ACCOUNTS[place.poc], INSTALLATIONS[place.poc])
        )
        apply_index(point.meters, P.index(place.poc, INSTALLATIONS[place.poc]))
        if place.poc == StubApi.electricity_poc:
            point.meters.append(Meter(division="elec", installation_number="777", last_index=4321.0))
        point.consumption = {m.division: parse_consumption(P.CONSUMPTION, m.division) for m in point.meters}
        point.invoices = parse_invoices(P.invoices(place.poc, ACCOUNTS[place.poc]))
        point.balance, point.balance_by_division = parse_balance(P.BALANCE)
        return point

    async def async_get_payments(self, pa):
        return parse_payments(P.PAYMENTS)

    async def async_submit_index(self, point, meter, index):
        self._check(point.poc)
        if StubApi.submit_error:
            raise StubApi.submit_error
        if StubApi.reject_index:
            raise EngieRejectedError(StubApi.reject_index)
        StubApi.submitted.append(
            (point.poc, point.pa, meter.division, meter.installation_number, meter.serial, index)
        )
