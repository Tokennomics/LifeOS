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

They tap **Register**, pick a handle and a password, and they are in.

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

## Being the operator

Your `LIFEOS_GATEWAY_TOKEN` is also your moderator credential — abuse reports at
`GET /v1/dating/reports` and `GET /v1/crews/reports/open` are operator-only, and the token
is how you prove you are the operator. To service the queue from a phone without carrying
that token around, put your own account id in `LIFEOS_MODERATOR_ACCOUNTS`.

**Backups.** The VPS path runs `tools/backup.py` on a schedule. On Render, add a Cron Job
service running `python -m tools.backup --dest /app/data/backups --keep 14` and, when it
matters, copy those off the box — a snapshot on the same disk survives a bad deploy but not
a lost disk.

## Checking everything works

```sh
python -m pytest              # 934, and CI runs the same on 3.11 and 3.13
```

For a live instance, the honest check is to walk it: register two accounts on two phones,
have one create a public crew, have the other find it in the directory and join, publish an
event, and read `/v1/weekend`. That path is what the end-to-end journey script exercises, and
it is where the last two bugs were found — both at seams no unit test covered.

## Turning things on later

| Variable | Effect when unset |
|---|---|
| `LIFEOS_GOOGLE_CLIENT_ID` / `LIFEOS_APPLE_CLIENT_ID` | sign-in offers password only |
| `LIFEOS_RESEND_KEY` / `LIFEOS_MAIL_FROM` | no email sign-in, no password reset |
| `LIFEOS_TICKETMASTER_KEY` | Tier 2 listings contribute nothing; venue feeds still work |
| `LIFEOS_SEED_CITY` | the app starts empty |
| `LIFEOS_DATING_ENABLED` | `/v1/dating/*` returns 503 — leave it empty until you mean it |
| `ANTHROPIC_API_KEY` | everything works; nothing gets smarter |

Nothing in that table errors when it is missing. That is the rule the codebase is built on.
