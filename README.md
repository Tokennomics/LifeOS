# Life OS

One context graph. Many agents. Compounding value on hardware you own.
See the master build document for mission, laws, and roadmap.

## Sprint 1 status

| Ticket | Status |
|---|---|
| 1. Substrate schema + graph.py (scope/provenance enforcement) + tests | ✅ |
| 2. Gateway skeleton + Telegram bot echo | ✅ |
| 3. Horizon vision_intake → life_plan in graph | ✅ (Claude path + offline fallback) |
| 4. Planner + Monday push + /log | next |
| 5. Sunday retro | next |
| 6. VoiceOS /capture → entities | next |
| 7. Google Calendar free/busy ingest | next |
| 8. NucBox deploy scripts | next |

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
| `ANTHROPIC_API_KEY` | Real Claude interview in `/vision` + light-model intent routing. Without it, intake uses the deterministic offline parser. |
| `TELEGRAM_BOT_TOKEN` | The Telegram bot (create one via @BotFather). |
| `LIFEOS_GATEWAY_TOKEN` | Bearer auth on the HTTP gateway (leave unset for localhost dev). |
| `LIFEOS_PG_DSN` | Postgres instead of SQLite (set `env: postgres` in config.yaml; needs pgvector). |

After the bot's first accepted message it logs your Telegram user id — pin it in
`config.yaml → telegram.allowed_user_ids` so only you can talk to it.

## Run

```powershell
# Telegram bot (echo + /vision)
.venv\Scripts\python -m surfaces.bot.telegram

# HTTP gateway
.venv\Scripts\uvicorn gateway.main:create_app --factory --host 127.0.0.1 --port 8787
```

Gateway endpoints: `GET /health`, `POST /v1/route {"text": ...}`, `POST /v1/vision {"text": ...}`.

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
