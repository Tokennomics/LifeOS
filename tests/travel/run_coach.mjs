/* Tests for surfaces/app/www/travel-coach.js — the propose-only coach.
 *
 * The coach's whole claim is that it tells you true things about your own week. So most of
 * what follows is about it staying QUIET: a coach that fires on two weeks of data, or
 * re-raises what you dismissed, or calls a goal stuck the week after you finished something
 * on it, is one you stop reading — and an assistant you stop reading is worse than none.
 *
 * Run by tests/test_travel_coach.py under pytest, and directly in CI.
 */
import assert from "node:assert/strict";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const C = require(path.join(here, "..", "..", "surfaces", "app", "www", "travel-coach.js"));

const TODAY = "2026-07-27";
const WK = (n) => `2026-W${String(n).padStart(2, "0")}`;
const THIS = WK(31);

let n = 0;
const goal = (key, title) =>
  ({ key, type: "entity", kind: "goal", ts: "2026-06-01T00:00:00Z",
     attrs: { level: "goal", title } });
const task = (week, status, goalKey) => {
  const key = `t${n++}`;
  const out = [{ key, type: "entity", kind: "task", ts: `${week}-x`,
                 attrs: { title: "a task", week, status } }];
  if (goalKey) out.push({ key: `e${n++}`, type: "edge", src: key, dst: goalKey, rel: "feeds" });
  return out;
};
const capture = (text) =>
  ({ key: `c${n++}`, type: "entity", kind: "content", ts: "2026-07-20T09:00:00Z",
     attrs: { type: "capture", text } });
const retro = (week) =>
  ({ key: `r-${week}`, type: "entity", kind: "metric", ts: "2026-07-20T20:00:00Z",
     attrs: { type: "weekly_retro", week } });

const propose = (items, dismissed) => C.proposals(items, TODAY, THIS, dismissed || [], 5);
const kinds = (items, dismissed) => propose(items, dismissed).map((p) => p.kind);

let failures = 0;
function test(name, fn) {
  try { fn(); } catch (err) { failures++; console.error(`FAIL  ${name}\n      ${err.message}`); }
}

/* ---- plan the week ---- */

test("with no plan for this week, drafting it is the top proposal", () => {
  const out = propose([goal("g1", "Ship LifeOS")]);
  assert.equal(out[0].kind, "plan");
  assert.equal(out[0].action, "plan");
});

test("once this week is planned, it stops asking", () => {
  assert.ok(!kinds([...task(THIS, "open")]).includes("plan"));
});

/* ---- right-sizing: the advice nothing else gives ---- */

test("consistent over-planning proposes a smaller, evidenced commitment", () => {
  const items = [
    ...task(WK(28), "done"), ...task(WK(28), "open"), ...task(WK(28), "open"),
    ...task(WK(29), "done"), ...task(WK(29), "open"), ...task(WK(29), "open"),
    ...task(WK(30), "done"), ...task(WK(30), "open"), ...task(WK(30), "open"),
  ];
  const p = propose(items).find((x) => x.kind === "right_size");
  assert.ok(p, "should propose right-sizing after 3 weeks at 33%");
  assert.equal(p.limit, 1);
  assert.match(p.why, /planned 9 and finished 3 \(33%\)/, "the evidence must be in the text");
});

test("it will not draw a trend from fewer than three weeks", () => {
  const items = [...task(WK(29), "open"), ...task(WK(29), "open"),
                 ...task(WK(30), "open"), ...task(WK(30), "open")];
  assert.ok(!kinds(items).includes("right_size"), "two bad weeks is a bad fortnight, not a pattern");
});

test("someone who finishes what they plan is never told to do less", () => {
  const items = [...task(WK(28), "done"), ...task(WK(29), "done"), ...task(WK(30), "done")];
  assert.ok(!kinds(items).includes("right_size"));
});

test("the suggestion is never zero", () => {
  const items = [...task(WK(28), "open"), ...task(WK(29), "open"), ...task(WK(30), "open")];
  const p = propose(items).find((x) => x.kind === "right_size");
  assert.ok(!p || p.limit >= 1, "proposing a week of nothing is not coaching");
});

test("right-sizing is not offered once the week is already planned", () => {
  const items = [
    ...task(WK(28), "open"), ...task(WK(28), "open"), ...task(WK(28), "done"),
    ...task(WK(29), "open"), ...task(WK(29), "open"), ...task(WK(29), "done"),
    ...task(WK(30), "open"), ...task(WK(30), "open"), ...task(WK(30), "done"),
    ...task(THIS, "open"),
  ];
  assert.ok(!kinds(items).includes("right_size"),
            "telling you to plan less after you planned is a no-op or a request to undo");
});

test("it never asks the same question twice at two sizes", () => {
  const items = [
    ...task(WK(28), "open"), ...task(WK(28), "open"), ...task(WK(28), "done"),
    ...task(WK(29), "open"), ...task(WK(29), "open"), ...task(WK(29), "done"),
    ...task(WK(30), "open"), ...task(WK(30), "open"), ...task(WK(30), "done"),
  ];
  const out = kinds(items);
  assert.ok(out.includes("right_size"), "should propose a size");
  assert.ok(!out.includes("plan"), "the sized proposal already implies 'plan this week'");
});

/* ---- stuck goals ---- */

test("a goal with nothing finished for weeks is surfaced, with the date", () => {
  const items = [goal("g1", "Train 3x per week"), ...task(WK(20), "done", "g1"),
                 ...task(THIS, "open")];
  const p = propose(items).find((x) => x.kind === "stuck");
  assert.ok(p);
  assert.match(p.title, /Train 3x per week/);
  assert.match(p.why, /2026-W20/);
  assert.equal(p.goalKey, "g1");
});

test("a goal you moved recently is not called stuck", () => {
  const items = [goal("g1", "Train"), ...task(WK(30), "done", "g1"), ...task(THIS, "open")];
  assert.ok(!kinds(items).includes("stuck"));
});

test("a goal never started is not 'stuck' — it just hasn't begun", () => {
  const items = [goal("g1", "Someday thing"), ...task(THIS, "open")];
  assert.ok(!kinds(items).includes("stuck"), "nagging about untouched goals is how lists become guilt");
});

/* ---- recurring themes ---- */

test("a word across three separate captures becomes a question", () => {
  const items = [...task(THIS, "open"), capture("climbing gym near the river"),
                 capture("ask Marco about climbing"), capture("climbing shoes are dead")];
  const p = propose(items).find((x) => x.kind === "theme");
  assert.ok(p);
  assert.equal(p.query, "climbing");
  assert.match(p.why, /3 separate captures/);
});

test("one rambling note repeating a word is not a pattern", () => {
  const items = [...task(THIS, "open"), capture("gym gym gym gym gym")];
  assert.ok(!kinds(items).includes("theme"), "distinct captures, not occurrences");
});

test("a theme already covered by a goal is not raised", () => {
  const items = [goal("g1", "Go climbing weekly"), ...task(THIS, "open"),
                 capture("climbing gym"), capture("climbing partner"), capture("climbing shoes")];
  assert.ok(!kinds(items).includes("theme"), "you're already working on it");
});

test("filler words never become themes", () => {
  const items = [...task(THIS, "open"), capture("I should really do the thing"),
                 capture("I should really go"), capture("I should really call")];
  const p = propose(items).find((x) => x.kind === "theme");
  assert.ok(!p, `stop words leaked: ${p && p.query}`);
});

/* ---- retro ---- */

test("a finished week with no retro is raised once", () => {
  const items = [...task(WK(30), "done"), ...task(WK(30), "open"), ...task(THIS, "open")];
  const p = propose(items).find((x) => x.kind === "retro");
  assert.ok(p);
  assert.equal(p.week, WK(30));
  assert.match(p.why, /1 of 2 finished/);
});

test("a week already reviewed is not raised", () => {
  const items = [...task(WK(30), "done"), ...task(THIS, "open"), retro(WK(30))];
  assert.ok(!kinds(items).includes("retro"));
});

/* ---- the discipline ---- */

test("dismissing a proposal silences it", () => {
  const items = [goal("g1", "Ship it")];
  const first = propose(items)[0];
  assert.ok(!propose(items, [first.id]).some((p) => p.id === first.id));
});

test("proposal ids are stable, so a dismissal survives a reload", () => {
  const items = [goal("g1", "Ship it")];
  assert.deepEqual(propose(items).map((p) => p.id), propose(items).map((p) => p.id));
});

test("it never says more than a few things at once", () => {
  const items = [
    goal("g1", "Train"), ...task(WK(20), "done", "g1"),
    ...task(WK(28), "open"), ...task(WK(29), "open"), ...task(WK(30), "open"),
    capture("sushi one"), capture("sushi two"), capture("sushi three"),
  ];
  assert.ok(C.proposals(items, TODAY, THIS, [], 3).length <= 3,
            "nine observations is the same as none");
});

test("an empty graph proposes exactly one thing: start", () => {
  const out = propose([]);
  assert.equal(out.length, 1);
  assert.equal(out[0].kind, "plan");
});

test("every proposal carries evidence and a stable id", () => {
  const items = [
    goal("g1", "Train"), ...task(WK(20), "done", "g1"),
    ...task(WK(28), "open"), ...task(WK(29), "open"), ...task(WK(30), "open"),
    capture("sushi one"), capture("sushi two"), capture("sushi three"),
  ];
  for (const p of propose(items)) {
    assert.ok(p.id && p.kind && p.title && p.why && p.action, `incomplete: ${JSON.stringify(p)}`);
    assert.ok(p.why.length > 20, `too thin to be evidence: ${p.why}`);
  }
});

if (failures) {
  console.error(`\n${failures} coach check(s) failed.`);
  process.exit(1);
}
console.log("travel-coach: all checks passed");
