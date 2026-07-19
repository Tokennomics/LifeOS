# Life OS

One context graph. Many agents. Compounding value on hardware you own.
See the master build document for mission, laws, and roadmap.

## Module registry status

| Module | What ships today (P0) |
|---|---|
| **VoiceOS** | /capture → content entity + light-model extraction (tasks/people/interests, `feeds` edges) |
| **Horizon** | vision intake → plan graph; weekly if-then planner (energy-aware); /log; Sunday retro → metric |
| **Reconnect** | decay radar (cadence vs last_contact), one-tap invite drafts, executed-touch logging |
| **Convoy** | manual social events, crew invites + RSVP, attendance → refreshes friendships + fires quests |
| **Memento** | capsules drop/lock at coordinates, check-in unlock (haversine), quests from attended events |
| **Steward** | graph scanners (stale tasks, admin-keyword captures, ghosted people) → approve-to-schedule |
| **Vitals** | energy windows layer (defaults; planner schedules deep work into peaks) |
| **Ledger** | spend log + monthly by-category shape |
| **Calibre** | decision journal with confidence → Brier calibration on resolve |
| **Hearth** | shared spaces on the grants ACL (membership model; sync later) |
| **SDK** | `sdk/manifest_schema.json` + `module_spec.md` (dogfooded; opens at 2K WAU) |
| **Billing** | scaffolding, OFF by default — everything entitled until STRIPE_KEY exists |

Deferred honestly: Ticketmaster ingest (needs API key), email/calendar OAuth scanners,
sleep import, AR lens, Seasons arcs, multi-user sync — each has its seam ready.

## Sprint 1 status

| Ticket | Status |
|---|---|
| 1. Substrate schema + graph.py (scope/provenance enforcement) + tests | ✅ |
| 2. Gateway skeleton + Telegram bot echo | ✅ |
| 3. Horizon vision_intake → life_plan in graph | ✅ (Claude path + offline fallback) |
| 4. Planner + Monday 07:00 push + /log | ✅ |
| 5. Sunday retro (score → metric → reflection) | ✅ |
| 6. VoiceOS /capture → entities + feeds edges | ✅ |
| 7. Calendar free/busy ingest | ✅ via secret ICS URL (zero-OAuth; Google OAuth deferred) |
| 8. NucBox deploy scripts | ✅ docker-compose + Windows scheduled tasks |

**v0.1 gate (D11–14):** self-use. `/vision` → Monday push → obey → `/log` → Sunday retro.
If you won't use it daily for 4 weeks, stop before any social code (risk register #2).

## v0.2 — the app (iOS + Android, no tokens required)

The mobile app lives at `surfaces/app/www` (zero-build PWA: Today / Capture / Graph tabs)
and is served by the gateway at **`/app/`**. Every feature works with **no API key and no
Telegram token** — the gateway's offline fallbacks handle vision intake, planning, retro,
and capture; `ANTHROPIC_API_KEY` upgrades all of them in place (badge flips to "AI mode").

**Install on your phone today (no app store, no toolchain):**
1. Run the gateway bound to your LAN: `deploy\run_gateway.ps1` (binds 0.0.0.0).
2. On the phone, open `http://<pc-name-or-ip>:8787/app/`.
3. iOS Safari: Share → *Add to Home Screen*. Android Chrome: menu → *Install app*.
It launches standalone (own icon, no browser chrome); the shell works offline via a
service worker, actions need the gateway reachable (your hardware — Law 6).

**Native shells (Capacitor):** `surfaces/app/android` is generated and synced. Building
the APK needs Android Studio: `deploy\build-mobile.ps1` then `npx cap open android`.
iOS requires a Mac: `cd surfaces/app && npm i && npx cap add ios && npx cap open ios`.
In native builds, set the gateway URL in the app's ⚙ Settings on first run.

**API for the app:** `GET /v1/vision|/v1/week|/v1/today|/v1/graph|/v1/export`,
`POST /v1/vision|/v1/plan|/v1/log|/v1/retro|/v1/capture`. Full graph export is one tap
in Settings (Law 2).

## Quickstart (Windows)

```powershell
cd C:\Ventures\lifeos
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m substrate.migrate      # creates data\lifeos.db
.venv\Scripts\python -m pytest                 # 24 tests
```

Try the vision intake end-to-end without any API keys:

```powershell
.venv\Scripts\python -m modules.horizon.vision_intake --offline "Freedom by 40`n- Ship Life OS v0.1`n- Train 3x per week"
```

## Secrets (all optional per feature, via environment variables)

| Variable | Enables |
|---|---|
| `ANTHROPIC_API_KEY` | Real Claude paths: `/vision` interview, weekly planner, retro reflection, capture extraction, intent routing. Without it, every command still works via deterministic offline fallbacks. |
| `TELEGRAM_BOT_TOKEN` | The Telegram bot (create one via @BotFather). |
| `TELEGRAM_OWNER_CHAT_ID` | Monday-plan / Sunday-retro pushes (bot logs your id on first message). |
| `LIFEOS_CALENDAR_ICS` | Free/busy ingest from your calendar's secret ICS URL (daily 06:30). |
| `LIFEOS_GATEWAY_TOKEN` | Bearer auth on the HTTP gateway (leave unset for localhost dev). |
| `LIFEOS_PG_DSN` | Postgres instead of SQLite (set `env: postgres` in config.yaml; needs pgvector). |

After the bot's first accepted message it logs your Telegram user id — pin it in
`config.yaml → telegram.allowed_user_ids` so only you can talk to it.

## Run

```powershell
# Telegram bot: /vision /plan /log /retro /capture (+ Mon 07:00 & Sun 19:00 pushes)
.venv\Scripts\python -m surfaces.bot.telegram

# HTTP gateway
.venv\Scripts\uvicorn gateway.main:create_app --factory --host 127.0.0.1 --port 8787
```

Gateway endpoints: `GET /health`, `POST /v1/route {"text": ...}`, `POST /v1/vision {"text": ...}`.

Every module also runs standalone (all support `--offline`):

```powershell
.venv\Scripts\python -m modules.horizon.planner
.venv\Scripts\python -m modules.horizon.retro
.venv\Scripts\python -m modules.voiceos.capture "the thought"
.venv\Scripts\python -m modules.calendars.freebusy
```

## Deploy (NucBox)

- **Windows-native:** `powershell -ExecutionPolicy Bypass -File deploy\nucbox-install.ps1` —
  venv + migrate + tests, then registers `LifeOS-Bot` and `LifeOS-Gateway` scheduled tasks
  (ONLOGON, short command lines — WinError 206 safe). Logs land in `data\*.log`.
- **Docker:** `cd deploy; docker compose up -d --build`.

## Architecture (v0.1 slice)

- `substrate/` — the shared context graph. `graph.py` is the ONLY write path: every write
  needs a module scope (`goals:write`, ...) and provenance (source + confidence → an
  `observations` row), and publishes `observation.created` on the bus. Schema is FINAL for
  v0; extend via `attrs` JSON only.
- `gateway/` — auth, rule-based intent router (light-Claude fallback), and `claude.py`,
  the single choke point for model routing (heavy: claude-opus-4-8, light: claude-haiku-4-5),
  prompt caching, and structured outputs.
- `modules/horizon/` — vision intake: backcasting interview → `goal(level=vision|goal|milestone)`
  and `task` entities linked by `feeds` edges; publishes `plan.updated`. Returns clarifying
  questions instead of guessing when the vision is too thin.
- `surfaces/bot/` — Telegram long-polling bot: `/vision`, `/help`, echo.

SQLite is the v0.1 runtime (`data\lifeos.db`, WAL mode). The Postgres/pgvector schema ships
in `substrate/schema.sql` and `connect()` supports it, but it is untested on this box until
a server exists — treat the postgres path as v0.2 work.
