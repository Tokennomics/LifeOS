# Deploying, in about fifteen minutes

Everything here happens in a browser. It has to be done by you — it needs your Render
account and two secrets that must never live in this repo or in a chat log.

## 1. Create the service

1. [dashboard.render.com](https://dashboard.render.com) → **New** → **Blueprint**
2. Point it at `Tokennomics/LifeOS`. It reads `render.yaml` and proposes one web service.
3. **Do not remove the disk.** Everything is one SQLite file at `/app/data`. Without a
   persistent disk every deploy resets the database to empty, and Render's free tier has no
   disks *and* sleeps — which also breaks certificate renewal. `starter` is the floor that
   works.

## 2. Set the two secrets

In the dashboard, on the service, under **Environment**. Generate each **separately** —
reusing one value for both makes the signing key as widely known as the gateway token:

```
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # LIFEOS_SIGNING_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # LIFEOS_GATEWAY_TOKEN
```

No terminal? Any password manager's 32-character generator is fine. What matters is that
they are random and different.

## 3. Deploy, and check it is alive

```
https://<your-app>.onrender.com/health   →  {"ok": true, ...}
```

## 4. The one test that matters

Open **`https://<your-app>.onrender.com/app/`**, sign up, and go to the City tab. Type a
city and open it.

Nothing happens on the first look — that is correct, seeding runs behind the response. Open
it again a few seconds later. You should see **Places on the map**, with an OpenStreetMap
credit under it.

If you do, the whole external stack is working: geocoding, Overpass and Open-Meteo have all
answered for real for the first time. **None of that has ever been verified from a
sandbox** — the proxy there blocks those hosts — so this is the first genuine test of it.

If you do not, check `GET /v1/seeding/queue` with your gateway token. Every attempt records
what came back, so the failure will be named there rather than guessed at.

## 5. Worth doing the same day

- **A cron job for `POST /v1/seeding/drain`**, hourly. Seeding runs in-process, so a deploy
  mid-seed leaves a city queued; this picks those up. Render → New → Cron Job, same
  environment, `curl -X POST -H "Authorization: Bearer $LIFEOS_GATEWAY_TOKEN" .../v1/seeding/drain`
- **A cron job for backups**: `python -m tools.backup --dest /app/data/backups --keep 14`.
  A snapshot on the same disk survives a bad deploy but not a lost disk, so copy them off
  when it starts to matter.
- **Email** (`LIFEOS_RESEND_KEY`, `LIFEOS_MAIL_FROM`). Without it a forgotten password is an
  account nobody can get back into. Fine for friends, not for strangers.

## What to leave alone at first

- `LIFEOS_DATING_ENABLED` — off until there are people in a city.
- Signup is **open**: anyone with the URL can create an account. Right for friends, wrong
  for anywhere indexable.
