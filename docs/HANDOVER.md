# Handover — next session start here

_Rewritten 2026-07-26. This is the 60-second version; `docs/STATUS.md` is the fuller picture and
`docs/ROADMAP.md` is the parked map. Where any document and the code disagree, **the code wins**._

## Context

Owner is travelling, **phone-only, no NucBox access**. Working rules, still in force:
small diffs, **one ticket per PR**, stop and report after each — do not chain tickets.
`substrate/graph.py` is the only write path; every write carries scope + provenance.
The v0 schema is final — extend via `attrs` JSONB only. Every feature works with **no API key**
and improves with one. **No secrets in the repo, ever.** Tests pass before every commit.

Branch: `claude/lifeos-repository-connection-lfeqba` (always; never push elsewhere without
explicit permission). **PRs #1–#10 are merged.** `python -m pytest` → **219 passing**.

## Where we are

**The social layer is complete and tested end to end.** The full scenario works across three
separate accounts: land in a city → find a local crew of strangers in the public directory → join
it → plan a night together → everyone gets it on their own calendar. None of it requires an entity
in anyone else's graph.

| Layer | State |
|---|---|
| Substrate, gateway, Horizon, VoiceOS, ICS ingest | Sprint 1, shipped |
| **T1 Travel Mode** | live — `tokennomics.github.io/LifeOS/travel.html` |
| Android APK | live — rolling prerelease from `android.yml` |
| **T3 anti-hindrance** | shipped (distraction sink · boredom · doubt · energy · gate floor · focus cap) |
| Accounts + per-user isolation | shipped, enforced at the substrate |
| Crews · admission policy · safety rails | shipped |
| Discover · feed | shipped |
| Coordination (1:1 + crew, quorum-based) | shipped |
| Cross-account discovery / membership / **scheduling** | shipped (#8, #9, **#10**) |

Only two things the owner can actually *use* today are Travel Mode and the APK. Everything in the
social layer is exercisable only in the test suite until there is a reachable host.

## Do next — **the VPS** (decided 2026-07-26)

The owner's call, verbatim in intent: *"we'll need to build it on a VPS if we want to actually
scale the app."* That settles the long-standing NucBox-vs-VPS question — **it is a VPS**, and the
NucBox path stays as the personal/offline option, not the deployment target. This is now the
blocker in front of every social feature, and it is the next ticket.

**What already exists:** `Dockerfile` + `deploy/docker-compose.yml` (bot + gateway, SQLite on a
mounted volume, secrets from the host environment). That is most of a deploy already.

**What a VPS additionally needs — the actual ticket:**
- **TLS + a reverse proxy.** Caddy is the least-effort correct answer (automatic Let's Encrypt).
  The gateway currently binds `0.0.0.0:8787` in plain HTTP; it must not be exposed directly.
  Sessions are bearer tokens — **without TLS every login is on the wire.** Treat as blocking.
- **Backups.** SQLite in WAL mode on a volume. Needs a scheduled `VACUUM INTO` (not a file copy —
  copying a live WAL database can produce a corrupt snapshot) plus off-box retention.
- **Not root, not the host network.** Non-root container user, firewall to 80/443 only,
  SSH keys only.
- **Secrets from the environment**, never a committed file. The compose file is already written
  this way — keep it that way.
- **A health check + restart policy**, so a crashed gateway comes back without the owner's laptop.
- **Then, and only then:** point the PWA at it and do the first real two-phone test.

**Open question the VPS forces, worth deciding deliberately:** SQLite is fine for one household
and probably fine for the first hundred users, but "scale the app" eventually means Postgres.
`substrate/graph.py` already parameterises the dialect (`g.ph`, `g.dialect`, JSON-path branches for
`json_extract` vs `->>`), so the port is real but not free. **Do not do it as part of the VPS
ticket** — get the box up first, measure, then decide. Postgres migration is still on the
Don't-build list until there is a reason.

**After the VPS:** T2 reconciliation (`POST /v1/import` — ingest the Travel Mode bundle with
original timestamps + idempotency keys; format `lifeos-travel-export/v1`, see `buildBundle()` in
`travel.js`; test the double-import replay case). The owner deferred it until he's home, but it
stops being NucBox-shaped once there's a server.

## Gotchas — read these before touching anything

- **Never edit only one side of the twin core.** `modules/horizon/core.py` and
  `surfaces/app/www/horizon-core.js` are line-for-line twins. Change one, mirror the other, or the
  golden suite fails CI. A diff in `tests/golden/cases.json` is a *reviewed behaviour change*,
  never a convenience.
- **Run a narrated simulation, not just the tests.** This has now caught four bugs the green suite
  missed — including, in #10, a forgeable participant grant and a departed member still counting
  toward quorum. If a security-shaped change passes on the first run, that is a reason to simulate,
  not a reason to ship.
- **Grants are not owner-authenticated.** Any session with `content:write` can write any row in
  `grants`. Nothing exposed reaches it (the gateway offers only module functions, and crews and
  coordinate both re-derive authority from the crew), but **never treat a grant alone as a
  permission** — it is how you *reach* a thing; the crew is who *belongs*. Its own ticket, written
  up in ROADMAP.
- **`find_public` is the only cross-owner read, and it is narrow by construction** —
  `visibility == "public"` is forced into the query and it is read-only. Do not widen it. Anything
  shared with *named* people goes through `get_if_granted` / `update_if_granted` instead.
- **Nobody writes an entity into someone else's graph.** Shared outcomes live on the shared entity;
  each account materialises its own local copy (see `coordinator.add_to_calendar`).
- Publish URL is `/travel.html`, not root, so the gateway app still works. Pages needs
  Settings → Pages → Source = "GitHub Actions" (already set).
- Android CI needs **JDK 21** — Capacitor 7 compiles with 21 and fails with 17.
- The bus enforces a fixed topic allowlist; don't publish a new topic without adding it there.
- Energy baseline is `config.yaml → vitals.energy_baseline` (tired|rested). Travel Mode is always
  the tired context.
- The sandbox cannot reach `github.io` (proxy 403 on CONNECT). Verify Pages deploys via the GitHub
  API, and say so rather than claiming a browser check that didn't happen.

## Parked — don't let it pull focus

`docs/ROADMAP.md` holds the map: Agentic OS (single orchestrator, propose-only, autonomy as a
per-action dial), Urgency/Triage OS (explicitly *not* a safety-critical Emergency OS), the
developer platform, and — added 2026-07-26 — **Phase 3b, dating**: intent-based, mutual-consent,
meet-through-shared-activity, behind five ordered kill-gates with hosting first. Age assurance and
GDPR Art. 9 handling are legal preconditions there, not features. Nothing on that map is built
until the v0.1 gate passes. **Current gate first.**

## Don't build

Convoy · Memento · Steward · Seasons · Vitals · Ledger · Hearth · Calibre · Ticketmaster ·
Google OAuth · Postgres migration (until measured, see above) · native store builds · SDK opening ·
billing · licence/entity/ToS content · a swipe-style dating surface · sub-city location anywhere in
the social layer.
