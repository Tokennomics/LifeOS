/* LifeOS Travel Mode — the coach: a propose-only agent that runs on your own phone.
 *
 * This is Phase 1 of the agentic arc, at autonomy level **L0: it proposes, you decide.**
 * Nothing in this file writes anything. It reads the item log and returns a list of
 * proposals; the view renders them as cards and only your tap causes a write. That is not
 * a limitation to be lifted later by default — it is the design, and the roadmap's
 * kill-gate for raising it is explicit.
 *
 * Three rules it is built to keep:
 *
 *   1. **Every proposal carries its evidence.** A coach that says "you should do less"
 *      without showing the count is indistinguishable from a nag. Each proposal has a
 *      `why` built from real numbers, in the same spirit as the doubt rule: check the
 *      metric, don't re-decide.
 *   2. **No API key.** All of this is arithmetic over what you already stored. An LLM can
 *      make the wording warmer later; it can never be required for the coach to work.
 *   3. **It says at most a few things.** An assistant that surfaces nine observations has
 *      told you nothing. Proposals are ranked and the caller takes the top handful.
 *
 * Travel-only, no Python twin. Tested by tests/travel/run_coach.mjs under pytest.
 * Loads as a browser global (window.TravelCoach) or a CommonJS module — no build step.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.TravelCoach = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const STALE_WEEKS = 3;        // a goal untouched this long is worth mentioning, once
  const THEME_MIN_HITS = 3;     // a word must recur this often before it means anything
  const MIN_WEEKS_FOR_ADVICE = 3;  // never draw a trend from one or two weeks
  const OVERCOMMIT_RATE = 55;   // finishing below this share, consistently, is over-planning

  const isEntity = (i, kind) => i && i.type === "entity" && i.kind === kind;
  const attrs = (i) => (i && i.attrs) || {};
  const textOf = (i) => String(attrs(i).text || "");

  /* Words too common to mean anything. Deliberately small: an over-eager stop list hides
   * exactly the domain words ("gym", "book") that make a theme worth noticing. */
  const STOP = new Set(("the a an and or but if then to of in on at for with from by about "
    + "is are was were be been being do does did doing have has had i me my we our you your "
    + "it its this that these those there here not no yes so as up out get got go going "
    + "just really very more most some any all can could should would will just need needs "
    + "want wants like").split(" "));

  function words(text) {
    return String(text || "").toLowerCase()
      .split(/[^a-z0-9']+/)
      .filter((w) => w.length > 2 && !STOP.has(w));
  }

  /* Milliseconds at the Monday of an ISO week id ("2026-W31"), or NaN if unparseable.
   *
   * Real dates, not a position in the list of weeks you happen to have planned: if you
   * planned W20 and then W31, those are adjacent entries but eleven weeks apart, and a
   * coach that can't tell the difference will call a long-abandoned goal "recent". */
  function weekStart(id) {
    const m = /^(\d{4})-W(\d{2})$/.exec(String(id || ""));
    if (!m) return NaN;
    const [year, week] = [Number(m[1]), Number(m[2])];
    const jan4 = Date.UTC(year, 0, 4);
    const isoDow = (new Date(jan4).getUTCDay() + 6) % 7;   // 0 = Monday
    return jan4 - isoDow * 86400000 + (week - 1) * 7 * 86400000;
  }

  const weeksApart = (a, b) => {
    const [x, y] = [weekStart(a), weekStart(b)];
    return Number.isNaN(x) || Number.isNaN(y) ? null : Math.round((y - x) / (7 * 86400000));
  };

  /* ---- the proposals -------------------------------------------------- */

  function planWeek(ctx) {
    const { thisWeek, weeks } = ctx;
    if (weeks.some((w) => w.week === thisWeek)) return null;
    return {
      id: `plan:${thisWeek}`,
      kind: "plan",
      title: "Draft this week",
      why: weeks.length
        ? `You've planned ${weeks.length} week${weeks.length === 1 ? "" : "s"} before. Nothing yet for ${thisWeek}.`
        : "Nothing planned yet. The planner will keep it to what a tired week can hold.",
      action: "plan",
      weight: 100,
    };
  }

  function rightSize(ctx) {
    // Advice for BEFORE you commit. Once the week is planned, telling you to plan less is
    // either a no-op or a request to undo — neither is coaching.
    if (ctx.weeks.some((w) => w.week === ctx.thisWeek)) return null;
    const recent = ctx.weeks.filter((w) => w.week !== ctx.thisWeek).slice(-4);
    if (recent.length < MIN_WEEKS_FOR_ADVICE) return null;
    const planned = recent.reduce((n, w) => n + w.planned, 0);
    const done = recent.reduce((n, w) => n + w.done, 0);
    if (!planned) return null;
    const rate = Math.round((done / planned) * 100);
    if (rate >= OVERCOMMIT_RATE) return null;
    // Propose what you have actually been finishing, rounded up, never below one.
    const suggest = Math.max(1, Math.round(done / recent.length));
    if (suggest >= Math.round(planned / recent.length)) return null;
    return {
      id: `size:${ctx.thisWeek}`,
      kind: "right_size",
      title: `Try committing to ${suggest} this week`,
      why: `Over the last ${recent.length} weeks you planned ${planned} and finished ${done} (${rate}%). `
        + `A week you finish beats a week you abandon.`,
      action: "plan_smaller",
      limit: suggest,
      weight: 100,
    };
  }

  function stuckGoal(ctx) {
    const { goals, tasksByGoal, thisWeek } = ctx;
    let worst = null;
    for (const goal of goals) {
      const planned = tasksByGoal[goal.key] || [];
      if (!planned.length) continue;      // never started is not stuck — it just hasn't begun
      const done = planned.filter((t) => attrs(t).status === "done");
      const last = done.map((t) => attrs(t).week).sort().pop();
      const gap = last ? weeksApart(last, thisWeek) : null;
      if (gap !== null && gap < STALE_WEEKS) continue;     // moved recently enough
      if (!worst || (last || "") < (worst.last || "")) worst = { goal, last };
    }
    if (!worst) return null;
    return {
      id: `stuck:${worst.goal.key}`,
      kind: "stuck",
      title: `"${attrs(worst.goal).title}" hasn't moved`,
      why: worst.last
        ? `Nothing finished on it since ${worst.last}. Either make it the focus, or let it go for now — carrying it silently is the expensive option.`
        : `Planned but never finished. Either make it the focus, or let it go for now.`,
      action: "focus_goal",
      goalKey: worst.goal.key,
      weight: 70,
    };
  }

  function recurringTheme(ctx) {
    const { captures, goalText } = ctx;
    const seen = new Map();
    for (const capture of captures) {
      // Count DISTINCT captures per word, not occurrences — one rambling note repeating
      // "gym" six times is one thought, not a pattern.
      for (const word of new Set(words(textOf(capture)))) {
        seen.set(word, (seen.get(word) || 0) + 1);
      }
    }
    let best = null;
    for (const [word, hits] of seen) {
      if (hits < THEME_MIN_HITS) continue;
      if (goalText.includes(word)) continue;              // already something you're working on
      if (!best || hits > best.hits) best = { word, hits };
    }
    if (!best) return null;
    return {
      id: `theme:${best.word}`,
      kind: "theme",
      title: `"${best.word}" keeps coming up`,
      why: `It's in ${best.hits} separate captures and none of your goals. That's either a goal `
        + `you haven't admitted to, or noise worth clearing.`,
      action: "search",
      query: best.word,
      weight: 60,
    };
  }

  function retroDue(ctx) {
    const { weeks, thisWeek, retroWeeks } = ctx;
    const past = weeks.filter((w) => w.week < thisWeek);
    const last = past[past.length - 1];
    if (!last || retroWeeks.has(last.week)) return null;
    return {
      id: `retro:${last.week}`,
      kind: "retro",
      title: `${last.week} never got its retro`,
      why: `${last.done} of ${last.planned} finished. The retro is the part that compounds — `
        + `it's also what the gate counts.`,
      action: "retro",
      week: last.week,
      weight: 80,
    };
  }

  /* ---- assembly -------------------------------------------------------- */

  function context(items, today, thisWeek) {
    const list = items || [];
    const goals = list.filter((i) => isEntity(i, "goal") && attrs(i).level === "goal");
    const tasks = list.filter((i) => isEntity(i, "task"));
    const edges = list.filter((i) => i && i.type === "edge" && i.rel === "feeds");

    const goalOf = {};
    for (const edge of edges) goalOf[edge.src] = edge.dst;
    const tasksByGoal = {};
    for (const task of tasks) {
      const key = goalOf[task.key];
      if (!key) continue;
      (tasksByGoal[key] = tasksByGoal[key] || []).push(task);
    }

    const byWeek = new Map();
    for (const task of tasks) {
      const week = attrs(task).week;
      if (!week) continue;
      const row = byWeek.get(week) || { week, planned: 0, done: 0 };
      row.planned++;
      if (attrs(task).status === "done") row.done++;
      byWeek.set(week, row);
    }
    const weeks = [...byWeek.values()].sort((a, b) => (a.week < b.week ? -1 : 1));

    return {
      today, thisWeek, goals, weeks, tasksByGoal,
      // `coach_dismissed` rows are the coach's own bookkeeping — never its evidence.
      captures: list.filter((i) => isEntity(i, "content")
        && attrs(i).type !== "coach_dismissed"),
      goalText: goals.map((g) => String(attrs(g).title || "").toLowerCase()).join(" "),
      retroWeeks: new Set(list
        .filter((i) => isEntity(i, "metric") && attrs(i).type === "weekly_retro")
        .map((i) => attrs(i).week)),
    };
  }

  /* The whole coach. `dismissed` is a list of proposal ids you've already waved away —
   * an assistant that re-raises something you declined is one you stop reading. */
  function proposals(items, today, thisWeek, dismissed, limit = 3) {
    const ctx = context(items, today, thisWeek);
    const skip = new Set(dismissed || []);
    let found = [planWeek, retroDue, rightSize, stuckGoal, recurringTheme]
      .map((fn) => fn(ctx))
      .filter((p) => p && !skip.has(p.id));
    // "Draft this week" and "try committing to N" are the same decision at two sizes.
    // Offering both is asking a question twice; the sized one already implies the plain one.
    if (found.some((p) => p.kind === "right_size")) {
      found = found.filter((p) => p.kind !== "plan");
    }
    return found.sort((a, b) => b.weight - a.weight).slice(0, limit);
  }

  return { proposals, words, weeksApart, STALE_WEEKS, THEME_MIN_HITS, OVERCOMMIT_RATE, MIN_WEEKS_FOR_ADVICE };
});
