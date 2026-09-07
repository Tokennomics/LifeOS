# AGENTS.md — read this before you write anything

Conventions for every tool that works on this repo: Claude Code, Gemini, Antigravity, a
human with a terminal. `CLAUDE.md` and `GEMINI.md` point here. Where this file and the code
disagree, **the code wins**.

## 1. Never force-push `main`

Before you push: **`git pull --rebase origin main`** (or merge). **Never `git push --force`
to `main`.** Not with `--force-with-lease` either, unless a person has asked for that exact
push in that exact minute.

This has already happened twice. On **2026-08-2x** and again on **2026-08-31**, `main` was
force-pushed from a local workspace whose base was a **2026-08-21** commit (`c4f9899`), and
each push erased the line of work that had landed after it — **77 commits**, PRs **#19–#25**:
seven tickets, thirteen modules, roughly nine hundred tests. Both pushes also reinstated two
modules that fabricate — the `SAFE-8921` SafeWalk that reported "crew notified" with nothing
sent, and the Munich journal that invented the user's day in the first person. Nothing was
lost either time, because both were recovered by a **two-parent merge** rather than a reset
(PR #24 on 2026-08-22, and commit `17810f7` on 2026-09-04, "Merge main a third time: keep
the audio engine and brand assets, drop nothing") — a merge keeps both lines, a force-push
keeps one. **Recovery is not the plan; it is what happens when the plan failed.**

Owner action, still open: **enable branch protection on `main`** in GitHub → Settings →
Branches — block force-pushes and require a pull request. That is the only thing that makes
this rule hold against a tool that does not read files.

Until that exists, `.github/workflows/force-push-alarm.yml` is the fallback: it cannot stop a
force-push, but it fires on one, names the commits that left the branch, opens an issue with
the recovery that worked both times, and fails the run. It denies the erasure its silence —
both previous ones were noticed by chance, days later. It is a smoke alarm, not a sprinkler.

## 2. One ticket, one branch, one PR

Work on a branch. Open a PR. Keep the diff small. **One ticket per PR** — stop and report
after each, do not chain tickets. Do not refactor working code you were not asked to touch.
Additive work only.

## 3. The invariants

Verbatim from `docs/HANDOVER.md`, "Working rules, still in force":

> small diffs, **one ticket per PR**, stop and report after each — do not chain tickets.
> `substrate/graph.py` is the only write path; every write carries scope + provenance.
> The v0 schema is final — extend via `attrs` JSONB only. Every feature works with **no API
> key** and improves with one. **No secrets in the repo, ever.** Tests pass before every
> commit.

Two more that live in the code: money is **whole cents**, never floats, and currencies never
mix (`modules/ledger/tab.py`). Shared or addressed rows live under `SYSTEM_OWNER`; private
rows in the owner slice.

## 4. Honesty rules — what "not a prop" means here

1. **No invented numbers.** No scores, match percentages, karma, XP, streak multipliers. A
   number that is shown was counted from rows, and the response says so.
2. **No `verified: True` unless something was verified.** A claim by one person is a vouch,
   not a verification. "Cannot check" is never reported as "checked and failed" — raise 503.
3. **No `found: True` for something not found.** Unknown handle → 404. Empty is empty
   (`empty: True`, plus a `suggestion` naming what would fill it).
4. **Nothing is minted as a constant.** No fixed ids, codes or URLs. Capability tokens are
   minted per call, stored as SHA-256, shown once.
5. **No links to hosts this deployment does not serve** (`connectos.app`, `revolut.me`,
   `checkout.stripe.com`). Build URLs relative, or from the request base URL.
6. **Nothing "notifies", "syncs", "moves money" or "pushes" unless it does.** The pinned
   invariants are `push_delivered: False`, `calendars_synced: 0`, `money_moved: False`.
7. **Unbuildable is said, not simulated.** A read answers `{"available": False, "why": ...,
   "needs": [...]}`; an action answers **HTTP 503 with a dict detail** — not 400 (the caller
   did nothing wrong) and not 200 with `ok: false` (that reads as "tried and declined").
   Share the wording with `modules/platform/overview.py` so the status page cannot drift.
8. **Defaults never invent a person or a place.** `body.get("venue", "Miradouro Rooftop
   Bar")` is a prop. Missing input → 400 with a plain message.
9. **Disclaimers live in named fields** — `no_money`, `note`, `suggestion`, `reason`, `why` —
   in plain prose. No emoji, no exclamation marks, no marketing register in new copy.
10. **Every replaced handler gets a docstring** saying what the prop claimed and why the
    replacement is shaped as it is. Module docstrings are the changelog; responses are not.

## 5. Tests

```
python -m pytest -q                     # the whole suite, about 15 minutes
python -m pytest tests/test_x.py -q     # while you work
```

**Tests pass before every commit.** Run your own files plus these two guards every time:

```
python -m pytest \
  "tests/test_city_guide.py::test_no_route_references_a_name_that_does_not_exist" \
  "tests/test_security_audit.py::test_no_vendor_credential_prefixes_are_committed" -q
```

The second reads `git ls-files` only, so `git add` new files first or it cannot see them.

**A guard is not finished until it has been seen to fail.** After writing a test for a
replaced handler, reinstate the old behaviour — or a one-line lie such as `"verified": True`
— watch the test fail, restore, watch it pass, and say so in your report. Three guards in
this repo were found passing while checking nothing. Do not add a fourth.

A test that **pins a prop** (asserts the invented value) is rewritten to preserve its intent,
never deleted and never weakened. `grep -rn "<route>" tests/` before changing a handler.

Outbound network and ambient credentials are disabled in `tests/conftest.py`: your code must
work with no network, and a test that needs a response injects one.

**A green suite does not mean the button works.** Nothing in `pytest` runs the front end.
Any ticket touching a route the PWA calls ends with a browser walk — Playwright against a
real gateway, Chromium at `/opt/pw-browsers/chromium-1194/chrome-linux/chrome`. The last
three tickets each found a defect that way that the suite could not see.

## 6. Where things are

| where | what |
|---|---|
| `docs/HANDOVER.md` | **start here** — the 60-second version, the gotchas, what is still open |
| `docs/STATUS.md` | the history, appended per PR |
| `docs/DEPLOY.md` | launch: the Render steps and the two secrets, which are the owner's |
| `docs/ROADMAP.md` | the parked map — nothing on it is built until the current gate passes |
| `tools/audit_props.py` | how much of the app is still a prop, in two passes |
| `substrate/graph.py` | the only write path |
| `gateway/modules_api.py` | ~500 routes; handlers are thin, logic lives in `modules/` |
