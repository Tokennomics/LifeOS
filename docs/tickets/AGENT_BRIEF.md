# LifeOS — brief for an execution agent

You are working in a **git worktree** of `Tokennomics/LifeOS`, on a temporary branch. You own a
specific ticket (see the ticket file you were given) and a specific list of files. Commit on your
worktree branch with clear messages. **Do not push. Do not touch `main`. Do not edit files outside
your ownership list** — another agent owns them and I merge everything at the end.

The lead (me) will merge your branch, run the full suite, walk the app in a browser, and report to
the owner. Your final message to me is a short report: files changed, routes changed, tests added,
the guard-seen-to-fail evidence, anything you left out and why. Be plain and specific.

## What this repo is, in one paragraph

A local-first "life OS": a SQLite graph (`substrate/graph.py`) with a FastAPI gateway
(`gateway/modules_api.py`, ~500 routes; `gateway/main.py` for auth and a few core routes) and a
vanilla-JS PWA (`surfaces/app/www/app.js`, `index.html`). Over the last month the project's whole
effort has been replacing **props** — handlers that returned invented data as if it were real —
with implementations that read and write the graph honestly. Prop count went 184/445 → 24/498.
Your ticket continues that work.

## Invariants (from `docs/HANDOVER.md`; where a doc and the code disagree, the code wins)

- `substrate/graph.py` is the **only write path**; every write carries scope + provenance
  (`session.create_entity(kind, attrs, source=...)`).
- The v0 schema is **final** — extend via `attrs` JSONB only. Row "types" are `attrs["type"]`.
- Every feature works with **no API key** and improves with one.
- **No secrets in the repo, ever.** Not even fake ones shaped like real ones (see traps).
- Do not refactor working code you were not asked to touch. **Additive work only.**
- Tests pass before every commit.
- Money is **whole cents**, never floats; currencies never mixed. See `modules/ledger/tab.py`.
- Shared/addressed rows live under `SYSTEM_OWNER` (`Graph(graph.conn, graph.bus,
  default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)`); private rows in the owner slice.

## Honesty rules (these are what "not a prop" means here)

1. **No invented numbers.** No scores, percentages, match %, karma, XP, streak multipliers,
   "98% verified". If a number is shown it was **counted** from rows, and the response says so.
2. **No `verified: True` unless something was verified.** A claim by one person is a *vouch*
   (`modules/social/trust.py`, which carries `NOT_VERIFICATION`). A signature is verified only
   by checking it. "Cannot check" is never reported as "checked and failed" — raise / 503.
3. **No `found: True` for something not found.** Unknown handle → 404. Empty is empty
   (`empty: True`, and a `suggestion` naming what would fill it).
4. **Nothing is minted as a constant.** No fixed ids, codes, URLs. Capability tokens are minted
   per call, stored as SHA-256, shown once (`modules/crews/invites.py::_hash_token` pattern).
5. **No links to hosts this deployment does not serve** (`connectos.app`, `lifeos.app`,
   `revolut.me`, `checkout.stripe.com`…). Build URLs relative or from the request base URL the way
   `gateway/main.py` builds `/invite/{token}`.
6. **Nothing "notifies", "syncs", "moves money" or "pushes" unless it does.** The pinned
   invariants are `push_delivered: False`, `calendars_synced: 0`, `money_moved: False`.
7. **Unbuildable is said, not simulated.** If the app genuinely cannot do a thing (hardware,
   a processor that is not connected), answer `{"available": False, "why": ..., "needs": [...]}`
   for a describe/read, or **HTTP 503 with a dict detail** for an action. Wording must match
   `modules/platform/overview.py::system()["unavailable"]` — import/share the constants so the
   status page and the endpoint cannot drift apart. 503 not 400 (the caller did nothing wrong)
   and not 200-with-`ok: false` (reads as "tried and declined").
8. **Defaults never invent a person or a place.** `body.get("venue", "Miradouro Rooftop Bar")`
   is a prop. Missing input → 400 via `guard(...)` with a plain message, or the `needs_city`
   pattern from `modules/city/live.py::_nowhere()`.
9. **Disclaimers live in named fields** — `no_money`, `note`, `suggestion`, `reason`, `why` — in
   plain prose. No emoji, no exclamation marks, no marketing register in *new* copy.

## House style for a replaced handler

Every replaced handler gets a docstring that says **what the prop claimed** and **why the
replacement is shaped as it is**. Read three before writing one: `/payments/one-tap-settle`,
`/economics/revenue-share` and `/monetization/sponsored-perks` in `gateway/modules_api.py`, and
the module docstrings of `modules/money/rails.py` and `modules/ledger/tab.py`. Module docstrings
are the changelog; **responses are not** (see trap 1).

Handlers are thin: parse the body, resolve the caller, call a module function inside
`guard(lambda: ...)` (which maps `ValueError` → 400), and return. Logic lives in `modules/`.

Caller helpers already in `modules_api.py` (use them, do not re-implement):
`_graph(request)`, `_actor(request, None)`, `_signal_caller(request)` → `(account_id, handle)`,
`_named_account(request, handle_or_id)`, `_with_handles(request, payload)` (resolves ids → handles
on `balances`/`entries`/`settled` **lists**), `_crew_caller`, `_viewer_city`, `_synergy_city`,
`_operator(request)` (operator-only), `no_processor(name)` (503 for payments),
`rate_limiter.enforce(request, key, max_requests=, window_seconds=)` for write endpoints that
could be spammed.

## Tests

- Fixtures in `tests/conftest.py`: `cfg` (a temp config) and `graph`. Outbound network and
  ambient credentials are disabled autouse — your code must work with **no network**.
- API tests: copy the `world` fixture from `tests/test_money_rails_api.py` (two signed-in accounts
  `ana` and `bruno`; `people[name]["h"]` are headers, `people[name]["id"]` the account id).
- Module tests take `graph` directly.
- Run: `python -m pytest tests/test_x.py -q`. Full suite is ~15 min; run only your files plus the
  two guards below, and I will run the whole thing after merging.
- **Two guards to run before every commit:**
  `python -m pytest "tests/test_city_guide.py::test_no_route_references_a_name_that_does_not_exist" "tests/test_security_audit.py::test_no_vendor_credential_prefixes_are_committed" -q`
  The second scans **`git ls-files` only** — `git add` your new files first or it cannot see them.
- **A guard is not finished until it has been seen to fail.** After writing tests for a replaced
  handler, temporarily reinstate the old behaviour (or a one-line lie such as `"verified": True`),
  confirm the tests fail, restore, confirm they pass. Put one sentence of that evidence in your
  report. Three guards in this repo were found passing while checking nothing; do not add a fourth.
- Tests that **pin a prop** (assert the invented value) must be **rewritten to preserve their
  intent**, never deleted and never weakened. `grep -rn "<route>" tests/` before you change a
  handler.
- `python tools/audit_props.py` lists remaining literal props; your routes should leave the list.

## Traps that have each cost a fix in this repo

1. **Substring collision.** Honest copy names the thing it disclaims ("no karma", "not a
   verification"). A whole-body `assert "karma" not in str(out)` then fails on your own
   disclaimer. Strip `no_*`, `note`, `suggestion`, `reason`, `why` before such asserts, or assert
   on keys/shape. And keep changelog prose out of responses.
2. **Swallowing the next helper.** Replacing a handler by text range from its decorator to
   "the next `@router`" can delete a `def _helper(...)` that sits between them. This has happened
   **three times**. Replace exactly the handler body, then run the dead-name guard above.
3. **`_with_handles` bool/list.** `tab.settle()` returns `settled: True`; `tab.settle_all()`
   returns a list. Check `isinstance(..., list)` before extending.
4. **Nested code objects.** Handlers wrap work in `guard(lambda: ...)`; bytecode checks must
   recurse into `co_consts`. If you touch a guard test, remember that.
5. **Credential-shaped literals.** Never write a string that begins with a real vendor's key
   prefix — Stripe's, GitHub's, AWS's, Slack's, Google's, Anthropic's, OpenAI's — anywhere,
   including tests and sample data. The authoritative list is `_VENDOR_PREFIXES` in
   `tests/test_security_audit.py`; read it there rather than trusting a copy. Use something
   like `a-signing-key-for-this-suite-only` instead.

   *This paragraph used to quote the prefixes, and that is why it is written this way now:
   the committed copy of this brief failed the very guard it describes. The guard cannot tell
   prose from a key, and it should not try — a scanner reading the repo cannot either. That is
   the whole point of the rule.*
6. **A flaky negative.** Do not assert a short digit string is absent from a body that contains
   ids or hashes (`"94" not in text` fails 1 run in 200). Assert on shape instead.
7. **Route shadowing.** Literal path segments must be declared before parameterised ones on the
   same router.
8. **A green suite does not mean the button works.** Every ticket that touches a route the PWA
   calls ends with a browser walk (below). The last three tickets each found a defect this way that
   the suite could not see.

## Browser walk template

Copy `/tmp/claude-0/-home-user-LifeOS/453d2e57-44ed-54de-9b1f-ab524e45af33/scratchpad/walk_money.py`
and `walk_settle.py` next to it. They start uvicorn with a temp config, sign in with Playwright,
click through the dock to find a `[data-act=...]` button, and assert the output panel has no
`undefined` / `[object Object]` / `NaN` and none of a banned-string list. Chromium executable:
`/opt/pw-browsers/chromium-1194/chrome-linux/chrome`. Use a **unique port per script** (89xx) and
`pkill -f "uvicorn gateway.main"` if a previous run left one behind (a stale server on the same
port makes `register` 400 and every later step misleading). To sign in an account that already
exists, set `localStorage lifeos.token` and reload rather than using the register form.

## Commit messages

Imperative subject under 70 chars, then a body that says what the prop claimed, what replaces
it, and how it was verified. Do not mention model names. Sign off exactly:

```
Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HqS6pAxUd4JxDSdDTVNFRo
```
