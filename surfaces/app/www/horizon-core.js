/* Horizon — the anti-hindrance core (T3), JS twin of modules/horizon/core.py.
 *
 * Pure, deterministic, no DOM and no IndexedDB. Travel Mode (travel.js) and the
 * Python server share this exact logic; the golden-file suite runs both against
 * tests/golden/cases.json so any drift between them fails CI instead of showing
 * up as odd behaviour on a phone with no laptop. Keep every function a
 * line-for-line mirror of core.py.
 *
 * Loads as a browser global (window.HorizonCore) or a CommonJS module (Node test
 * runner) — no build step, no bundler.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.HorizonCore = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"];
  const EVENING_TIME = "20:00";   // deep work -> evening/night, never morning
  const TROUGH_TIME = "14:00";    // admin -> the daytime trough
  const WEEKLY_CAP_TIRED = 3;     // hard cap on the week while baseline == tired
  const WEEKLY_CAP_RESTED = 7;
  const NEW_WORK_FLOOR = 3;       // start at most this many new items when unstuck
  const STALE_CYCLES = 2;         // carried past this many cycles => "smallest piece"

  const GATE_TARGET_DAYS = 28;
  const GATE_TARGET_RETROS = 4;

  const PARK_MESSAGE = "Captured, not abandoned — current gate first.";

  const PROJECT_IDEA_MARKERS = [
    "idea:", "new idea", "new project", "side project", "startup", "start a company",
    "i should build", "i want to build", "we could build", "i could build",
    "what if i built", "what if we built", "build an app", "build a platform",
    "launch a ", "new app", "new venture",
  ];
  const ADMIN_MARKERS = [
    "email", "invoice", "pay the", "pay my", "bill", "tax", "form", "renew",
    "book a", "book the", "schedule", "admin", "call the", "reply to", "submit",
    "file the", "paperwork", "appointment",
  ];

  /* ISO-8601 week id, e.g. "2026-W30" — twin of core.week_id / planner.week_id. */
  function weekId(d) {
    const date = d ? new Date(d) : new Date();
    const u = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
    const day = (u.getUTCDay() + 6) % 7;            // Mon=0 … Sun=6
    u.setUTCDate(u.getUTCDate() - day + 3);         // shift to the week's Thursday
    const firstThu = new Date(Date.UTC(u.getUTCFullYear(), 0, 4));
    const week = 1 + Math.round(((u - firstThu) / 864e5 - 3 + ((firstThu.getUTCDay() + 6) % 7)) / 7);
    return `${u.getUTCFullYear()}-W${String(week).padStart(2, "0")}`;
  }

  function hasMarker(text, markers) {
    const low = (text || "").toLowerCase();
    return markers.some((m) => low.indexOf(m) !== -1);
  }

  function isProjectIdea(text) { return hasMarker(text, PROJECT_IDEA_MARKERS); }
  function isAdmin(name) { return hasMarker(name, ADMIN_MARKERS); }

  function weeklyCap(baseline) {
    return (baseline || "tired") === "tired" ? WEEKLY_CAP_TIRED : WEEKLY_CAP_RESTED;
  }

  function shapeIfThen(ref, cycles, dayIndex) {
    const day = DAYS[dayIndex % DAYS.length];
    if (isAdmin(ref)) {
      return `If it's ${day} ${TROUGH_TIME}, then I clear '${ref}' (admin — batch it in the daytime dip)`;
    }
    if (cycles > STALE_CYCLES) {
      return `If it's ${day} ${EVENING_TIME}, then I do the smallest remaining piece of `
        + `'${ref}': one concrete physical step, 15 minutes`;
    }
    return `If it's ${day} ${EVENING_TIME}, then I spend 45 min on '${ref}'`;
  }

  /* Deterministic weekly plan — see core.offline_plan for the contract. */
  function offlinePlan(inp) {
    const cap = weeklyCap(inp.baseline || "tired");
    // Focus goals first (stable) — the gate/keystone goal is never crowded out.
    const goals = (inp.goals || []).slice().sort((a, b) => (a.focus ? 0 : 1) - (b.focus ? 0 : 1));
    const openTasks = inp.open_tasks || [];

    const carry = openTasks.slice().sort((a, b) => (Number(b.cycles) || 0) - (Number(a.cycles) || 0));

    const proposals = [];
    let stalePresent = false;
    let day = 0;
    for (const t of carry) {
      if (proposals.length >= cap) break;
      const cycles = (Number(t.cycles) || 0) + 1;
      const smallest = cycles > STALE_CYCLES;
      const ref = t.title || "";
      proposals.push({
        origin: "reuse",
        id: t.id === undefined ? null : t.id,
        title: ref,
        if_then: shapeIfThen(ref, cycles, day),
        status: "open",
        cycles: cycles,
        smallest_piece: smallest,
        goal_title: "",
      });
      stalePresent = stalePresent || smallest;
      day += 1;
    }

    if (!stalePresent) {
      const newLimit = Math.min(NEW_WORK_FLOOR, cap);
      for (const g of goals) {
        if (proposals.length >= newLimit) break;
        const title = g.title || "";
        proposals.push({
          origin: "new",
          id: null,
          title: `Advance: ${title}`,
          if_then: shapeIfThen(title, 1, day),
          status: "open",
          cycles: 1,
          smallest_piece: false,
          goal_title: title,
        });
        day += 1;
      }
    }
    return proposals;
  }

  function retro(week, tasks) {
    const done = tasks.filter((t) => t.status === "done");
    const planned = tasks.length;
    const rate = planned ? Math.round((done.length / planned) * 100) / 100 : 0.0;
    const lines = [`Retro ${week}: ${done.length}/${planned} tasks done (${Math.trunc(rate * 100)}%).`];
    for (const t of tasks) lines.push(`[${t.status === "done" ? "x" : " "}] ${t.title || ""}`);
    if (planned === 0) lines.push("Nothing was planned this week — plan it now.");
    return { week, planned, done: done.length, rate, text: lines.join("\n") };
  }

  function gateFromCounts(daysUsed, logsRecorded, retrosCompleted) {
    const cleared = daysUsed >= GATE_TARGET_DAYS && retrosCompleted >= GATE_TARGET_RETROS;
    const lines = [
      "v0.1 gate — use it daily for 4 weeks before any new surface.",
      `Days used: ${daysUsed}/${GATE_TARGET_DAYS}`,
      `Logs recorded: ${logsRecorded}`,
      `Retros completed: ${retrosCompleted}/${GATE_TARGET_RETROS}`,
    ];
    if (cleared) {
      lines.push("Gate cleared. You earned the next surface.");
    } else {
      const remaining = Math.max(0, GATE_TARGET_DAYS - daysUsed);
      lines.push(`${remaining} day(s) to go. Check the metric, don't re-decide — keep logging.`);
    }
    return {
      target_days: GATE_TARGET_DAYS,
      target_retros: GATE_TARGET_RETROS,
      days_used: daysUsed,
      logs_recorded: logsRecorded,
      retros_completed: retrosCompleted,
      cleared: cleared,
      text: lines.join("\n"),
    };
  }

  return {
    DAYS, EVENING_TIME, TROUGH_TIME, WEEKLY_CAP_TIRED, WEEKLY_CAP_RESTED,
    NEW_WORK_FLOOR, STALE_CYCLES, GATE_TARGET_DAYS, GATE_TARGET_RETROS, PARK_MESSAGE,
    weekId, isProjectIdea, isAdmin, weeklyCap, shapeIfThen, offlinePlan, retro,
    gateFromCounts,
  };
});
