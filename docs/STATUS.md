# LifeOS — STATUS

_The one-page memory between phone-driven sessions. Update at the end of every PR._

_Last updated: 2026-08-04_

## Where we are

Sprint 1 shipped (substrate + graph.py, gateway, Horizon, VoiceOS, ICS ingest, deploy
scripts). The v0.2 PWA (`surfaces/app/www`, served by the gateway at `/app/`) needs a
reachable gateway; **Travel Mode** (`travel.html`) runs the week from a phone abroad with no
server.

**Tests:** `python -m pytest` → **774 passing** in the cloud env, gated by
`.github/workflows/tests.yml`. (The 2026-07-18 brief said 24 — the code has moved on.)

### The Antigravity expansion (2026-07-29 → 08-04) — read this before believing the rest

43 commits by the owner, built with **Antigravity** rather than in these sessions:
**+10,514 lines, 204 files, 18 new modules, 205 endpoints**, tests 246 → 446. Everything
from `modules/dating` down to `substrate/centrality.py` came from that stretch, and this
file did not move with it — which is why it says so here rather than pretending the arc was
continuous.

**The four architectural invariants held across all of it**, which is the genuinely notable
part and was checked rather than assumed:

- `substrate/schema.sql` / `schema_sqlite.sql` — **unchanged**. v0 schema still final;
  every new module extended through `attrs`.
- `KINDS` / `RELS` / `SCOPE_DOMAIN` — **unchanged**.
- **Zero** `INSERT`/`UPDATE` outside `substrate/`. `graph.py` is still the only write path.
- No secrets committed; no module requires an API key.

**What that expansion added:** T2 reconciliation at last (`modules/travel/reconcile.py` +
`POST /v1/import`, replay-tested); a triage/urgency layer; routines; venues; vault; comms;
finance; health; safety; security; billing; a mini-program registry; and a large set of
graph-analysis helpers in `substrate/` (centrality, clusters, path finding, topology,
integrity, GraphML export, a QA bot).

**Where it is thin, stated plainly so the next session doesn't over-trust it:** the 446
tests are concentrated in the older core and in `venues`/`routines`. `comms` (257 LOC),
`finance`, `health`, `telemetry`, `notifications` and `calendar` have **no test file of
their own**. `security` and `dating` have since been covered (they were the two worst);
**`comms` is now the one untested module that touches a trust boundary**, and is what to
cover next.

### Known-broken, found by running it (2026-08-04)

Both entries that stood here — dating not working across accounts, and dating shipping past
all five of its kill-gates — are **fixed below**. Nothing is currently known-broken. That is
a statement about what has been *run*, not a claim of correctness: `comms` still has no test
file and still touches a trust boundary.

### Fixed since (2026-08-04)

- **Dating: matching rebuilt, and the kill-gates actually enforced.** The reciprocity check
  used owner-scoped `find_entities`, so one account structurally could not see another's
  `dating_intent` — two real accounts both got `is_mutual: False` forever. Neither obvious
  fix works: `find_public` publishes to the world, which is the exact opposite of the
  invariant, and `get_if_granted` needs a grant that neither side can hold *before* the
  match. Now each side publishes a **blinded rendezvous digest** — an HMAC of
  `(from, to, activity)` under `LIFEOS_SIGNING_KEY` — and mutuality is "does the digest the
  other side would have published exist?", computable only for a pair you already name. The
  rows are owned by the system account, so a full scan of them is a population count rather
  than a directory of who is looking. **G1** (the invariant, one test per named attack
  route), **G2** (18+, failing closed, DOB checked and discarded) and **G3** (block/report
  that need no crew and outlive one) are written; **G0** (this host) and **G4** (≥2 people
  who asked) are open and enforced by `LIFEOS_DATING_ENABLED`, which defaults to off.
  The ROADMAP's claim that age assurance "needs a third party" was overstated and has been
  corrected in place — the major services collect a DOB and enforce 18+; ID verification
  appears where a jurisdiction compels it, not as the floor. 77 tests.
  *Two defects came from the narrated HTTP simulation, not the green suite: each side was
  shown the other's declaration date as `matched_at` (two different answers to one shared
  question), and the public row carried a microsecond timestamp — a global "somebody
  declared interest at 21:03:44.118" log that correlates against other public signals to
  undo the blinding. Now the later of the two declarations, and a date.*

- **The payload signing key was published in the repo.** `crypto_tokens.sign_payload` /
  `verify_payload` defaulted to `secret="lifeos_secret_key_2026"`, and the gateway called
  `verify_payload()` without overriding it — so the HMAC key guarding against "token
  tampering and unauthorized data forgery" was a public string, and anyone could mint a
  valid signature. The inverse of the no-secrets rule: nothing real leaked, but a fake key
  was trusted as real. Now `LIFEOS_SIGNING_KEY` from the environment with **no default**;
  the old value and other placeholders are refused *by name* so copying one out of git
  history can't restore the hole; keys under 32 chars are refused. `/v1/security/verify-token`
  returns **503, not `valid: false`**, when unconfigured — "cannot check" and "checked and
  rejected" are different facts, and collapsing them is how a broken deployment reports
  clean verifications. 18 tests, plus the two pre-existing ones updated (they had been
  passing *because* of the default).

## Shipped

- **T1 — Travel Mode.** Standalone offline PWA at `surfaces/app/www/travel.html`. No gateway.
  Persists to **IndexedDB**. Offline Horizon flows mirror the server's deterministic
  fallbacks. Service worker for airplane-mode load; installable; "Travel · local only" badge.
  Publishes to GitHub Pages via `.github/workflows/pages.yml` (shell only — data stays local).
  **Daily-driver hardening:** tap a task to log / tap again to undo; edit the vision & goals
  (rename/add/remove) instead of re-pasting; the retro persists across reload; delete a capture
  or parked idea. Gate honesty fix (server + Travel): `retros_completed` counts distinct weeks,
  so re-running a week's retro can't inflate gate progress.
- **Travel Mode — craft + Journey (2026-07-27).** The single-player product is the foundation the
  network multiplies, so this pass went into the surface actually in daily use.
  - **Journey tab** — the compounding made visible, which is the structural retention advantage a
    graph has over a habit tracker (`docs/GROWTH.md`): days in vs. days shown up, tasks finished,
    longest run, a 12-week activity grid (Monday-aligned, so a column is a real week), per-week
    planned-vs-finished bars, and **recall** — something you wrote on this day of the month, a
    while back, because that is what makes the pile a memory rather than a landfill.
  - **The daily gesture got a body.** A week-progress ring, a pop on the checkbox, a short haptic,
    and exactly one quiet flare when the last task of the week lands — rationed so it keeps
    meaning something. All motion is <500ms and honours `prefers-reduced-motion`.
  - **Share to LifeOS (Web Share Target).** Capture used to cost six steps: unlock, find the app,
    open, Capture tab, type, tap. Now: highlight anything in any app → share → LifeOS → done. That
    matters more than it sounds, because the anti-hindrance sorter only ever fires on things that
    actually got captured. The confirm screen **names the decision before you commit** — "Captured,
    not abandoned — current gate first." when the shared thing classifies as a new-project idea —
    since the distraction sink is most useful at exactly the moment it is least visible.
    `parseShare` is pure and tested against the shapes real Android apps send (title+url; link
    inside `text` with no url; duplicated title; url echoed inside text; pre-joined "title — url"),
    because naive concatenation puts the URL in twice on the one screen whose whole promise is "one
    gesture, no editing". The launch URL is scrubbed via `replaceState`, so a reload or a task
    restore cannot capture the same thing twice — verified in a real browser, along with discard
    writing nothing and a hostile payload rendering as text. Plus a manifest **shortcut**
    (long-press the icon → Capture). **Android/Chrome only:** iOS Safari has no share target and
    degrades to the existing flow; the Capacitor APK would need its own native intent filter, which
    is deliberately not done here.
  - **The coach — a propose-only agent (Phase 1a, autonomy L0).** `travel-coach.js` reads the log
    and returns ranked proposals; Today renders them as cards. **It writes nothing** — accepting is
    the write, and accepting is a tap. All arithmetic, **no API key**. It proposes: draft this week;
    **right-size it** ("you planned 10 and finished 4 — try committing to 1"), which is the piece
    nothing on the market does, since every other tool will happily let you add forty things
    forever; a goal with nothing finished for ≥3 real weeks (measured from ISO week dates, not
    position in the list of weeks you happened to plan); a word in ≥3 *distinct* captures that
    matches none of your goals; and a week that never got its retro. Every proposal carries its
    evidence, at most three show at once, and dismissals persist by stable id. Most of its 22 tests
    are about staying **quiet**: no trend from under three weeks, a goal never started is not
    "stuck", one rambling note repeating a word is not a pattern. Two bugs came from driving it in a
    browser — it offered to shrink a week that was already planned, and asked the same question
    twice at two sizes.
  - **Capture search** with match highlighting, appearing only once there are ≥8 items (a filter
    over four notes is furniture). Re-render restores focus and caret so typing isn't interrupted.
  - **Share sheet export** (`navigator.share` with a file, falling back to download) — a silent
    download into a folder you can't browse is not a backup a phone-only owner would ever find.
  - **Deliberately not built:** loss-aversion streaks, scores, grades, badges, or any red. The
    streak reports what happened and never asks for anything; an unlogged today reads as *still
    open*, not broken. Per GROWTH.md, engagement bought that way doesn't produce meetings.
  - New pure module `surfaces/app/www/travel-stats.js` (Travel-only, **no Python twin**) with 21
    checks in `tests/travel/run_stats.mjs`, run under pytest. Verified by driving the real page in
    headless Chromium: every figure, search, week-completion and the gate cross-checked, no JS
    errors.
- **T3 — Anti-hindrance planner mechanics.** All four obstacles encoded as product behaviour,
  working on BOTH the server and in Travel Mode via one shared pure core
  (`modules/horizon/core.py` ⇄ `surfaces/app/www/horizon-core.js`):
  - **Distraction sink** — a capture classified as a new-project idea is *parked, not planned*
    ("Captured, not abandoned — current gate first."); `/parked` + `GET /v1/parked` list them.
  - **Boredom rule** — the planner finishes stuck work before starting new; a task carried >2
    cycles surfaces as its "smallest remaining piece" with a concrete next physical action.
  - **Doubt rule** — `/gate` + `GET /v1/gate` print honest v0.1-gate progress (days used, logs,
    retros) from real stored counts, never estimates.
  - **Energy shaping** — deep work → evening (never mornings), admin → the daytime trough, and
    a hard weekly cap (3) while `vitals.energy_baseline: tired` in config.
  - **Gate-first ordering** — goals carry a `focus` flag; focused goals lead the week instead of
    losing to input order. Vision intake defaults the first goal to focus; retarget via the ★
    toggle in Travel Mode, `/focus <n>` on the bot, or `POST /v1/focus`. At most **2** goals can
    be starred at once (`FOCUS_CAP`), so starring everything can't flatten priority.
  - **Gate floor** — while the v0.1 gate is unpassed, one slot of the capped week is always a
    gate-advancing ritual task (log today / run the retro), regardless of focus; focus steers the
    rest. When the gate passes the floor lifts automatically and focus governs the full week.
  - **Anti-drift golden tests** — `tests/golden/cases.json` runs against both implementations
    (`tests/test_golden.py` + `tests/golden/run_js.mjs`) so JS↔Python drift fails CI.

## Roadmap work started

- **Phase 3 engine — mediator-brokered 1:1 coordination (server-side).** `modules/coordinate/`
  (`core.py` pure ranking engine + `coordinator.py` graph flow) + `/v1/coordinate/{propose,respond,
  approve}` + `GET /v1/coordinate`. Two people converge on a `{time, place}` from private weight
  vectors over the *proposed* options (never a calendar); both humans ratify; on match it writes a
  busy meet `event` linked to the person. Peer input is sanitized to the proposed keys (untrusted
  data, never instructions) — the sanctioned alternative to open agent-to-agent negotiation.
  Tested + simulated (8 tests). **This is the testable substrate; live cross-device use still needs
  accounts + a reachable coordinator (the NucBox) and ≥2 real users, per the roadmap gate.**
- **Crews + group coordination.** `modules/crews/` — named groups with a **topic + home city**
  ("Lisbon Climbing"), membership on the same grants ACL Hearth uses, and a directory-shaped
  read (`browse(topic, city)`). `coordinator.propose_group/respond_group/approve_group` +
  `/v1/crews`, `/v1/coordinate/group/*` generalize the engine to N people: **quorum, not
  unanimity** (a crew night happens when enough can make it), attendance outranks mild
  preference, and a venue veto only binds from people actually attending that slot. Confirmed
  meets link only the people coming. 10 tests + simulation.
  **Local-only by design:** crews are built from people already in your graph. A *public*
  cross-user directory (land in a new city, join a local crew of strangers) additionally needs
  accounts, a reachable host, moderation/reporting and location privacy — a separate arc.
- **Crew membership lifecycle + safety rails.** `visibility: private|public`; invite →
  accept/decline; request → approve/deny (public crews only); leave (always allowed, no
  friction); admin-gated invite/approve/block. **Safety shipped with discovery, not after it:**
  block (removes + bars return), unblock, and `report` → an auditable `crew_report` entity with
  an open/actioned/dismissed moderation queue. Blocked people are excluded from joining *and*
  from group coordination. `browse(visibility="public")` is the directory query — the only view
  a stranger should get. Membership states live on the grants ACL
  (`crew:admin|member|invited|requested|blocked`), which required adding
  **`GraphSession.revoke()`** to substrate — an ACL that can't revoke can't express leave/block.
- **Admission policy (admins choose how people get in).** Orthogonal to visibility:
  `admission = invite | approval | open` — invite-only, request-then-admin-approves (default),
  or drop-in (a request admits instantly). Private crews are always invite-only, since something
  unlisted can't be requested. `set_policy()` / `POST /v1/crews/policy` is admin-gated.
- **Discover — intent-driven local matching.** `modules/discover/` (`core.py` pure matcher +
  `discover.py` graph flow) + `/v1/discover*`. Declare an intent ("in Lisbon, want sushi night");
  public events and public crews are ranked by interest overlap, soonest first. Two invariants,
  in order: **only `visibility: public` items are ever returned** (privacy is a filter applied
  before scoring — invisibility is never just a low rank), and a city filter means local.
  Browse (`min_score=0`) shows everything local and public best-first; search
  (`only_matches=True`) returns only genuine matches. With no interests given it falls back to
  the graph's own `interest` entities — the ones VoiceOS already extracts from your captures.
- **Feed.** `GET /v1/feed` — one ranked stream for **where you are and where you're going**:
  scopes come from the cities you pass plus every stored travel intent (respecting its date
  window, so a trip only feeds you its city while you're actually there). Ranking blends
  interest match + a **saturating** crowd signal (40 interested beats 4, but not 10× — one big
  event can't bury what you'd enjoy) + how soon it is. An item earns a slot on match *or*
  popularity, so "could be interesting" still surfaces. Interests declared in an intent drive
  that city's slice. Every item carries `reasons` ("matches sushi · 9 interested · while you're
  in Lisbon") — a feed you can't interrogate is one you can't trust. `POST /v1/feed/interested`
  is the popularity signal (idempotent, reversible). Same privacy invariant: private items are
  filtered before scoring and can never appear.
- **Accounts + per-user isolation (the last blocker).** `gateway/accounts.py` +
  `/v1/auth/{register,login,me,logout,logout-everywhere}`. Passwords are PBKDF2-HMAC-SHA256
  with a per-account salt; session tokens are random 256-bit values of which only the SHA-256
  is stored, so reading the database cannot impersonate anyone. Sessions are **stored and
  therefore revocable** (single logout, or cut every session at once when a phone goes
  missing) — stateless tokens would have been less work but revocation is a standing rule.
  No new tables: accounts/sessions are `content` entities under a fixed SYSTEM owner.
  **Mode is chosen by the data, not a flag:** with no accounts registered the gateway behaves
  exactly as before (static token or open localhost); once any account exists, callers must
  log in — and the configured owner key keeps working so the bot and local scripts don't break.
  Each account gets its own `owner_id`, and `_graph(request)` resolves to that account's slice,
  which scopes the entire module surface in one place.
  **Isolation is now real, not nominal:** `_fetch_entity` honours the owner scope, so knowing
  an id is no longer enough to read or write someone else's entity — an out-of-scope id is
  indistinguishable from a missing one (404, not 500; `GraphError`/`ScopeError` now map to
  404/400/403 across the API instead of surfacing as server errors).
- **Cross-account public discovery.** `GraphSession.find_public()` / `get_public()` — the single
  deliberate crossing of the owner boundary, narrow *by construction*: `visibility == "public"` is
  forced into the query so a caller can't widen it, it's **read-only** (there is no cross-owner
  write), and scope checks still apply. `crews.directory()` + `GET /v1/crews/directory` and all of
  `discover` (find / intents / feed) now span accounts. Proven with two real accounts: Bruno sees
  Ana's published crews and events, sees a public crew's **size but not its roster**, and cannot
  reach anything private — not by listing, not by id, not by asking for `visibility=private`.
- **Cross-account membership.** A member subject is a local `person` (your private record of
  someone you know — unchanged) **or an ACCOUNT** (who you are across the system). A traveller can
  browse the directory, join a drop-in crew or be approved into a curated one, show up in the
  owner's roster by handle, see it in their own `my_crews`, and leave at will — none of it needing
  an entity in the other person's graph. `SYSTEM_OWNER` moved to `substrate` so modules resolve an
  account's handle (and only the handle) without importing the gateway.
  **The trust boundary:** the grants ACL is deliberately shared across accounts; entity data is
  not. Joining writes one ACL row about yourself, never the owner's entities; it can only ever
  reach `requested` (or `member` where the admin declared the crew open), never `admin`; and every
  admin action on a crew you don't own needs a real admin grant — including on adminless public
  crews, where the "your own group stays open to you" leniency deliberately does not apply.
- **Cross-account scheduling.** A crew that spans accounts can now agree a night. Opening a group
  session grants every current member `coord:participant` on the coordination;
  `GraphSession.get_if_granted()` / `update_if_granted()` let them read it and add their own
  availability without owning it, and `spaces_granted()` (the reverse of `grants_for`) means
  `GET /v1/coordinate/group/mine` can show a member their sessions instead of them needing an id
  passed out of band. **Authorisation is two things on purpose:** the grant is what lets you
  *reach* the session; the crew is the authority on who *belongs* — membership is re-derived from
  it on every action, so a forged grant row buys nothing and leaving/being blocked takes effect at
  once. Quorum counts current members only, so someone who left can't be the reason a night goes
  ahead. The confirmed meet is shared state on the coordination; the calendar entry is local —
  `POST /v1/coordinate/group/calendar` writes it into *your* graph, because nobody writes an event
  into someone else's. 11 tests + simulation (which is what caught the forged-grant and
  stale-quorum bugs the tests had missed).
- **Crew invite links — the growth loop.** `modules/crews/invites.py` +
  `/v1/crews/invite-link{,/redeem,/revoke}`. The public directory only helps where there are
  already people; a link works from zero — paste it into the group chat you're already in and the
  group becomes a crew. This is the one mechanic that functions *before* the network exists, and
  it means the first crew can be **imported** rather than recruited (rationale in `docs/GROWTH.md`).
  **A link is a capability and is held to session-token discipline:** 256 random bits with only the
  SHA-256 stored (the token is shown once and is never re-readable), bounded *twice over* by expiry
  (7d, hard-capped at 90d) and use count (25), revocable instantly, and it can never confer `admin`
  — an admin invites people to the crew, not to their own privileges. **A block outranks an
  invite**, which is the obvious hole in any share-link design. Every refusal reads identically
  ("that link isn't valid") so a token can't be used to probe what exists. Invites live under
  `SYSTEM_OWNER` alongside accounts and sessions — that is what lets a holder in any other account
  resolve one without reaching into anybody's personal graph.
  **Membership now confers read access** (`_load_visible` gained a third route via
  `get_if_granted`): links made *private cross-account crews* possible for the first time, and the
  read path hadn't caught up — a member couldn't see the very group they'd just joined, and such a
  crew couldn't schedule at all. `my_crews` uses `spaces_granted` to find them, since an unlisted
  crew in someone else's graph appears in no other index. 17 tests; two of the three bugs here were
  found by simulation, not by the suite.
- **Crews in the gateway PWA.** People tab: your crews, create (with public/invite-only),
  and a crew planner — propose times/places + quorum, record each member's availability, see
  the best night ranked, lock it in. Verified in a real browser against a live gateway.

## Hosting — VPS deployment (decided and written 2026-07-26)

The owner settled the long-open NucBox-vs-VPS question in favour of a **VPS**, on the reasoning
that scaling the app needs one; the NucBox stays the personal/offline option. `deploy/vps/` now
holds the whole path — `compose.yml`, `Caddyfile`, `.env.example` and a runbook:

- **TLS is not optional here.** Sessions are bearer tokens, so plain HTTP hands the token to
  anyone on the path. Caddy terminates TLS with automatic Let's Encrypt, sets HSTS, and is the
  only thing listening. **The gateway has no `ports:` at all** — it exists only on the compose
  network, so 8787 cannot be reached from outside even by accident.
- **Backups that were actually opened.** `tools/backup.py` uses `VACUUM INTO`, because copying a
  live SQLite file in WAL mode can restore corrupt — and it *usually looks fine*, which is the
  dangerous part. Every snapshot is integrity-checked and row-counted as it is taken; retention
  prunes by mtime and never touches files it didn't write. Verified against a running gateway:
  a row written through the API while the connection was open and still in the WAL was present
  in the snapshot. 8 tests.
- **`/health` is liveness only now.** It used to report the instance's total entity count without
  authentication — harmless on a private box, an information leak on a public one (watch the
  number move, learn how much the system holds and when people use it). Counts moved to
  `GET /v1/stats`, behind auth. `/health` keeps exactly what a load balancer, an uptime check and
  the PWA's mode badge need.
- Non-root containers (uid 10001), `no-new-privileges`, firewall to 80/443, keys-only SSH,
  health check + restart policy, secrets from the environment only.

**Still the owner's to do, and not automatable from here: provision the box and point DNS at it.**
Everything after that is `docker compose up -d --build`. Postgres is deliberately excluded —
`substrate/graph.py` already parameterises the dialect, so the port is real when a measurement
asks for it, not because a VPS felt like it deserved a bigger database.

## Next (from the 2026-07-18 brief)

- **T2 — Reconciliation.** `POST /v1/import`: ingest the Travel Mode bundle through
  `substrate/graph.py` with `module=travel`, original timestamps, idempotency keys → skip
  already-imported. Every record the bundle carries already has a stable `key` + `ts`.
- **T4 — Repo hygiene.** This file; suite green in CI (done, 446); README test command (done).

## Non-goals (do not build)

Convoy · Memento · Steward · Seasons · Vitals · Ledger · Hearth · Calibre ·
Google OAuth · Postgres migration · native store builds · SDK opening · billing activation ·
Tailscale/remote access (deferred until home) · licence/entity/ToS content.
