# Ticket T5 — the cards that now render `undefined`

Read `AGENT_BRIEF.md` in this directory first.

**Base:** run `git log --oneline -1`. If HEAD is not `2370932` or a descendant, fix that before
reading any source file (`git fetch origin && git merge --ff-only 2370932`). Four previous
agents started on a stale checkout; two lost real time to it.

**Ownership:** `surfaces/app/www/app.js`, `surfaces/app/www/dashboard.js`,
`surfaces/app/www/index.html`, `tests/test_pwa_honesty.py` (extend, do not rewrite),
and your walk scripts. **Nothing under `gateway/` or `modules/`** — if a route genuinely
needs a new field, say so in your report and work around it; do not add it.

## The finding

Every literal prop in the gateway is gone: `tools/audit_props.py` reads **0 of 502 handlers**.
That is the good news and it is also the defect. Those handlers used to return invented keys
(`community_karma_bonus`, `curated_underground_sessions`, `detected_footfall_hotspots`,
`exclusive_food_drops`, `cash_saved`, `compounding_score`…) and the PWA still reads them. The
lie is gone from the server; the card now prints `undefined`, or renders an empty row where a
fabricated one used to be.

Measure it with the lead's script, which is the definition of done:

```
python /tmp/claude-0/-home-user-LifeOS/453d2e57-44ed-54de-9b1f-ab524e45af33/scratchpad/dead_keys.py
```

It strips comments, collects every `res.X` read in `app.js`, and subtracts every `"key":`
emitted anywhere in `gateway/` or `modules/`. On `2370932` it reports **76 distinct dead keys
of 263 reads**. Drive that to as close to 0 as the routes honestly allow.

Two cautions the previous ticket paid for:
- The script is a **whole-word** check by construction. Do not "fix" a key by renaming it to a
  substring of a live one.
- Some names are dead on *one* route and live on another (`venue_name`, `perks`,
  `treasury_balance` were each still live elsewhere). Confirm a key is dead for **the route
  that card actually calls** before you touch it, by reading that handler.

## What to do for each card

Read the handler in `gateway/modules_api.py` (read-only), take the shape it really returns,
and render that. The honest shapes are already there — almost every one of these routes now
carries `empty`, a `suggestion` naming what would fill it, and a disclaimer field
(`no_*`, `note`, `why`, `reason`). Render those instead of inventing a replacement.

Where a route now refuses (**503** with `{available:false, capability, why, needs}`), use the
existing `renderUnavailable(source, sel, title)` / `unbuildable(...)` helpers T3 added — do not
write a third variant.

Where a card's whole premise is gone (the route no longer produces anything like what the card
promised), the card becomes the honest thing the route does return, or it goes — and if it
goes, say so in the commit message and in your report. Do not leave a button that does nothing.

## Also in scope

1. **`dashboard.js:38`** has the last inline `onclick` in the codebase:
   `onclick="LifeOSDashboard.completeRoutine('${r.routine_id}')"`. Unlike the five T3 removed
   this one calls a real function, so it is a style and injection-surface issue rather than a
   lie: `routine_id` is interpolated into an HTML attribute. Convert it to the
   `on("[data-act=…]")` + `dataset` pattern used everywhere else, and widen the honesty test's
   inline-handler check to cover `dashboard.js`.
2. **`travel-coach.js:191`** throws `TypeError: list.filter is not a function` on every Today
   render. Its own try/catch swallows it, so the coach silently produces nothing. Diagnose it;
   fix it if the fix is small and clearly right, otherwise report the cause precisely.
3. **~44 asserting labels** T3 left: `VIP`, `1-Tap`, `Instant`, `Live` on cards whose routes
   were outside its scope (the live-APIs studio, the nightlife/vinyl/culinary seeding studios,
   the twin-city bridge, the plugin sandbox). Now that you are fixing those same cards' render
   paths, reword the labels to what the route does. T3 deliberately left them because
   rewording a label above a broken render would make the card *more* misleading — that reason
   expires the moment you fix the render.

## Tests

Extend `tests/test_pwa_honesty.py` (69 checks today, all passing — keep them passing). Add a
test that runs the dead-key analysis in-process and asserts the count is 0, or an explicit
allowlist with a one-line reason per entry. An allowlist entry is a promise you can defend;
`# TODO` is not a reason.

**Guard seen to fail:** reintroduce one dead key read into a card, confirm the new test names
it, restore.

## Browser walk

Extend T3's `scratchpad/walk_pwa_honesty.py` (port 8926 — use a different one, e.g. 8931) to
click every card you touch. Assert no `undefined`, `[object Object]`, `NaN`, or empty panel.
Paste the final output in your report. T3 found three defects this way that no Python test
could see; expect the same.

## Report back

Cards changed, dead-key count before and after, the allowlist with reasons if any, the
`travel-coach.js` diagnosis, the walk output, and anything left out and why.

---
## Status (lead, 2026-09-05)

Written and launched at ~11:30 UTC; the agent terminated immediately on an account session
limit (resets 15:20 UTC), before it read anything. **Nothing was started, so nothing is
half-done** — this ticket is untouched and can be run as written.

Base to use is now the tip of `claude/lifeos-repository-connection-lfeqba` (T3 merged at
`2370932`, plus whatever follows). Re-measure with `dead_keys.py` before starting; the count
was 76 distinct dead keys of 263 reads at `2370932`.
