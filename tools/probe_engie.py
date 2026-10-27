"""Development probe for the MyENGIE România API.

Logs in with the accounts configured in ``~/.config/ha-engie/*.env`` (written by
the Vaultwarden broker, never committed) and walks the read-only endpoints.

It prints the *shape* of every response - keys, types, list lengths - and masks
every scalar, so its output is safe to paste into an issue or a chat. Pass
``--save`` to keep the raw JSON under ``tools/captures/`` (gitignored) for
writing parser fixtures; captures hold personal data and must never be committed.

    python tools/probe_engie.py            # every account
    python tools/probe_engie.py tower      # one account
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import sys
import uuid
from datetime import date, timedelta
from typing import Any

import aiohttp

API = "https://gwss.engie.ro/myservices"
CRED_DIR = pathlib.Path.home() / ".config" / "ha-engie"
CAPTURES = pathlib.Path(__file__).parent / "captures"

# The gateway rejects requests without the mobile app's device headers.
DEVICE_HEADERS = {
    "source": "android",
    "App-Version": "2.1.11",
    "App-Build": "177",
    "OS-Version": "14",
    "OS-Platform": "android",
    "Device-Type": "phone",
    "Device-Manufacturer": "Google",
    "Device-Model": "Pixel 8",
    "Screen-Height": "2400",
    "Screen-Width": "1080",
    "User-Agent": "MyEngie/2.1.11 (Android; ro.engie.agentia; build 177)",
}


def load_accounts() -> dict[str, dict[str, str]]:
    env: dict[str, str] = {}
    for f in sorted(CRED_DIR.glob("*.env")):
        for line in f.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep:
                env[key.strip()] = value.strip()
    accounts: dict[str, dict[str, str]] = {}
    for key, value in env.items():
        parts = key.split("_")  # ENGIE_<NAME>_<USERNAME|PASSWORD>
        if len(parts) == 3 and parts[0] == "ENGIE":
            accounts.setdefault(parts[1].lower(), {})[parts[2].lower()] = value
    return accounts


def shape(node: Any, depth: int = 0, max_depth: int = 6) -> Any:
    """Keys and types only; every scalar is masked."""
    if depth > max_depth:
        return "…"
    if isinstance(node, dict):
        # Some responses key entries by identifiers (place number + meter serial),
        # so a key containing digits is masked like a value.
        return {
            (f"<key str[{len(k)}]>" if any(c.isdigit() for c in str(k)) else k): shape(v, depth + 1, max_depth)
            for k, v in node.items()
        }
    if isinstance(node, list):
        if not node:
            return []
        return [f"{len(node)} item(s), first:", shape(node[0], depth + 1, max_depth)]
    if node is None:
        return None
    if isinstance(node, bool):
        return "bool"
    if isinstance(node, (int, float)):
        return type(node).__name__
    text = str(node)
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return "date-string"
    return f"str[{len(text)}]"


class Probe:
    def __init__(self, session: aiohttp.ClientSession, name: str, save: bool) -> None:
        self.session = session
        self.name = name
        self.save = save
        self.token: str | None = None
        self.headers = {**DEVICE_HEADERS, "Device-Id": str(uuid.uuid4()), "Accept": "application/json"}

    def report(self, label: str, status: int, body: Any) -> None:
        print(f"\n--- {self.name}: {label} -> HTTP {status}")
        print(json.dumps(shape(body), indent=1, ensure_ascii=False)[:3000])
        if self.save and body is not None:
            CAPTURES.mkdir(exist_ok=True)
            safe = label.replace("/", "_").replace(" ", "_")
            (CAPTURES / f"{self.name}-{safe}.json").write_text(
                json.dumps(body, indent=1, ensure_ascii=False), encoding="utf-8"
            )

    async def login(self, username: str, password: str) -> bool:
        async with self.session.post(
            f"{API}/v1/login",
            data={"username": username, "password": password},
            headers=self.headers,
        ) as resp:
            body = await resp.json(content_type=None)
        payload = (body or {}).get("data") or {}
        self.token = payload.get("token")
        self.report("login", resp.status, {k: v for k, v in payload.items() if "token" not in k} | {"token_present": bool(self.token)})
        return bool(self.token)

    async def get(self, label: str, path: str, **params: Any) -> Any:
        async with self.session.get(
            f"{API}/{path}",
            params={k: v for k, v in params.items() if v is not None},
            headers={**self.headers, "Authorization": f"Bearer {self.token}"},
        ) as resp:
            body = await resp.json(content_type=None)
        self.report(label, resp.status, body)
        return (body or {}).get("data", body) if isinstance(body, dict) else body

    async def post(self, label: str, path: str, payload: dict[str, Any]) -> Any:
        async with self.session.post(
            f"{API}/{path}",
            json=payload,
            headers={**self.headers, "Authorization": f"Bearer {self.token}"},
        ) as resp:
            body = await resp.json(content_type=None)
        self.report(label, resp.status, body)
        return (body or {}).get("data", body) if isinstance(body, dict) else body


async def walk(name: str, creds: dict[str, str], save: bool) -> None:
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        p = Probe(session, name, save)
        if not await p.login(creds["username"], creds["password"]):
            print(f"{name}: login failed, stopping")
            return
        await p.get("user-me", "v1/user/me")
        places = await p.get("places", "v1/placesofconsumption")
        pocs = (places or {}).get("places_of_consumption") or [] if isinstance(places, dict) else []
        print(f"\n=== {name}: {len(pocs)} place(s) of consumption")
        today = date.today()
        three_years = (today - timedelta(days=3 * 365)).isoformat()
        accounts: set[Any] = set()
        for i, poc in enumerate(pocs):
            pa = poc.get("pa") or poc.get("clientId")
            number = poc.get("poc_number") or poc.get("poc") or poc.get("id")
            tag = f"poc{i}"
            divisions = await p.get(f"{tag}-divisions", f"v1/placesofconsumption/divisions/{number}", pa=pa)
            details = (divisions or {}).get("details") or {} if isinstance(divisions, dict) else {}
            for div in details.values():
                d = div.get("division")
                inst = div.get("installation_number")
                serie = div.get("serial_number")
                await p.get(f"{tag}-{d}-index", f"v1/index/{number}", division=d, pa=pa,
                            installation_number=inst, serie_contor=serie)
                await p.get(f"{tag}-{d}-consumption", f"v1/index/consumption/{number}",
                            startDate=three_years, endDate=today.isoformat(), pa=pa)
                if div.get("contract_account_number"):
                    accounts.add(div["contract_account_number"])
            # The server rejects invoice-history windows longer than 12 months.
            one_year = (today - timedelta(days=364)).isoformat()
            await p.get(f"{tag}-invoices", f"v1/invoices/history/{number}", pa=pa,
                        startDate=one_year, endDate=today.isoformat())
        if pocs:
            pa = pocs[0].get("pa") or pocs[0].get("clientId")
            await p.get("payments", f"v1/invoices/payment/history/{pa}",
                        startDate=three_years, endDate=today.isoformat())
        if accounts:
            await p.post("balance", "v1/invoices/ballance-details",
                         {"contract_account": sorted(accounts)})


async def main() -> None:
    save = "--save" in sys.argv
    only = [a for a in sys.argv[1:] if not a.startswith("--")]
    accounts = load_accounts()
    print(f"accounts configured: {sorted(accounts)}")
    for name, creds in accounts.items():
        if only and name not in only:
            continue
        await walk(name, creds, save)


if __name__ == "__main__":
    asyncio.run(main())
