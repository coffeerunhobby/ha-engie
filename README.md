# ENGIE România for Home Assistant

Unofficial Home Assistant integration for MyENGIE România accounts.

**Status: in development (0.1.0).** Read-only so far; not yet published to HACS.

## What it shows

Each place of consumption on the account becomes a device with:

- **Amount due** — the account balance for that place (negative means credit), with
  the invoice history as attributes
- **Last invoice**, **Last payment**
- **Due date** and **Due date (relative)** — the earliest unpaid invoice's deadline
- **Overdue** — also as a `problem` binary sensor, red on a dashboard card when an
  invoice is unpaid past its due date
- **Gas meter index** (m³) / **Electricity meter index** (kWh)
- **Self-reading window** and a **Self-reading open** binary sensor per metered service

Billed monthly consumption (kWh, gas included — ENGIE converts it) is imported into
long-term statistics, so it can be added to the Energy Dashboard or charted with the
Statistics Graph card.

## Setup

**Settings → Devices & services → Add integration → ENGIE România**, then the e-mail
and password of your MyENGIE account. Every place of consumption on the account is
added automatically. To change the password later: the entry's **⋮ → Reconfigure**.

The password is stored encrypted (Fernet, via the `cryptography` package Home
Assistant already ships), with the key in a separate file.

Not affiliated with or endorsed by ENGIE. "ENGIE" and "MyENGIE" are trademarks of
their respective owners.
