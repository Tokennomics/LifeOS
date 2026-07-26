# LifeOS — STATUS

_The one-page memory between phone-driven sessions. Update at the end of every PR._

_Last updated: 2026-07-26_

## Where we are

Sprint 1 shipped (substrate + graph.py, gateway, Horizon, VoiceOS, ICS ingest, deploy
scripts). The v0.2 PWA (`surfaces/app/www`, served by the gateway at `/app/`) needs a
reachable gateway; **Travel Mode** (`travel.html`) runs the week from a phone abroad with no
server. **T3 (anti-hindrance) was pulled ahead of T2** by the owner: T2's import has no
user-facing value until he's home at the NucBox, while T3 improves daily use while travelling.

**Tests:** `python -m pytest` → **219 passing** in the cloud env, gated by
`.github/workflows/tests.yml`. (The 2026-07-18 brief said 24 — the code has moved on.)

## Shipped

- **T1 — Travel Mode.** Standalone offline PWA at `surfaces/app/www/travel.html`. No gateway.
  Persists to **IndexedDB**. Offline Horizon flows mirror the server's deterministic
  fallbacks. Service worker for airplane-mode load; installable; "Travel · local only" badge.
  Publishes to GitHub Pages via `.github/workflows/pages.yml` (shell only — data stays local).
  **Daily-driver hardening:** tap a task to log / tap again to undo; edit the vision & goals
  (rename/add/remove) instead of re-pasting; the retro persists across reload; delete a capture
  or parked idea. Gate honesty fix (server + Travel): `retros_completed` counts distinct weeks,
  so re-running a week's retro can't inflate gate progress.
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
- **Crews in the gateway PWA.** People tab: your crews, create (with public/invite-only),
  and a crew planner — propose times/places + quorum, record each member's availability, see
  the best night ranked, lock it in. Verified in a real browser against a live gateway.

## Next (from the 2026-07-18 brief)

- **T2 — Reconciliation.** `POST /v1/import`: ingest the Travel Mode bundle through
  `substrate/graph.py` with `module=travel`, original timestamps, idempotency keys → skip
  already-imported. Every record the bundle carries already has a stable `key` + `ts`.
- **T4 — Repo hygiene.** This file; suite green in CI (done, 219); README test command (done).

## Non-goals (do not build)

Convoy · Memento · Steward · Seasons · Vitals · Ledger · Hearth · Calibre · Ticketmaster ·
Google OAuth · Postgres migration · native store builds · SDK opening · billing activation ·
Tailscale/remote access (deferred until home) · licence/entity/ToS content.
