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
  **Daily-driver hardening:** tap a task to log / tap again to undo; edit the vision & goals
  (rename/add/remove) instead of re-pasting; the retro persists across reload; delete a capture
  or parked idea. Gate honesty fix (server + Travel): `retros_completed` counts distinct weeks,
  so re-running a week's retro can't inflate gate progress.
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
  - **Gate-first ordering** — goals carry a `focus` flag; focused goals lead the week instead of
    losing to input order. Vision intake defaults the first goal to focus; retarget via the ★
    toggle in Travel Mode, `/focus <n>` on the bot, or `POST /v1/focus`. At most **2** goals can
    be starred at once (`FOCUS_CAP`), so starring everything can't flatten priority.
  - **Gate floor** — while the v0.1 gate is unpassed, one slot of the capped week is always a
    gate-advancing ritual task (log today / run the retro), regardless of focus; focus steers the
    rest. When the gate passes the floor lifts automatically and focus governs the full week.
  - **Anti-drift golden tests** — `tests/golden/cases.json` runs against both implementations
    (`tests/test_golden.py` + `tests/golden/run_js.mjs`) so JS↔Python drift fails CI.

## Roadmap work started

- **Phase 3 engine — mediator-brokered 1:1 coordination (server-side).** `modules/coordinate/`
  (`core.py` pure ranking engine + `coordinator.py` graph flow) + `/v1/coordinate/{propose,respond,
  approve}` + `GET /v1/coordinate`. Two people converge on a `{time, place}` from private weight
  vectors over the *proposed* options (never a calendar); both humans ratify; on match it writes a
  busy meet `event` linked to the person. Peer input is sanitized to the proposed keys (untrusted
  data, never instructions) — the sanctioned alternative to open agent-to-agent negotiation.
  Tested + simulated (8 tests). **This is the testable substrate; live cross-device use still needs
  accounts + a reachable coordinator (the NucBox) and ≥2 real users, per the roadmap gate.**

## Next (from the 2026-07-18 brief)

- **T2 — Reconciliation.** `POST /v1/import`: ingest the Travel Mode bundle through
  `substrate/graph.py` with `module=travel`, original timestamps, idempotency keys → skip
  already-imported. Every record the bundle carries already has a stable `key` + `ts`.
- **T4 — Repo hygiene.** This file; suite green in CI (done, 104); README test command (done).

## Non-goals (do not build)

Convoy · Memento · Steward · Seasons · Vitals · Ledger · Hearth · Calibre · Ticketmaster ·
Google OAuth · Postgres migration · native store builds · SDK opening · billing activation ·
Tailscale/remote access (deferred until home) · licence/entity/ToS content.
