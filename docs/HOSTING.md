# Getting it online so friends can use it

Two paths. **Pick Render if you are on a phone** — that is the whole reason it wins, not
price. Pick Hetzner if you have a terminal and want it cheaper.

| | Render | Hetzner VPS |
|---|---|---|
| Setup | a browser, ~15 min | SSH, ~30 min |
| Cost | ~$7/mo + ~$0.25/GB disk | ~€4/mo |
| TLS | automatic | Caddy, automatic |
| Config | `render.yaml` (committed) | `deploy/vps/compose.yml` |

Everything below assumes a handful of friends, not a hundred users. One box, one SQLite
file, no cluster.

---

## Render, start to finish

1. **New → Blueprint**, point it at this repo. It reads `render.yaml`.
2. **Do not remove the disk.** Everything lives in one SQLite file at `/app/data`. Without
   a persistent disk every deploy resets the database to empty. Render's free tier has no
   disks *and* sleeps after inactivity, which also breaks certificate renewal — the
   `starter` plan is the floor that actually works.
3. **Set the two secrets** in the dashboard (they are `sync: false`, so they are never in
   the repo). Generate each **separately** — reusing one value for both is the mistake that
   makes the signing key as widely known as the gateway token:
   ```
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # LIFEOS_SIGNING_KEY
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # LIFEOS_GATEWAY_TOKEN
   ```
4. **Deploy.** Watch for `[seed]` in the logs if you set `LIFEOS_SEED_CITY`.
5. **Check it is alive:** `https://<your-app>.onrender.com/health` → `{"ok": true, ...}`.

## Sharing it with friends

Send them **`https://<your-app>.onrender.com/app/`** and nothing else. The PWA is served by
the gateway itself and talks to its own origin, so there is no API URL to configure, no
build step, and no app store. On a phone: open it, then "Add to Home Screen" — it behaves
like an installed app from then on.

The app opens on a sign-in screen: they pick a handle and a password and they are in. If
you have set up email (below), they can use a six-digit code instead and never have a
password to forget.

*This was not true until 2026-08-12.* The PWA had no sign-in screen at all — the only way to
a session was pasting a bearer token into a developer field, and the buttons that looked
like sign-in called an endpoint that returned a fabricated user id and no session, then said
"Authenticated!". Anyone you sent the link to before that date could not have got in.

**Before you send the link, know this:**

- **Signup is open.** Anyone with the URL can create an account. That is right for friends
  and wrong for a public link — do not post it anywhere indexable yet.

Password reset and email sign-in now exist, but **only if you set up email** — see below.
Without it a forgotten password is still an account nobody can get back into.

## Email: sign-in codes and password reset

Fifteen minutes, and it is what turns "tell them to save the password" into a real recovery
path. Two variables:

```
LIFEOS_RESEND_KEY=re_...                  # resend.com — free tier is 3,000 emails/month
LIFEOS_MAIL_FROM=LifeOS <hi@yourdomain>   # the domain must be verified in Resend
```

Resend rather than SMTP because it is one HTTPS POST — no port 587, which most hosts block
outbound anyway. You need a domain you control to verify as the sender; a free-tier address
will not send.

With both set, `GET /v1/auth/providers` reports `email.available: true` and three things
start working: signing in with a code instead of a password, adding an address to an account
you already have, and resetting a forgotten password. A reset **ends every open session on
that account** — that is deliberate, since most resets follow a suspected compromise.

**With neither set, email sign-in is simply unavailable** rather than half-working. The one
thing not to do is set `LIFEOS_OTP_ECHO=1` on a public box: it returns the code in the HTTP
response so a laptop install is usable without a provider, and on a reachable host it lets
anyone request a code for any address and read it — a complete bypass. It is off by default
and should stay off anywhere friends can reach.

## SafeWalk, and what it does not do

`/v1/safety/escort` records where somebody said they were going and when they should have
arrived, and shows that to the watchers they named. **It cannot message anyone.** There is no
SMS, no push, no phone call and no background location in this app — a watcher sees an
overdue walk when they next open it.

That limit is stated in the response (`push_delivered: false`) and on the screen, and it
needs to stay stated. The version this replaced told people "Crew notified & ETA timer set"
while nothing left the building, which is worse than having no feature at all: somebody who
believes their crew is watching walks home differently.

If you want real delivery, that is a push provider and a decision about notification
permissions — not a config flag that exists today.

## Being the operator

Your `LIFEOS_GATEWAY_TOKEN` is also your moderator credential — abuse reports at
`GET /v1/dating/reports` and `GET /v1/crews/reports/open` are operator-only, and the token
is how you prove you are the operator. To service the queue from a phone without carrying
that token around, put your own account id in `LIFEOS_MODERATOR_ACCOUNTS`.

**Backups.** The VPS path runs `tools/backup.py` on a schedule. On Render, add a Cron Job
service running `python -m tools.backup --dest /app/data/backups --keep 14` and, when it
matters, copy those off the box — a snapshot on the same disk survives a bad deploy but not
a lost disk.

## What a seeded city looks like

Once a city has places, the guide views are what people actually read:

```
GET /v1/city/guide?city=Lisbon&view=trails
GET /v1/city/guide/views            # trails, vinyl, food, literary, culture, wellness
```

Each view draws on two things and nothing else: the OpenStreetMap places for its categories,
and the meetups and listings whose titles genuinely mention it. A city with no trails mapped
says so — and says *which* half is missing, because "OpenStreetMap has no trails here" and
"nobody has proposed a walk" need different fixes.

Two of these have no source at all and say so rather than approximating: **live footfall**
needs sensors nobody has installed, and **editorial press** would mean scraping publications
with no agreement to do so. The press endpoint instead looks for a feed a site actually
publishes, which is the same content offered rather than taken.

## Letting other things talk to it

API keys, webhooks and the plugin registry are real — see `docs/DEVELOPER.md`. Two things
worth knowing as the operator:

- **An API key authenticates as the account that issued it.** It is a full credential for
  that account, not a read-only side channel, unless the issuer scoped it to `read`.
- **Webhook targets are fetched by your server**, so they go through the same SSRF guard as
  venue feeds: private and link-local addresses are refused. Leave
  `LIFEOS_ALLOW_PRIVATE_FETCH` unset on anything reachable from the internet.

## Checking everything works

```sh
python -m pytest              # 1270, and CI runs the same on 3.11 and 3.13
```

For a live instance, the honest check is to walk it: register two accounts on two phones,
have one create a public crew, have the other find it in the directory and join, publish an
event, and read `/v1/weekend`. That path is what the end-to-end journey script exercises, and
it is where the last two bugs were found — both at seams no unit test covered.

## Seeding a city

A city has something in it before anybody arrives, because third places come from
OpenStreetMap and the weather comes from Open-Meteo. **Neither needs a key** — they are the
first external sources in this repo that need no configuration at all.

**Cities seed themselves, with content.** The first person to arrive somewhere unseeded
queues it, and the seed runs after their response has gone out. What lands is everything a
city can have with nobody in it:

| | source | key needed |
|---|---|---|
| Places, all ten categories | OpenStreetMap | none |
| Conditions and tonight's triggers | Open-Meteo | none |
| Ticketed listings | Ticketmaster | `LIFEOS_TICKETMASTER_KEY` |

Without the Ticketmaster key the first two still land, and the third reports
`not_configured` rather than failing. A city the geocoder cannot place is asked about once
and then left alone — no second lookup, no daily retry.
 The first person to arrive somewhere unseeded queues it, and the
seed runs after their response has gone out — so they see the empty city they landed in, and
the next person finds it on the map. You do not have to do anything per city.

The guardrails matter, because this is the only place where a user typing a name makes your
server call a third party:

- a name that geocodes to nothing is asked about **once**, not daily;
- a real city is refreshed at most every 30 days;
- **six cities an hour**, globally — a burst queues instead of fanning out;
- one at a time, never in parallel.

`GET /v1/seeding/queue` shows what is waiting and what was tried. `POST /v1/seeding/drain`
seeds queued cities and is safe to run from a Render Cron Job — worth adding, because the
background task runs in-process and a deploy mid-seed leaves a city queued until something
picks it up.

You can still seed a city by hand, and it is the right thing to do for a city you know you
are about to launch in. Seeding writes public rows, so it is operator-only. With your gateway
token:

```sh
curl -X POST https://<your-app>.onrender.com/v1/seeding/city-bootstrap \
  -H "Authorization: Bearer $LIFEOS_GATEWAY_TOKEN" \
  -H "Content-Type: application/json" -d '{"city": "Lisbon"}'
```

That pulls cafés, climbing walls, viewpoints, parks, libraries, galleries, markets, trails,
swim spots and saunas into the graph, and syncs any venue feeds you have subscribed. Running
it again **updates rather than doubles** — it is deduped by OSM id, because an operator
running it twice is the expected case.

Anyone can then read `GET /v1/city/places?city=Lisbon`, and the City tab shows them on the
arrival screen. Opening hours appear only where OSM has them; nothing is independently
verified and the response says so.

Be a good citizen of Overpass: it is volunteer-run and free. One city at a time, not a loop
over every city you can think of.

## Turning things on later

| Variable | Effect when unset |
|---|---|
| `LIFEOS_GOOGLE_CLIENT_ID` / `LIFEOS_APPLE_CLIENT_ID` | sign-in offers password only |
| `LIFEOS_RESEND_KEY` / `LIFEOS_MAIL_FROM` | no email sign-in, no password reset |
| `LIFEOS_TICKETMASTER_KEY` | Tier 2 listings contribute nothing; venue feeds still work |
| *(no variable)* | OpenStreetMap places and Open-Meteo weather need no key and are always on |
| `LIFEOS_SEED_CITY` | the app starts empty |
| `LIFEOS_DATING_ENABLED` | `/v1/dating/*` returns 503 — leave it empty until you mean it |
| `ANTHROPIC_API_KEY` | everything works; nothing gets smarter |

Nothing in that table errors when it is missing. That is the rule the codebase is built on.
