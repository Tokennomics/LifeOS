# Handover — next session start here

_Written 2026-07-24. Read `docs/STATUS.md` for the fuller picture; this is the 60-second version._

## Context
Owner is travelling, **phone-only, no NucBox access**. Small diffs, one ticket per PR, stop
and report after each. `substrate/graph.py` is the only write path. No secrets in the repo.
The working brief is CONTINUE BUILDING — LIFE OS (2026-07-18). Where brief and code disagree,
**code wins** (e.g. tests are 73 passing, not 24; Tailscale is deferred until home).

## Just shipped — T1 (draft PR #1)
Travel Mode: standalone offline PWA at `surfaces/app/www/travel.html` (+ `travel.js`,
`travel-sw.js`, `travel.webmanifest`). No gateway; persists to IndexedDB; mirrors the server's
offline fallbacks. Published to GitHub Pages via `.github/workflows/pages.yml` (shell only).
Verified end-to-end offline in headless Chromium. **Existing `app.js`/gateway untouched.**

Branch: `claude/lifeos-repository-connection-lfeqba` · PR: Tokennomics/LifeOS#1 (draft).

## Do next (in order, one PR each)
- **T2 — Reconciliation.** `POST /v1/import` ingests the Travel Mode export bundle through
  `graph.py` with `module=travel`, original timestamps, and idempotency keys → skip anything
  already imported; return created/skipped/failed. The bundle format is
  `lifeos-travel-export/v1` (see `buildBundle()` in `travel.js`); every item already carries a
  stable `key`, `ts`, `type` (`entity`/`edge`), and for edges `src`/`dst`/`rel`. Test the
  double-import replay case.
- **T3 — Anti-hindrance mechanics.** `/parked` (distraction sink), boredom rule (finish
  partial work; "smallest remaining piece"), `/gate` (real v0.1 gate counts, never estimates),
  energy shaping (deep work → evening, weekly task cap while `energy_baseline: tired`). Must
  work in Travel Mode too. Tests per rule.
- **T4 — Hygiene.** Keep `python -m pytest` green (73 now); STATUS.md updated each PR (done).

## Gotchas
- Publish URL is `/travel.html` (not root) so the gateway app still works; after merge set
  Settings → Pages → Source = "GitHub Actions".
- `travel.js` offline flows must stay one-for-one with the Python fallbacks — if you change
  planner/retro logic server-side, mirror it here (and vice versa) or reconciliation drifts.
- Verify Travel Mode by driving `travel.html` in headless Chromium
  (`/opt/pw-browsers/chromium-1194/chrome-linux/chrome`) with the network forced offline.

## Don't build
Convoy · Memento · Steward · Seasons · Vitals · Ledger · Hearth · Calibre · Ticketmaster ·
Google OAuth · Postgres migration · native store builds · SDK opening · billing · Tailscale ·
licence/entity/ToS content.
