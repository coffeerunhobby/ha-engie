# ENGIE România for Home Assistant

Unofficial Home Assistant integration for MyENGIE România accounts.

**Status: in development (0.3.0).** Submitted to the HACS default store; until it
is listed, add it as a custom repository.

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
- **Reading to submit** and **Submit reading** per metered service — see below

Billed monthly consumption (kWh, gas included — ENGIE converts it) is imported into
long-term statistics, so it can be added to the Energy Dashboard or charted with the
Statistics Graph card.

## Self-reading

ENGIE accepts one self-read meter index per metered service during a few days each
month. To send one from Home Assistant:

1. Enter the index in **Gas reading to submit** (or the electricity one). It starts at
   the last known index; changing it sends nothing.
2. Press **Submit gas reading**.

The press is refused, with the reason and without contacting ENGIE, when the window
is closed, when an index was already sent from Home Assistant in this window, or when
the value is below the last known index (a meter cannot run backwards). If ENGIE
refuses the index, its own reason is shown. Nothing is ever sent automatically.

The button's attributes show what the next press will do: `will_submit_to_engie`,
`window_open`, `window_start`, `window_end` and `already_submitted_this_window`.

## Setup

**Settings → Devices & services → Add integration → ENGIE România**, then:

- **E-mail**: the address you sign in to MyENGIE with.
- **Password**: your MyENGIE password.

Every place of consumption on the account is added automatically, as a device named
"ENGIE România" plus ENGIE's place number; rename it (for example to "Acasă") and its
entities follow. The address is shown as an attribute of **Amount due**. To change the
password later: the entry's **⋮ → Reconfigure**.

## Data updates

The integration asks MyENGIE every 6 hours: ENGIE bills monthly and the meter index
changes at most daily. To refresh sooner, call the `homeassistant.update_entity`
action on any of its entities, for example from an automation.

## Removal

**Settings → Devices & services → ENGIE România**, then **⋮ → Delete** on the account.
This removes its devices, entities and the record of sent self-readings. Imported
consumption statistics stay in the database until you delete them under
**Developer tools → Statistics** (**Tools → Statistics** from Home Assistant 2026.11).

The password is stored encrypted (Fernet, via the `cryptography` package Home
Assistant already ships), with the key in a separate file.

Not affiliated with or endorsed by ENGIE. "ENGIE" and "MyENGIE" are trademarks of
their respective owners.
