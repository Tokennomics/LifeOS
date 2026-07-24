# LifeOS — STATUS

_The one-page memory between phone-driven sessions. Update at the end of every PR._

_Last updated: 2026-07-24_

## Where we are

Sprint 1 shipped (substrate + graph.py, gateway, Horizon, VoiceOS, ICS ingest, deploy
scripts). The v0.2 PWA (`surfaces/app/www`, served by the gateway at `/app/`) works but
needs a reachable gateway. The push now is **Travel Mode**: run the week from a phone
abroad with no server at all, then reconcile at home.

**Tests:** `python -m pytest` → **73 passing** in the cloud env. (The 2026-07-18 brief
said 24 — the code has moved on; the code wins.)

## Shipped

- **T1 — Travel Mode (this PR).** Standalone offline PWA at `surfaces/app/www/travel.html`.
  No gateway required. Persists to **IndexedDB** (not localStorage). Offline Horizon flows —
  `/vision` (paste plan text), weekly plan, `/log`, Sunday retro, `/capture` — each mirrors
  the server's deterministic offline fallback exactly. Service worker (`travel-sw.js`) caches
  the full shell for airplane-mode load; installable via its own `travel.webmanifest`. Clear
  "Travel · local only" indicator. Export produces the reconciliation bundle T2 will import.
  Published to GitHub Pages via `.github/workflows/pages.yml` (shell only — all data stays in
  the browser).

## Next (from the 2026-07-18 brief)

- **T2 — Reconciliation.** `POST /v1/import`: ingest the Travel Mode bundle through
  `substrate/graph.py` with `module=travel`, original timestamps, idempotency keys → skip
  already-imported. Every record the bundle carries already has a stable `key` + `ts`.
- **T3 — Anti-hindrance planner mechanics.** Distraction sink (`/parked`), boredom rule
  (finish partial work; "smallest remaining piece"), doubt rule (`/gate`), energy shaping
  (deep work → evening, weekly task cap while `energy_baseline: tired`). Must work in Travel
  Mode too.
- **T4 — Repo hygiene.** This file; keep the suite green in the cloud (done); README one-line
  test command (done).

## Non-goals (do not build)

Convoy · Memento · Steward · Seasons · Vitals · Ledger · Hearth · Calibre · Ticketmaster ·
Google OAuth · Postgres migration · native store builds · SDK opening · billing activation ·
Tailscale/remote access (deferred until home) · licence/entity/ToS content.
