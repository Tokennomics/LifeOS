/* Tests for surfaces/app/www/travel-stats.js — Travel Mode's Journey numbers.
 *
 * These are the figures the app shows you about your own life, so "roughly right" is not
 * good enough: a streak that flatters, or a day count that disagrees with the gate, is the
 * kind of dishonesty the doubt rule exists to prevent. Every function takes `today` as an
 * argument, so all of it is deterministic.
 *
 * Run by tests/test_travel_stats.py under pytest, and directly in CI.
 */
import assert from "node:assert/strict";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const S = require(path.join(here, "..", "..", "surfaces", "app", "www", "travel-stats.js"));

const TODAY = "2026-07-27";

const capture = (day, text = "a thought", type = "capture") =>
  ({ key: `c-${day}-${text}`, type: "entity", kind: "content", ts: `${day}T09:00:00Z`,
     attrs: { type, text } });
const task = (week, status, doneDay) =>
  ({ key: `t-${week}-${status}-${doneDay || ""}`, type: "entity", kind: "task",
     ts: `${(doneDay || "2026-07-01")}T08:00:00Z`,
     attrs: { title: "do the thing", week, status, done_at: doneDay ? `${doneDay}T18:00:00Z` : "" } });
const retro = (week, day) =>
  ({ key: `r-${week}`, type: "entity", kind: "metric", ts: `${day}T20:00:00Z`,
     attrs: { type: "weekly_retro", week, planned: 3, done: 2 } });

let failures = 0;
function test(name, fn) {
  try {
    fn();
  } catch (err) {
    failures++;
    console.error(`FAIL  ${name}\n      ${err.message}`);
  }
}

/* ---- activity days ---- */

test("a day counts when a task was FINISHED, not when it was planned", () => {
  // planned on the 1st, finished on the 26th -> the 26th is the day you showed up
  const days = S.activityDays([task("2026-W30", "done", "2026-07-26")]);
  assert.deepEqual([...days], ["2026-07-26"]);
});

test("open tasks are not evidence of a day", () => {
  assert.equal(S.activityDays([task("2026-W30", "open")]).size, 0);
});

test("captures, parked ideas and retros all count", () => {
  const days = S.activityDays([
    capture("2026-07-20"), capture("2026-07-21", "idea", "parked_idea"), retro("2026-W29", "2026-07-22"),
  ]);
  assert.deepEqual([...days].sort(), ["2026-07-20", "2026-07-21", "2026-07-22"]);
});

/* ---- streak ---- */

test("an unlogged today does not break the run — it is still open", () => {
  const items = ["2026-07-24", "2026-07-25", "2026-07-26"].map((d) => capture(d));
  const s = S.streak(items, TODAY);
  assert.equal(s.current, 3, "run should be measured from yesterday when today is blank");
  assert.equal(s.loggedToday, false);
});

test("logging today extends the run rather than restarting it", () => {
  const items = ["2026-07-25", "2026-07-26", TODAY].map((d) => capture(d));
  const s = S.streak(items, TODAY);
  assert.equal(s.current, 3);
  assert.equal(s.loggedToday, true);
});

test("a gap ends the run, and the best run is remembered", () => {
  const items = ["2026-07-10", "2026-07-11", "2026-07-12", "2026-07-13",  // best: 4
                 "2026-07-25", "2026-07-26"].map((d) => capture(d));      // current: 2
  const s = S.streak(items, TODAY);
  assert.equal(s.current, 2);
  assert.equal(s.best, 4);
  assert.equal(s.days, 6);
});

test("no history is zero, not a crash", () => {
  assert.deepEqual(S.streak([], TODAY), { current: 0, best: 0, loggedToday: false, days: 0 });
});

test("two things on one day are one day", () => {
  const s = S.streak([capture("2026-07-26", "one"), capture("2026-07-26", "two")], TODAY);
  assert.equal(s.current, 1);
  assert.equal(s.days, 1);
});

/* ---- heatmap ---- */

test("the grid is exactly `span` days and ends today", () => {
  const { cells } = S.heatmap([], TODAY, 84);
  assert.equal(cells.length, 84);
  assert.equal(cells[83].day, TODAY);
  assert.equal(cells[0].day, "2026-05-05");
});

test("pad aligns the first column to a Monday, so columns are real weeks", () => {
  // 2026-05-05 is a Tuesday -> one blank cell before it
  assert.equal(S.heatmap([], TODAY, 84).pad, 1);
  // a span landing exactly on a Monday needs no padding
  const { cells, pad } = S.heatmap([], TODAY, 85);
  assert.equal(cells[0].day, "2026-05-04");
  assert.equal(new Date(cells[0].day + "T00:00:00Z").getUTCDay(), 1, "sanity: that is a Monday");
  assert.equal(pad, 0);
});

test("levels bucket 0 / 1 / 2-3 / 4+", () => {
  const many = (day, n) => Array.from({ length: n }, (_, i) => capture(day, `note ${i}`));
  const { cells } = S.heatmap(
    [...many("2026-07-24", 1), ...many("2026-07-25", 3), ...many("2026-07-26", 5)], TODAY, 7);
  const level = (d) => cells.find((c) => c.day === d).level;
  assert.equal(level("2026-07-23"), 0);
  assert.equal(level("2026-07-24"), 1);
  assert.equal(level("2026-07-25"), 2);
  assert.equal(level("2026-07-26"), 3);
});

/* ---- week history ---- */

test("weeks are oldest-first with an honest completion rate", () => {
  const rows = S.weekHistory([
    task("2026-W30", "done", "2026-07-22"), task("2026-W30", "open"),
    task("2026-W29", "done", "2026-07-15"),
  ]);
  assert.deepEqual(rows, [
    { week: "2026-W29", planned: 1, done: 1, rate: 100 },
    { week: "2026-W30", planned: 2, done: 1, rate: 50 },
  ]);
});

test("a week you never planned is not a week you failed", () => {
  assert.deepEqual(S.weekHistory([capture("2026-07-20")]), []);
});

/* ---- totals ---- */

test("totals count what happened, and the span is inclusive of day one", () => {
  const t = S.totals([
    capture("2026-07-20"), capture("2026-07-21", "big idea", "parked_idea"),
    task("2026-W30", "done", "2026-07-22"), task("2026-W30", "open"),
    retro("2026-W30", "2026-07-26"), retro("2026-W30", "2026-07-26"),
  ], TODAY);
  assert.equal(t.captures, 1);
  assert.equal(t.parked, 1);
  assert.equal(t.tasksDone, 1);
  assert.equal(t.tasksPlanned, 2);
  assert.equal(t.retros, 1, "re-running a week's retro must not inflate the count");
  assert.equal(t.firstDay, "2026-07-20");
  assert.equal(t.spanDays, 8, "20th to 27th inclusive");
});

test("an empty log reports zeroes rather than NaN", () => {
  const t = S.totals([], TODAY);
  assert.equal(t.spanDays, 0);
  assert.equal(t.daysShownUp, 0);
});

/* ---- search ---- */

test("search narrows, case-insensitively, newest first", () => {
  const items = [capture("2026-07-20", "Sushi in Lisbon"), capture("2026-07-25", "climbing gym"),
                 capture("2026-07-26", "sushi again")];
  const hits = S.searchCaptures(items, "SUSHI");
  assert.deepEqual(hits.map((h) => h.attrs.text), ["sushi again", "Sushi in Lisbon"]);
});

test("an empty query returns everything — search narrows, never gates", () => {
  const items = [capture("2026-07-20"), capture("2026-07-21")];
  assert.equal(S.searchCaptures(items, "   ").length, 2);
});

test("search can be pinned to one kind", () => {
  const items = [capture("2026-07-20", "a", "capture"), capture("2026-07-21", "b", "parked_idea")];
  assert.deepEqual(S.searchCaptures(items, "", "parked_idea").map((i) => i.attrs.text), ["b"]);
});

/* ---- on this day ---- */

test("recall finds this day of the month, a while back — not last night", () => {
  const items = [capture("2026-06-27", "a year of noticing"), capture("2026-07-26", "yesterday")];
  const hit = S.onThisDay(items, TODAY);
  assert.equal(hit.attrs.text, "a year of noticing");
});

test("recall stays quiet when there is nothing old enough", () => {
  assert.equal(S.onThisDay([capture("2026-07-26")], TODAY), null);
  assert.equal(S.onThisDay([], TODAY), null);
});

/* ---- week progress ---- */

test("progress is out of what was planned, and knows when the week is done", () => {
  const items = [task("2026-W31", "done", "2026-07-27"), task("2026-W31", "open")];
  assert.deepEqual(S.weekProgress(items, "2026-W31"), { planned: 2, done: 1, pct: 50, complete: false });
  const all = [task("2026-W31", "done", "2026-07-27")];
  assert.equal(S.weekProgress(all, "2026-W31").complete, true);
});

test("an unplanned week is 0%, and is NOT 'complete'", () => {
  assert.deepEqual(S.weekProgress([], "2026-W31"), { planned: 0, done: 0, pct: 0, complete: false });
});

/* ---- share target ---- */

test("Chrome's shape: title + url, joined once", () => {
  assert.equal(S.parseShare("?title=Sushi%20in%20Lisbon&url=https://ex.com/a"),
               "Sushi in Lisbon — https://ex.com/a");
});

test("the app that puts the link in `text` and sends no url", () => {
  assert.equal(S.parseShare("?text=https://ex.com/a"), "https://ex.com/a");
});

test("a duplicated title is not captured twice", () => {
  assert.equal(S.parseShare("?title=Great%20read&text=Great%20read&url=https://ex.com/a"),
               "Great read — https://ex.com/a");
});

test("a url echoed inside text is not captured twice", () => {
  assert.equal(S.parseShare("?text=Look%20at%20https://ex.com/a&url=https://ex.com/a"),
               "Look at https://ex.com/a");
});

test("the pre-joined 'title url' case collapses to one line", () => {
  assert.equal(S.parseShare("?title=Great%20read&text=Great%20read%20https://ex.com/a"),
               "Great read https://ex.com/a");
});

test("plain selected text with nothing else", () => {
  assert.equal(S.parseShare("?text=the%20thing%20I%20highlighted"), "the thing I highlighted");
});

test("newlines and runs of whitespace collapse — a capture is one line", () => {
  assert.equal(S.parseShare("?text=two%0A%0A%20%20lines"), "two lines");
});

test("nothing shared is empty, not a crash", () => {
  for (const q of ["", "?", "?title=&text=&url=", null, undefined]) {
    assert.equal(S.parseShare(q), "", `for ${JSON.stringify(q)}`);
  }
});

test("a hostile payload comes back verbatim — escaping is the view's job", () => {
  assert.equal(S.parseShare("?text=" + encodeURIComponent('<img src=x onerror=alert(1)>')),
               '<img src=x onerror=alert(1)>');
});

if (failures) {
  console.error(`\n${failures} travel-stats check(s) failed.`);
  process.exit(1);
}
console.log("travel-stats: all checks passed");
