# Handover — next session start here

_Written 2026-07-24. Read `docs/STATUS.md` for the fuller picture; this is the 60-second version._

## Context
Owner is travelling, **phone-only, no NucBox access**. Small diffs, one ticket per PR, stop
and report after each. `substrate/graph.py` is the only write path. No secrets in the repo.
The working brief is CONTINUE BUILDING — LIFE OS (2026-07-18). Where brief and code disagree,
**code wins** (e.g. tests are 73 passing, not 24; Tailscale is deferred until home).

## Order was reordered by the owner: T3 before T2
T2's import has no user-facing value until he's home at the NucBox to test it end-to-end; T3
improves what he uses daily while travelling. So T3 shipped next; T2 is now the remaining work.

## Shipped — T1 + T3 (draft PR #1)
- **T1 — Travel Mode:** standalone offline PWA at `surfaces/app/www/travel.html`. No gateway;
  IndexedDB; mirrors the server's offline fallbacks. GitHub Pages via `pages.yml` (shell only).
- **T3 — Anti-hindrance mechanics:** distraction sink (`/parked`), boredom rule (finish stuck
  work; >2-cycle tasks → "smallest remaining piece"), doubt rule (`/gate`), energy shaping
  (deep work → evening, admin → trough, weekly cap while `vitals.energy_baseline: tired`).
  Both server and Travel Mode share ONE pure core: `modules/horizon/core.py` ⇄
  `surfaces/app/www/horizon-core.js`. Golden fixtures (`tests/golden/cases.json`) run against
  both via `tests/test_golden.py` + `tests/golden/run_js.mjs`, gated by `.github/workflows/tests.yml`.

Branch: `claude/lifeos-repository-connection-lfeqba` · PR: Tokennomics/LifeOS#1 (draft, stacks
T1+T3 — one working branch per the git rules).

## Do next
- **T2 — Reconciliation.** `POST /v1/import` ingests the Travel Mode export bundle through
  `graph.py` with `module=travel`, original timestamps, and idempotency keys → skip anything
  already imported; return created/skipped/failed. Bundle format `lifeos-travel-export/v1` (see
  `buildBundle()` in `travel.js`); every item carries a stable `key`, `ts`, `type`
  (`entity`/`edge`), and for edges `src`/`dst`/`rel`. Test the double-import replay case.
- **T4 — Hygiene.** Keep `python -m pytest` green (104 now); STATUS.md updated each PR (done).

## Gotchas
- **Never edit only one side of the core.** `modules/horizon/core.py` and
  `surfaces/app/www/horizon-core.js` are line-for-line twins; change one, mirror the other, or
  the golden suite fails CI. Regenerate `tests/golden/cases.json` deliberately — a diff there
  is a reviewed behaviour change.
- Publish URL is `/travel.html` (not root) so the gateway app still works; after merge set
  Settings → Pages → Source = "GitHub Actions".
- Verify Travel Mode by driving `travel.html` in headless Chromium
  (`/opt/pw-browsers/chromium-1194/chrome-linux/chrome`) with the network forced offline.
- Energy baseline lives in `config.yaml → vitals.energy_baseline` (tired|rested); Travel Mode
  is always the tired context.

## Don't build
Convoy · Memento · Steward · Seasons · Vitals · Ledger · Hearth · Calibre · Ticketmaster ·
Google OAuth · Postgres migration · native store builds · SDK opening · billing · Tailscale ·
licence/entity/ToS content.
