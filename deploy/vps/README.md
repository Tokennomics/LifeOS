# Life OS on a VPS

The runbook for putting Life OS on a public box. This is the deployment target; the NucBox
path (`deploy/docker-compose.yml`, `deploy/nucbox-install.ps1`) stays as the personal /
offline option.

**Two steps are yours and cannot be automated from here:** provisioning the box and pointing
DNS at it. Everything after that is `docker compose up`.

## 0. What you need first

- A VPS (1 vCPU / 1 GB is enough to start — this is SQLite and a Python process).
- A domain, with an **A record** (and AAAA if the box has IPv6) pointing at its IP.
  Do this *before* the first start: Caddy asks Let's Encrypt for a certificate on boot and
  the challenge fails if the name doesn't resolve to the box yet.
- Docker + the compose plugin.

## 1. Harden the box before it holds anyone's data

```sh
adduser lifeos && usermod -aG docker lifeos      # don't run this as root
# SSH: keys only
sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#*PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
systemctl reload ssh

ufw default deny incoming && ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw enable
```

Nothing else should be reachable. In particular **8787 is never exposed** — `compose.yml`
deliberately has no `ports:` on the gateway, so it exists only on the compose network with
Caddy in front. If you ever find yourself adding `-p 8787:8787` to debug something, use
`docker compose exec` instead; publishing it puts bearer tokens on the wire.

## 2. Configure

```sh
git clone https://github.com/Tokennomics/LifeOS.git && cd LifeOS/deploy/vps
cp .env.example .env && chmod 600 .env    # then edit it
mkdir -p backups && sudo chown 10001:10001 backups   # the container's non-root uid
```

`.env` is gitignored and must stay that way. **No secrets in the repo, ever** — the compose
file only ever names variables, never values.

Generate the gateway token **and the signing key** — two different values, neither invented
by hand:

```sh
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # LIFEOS_GATEWAY_TOKEN
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # LIFEOS_SIGNING_KEY
```

`LIFEOS_SIGNING_KEY` has **no default on purpose**. `/v1/security/verify-token` returns 503
rather than `valid: false` when it is missing, because "cannot check" and "checked and
rejected" are different facts and collapsing them is how a broken deployment looks healthy.

## 3. Start

```sh
docker compose up -d --build
docker compose logs -f caddy      # watch the certificate get issued
curl https://your.domain/health   # {"ok":true,...}
```

`/health` is the only route that answers without credentials, and it reports liveness only.
Anything that counts what's inside the instance lives behind auth on `/v1/stats`.

## 4. Verify the backups — before you need them

The `backup` service snapshots every 6 hours and keeps 14. It uses `VACUUM INTO`, because
copying a live SQLite file in WAL mode can produce a database that restores corrupt (see
`tools/backup.py`). Every snapshot is integrity-checked as it is taken.

```sh
docker compose logs backup                 # each line: path, size, row counts
docker compose run --rm backup python -m tools.backup --dest /backups --keep 14
```

**Get them off the box.** A backup on the same disk as the database is not a backup:

```sh
# from your laptop, in cron
rsync -az lifeos@your.domain:~/LifeOS/deploy/vps/backups/ ~/lifeos-backups/
```

**Restore** (a snapshot is a plain database — nothing to unpack):

```sh
docker compose stop gateway bot
docker compose run --rm -v "$PWD/backups:/backups" gateway \
  sh -c 'cp /backups/lifeos-YYYYMMDDThhmmssZ.db /app/data/lifeos.db'
docker compose start gateway bot
```

Do a restore drill once, now, while nothing is at stake. An untested restore is a guess.

## 5. Point the app at it

In the PWA (⚙ Settings) and the Android app, set the gateway URL to `https://your.domain`.
Then register the first account — until one exists the gateway runs in single-owner mode:

```sh
curl -X POST https://your.domain/v1/auth/register \
  -H 'content-type: application/json' -d '{"handle":"you","password":"..."}'
```

Once any account exists, callers must log in; the configured owner token keeps working so
the bot and local scripts don't break.

## Updating

```sh
git pull && docker compose up -d --build
```

The schema migration runs at container start and is idempotent. Take a manual snapshot
first if the release touched `substrate/`.

## What this deliberately does not do

- **No Postgres.** SQLite in WAL mode is fine well past the first users. `substrate/graph.py`
  already parameterises the dialect, so the port is real when it's needed — but do it because
  a measurement said so, not because a VPS felt like it deserved a bigger database.
- **No horizontal scaling.** One box, one SQLite file. Adding a second gateway container
  would need a shared database first; that is the same decision as above.
- **No secret management beyond the environment.** A `.env` with `chmod 600` on a box only
  you can SSH into is proportionate. If that stops being true, it's Vault-shaped, not
  a-slightly-cleverer-file-shaped.
