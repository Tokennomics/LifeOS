/* LifeOS Travel Mode — the compounding, made visible.
 *
 * Pure functions over the raw item log. No DOM, no IndexedDB, no clock of their own:
 * `today` is always passed in, so every number here is reproducible and testable
 * (tests/travel/run_stats.mjs, run under pytest).
 *
 * Why this file exists at all: a habit tracker is worth the same on day 90 as on day 1,
 * while something you have been putting things into is worth more. This graph is the
 * second kind — and that advantage only becomes a reason to come back if you can SEE it.
 * So these functions answer "look how far you've come", honestly, from real counts and
 * never an estimate.
 *
 * Deliberately NOT here: anything that manufactures pressure. No "don't break the chain",
 * no decaying score, no red. The streak reports what happened; it never asks for anything.
 *
 * NOTE: Travel-only, with no Python twin — unlike horizon-core.js, which is a
 * byte-identical mirror of modules/horizon/core.py and must never be edited alone.
 *
 * Loads as a browser global (window.TravelStats) or a CommonJS module (Node test runner),
 * the same UMD shape horizon-core.js uses — no build step, no bundler.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.TravelStats = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const DAY_MS = 86400000;

  const dayOf = (iso) => String(iso || "").slice(0, 10);
  const isEntity = (i, kind) => i && i.type === "entity" && i.kind === kind;
  const attrs = (i) => (i && i.attrs) || {};
  const shift = (day, n) =>
    new Date(Date.parse(day + "T00:00:00Z") + n * DAY_MS).toISOString().slice(0, 10);

  /* The day an item counts against: when a task was finished, otherwise when it was
   * written. Returns "" for items that are not evidence of a day spent. */
  function activeDay(item) {
    if (isEntity(item, "task") && attrs(item).status === "done") {
      return dayOf(attrs(item).done_at || item.ts);
    }
    if (isEntity(item, "content")) return dayOf(item.ts);
    if (isEntity(item, "metric") && attrs(item).type === "weekly_retro") return dayOf(item.ts);
    return "";
  }

  /* Every calendar day (UTC) with any trace of you: a task logged, a thought captured,
   * a retro run. Same rule the gate counts by, so the two can never disagree. */
  function activityDays(items) {
    const days = new Set();
    for (const item of items || []) {
      const day = activeDay(item);
      if (day) days.add(day);
    }
    return days;
  }

  /* Current run of consecutive days, plus the best run ever.
   *
   * Today counts as still open, not as broken: if you haven't logged yet the run is
   * measured from yesterday, so opening the app in the morning never shows a zero you
   * haven't earned. The asymmetry is deliberate — this is a mirror, not a threat. */
  function streak(items, today) {
    const days = activityDays(items);
    const loggedToday = days.has(today);
    let cursor = loggedToday ? today : shift(today, -1);
    let current = 0;
    while (days.has(cursor)) {
      current++;
      cursor = shift(cursor, -1);
    }

    let best = 0, run = 0, prev = null;
    for (const day of [...days].sort()) {
      run = prev && shift(prev, 1) === day ? run + 1 : 1;
      prev = day;
      if (run > best) best = run;
    }
    return { current, best, loggedToday, days: days.size };
  }

  /* A calendar grid of the last `span` days, oldest first — one cell per day.
   * `level` 0..3 buckets the count so the grid reads at a glance without a legend.
   *
   * `pad` is how many blank cells the view must draw before the first day so that the
   * grid starts on a Monday. Without it the columns are seven arbitrary days rather than
   * weeks, and a gap in a run stops lining up with the week it happened in — which is the
   * only reason to draw a grid instead of a list. */
  function heatmap(items, today, span = 84) {
    const counts = new Map();
    for (const item of items || []) {
      const day = activeDay(item);
      if (day) counts.set(day, (counts.get(day) || 0) + 1);
    }
    const cells = [];
    for (let n = span - 1; n >= 0; n--) {
      const day = shift(today, -n);
      const count = counts.get(day) || 0;
      cells.push({ day, count, level: count === 0 ? 0 : count === 1 ? 1 : count <= 3 ? 2 : 3 });
    }
    // getUTCDay is 0=Sunday; the grid reads Monday-first, as the planner's week does.
    const pad = (new Date(cells[0].day + "T00:00:00Z").getUTCDay() + 6) % 7;
    return { cells, pad };
  }

  /* Per-week planned/done, oldest first. Only weeks that had a plan appear —
   * a week you never planned is not a week you failed. */
  function weekHistory(items, limit = 8) {
    const weeks = new Map();
    for (const item of items || []) {
      if (!isEntity(item, "task")) continue;
      const week = attrs(item).week;
      if (!week) continue;
      const row = weeks.get(week) || { week, planned: 0, done: 0 };
      row.planned++;
      if (attrs(item).status === "done") row.done++;
      weeks.set(week, row);
    }
    return [...weeks.values()]
      .sort((a, b) => (a.week < b.week ? -1 : a.week > b.week ? 1 : 0))
      .slice(-limit)
      .map((r) => ({ ...r, rate: r.planned ? Math.round((r.done / r.planned) * 100) : 0 }));
  }

  /* The headline numbers. `spanDays` is inclusive, so the day you started reads as 1. */
  function totals(items, today) {
    const list = items || [];
    const count = (fn) => list.filter(fn).length;
    const days = activityDays(list);
    const first = [...days].sort()[0] || "";
    return {
      daysShownUp: days.size,
      tasksDone: count((i) => isEntity(i, "task") && attrs(i).status === "done"),
      tasksPlanned: count((i) => isEntity(i, "task")),
      captures: count((i) => isEntity(i, "content") && attrs(i).type === "capture"),
      parked: count((i) => isEntity(i, "content") && attrs(i).type === "parked_idea"),
      retros: new Set(
        list.filter((i) => isEntity(i, "metric") && attrs(i).type === "weekly_retro")
          .map((i) => attrs(i).week)).size,
      firstDay: first,
      spanDays: first ? Math.round((Date.parse(today) - Date.parse(first)) / DAY_MS) + 1 : 0,
    };
  }

  /* Substring search over captures and parked ideas, newest first.
   * An empty query returns everything: search should narrow, never gate. */
  function searchCaptures(items, query, type) {
    const q = String(query || "").trim().toLowerCase();
    return (items || [])
      .filter((i) => isEntity(i, "content") && (!type || attrs(i).type === type))
      .filter((i) => !q || String(attrs(i).text || "").toLowerCase().includes(q))
      .sort((a, b) => (a.ts < b.ts ? 1 : a.ts > b.ts ? -1 : 0));
  }

  /* Something you wrote on this day of the MONTH, a while back.
   *
   * Recall is the payoff for having captured anything at all — it is what makes the pile
   * feel like a memory rather than a landfill. Matching the day of the month rather than
   * the full date is the difference between a feature that fires monthly and one that
   * fires on an anniversary the app is far too young to have.
   *
   * `minAgeDays` keeps last week out of it: being shown something you still remember
   * writing is not recall, it's clutter. */
  function onThisDay(items, today, minAgeDays = 14) {
    const cutoff = Date.parse(today) - minAgeDays * DAY_MS;
    const dayOfMonth = today.slice(8);
    const hits = (items || [])
      .filter((i) => isEntity(i, "content")
        && dayOf(i.ts).slice(8) === dayOfMonth
        && Date.parse(dayOf(i.ts)) <= cutoff)
      .sort((a, b) => (a.ts < b.ts ? 1 : -1));
    return hits[0] || null;
  }

  /* Progress through the current week's plan — the ring on the Today tab. */
  function weekProgress(items, week) {
    const tasks = (items || []).filter((i) => isEntity(i, "task") && attrs(i).week === week);
    const done = tasks.filter((i) => attrs(i).status === "done").length;
    return {
      planned: tasks.length,
      done,
      pct: tasks.length ? Math.round((done / tasks.length) * 100) : 0,
      complete: tasks.length > 0 && done === tasks.length,
    };
  }

  /* Turn a Web Share Target payload into one line of capture text.
   *
   * Lives here because this is where Travel's tested pure logic goes, and this needs testing
   * badly: Android apps are wildly inconsistent about what they put where. Chrome sends the
   * page title in `title` and the link in `url`; many apps put the link inside `text` and
   * send no `url` at all; some duplicate the title into `text`; Twitter-likes send
   * "title — url" pre-joined. Naively concatenating all three gives you the URL twice and
   * the title twice, on the one screen whose entire promise is "one gesture, no editing".
   *
   * Returns "" when there is nothing worth capturing, so the caller falls through to the
   * normal app rather than showing an empty confirmation. */
  function parseShare(search) {
    let params;
    try {
      params = new URLSearchParams(String(search || "").replace(/^\?/, ""));
    } catch (e) {
      return "";
    }
    const clean = (v) => String(v || "").replace(/\s+/g, " ").trim();
    const parts = [];
    for (const part of [clean(params.get("title")), clean(params.get("text")), clean(params.get("url"))]) {
      if (!part) continue;
      // Drop anything already contained in what we kept — that covers the duplicated title,
      // the URL echoed inside text, and the pre-joined "title — url" case at once.
      if (parts.some((kept) => kept.includes(part))) continue;
      // ...and if this part swallows an earlier one, replace rather than append.
      const swallowed = parts.findIndex((kept) => part.includes(kept));
      if (swallowed >= 0) parts[swallowed] = part;
      else parts.push(part);
    }
    return parts.join(" — ").slice(0, 2000);
  }

  return {
    activityDays, streak, heatmap, weekHistory, totals, searchCaptures, onThisDay,
    weekProgress, parseShare,
  };
});
