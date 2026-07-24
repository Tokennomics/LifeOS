# LifeOS — STATUS

_The one-page memory between phone-driven sessions. Update at the end of every PR._

_Last updated: 2026-07-24_

## Where we are

Sprint 1 shipped (substrate + graph.py, gateway, Horizon, VoiceOS, ICS ingest, deploy
scripts). The v0.2 PWA (`surfaces/app/www`, served by the gateway at `/app/`) needs a
reachable gateway; **Travel Mode** (`travel.html`) runs the week from a phone abroad with no
server. **T3 (anti-hindrance) was pulled ahead of T2** by the owner: T2's import has no
user-facing value until he's home at the NucBox, while T3 improves daily use while travelling.

**Tests:** `python -m pytest` → **104 passing** in the cloud env, gated by
`.github/workflows/tests.yml`. (The 2026-07-18 brief said 24 — the code has moved on.)

## Shipped

- **T1 — Travel Mode.** Standalone offline PWA at `surfaces/app/www/travel.html`. No gateway.
  Persists to **IndexedDB**. Offline Horizon flows mirror the server's deterministic
  fallbacks. Service worker for airplane-mode load; installable; "Travel · local only" badge.
  Publishes to GitHub Pages via `.github/workflows/pages.yml` (shell only — data stays local).
- **T3 — Anti-hindrance planner mechanics.** All four obstacles encoded as product behaviour,
  working on BOTH the server and in Travel Mode via one shared pure core
  (`modules/horizon/core.py` ⇄ `surfaces/app/www/horizon-core.js`):
  - **Distraction sink** — a capture classified as a new-project idea is *parked, not planned*
    ("Captured, not abandoned — current gate first."); `/parked` + `GET /v1/parked` list them.
  - **Boredom rule** — the planner finishes stuck work before starting new; a task carried >2
    cycles surfaces as its "smallest remaining piece" with a concrete next physical action.
  - **Doubt rule** — `/gate` + `GET /v1/gate` print honest v0.1-gate progress (days used, logs,
    retros) from real stored counts, never estimates.
  - **Energy shaping** — deep work → evening (never mornings), admin → the daytime trough, and
    a hard weekly cap (3) while `vitals.energy_baseline: tired` in config.
  - **Anti-drift golden tests** — `tests/golden/cases.json` runs against both implementations
    (`tests/test_golden.py` + `tests/golden/run_js.mjs`) so JS↔Python drift fails CI.

## Next (from the 2026-07-18 brief)

- **T2 — Reconciliation.** `POST /v1/import`: ingest the Travel Mode bundle through
  `substrate/graph.py` with `module=travel`, original timestamps, idempotency keys → skip
  already-imported. Every record the bundle carries already has a stable `key` + `ts`.
- **T4 — Repo hygiene.** This file; suite green in CI (done, 104); README test command (done).

## Non-goals (do not build)

Convoy · Memento · Steward · Seasons · Vitals · Ledger · Hearth · Calibre · Ticketmaster ·
Google OAuth · Postgres migration · native store builds · SDK opening · billing activation ·
Tailscale/remote access (deferred until home) · licence/entity/ToS content.
