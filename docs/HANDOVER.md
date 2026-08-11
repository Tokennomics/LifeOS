# Handover — next session start here

_Rewritten 2026-07-26, updated 2026-08-04. This is the 60-second version; `docs/STATUS.md` is the
fuller picture and `docs/ROADMAP.md` is the parked map. Where any document and the code disagree,
**the code wins** — and after the Antigravity expansion below, assume the code is ahead._

## Context

Owner is travelling, **phone-only, no NucBox access**. Working rules, still in force:
small diffs, **one ticket per PR**, stop and report after each — do not chain tickets.
`substrate/graph.py` is the only write path; every write carries scope + provenance.
The v0 schema is final — extend via `attrs` JSONB only. Every feature works with **no API key**
and improves with one. **No secrets in the repo, ever.** Tests pass before every commit.

Branch: `claude/lifeos-repository-connection-lfeqba` (always; never push elsewhere without
explicit permission). **PRs #1–#16 are merged; #17 (erasure + sign-in) is open.** `python -m pytest` → **976 passing**.

## READ FIRST: the repo doubled while these sessions were idle

Between **2026-07-29 and 08-04** the owner built 43 commits with **Antigravity**, not here:
**+10,514 lines, 18 new modules, 205 endpoints**, tests 246 → 446. `docs/` did not move with it,
so anything below that predates 08-04 describes a smaller system than the one on disk.

**Good news, and it was verified rather than assumed:** all four architectural invariants held.
Schema unchanged, `KINDS`/`RELS` unchanged, zero writes outside `substrate/`, no secrets, no
module needing an API key. **T2 reconciliation finally exists** (`modules/travel/reconcile.py`,
`POST /v1/import`, replay-tested) — it had been deferred since the first brief.

**Three things to know before trusting it:**

1. **Test coverage is uneven.** The count is concentrated in the older core plus
   `venues`/`routines`. `finance`, `health`, `telemetry`, `notifications` and `calendar` still
   have no test file. `security` and `dating` were the two worst and are now covered, which
   leaves **`comms` as the one untested module touching a trust boundary — cover it next.**
2. **`modules/dating` is now finished and gated** — it used to be broken across accounts and
   ungated. See "Dating" below for the shape and the one thing left to do.
3. **A signing key was published in the repo and is now fixed** — see below.

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
| **Weekend digest** (`GET /v1/weekend`, `/weekend/share`) | shipped |
| **Venue feeds** — ICS/RSS ingest + discovery + seed packs | shipped |
| **Scheduled feed refresh** (`tools/feedsync.py`, compose service) | shipped |
| **Tier 2 event APIs** (`modules/feeds/providers/`) | shipped, off without a key |
| Cross-account discovery / membership / **scheduling** | shipped (#8, #9, **#10**) |

Only two things the owner can actually *use* today are Travel Mode and the APK. Everything in the
social layer is exercisable only in the test suite until there is a reachable host.

## The VPS — **written; two steps are the owner's**

Everything below was the ticket, and `deploy/vps/` now implements it: `compose.yml`, `Caddyfile`,
`.env.example`, a runbook, `tools/backup.py` (+8 tests), a non-root `Dockerfile`, and `/health`
slimmed to liveness with counts moved behind auth on `/v1/stats`. Smoke-tested against a running
gateway, including taking a snapshot of the live WAL-mode database while it was open.

**What is left, and cannot be done from here: provision the box and point DNS at it.** Then
`cd deploy/vps && cp .env.example .env && docker compose up -d --build`. DNS must resolve *before*
the first start or the ACME challenge fails.

<details><summary>The original ticket write-up, kept for context</summary>

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

</details>

**After the VPS:** T2 reconciliation (`POST /v1/import` — ingest the Travel Mode bundle with
original timestamps + idempotency keys; format `lifeos-travel-export/v1`, see `buildBundle()` in
`travel.js`; test the double-import replay case). The owner deferred it until he's home, but it
stops being NucBox-shaped once there's a server.

## Dating — built, gated, off

Three of the five Phase 3b kill-gates are now written; the two that code cannot satisfy are
enforced by a kill switch rather than by discipline. `LIFEOS_DATING_ENABLED` defaults to off
and every entry point calls `gate.require_surface()` first.

- **Matching never reads anyone's data.** The old version asked `find_entities` for the other
  party's `dating_intent`; that is owner-scoped, so it always returned nothing and every match
  was `is_mutual: False`. Both obvious fixes are wrong — `find_public` publishes to the world by
  design, and `get_if_granted` needs a grant that neither side can have *before* matching.
  Instead each side publishes a **blinded rendezvous digest**, an HMAC of `(from, to, activity)`
  under `LIFEOS_SIGNING_KEY`, and mutuality is "does the digest the other side would have
  published exist?". You can only compute it for a pair you already name.
- **The published rows are system-owned on purpose.** If they were owned by their authors, a
  full scan of `find_public` would be a directory of everyone looking for a date. Owned by the
  system account, a full scan is a count.
- **Age is a self-declared 18+ that fails closed, and the ROADMAP's old claim that this needs a
  third party was wrong** — see the correction in ROADMAP Phase 3b. `method` is recorded on every
  declaration so a stricter provider drops in without a migration. The DOB is checked and
  discarded; only `adult: true` is kept.
- **Safety is account-to-account, not crew-scoped.** `crews.report` files against a `crew_id`;
  a date has no crew, and the thing worth reporting usually happens after everyone has left it.
  Filing a report blocks the pair immediately — the property has to hold on a day nobody
  services the queue — and resolving the report does not lift the block.
- **Left to do: G0 (this host) and G4 (≥2 people who asked).** Then set the flag. Nothing else.

## The weekend digest — and the thing it can't do

`GET /v1/weekend` answers "what's on this weekend?" from three sources that already exist:
public social events across accounts (`find_public`), your own confirmed meets and ICS
blocks (owner-scoped), and public crews in the city. `GET /v1/weekend/share` renders the
same weekend as plain text to send someone — **with your own plans left out unless
`include_yours=true`**, because there is no version of "here's what's on" that should carry
your dentist appointment to a friend.

**Where its content comes from — and the rule that governs it.** Owner's call, 2026-08-05:
an empty directory is the real failure mode, so aggregating events is now wanted rather than
forbidden. Tier 1 (**ICS/RSS venue feeds**) is built — see below. Tiers 2 and 3 (official
APIs, then scrapers) are in ROADMAP under "Event aggregation", which supersedes the old
Ticketmaster Don't-build entry.

The condition attached to all of it: **aggregated listings must stay distinguishable from
crew nights.** Every ingested event carries `origin: "feed"` and its `venue`, and the digest
renders `· listed`. GROWTH.md's atomic network is *one crew that actually meets twice*, and a
wall of listings looks identical whether that has happened or not. Keep the label.

An empty digest is still an honest report that nobody published anything — it says so, and
names the crews who could.

Two behaviours worth knowing before editing:

- **Mid-weekend it trims.** Opened at 15:00 on Saturday it shows what's left, not what you
  missed, and the header changes to "rest of the weekend". The cut is two hours *after* an
  event starts, not at the start — a club night at 23:00 is still the answer at 23:45.
- **It lists everything on, not just what scores.** `discover.rank_feed` drops items that
  are neither interest-matched nor popular, which is right for an infinite feed and wrong
  for a finite weekend. Ranking sets the order here; it never sets the membership.

## Venue feeds — `modules/feeds/`

Subscribe to a venue's ICS or RSS calendar; sync turns it into public events the weekend
digest and the discover feed both pick up. No API key, no scraping — a published feed is
published *to be* read, which is the whole difference from ROADMAP's Tier 3.

- **The subscription is yours; the events are everyone's.** A `venue_feed` record is
  owner-scoped (you added it); the events it produces are SYSTEM-owned and public, so one
  city's listings exist once rather than per account.
- **Dedupe is global on `(feed url, item uid)` and deliberately excludes who subscribed** —
  otherwise two people following the same venue double every event in the city.
- **`pubDate` is never an event date.** It is when a listing was *posted*. An RSS item with
  no determinable start is dropped and counted in `skipped_no_date`. A wrong date is
  invisible to the reader forever; a skipped item shows up in the sync report. Only
  unambiguous ISO dates are read out of text — `08/07/2026` is two different days depending
  on where you live, and guessing is how an aggregator loses trust.
- **A date lifted out of a title is removed from it.** `Late tour 2026-08-09T21:00` reads
  like a machine wrote it. Found by reading the digest, not by a test.
- **A dead venue is recorded, never raised.** `sync_all` reports per-feed status; one bad
  feed does not stop the others. `sync(feed_id, text=...)` bypasses the fetch, which is how
  the tests run and how an import works on a connection that blocks everything interesting.
- Bounded per sync: `MAX_ITEMS` per feed, and a horizon of `STALE_DAYS` back to
  `HORIZON_DAYS` forward, so a venue publishing its whole archive does not import it.
- **`POST /v1/feeds/discover` takes a venue's *website*, not its feed URL.** Nobody knows
  their favourite bar's `.ics` link, which made populating a city a page-source safari —
  i.e. a task that quietly never happens. It reads the standard
  `<link rel="alternate">` advertisement, ranks ICS above RSS (ICS states when an event is;
  RSS only sometimes does) and the events feed above the blog and comments feeds.
  **It proposes and does not add** unless asked: a page can advertise a dozen feeds and only
  a human knows which is the gig calendar. Query-string feeds count — Squarespace's
  `?format=rss`, The Events Calendar's `?ical=1`, WordPress's `?feed=rss2` — because a
  path-only check silently misses whole platforms.

### Seed packs, scheduling, Tier 2

- **`seeds/<city>.json` holds venue WEBSITES, not feed URLs**, and `POST /v1/feeds/seeds/<city>`
  subscribes to the lot. **No real packs are committed and that is deliberate** — verifying a
  URL means reaching it, and a pack of guessed addresses is a list of 404s that reads as
  "broken feature" rather than "unseeded city". `seeds/README.md` has the assembly recipe;
  `example.json` is the format. **The first real pack is the owner's to make**: paste 10–20
  venue websites once there is a box, check `last_status` on each, drop the ones that
  produced nothing, commit what is left.
- **`tools/feedsync.py` + the `feedsync` compose service refresh on a loop.**
  `--interval` is a *politeness floor*, not the loop period: a feed fetched more recently
  than that is skipped, so a crash-looping container cannot hammer a small venue's server.
  Skipped feeds are reported, so a scheduler doing nothing looks different from one that is
  not running. Ingested content that silently goes stale is worse than less content — the
  digest looks identical either way until someone turns up on the wrong night.
- **Tier 2 providers degrade, they never error.** `modules/feeds/providers/` is a registry;
  Ticketmaster is the first. No key ⇒ `not_configured`, zero writes, and the rest of the
  product is untouched. Its coverage is ticketed and mainstream — it finds the arena show
  and misses the basement party, which is the gap seeded venue feeds are for. **Provider
  events go through the same path as feeds**: system-owned, public, `origin: "feed"` so
  they render `· listed`, namespaced dedupe key so a venue ICS `uid` cannot collide with an
  API id. A provider is a new `search()`, not a new architecture.

**Not verified from here: any real external fetch.** The sandbox proxy 403s arbitrary hosts,
so neither a live venue calendar nor api.ticketmaster.com has been called. `_fetch` was
exercised against a reachable URL (bytes, redirects, `raise_for_status`, non-feed content
parsing to zero items rather than raising), and the Ticketmaster response shape is coded
from the documented `_embedded.events[]` structure against recorded-shape fixtures — which
is why `normalise` tolerates every level being missing or the wrong type. **Treat the first
real call as the test.** The failure mode is an empty result and a recorded status.

## The pre-hosting security audit (2026-08-05) — read before exposing this

Eight holes, every one **demonstrated against a running gateway with two real accounts**
before it was touched, and every one now covered in `tests/test_security_audit.py`. The
pattern worth internalising: **six of the eight were authorisation done on data the caller
supplied.** Nothing was wrong with the substrate — owner scoping held everywhere — the
gateway simply handed it the wrong identity.

- **CRITICAL — crew takeover.** `crews._require_admin` compared the ACL against `by`, which
  came straight off the request body. *Naming* the admin was the same as *being* the admin,
  and the public roster hands out the admin's account id. Verified: a signed-in stranger
  blocked a crew's owner from her own crew, members 1 → 0, admins emptied. **Every actor
  parameter is now pinned to the session** (`_actor` / `_actor_opt` in `modules_api.py`);
  a body id that disagrees with the session is a 403, not a silent override. **Targets are
  not actors** — `person_id` in "invite this person" still comes from the body.
- **HIGH — `/v1/export` and `/v1/graph` crossed the tenant boundary.** `entities` was
  owner-filtered; `edges` and `observations` were not. Every account's export carried a
  provenance row for every write on the box. Neither table has an `owner_id` and the v0
  schema is final, so both are scoped by joining back to owned entities.
- **HIGH — SSRF.** Three features fetch a URL a user chose. `169.254.169.254` hands out
  instance credentials on Render, Fly, AWS, GCP and DO alike. All outbound fetches now go
  through `substrate/safefetch.py`, which judges the **resolved address** (not the hostname —
  `127.0.0.1` has a thousand spellings) and **re-checks every redirect hop**.
- **HIGH — no brute-force protection.** `gateway/rate_limiter.py` existed, claimed to defend
  against "brute-force authentication", and was imported by nothing. 60 wrong passwords, 60
  clean 401s. Now wired into login (10/5min), registration (5/hr) and the fetch endpoints.
  It was also a process-global singleton whose counters outlived the app that made them; it
  is per-app now.
- **HIGH — sender spoofing** in chat, chatroom, RSVP, convoy location and milestones.
- **MED — signup is open.** Rate-limited now, still open by design; that is a product call.

**Still open, and it is functional rather than a leak: direct messages cannot be delivered
across accounts.** `chat.send_message` writes into the *sender's* owner slice and
`get_messages` reads owner-scoped, so only the sender ever sees the message — the same shape
as the dating bug. Inert, not leaky. Fix it the way dating was fixed (a shared home plus
grants, or a blinded rendezvous), **not** by reaching for `find_public`.

### Round two (2026-08-07), after `main` gained 80 more Antigravity commits

Found by **sweeping every POST body field that names an identity** rather than reading
thirteen new modules — that sweep is kept as a test (`test_every_identity_field_in_the_whole_api_is_pinned`),
so a new endpoint taking an identity from the body now fails in CI instead of in production.

- **CRITICAL — the moderation queue was readable and resolvable by anyone, including the
  person reported.** Mallory could read Ana's account of being followed home from a bar,
  see that Ana filed it, and then dismiss it — queue to zero, reporter never told. This was
  **my** code from the G3 work, and it is worse in kind than the crew takeover because it is
  a physical-safety feature failing open. Moderation is now `_operator` only: the static
  gateway token, or an account listed in `LIFEOS_MODERATOR_ACCOUNTS`. **The reporter cannot
  read the queue either** — "who else has complained about this person" is not hers.
- **HIGH — ballot stuffing.** `/v1/venues/vote` took `member_id` from the body, so one
  account could cast every member's vote in a crew's venue poll.
- **HIGH — forgeable audit log.** `/v1/security/audit-log` took `actor_id` from the body.
  The audit log is what you read *after* an incident; anyone could write false entries
  attributed to anyone.
- **MED — `/v1/miniapp/resources`** registered a resource owned by someone else.

**Also: `main` did not parse on Python 3.11**, which is what CI pins — an f-string in
`modules_api.py` contained a backslash (legal only from 3.12). The gateway would not have
started. Fixed, and every `.py` in the repo is now checked to parse under 3.11.

**Good news from this round:** the "grants are not owner-authenticated" gotcha that stood in
this file for weeks **has been closed at the substrate** — forging a grant now raises
`ScopeError`. And `modules/comms` gained its own caller check plus working cross-account
delivery, so the DM bug is fixed too.

## Erasure — `DELETE`-my-account, and the four categories it has to tell apart

Export shipped with Law 2; erasure did not, which made "the graph is the user's" half true —
you could take a copy of everything and remove none of it. `POST /v1/auth/account/erase`
closes that, and `substrate/graph.py` gained the first delete path it has ever had
(`delete_entity`, `purge_owner` — additive, and deletes go through the substrate for the
same reason writes do: edges and provenance live in tables with no foreign keys).

**The design is entirely in the four categories, which are not treated alike:**

1. **Yours alone** — captures, goals, feeds. Deleted via `purge_owner`.
2. **Yours but SYSTEM-owned** — the dating age declaration, rendezvous handshakes, block
   rows. Deleted too. Handshakes are found by *recomputing the digests this account could
   have produced*, because the row names nobody by design.
3. **Shared** — crew and coordination grants are revoked, so you vanish from every roster.
   **The crew survives**: it is other people's too.
4. **Abuse reports — pseudonymised, never deleted.** If erasing an account wiped the record
   of what that account did, deletion becomes a feature for the wrong person. Art. 17(3)(e)
   permits retention for legal claims, so the report text stays and the ids in it become a
   one-way `erased:<digest>` marker — stable enough that two reports about the same erased
   account still line up, useless for identifying anyone.

**Guards:** the password is required *again* even though the caller holds a valid token (a
borrowed phone must not be able to erase a life), and the handle must be typed into
`confirm`. `GET /v1/auth/account/erase-preview` shows what would go, first.

**Stated rather than hidden:** database snapshots taken before an erasure still hold the
data until they rotate out. Art. 17 is "without undue delay", not "instantly, everywhere" —
`RETENTION_NOTE` says so and it is returned in the receipt.

## Ways in — one account, several identities

An account is now separable from the way you prove you own it: `password`, `google`,
`apple`, `email`, `phone` are all `auth_identity` rows pointing at one account, so signing
in on a new phone reaches the same graph.

**The one rule, and it is the whole security of this: identities are NEVER auto-linked by
email.** "You already have an account with this address, let me connect them" is the obvious
convenience and the classic takeover — register the victim's address at a provider with weak
verification, sign in, inherit the account. So an unrecognised identity creates a **new**
account even when the email matches, and connecting a second way in is an explicit act
**while already signed in** (`POST /v1/auth/identities`). The cost is a user who signs up by
email then taps "Sign in with Google" gets a second empty account; that is confusing but
recoverable, and the alternative is not.

- **`modules/auth/rs256.py` verifies RS256 by hand, deliberately.** `cryptography` (which
  PyJWT needs) does not load in the dev sandbox, so the choice was a dependency plus
  *untested* signature verification, or a tested implementation with none. This repo has
  been bitten three times by controls that were real on paper — that would have been the
  fourth. It is defensible for this one primitive: verification uses only public values, so
  there is no timing channel and no key to leak, and the historic flaw (Bleichenbacher '06)
  comes from *parsing* the PKCS#1 block leniently — this rebuilds the whole expected block
  and compares it, so there is nothing to be lenient about. There is a test for that exact
  forgery shape. To swap in a library verifier later, keep `verify_rs256`'s signature.
- **`alg` is never read from the token.** The header is attacker-controlled; honouring it is
  how `alg: none` works. RS256 is assumed because that is what both providers issue.
- **`aud` is checked.** Skipping it turns "sign in with Google" into "sign in as anyone" —
  any other app's token would be accepted.
- **`email_verified` is load-bearing.** An unverified email is something the user typed; it
  is dropped and only the opaque `sub` is used.
- Unlinking your **last** identity is refused. Passwordless accounts have an empty
  `password_hash` and `_verify_password` refuses empty hashes outright, so they cannot be
  entered with a blank password.

**Not built yet: email and phone delivery.** The `email` and `phone` identity kinds work and
are linkable, but there is no one-time-code sender — that needs an SMTP/SMS provider, which
is the first thing here to need a real secret and a bill. `password reset` is the same
missing piece and should be built with it.

## Round three (2026-08-07) — walking the product, and probing my own code

**43-step end-to-end journey**, signup to erasure, through real HTTP. It found two things
the 865-test suite did not, both at seams rather than inside modules:

- **`/v1/auth/providers` needed a token** — it sat on the authed router, so a client had to
  be signed in to discover how to sign in. The sign-in screen could not render.
- **`/v1/crews/join` returned "unknown crew"** for a crew listed in the directory a moment
  earlier. `crews.join` (local: an owner adding someone from their own graph) and
  `crews.request_join` (cross-account) are both correct — the trap was that the
  obvious-sounding endpoint was the wrong one, with a misleading error. `join` now falls
  through to `request_join` for a crew outside the caller's slice; that grants nothing, it
  is the same narrow write already reachable at `/v1/crews/request`.

**Round-three security probe** (GETs, resource limits, and the erasure/identity code I wrote
myself — rounds 1-2 only swept POST bodies):

- **MED — no request body cap.** A 2MB capture was accepted and stored whole; a signed-up
  user could fill the disk, which on a small hosted box takes down everyone's instance.
  One middleware, `MAX_BODY_BYTES`, 413 past it.
- **HIGH — a pre-positioned takeover in my own identity code.** Linking an `email` identity
  proved nothing about owning the address, so an attacker could link `victim@example.com`
  to their own account **today** — and on the day an email sign-in ships, the victim would
  authenticate with their real address and land inside the attacker's account. `link()` now
  refuses `email`/`phone` without `verified=True`, which nothing in the API can set yet.
  Google and Apple are exempt: their `sub` arrives inside a signature we verified.

Clean afterwards: no IDOR through 11 templated GET paths or any GET query param, erasure
cannot be aimed at another handle, identities cannot be stolen or unlinked across accounts,
errors leak no internals, and `/health` plus `/v1/auth/providers` are the only routes that
answer without a token.

## Audit round four — one critical, eight broken endpoints

Found by **sweeping all 425 endpoints as a signed-in user**, which nothing in the suite had
ever done. That sweep is `POST`/`GET` with an empty body against every path in the OpenAPI
schema, counting 5xx. It is worth re-running after every merge from `main`.

**CRITICAL — any signed-in user could destroy the whole instance.** `POST /v1/graph/restore`
is an ordinary authenticated endpoint with no operator gate, and `substrate/backup.py` ran
`DELETE FROM edges; DELETE FROM observations; DELETE FROM entities` with **no owner
predicate**, then inserted `backup_data`, which for a `{}` body is nothing. Demonstrated
before fixing: a second account posted an empty body, the first account's graph went to zero,
and she could no longer log in — accounts are entities too. `export_backup` was the same hole
pointed the other way, dumping every user's graph to anyone with a login. Both are
owner-scoped now, and restore goes **through `substrate/graph.py`** instead of around it, so
it cannot name someone else's `owner_id`, invent a kind, or skip provenance.

The pre-existing `tests/test_backup.py` passed throughout — it asserted that restoring an
empty backup returns 200, which *is* the wipe. A test can encode the vulnerability.

**Eight endpoints had never worked**, each calling a function its module does not define:
`export_graph_topology`, `get_mindfulness_summary`, `Graph.all_entities`, and
`discover.create_event` (three call sites), plus `/v1/people/qr` looking up entity kind
`identity`, which is not in `KINDS`. All 500'd or 400'd on every call, including the PWA's
live "Export CSV" button.

**`find_topology_hubs` is the one to read before touching.** It counted `SELECT src, dst FROM
edges` with no join and resolved every node's name — every user's people and goals. It was
unreachable behind the wrong function name, so the *obvious* fix (correct the name) is what
would have shipped the leak. Scoping was the fix; the rename was incidental.

Two smaller ones: the CSV export now defuses spreadsheet formula injection (a person named
`=HYPERLINK(...)` executes on open in Excel), and two handlers raised bare `ValueError` for a
missing field, which reached the client as a 500 rather than a 400.

## Email verification, and the secret-scanning alert

**A GitHub secret-scanning alert fired on `gateway/modules_api.py` for a Stripe webhook
signing secret.** Nothing real leaked — this repo has never integrated Stripe, and the value
was invented by a generated commit on `main`. But it was spelled in Stripe's reserved
namespaces, which is what a scanner reads as a live key. The alert also undersold the actual
defect: all three `/v1/developers/*` endpoints returned the *same* constant to every caller,
and a shared signing secret authenticates nothing. Credentials are minted per call now
(`_issued_credential`), and `tests/test_security_audit.py` scans every tracked file for
eleven vendor credential prefixes so the next one fails in CI instead of in an email.

**Email verification exists** (`modules/auth/otp.py` + `modules/auth/mailer.py`), which
finally unlocks the `verified=True` seam `identities.link()` has been refusing since it was
written. Three flows: sign in with a code, link an address to an account you already have,
and reset a forgotten password. The security is not the six-digit code — a million values is
nothing — it is the attempt cap, the ten-minute expiry, single use, and a per-address
issuance cap so nobody can use us to mail-bomb a stranger.

**The one switch to never turn on in production is `LIFEOS_OTP_ECHO`.** `request_code`
returns the plaintext code when no mail provider is configured, so a laptop stays usable;
`_redact_code` strips it from HTTP responses unless that variable is explicitly set. Without
the strip, `/v1/auth/email/code` — which is unauthenticated by necessity — would let anyone
request a code for any address and read it straight back.

A password reset **revokes every open session** on the account. That is the point rather
than housekeeping: resets follow suspected compromise, and leaving the old sessions alive
means the reset changes nothing for whoever is already inside.

## Browser-side hardening

The gateway sent **no security headers at all**. It now sends a CSP, `nosniff`, `DENY`,
`no-referrer` and COOP on every response. Read the CSP honestly: `script-src` has to keep
`'unsafe-inline'` while the PWA carries ~950 inline styles and ~20 inline handlers, so it
does **not** stop an injected script running. What it does stop is what follows —
`connect-src 'self'` means an injected script cannot post the localStorage session token
anywhere, and `base-uri`/`object-src`/`frame-ancestors` close the rest.

**Known gap, needs a machine that can reach the internet:** the map loads Leaflet from
`unpkg.com` with no Subresource Integrity hash, into the origin that holds the session
token. The fix is to vendor `leaflet.js`/`leaflet.css` into `surfaces/app/www/vendor/` and
serve them locally — the sandbox proxy blocks unpkg, and writing an SRI hash from memory
that turns out wrong silently kills the map, so it was left alone rather than guessed at.

## Hosting — see `docs/HOSTING.md`

**Render if you are on a phone** (a browser, `render.yaml`, ~$7/mo + disk), **Hetzner if you
have a terminal** (~€4/mo, `deploy/vps/`). Friends get one URL — `/app/` — and nothing to
configure: the PWA is served by the gateway and talks to its own origin.

Three things found while writing this, all of which would have bitten on first deploy:

- **`scripts/launch.py` bound `127.0.0.1` unconditionally** — which is the Dockerfile's
  `CMD`. In a container the process starts, the logs look healthy, and nothing outside can
  reach it. It now honours `PORT` and flips to `0.0.0.0` when `PORT` is set (how every PaaS
  says "you are in a container"); an explicit `LIFEOS_HOST` still wins.
- **CI pinned Python 3.11 while the Dockerfile shipped 3.13** — CI was not testing what
  deploys. Now a matrix over both.
- **The disk is not optional on Render.** One SQLite file; no disk means every deploy resets
  to empty, and the free tier has no disks *and* sleeps, which also breaks ACME renewal.

`LIFEOS_SEED_CITY=lisbon` loads a committed pack on boot — subscribe only, never fetch (a
boot that waits on twenty venue servers fails its health check), and a bad pack is swallowed
rather than blocking startup.

## Gotchas — read these before touching anything

- **`LIFEOS_SIGNING_KEY` has no default, deliberately.** `modules/security/crypto_tokens.py` used
  to default to `"lifeos_secret_key_2026"`, and the gateway verified with it — a published HMAC
  key signs nothing, and anyone with the repo could forge a payload. The key now comes from the
  environment only; the old value and other placeholders are refused **by name** so it can't be
  restored from git history; short keys are refused. **Never add a fallback to make a test pass —
  the fallback is the vulnerability.** `/v1/security/verify-token` returns **503, not
  `valid: false`**, when unconfigured, because "cannot check" and "checked and rejected" are
  different facts. Set it in `deploy/vps/.env` alongside `LIFEOS_GATEWAY_TOKEN`.

- **`travel-stats.js` is Travel-only and has NO Python twin** — unlike `horizon-core.js`. Editing it
  alone is correct; editing `horizon-core.js` alone is not (see below). Its checks live in
  `tests/travel/run_stats.mjs`, run by `tests/test_travel_stats.py`.
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

Convoy · Memento · Steward · Seasons · Vitals · Ledger · Hearth · Calibre ·
Google OAuth · Postgres migration (until measured, see above) · native store builds · SDK opening ·
billing · licence/entity/ToS content · a swipe-style dating surface · sub-city location anywhere in
the social layer.
