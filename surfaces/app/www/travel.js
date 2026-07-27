/* LifeOS — Travel Mode: a fully standalone, offline-first Horizon.
 *
 * No gateway. No network. Every write lands in IndexedDB and never leaves the
 * browser. The flows here mirror the server's deterministic offline fallbacks
 * one-for-one (modules/horizon/{vision_intake,planner,retro}.py, voiceos/capture.py)
 * so that a bundle exported here reconciles cleanly into the real graph later
 * (ticket T2). Every record carries a stable key + original timestamp so import
 * is idempotent.
 */
"use strict";

const $ = (sel) => document.querySelector(sel);
const nowISO = () => new Date().toISOString();
const uid = () => (crypto.randomUUID ? crypto.randomUUID()
  : "x-" + Date.now() + "-" + Math.random().toString(16).slice(2));

const MODULE = "travel";
const Core = HorizonCore;   // shared, byte-identical logic (horizon-core.js) — no drift with Python.
const Stats = TravelStats;  // Travel-only, pure, tested by tests/travel/run_stats.mjs.
// Travel Mode is the tired-night-owl context by definition; the planner runs the
// same anti-hindrance rules the server uses at energy_baseline: tired.
const BASELINE = "tired";

const state = { tab: "today", items: [], editing: false, busy: false, enter: true,
                query: "", justDone: null, shared: "" };

const today = () => nowISO().slice(0, 10);

/* A short tap when something lands. Silent everywhere it isn't supported, and never
 * used for anything the user didn't just do with their thumb. */
function buzz(ms) {
  try { if (navigator.vibrate) navigator.vibrate(ms); } catch (e) { /* not supported */ }
}

/* ---------- IndexedDB (single 'items' store, keyed by stable key) ---------- */

const DB_NAME = "lifeos-travel";
const STORE = "items";
let _db = null;

function openDB() {
  return new Promise((resolve, reject) => {
    if (_db) return resolve(_db);
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains(STORE)) {
        req.result.createObjectStore(STORE, { keyPath: "key" });
      }
    };
    req.onsuccess = () => { _db = req.result; resolve(_db); };
    req.onerror = () => reject(req.error);
  });
}

function tx(mode) {
  return openDB().then((db) => db.transaction(STORE, mode).objectStore(STORE));
}

async function dbAll() {
  const store = await tx("readonly");
  return new Promise((resolve, reject) => {
    const req = store.getAll();
    req.onsuccess = () => resolve(req.result || []);
    req.onerror = () => reject(req.error);
  });
}

async function dbPut(item) {
  const store = await tx("readwrite");
  return new Promise((resolve, reject) => {
    const req = store.put(item);
    req.onsuccess = () => resolve(item);
    req.onerror = () => reject(req.error);
  });
}

async function dbClear() {
  const store = await tx("readwrite");
  return new Promise((resolve, reject) => {
    const req = store.clear();
    req.onsuccess = () => resolve();
    req.onerror = () => reject(req.error);
  });
}

async function dbDelete(key) {
  const store = await tx("readwrite");
  return new Promise((resolve, reject) => {
    const req = store.delete(key);
    req.onsuccess = () => resolve();
    req.onerror = () => reject(req.error);
  });
}

/* ---------- graph-shaped records (mirror substrate entity/edge shapes) ---------- */

async function createEntity(kind, attrs) {
  const item = { key: uid(), type: "entity", kind, attrs, ts: nowISO(), module: MODULE };
  state.items.push(item);
  await dbPut(item);
  return item;
}

async function createEdge(srcKey, dstKey, rel) {
  const item = { key: uid(), type: "edge", src: srcKey, dst: dstKey, rel, ts: nowISO(), module: MODULE };
  state.items.push(item);
  await dbPut(item);
  return item;
}

async function patchEntity(item, patch) {
  item.attrs = { ...item.attrs, ...patch };
  await dbPut(item);
  return item;
}

/* Remove an entity/edge and any edges that reference it (goal + its feeds edge). */
async function removeItem(key) {
  const gone = state.items.filter((i) => i.key === key || i.src === key || i.dst === key).map((i) => i.key);
  state.items = state.items.filter((i) => !gone.includes(i.key));
  for (const k of gone) await dbDelete(k);
}

/* ---------- selectors ---------- */

const entities = (kind) => state.items.filter((i) => i.type === "entity" && i.kind === kind);
const visions = () => entities("goal").filter((g) => g.attrs.level === "vision");
const planGoals = () => entities("goal").filter((g) => g.attrs.level === "goal");
const byTs = (a, b) => (a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : 0);

function weekTasks(week) {
  return entities("task").filter((t) => t.attrs.week === week).sort(byTs);
}

/* ISO-8601 week id — delegated to the shared core so JS and Python never drift. */
const weekId = (d) => Core.weekId(d);

/* ---------- flows (deterministic, offline — mirror the server fallbacks) ---------- */

/* vision_intake._offline_plan: line 1 = vision, remaining bullet lines = goals. */
async function doVision(text) {
  const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  if (!lines.length) {
    return { status: "questions", questions: ["Where do you want to be, and by when?"] };
  }
  const visionText = lines[0];
  const bullets = lines.slice(1)
    .map((l) => l.replace(/^[-*0-9.\s]+/, "").trim())
    .filter(Boolean);

  const vision = await createEntity("goal", { level: "vision", title: visionText });
  let idx = 0;
  for (const title of bullets) {
    // First goal is the default focus (gate-first) — retarget by tapping ★.
    const goal = await createEntity("goal", { level: "goal", title, why: "", horizon_weeks: 12, focus: idx === 0 });
    await createEdge(goal.key, vision.key, "feeds");
    idx++;
  }
  return { status: "created", vision: visionText, goals: bullets.length };
}

/* Weekly plan via the shared anti-hindrance core (boredom + energy shaping + cap). */
async function doPlan(week) {
  const cap = Core.weeklyCap(BASELINE);
  const existing = weekTasks(week);
  if (existing.length >= cap) return { week, tasks: existing.length, method: "already-planned" };

  const goals = planGoals();
  // Gate-ritual tasks are weekly, not goal work — never carry them over.
  const openTasks = entities("task").filter((t) => t.attrs.status === "open" && t.attrs.week !== week && !t.attrs.gate);
  const descriptors = Core.offlinePlan({
    baseline: BASELINE,
    gate_passed: computeGate().cleared,
    goals: goals.map((g) => ({ title: g.attrs.title || "", focus: !!g.attrs.focus })),
    open_tasks: openTasks.map((t) => ({
      id: t.key, title: t.attrs.title || "", if_then: t.attrs.if_then || "", cycles: t.attrs.cycles || 0,
    })),
  });

  const goalKeyByTitle = {};
  for (const g of goals) goalKeyByTitle[g.attrs.title || ""] = g.key;

  let count = 0;
  for (const d of descriptors) {
    const extra = { cycles: d.cycles, smallest_piece: d.smallest_piece, gate: d.gate };
    if (d.origin === "reuse" && d.id) {
      const task = state.items.find((i) => i.key === d.id);
      if (task) {
        const patch = { week, ...extra };
        if (d.if_then) patch.if_then = d.if_then;
        await patchEntity(task, patch);
      }
    } else {
      const task = await createEntity("task", { title: d.title, if_then: d.if_then, status: "open", week, ...extra });
      const gk = goalKeyByTitle[d.goal_title];
      if (gk) await createEdge(task.key, gk, "feeds");
    }
    count++;
  }
  return { week, tasks: count, method: "offline" };
}

/* Persist in-progress edit-view inputs so a re-render never drops unsaved text. */
async function flushEdits(root) {
  const v = visions()[0];
  const vt = root.querySelector("#edit-vision") && root.querySelector("#edit-vision").value.trim();
  if (v && vt) await patchEntity(v, { title: vt });
  for (const g of planGoals()) {
    const inp = root.querySelector(`[data-goal-name="${CSS.escape(g.key)}"]`);
    const nt = inp && inp.value.trim();
    if (nt && nt !== g.attrs.title) await patchEntity(g, { title: nt });
  }
}

/* Add a goal under the current vision (used by the edit view). */
async function addGoal(title) {
  const v = visions()[0];
  if (!v || !title) return;
  const g = await createEntity("goal", { level: "goal", title, why: "", horizon_weeks: 12, focus: false });
  await createEdge(g.key, v.key, "feeds");
}

/* Toggle a task's done state (tap logs it, tap again undoes a mis-tap). */
async function toggleLog(taskKey) {
  const task = state.items.find((i) => i.key === taskKey);
  if (!task) return;
  const done = task.attrs.status === "done";
  await patchEntity(task, done ? { status: "open", done_at: "" } : { status: "done", done_at: nowISO() });
}

const retroMetric = (week) =>
  entities("metric").filter((m) => m.attrs.type === "weekly_retro" && m.attrs.week === week).sort(byTs).pop();

/* Recompute the retro text for a week from its current tasks (survives reload). */
function retroText(week) {
  if (!retroMetric(week)) return null;
  const views = weekTasks(week).map((t) => ({ title: t.attrs.title || "", status: t.attrs.status || "open" }));
  return Core.retro(week, views).text;
}

/* Weekly retro via the shared core. One metric per week (upsert), so re-running
   the retro never inflates the gate's retro count. */
async function doRetro(week) {
  const views = weekTasks(week).map((t) => ({ title: t.attrs.title || "", status: t.attrs.status || "open" }));
  const scored = Core.retro(week, views);
  const patch = { planned: scored.planned, done: scored.done, rate: scored.rate };
  const existing = retroMetric(week);
  if (existing) await patchEntity(existing, patch);
  else await createEntity("metric", { type: "weekly_retro", week, ...patch });
  return scored;
}

/* Capture with the distraction sink (T3): a new-project idea is parked, not planned. */
async function doCapture(text) {
  if (Core.isProjectIdea(text)) {
    await createEntity("content", { type: "parked_idea", text, parked_at: nowISO() });
    return { parked: true, message: Core.PARK_MESSAGE };
  }
  await createEntity("content", { type: "capture", text });
  return { parked: false };
}

/* Doubt rule (T3): honest v0.1-gate progress from what's actually on this phone.
   Day counting lives in travel-stats.js so the gate and the Journey tab can never
   quote different numbers at you. */
function computeGate() {
  const done = entities("task").filter((t) => t.attrs.status === "done");
  const retroWeeks = new Set(entities("metric").filter((m) => m.attrs.type === "weekly_retro").map((m) => m.attrs.week));
  return Core.gateFromCounts(Stats.activityDays(state.items).size, done.length, retroWeeks.size);
}

/* ---------- export (the reconciliation bundle T2 imports) ---------- */

function buildBundle() {
  return {
    schema: "lifeos-travel-export/v1",
    exported_at: nowISO(),
    source: MODULE,
    count: state.items.length,
    items: state.items.slice().sort(byTs),
  };
}

const bundleName = () => `lifeos-travel-${weekId()}.json`;

function exportBundle() {
  const blob = new Blob([JSON.stringify(buildBundle(), null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = bundleName();
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/* Hand the bundle to the phone's own share sheet — AirDrop, Files, a note to yourself.
 * A silent download into a folder you can't browse is not a backup you'd ever find again,
 * and this app's only user is on a phone. Falls back to the download when sharing a file
 * isn't supported, and a cancelled share is not an error. */
async function shareBundle() {
  const file = new File([JSON.stringify(buildBundle(), null, 2)], bundleName(),
                        { type: "application/json" });
  if (navigator.canShare && navigator.canShare({ files: [file] })) {
    try {
      await navigator.share({ files: [file], title: "LifeOS travel data" });
      return "shared";
    } catch (e) {
      if (e && e.name === "AbortError") return "cancelled";
    }
  }
  exportBundle();
  return "downloaded";
}

/* ---------- helpers ---------- */

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(el._t);
  el._t = setTimeout(() => { el.hidden = true; }, 2600);
}

/* One quiet flare, then it removes itself. Skipped entirely under reduced-motion (the
   stylesheet hides it), so this never leaves a stray node behind. */
function flare() {
  const el = document.createElement("div");
  el.className = "spark-burst";
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 700);
}

async function act(fn, okMsg) {
  if (state.busy) return;
  state.busy = true;
  try {
    await fn();
    if (okMsg) toast(okMsg);
  } catch (e) {
    toast("⚠ " + e.message);
  } finally {
    state.busy = false;
  }
}

/* ---------- views ---------- */

function render() {
  const view = $("#view");
  const views = { today: todayView, capture: captureView, journey: journeyView, gate: gateView };
  // A pending share takes over the whole view: you came here to do exactly one thing.
  view.innerHTML = state.shared ? sharedView() : (views[state.tab] || todayView)();
  view.classList.toggle("enter", state.enter);
  state.enter = false;
  wire(view);
}

/* The one thing you see first, every day: how long you've kept showing up, and how far
   through this week's plan you are. Both are counts, never scores. */
function pulseCard() {
  const s = Stats.streak(state.items, today());
  const p = Stats.weekProgress(state.items, weekId());
  const label = p.planned ? `${p.done}/${p.planned}` : "–";
  const sub = s.loggedToday
    ? (p.complete ? "Week's plan is done" : "Logged today")
    : (s.current ? "Still open — today isn't spent yet" : "Nothing logged yet");
  const parts = [sub];
  if (s.best > s.current) parts.push(`best ${s.best}`);
  return `<div class="card hero"><div class="pulse">
      <div class="ring ${p.complete ? "full" : ""}" style="--pct:${p.pct}">
        <span class="ring-label">${label}</span></div>
      <div class="pulse-copy">
        <div class="streak-n">${s.current} <small>day${s.current === 1 ? "" : "s"} running</small></div>
        <div class="streak-sub">${esc(parts.join(" · "))}</div>
      </div></div></div>`;
}

function todayView() {
  const week = weekId();
  const tasks = weekTasks(week);
  const goals = planGoals();
  const v = visions()[0];
  let html = "";

  if (v) html += pulseCard();

  if (!v) {
    html += `<div class="card"><h2>Start here</h2>
      <p class="big">Paste your vision and a few goal lines — Travel Mode backcasts them into a plan, all on this phone.</p>
      <textarea id="vision-text" placeholder="Freedom by 40&#10;- Ship Life OS and run my week with it&#10;- Train 3x per week"></textarea>
      <button class="primary" data-act="vision">Create my plan</button>
      <p class="hint">Line 1 is the vision; each line below becomes a goal. No account, no server — it stays in this browser.</p></div>`;
  } else if (state.editing) {
    html += `<div class="card"><h2>Edit vision &amp; goals</h2>
      <input class="field" id="edit-vision" value="${esc(v.attrs.title)}" aria-label="Vision">
      ${goals.map((g) => `
        <div class="row2" style="align-items:center">
          <input class="field" data-goal-name="${g.key}" value="${esc(g.attrs.title)}">
          <button class="pill ${g.attrs.focus ? "warm" : ""}" data-focus="${g.key}" style="flex:none">${g.attrs.focus ? "★" : "☆"}</button>
          <button class="pill bad" data-goal-del="${g.key}" style="flex:none">✕</button>
        </div>`).join("")}
      <div class="row2"><input class="field" id="new-goal" placeholder="Add a goal">
        <button class="pill" data-act="add-goal" style="flex:none">Add</button></div>
      <button class="primary" data-act="save-goals">Done editing</button>
      <p class="hint">Rename, remove, or add goals. Changes apply to your next weekly plan.</p></div>`;
  } else {
    html += `<div class="card"><h2>Your vision</h2>
      <p class="big">${esc(v.attrs.title)}</p>`;
    if (goals.length) {
      html += `<p class="hint">Tap ★ to make a goal lead the week (gate-first, up to 2).</p>`;
      html += goals.map((g) => `
        <div class="person"><div class="who"><div class="name">${esc(g.attrs.title)}</div></div>
        <div class="pills"><button class="pill ${g.attrs.focus ? "warm" : ""}" data-focus="${g.key}">${g.attrs.focus ? "★ focus" : "☆"}</button></div></div>`).join("");
    }
    html += `<button class="ghost" data-act="edit">Edit vision &amp; goals</button></div>`;
  }

  html += `<div class="card"><h2>Week ${esc(week)}</h2>`;
  if (!tasks.length) {
    html += v
      ? `<p class="empty">Nothing planned yet.</p><button class="primary" data-act="plan">Plan this week</button>`
      : `<p class="empty">Create your plan above first.</p>`;
  } else {
    html += tasks.map((t, i) => `
      <div class="task ${t.attrs.status === "done" ? "done" : ""}${t.key === state.justDone ? " just-done" : ""}"
           data-log="${t.key}" data-n="${i + 1}">
        <div class="box">${t.attrs.status === "done" ? "✓" : ""}</div>
        <div><div class="title">${esc(t.attrs.title)}</div>
        ${t.attrs.if_then ? `<div class="ifthen">${esc(t.attrs.if_then)}</div>` : ""}</div>
      </div>`).join("");
    html += `<p class="hint">Tap a task to log it · tap again to undo.</p>`;
    html += `<button class="ghost" data-act="retro">Run the weekly retro</button>`;
  }
  html += `</div>`;

  const rt = retroText(week);
  if (rt) {
    html += `<div class="card"><h2>Retro</h2><div class="retro-text">${esc(rt)}</div></div>`;
  }
  return html;
}

/* A feed row with a delete (✕) button, for captures and parked ideas. */
function delRow(key, inner) {
  return `<div class="feed-item" style="display:flex;justify-content:space-between;align-items:center;gap:10px">
    <div class="label" style="margin:0">${inner}</div>
    <button class="pill bad" data-del-content="${key}" style="flex:none">✕</button></div>`;
}

/* Highlight the matched substring, on ALREADY-ESCAPED text — the query is escaped too,
   so nothing user-written is ever re-interpreted as markup. */
function highlight(text, query) {
  const safe = esc(text);
  const q = String(query || "").trim();
  if (!q) return safe;
  const needle = esc(q).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return safe.replace(new RegExp(needle, "gi"), (m) => `<mark>${m}</mark>`);
}

/* Something arrived from another app's share sheet.
 *
 * Shown for confirmation rather than saved silently, and the confirmation names the
 * DECISION: this is the moment the distraction sink is most useful and least visible, so
 * "this will be parked, not planned" gets said before you commit, not discovered later. */
function sharedView() {
  const parked = Core.isProjectIdea(state.shared);
  return `<div class="card hero"><h2>Shared to LifeOS</h2>
      <div class="shared-text">${esc(state.shared)}</div>
      <div class="verdict ${parked ? "park" : "keep"}">${parked
        ? esc(Core.PARK_MESSAGE)
        : "Captured with the rest of your week."}</div>
      <div class="row2" style="margin-top:14px">
        <button class="primary" data-act="shared-save">${parked ? "Park it" : "Capture it"}</button>
        <button class="ghost" data-act="shared-drop" style="flex:none">Discard</button>
      </div>
      <p class="hint">Shared straight from another app. It stays on this phone like everything
      else here.</p></div>`;
}

function captureView() {
  const q = state.query;
  const recent = Stats.searchCaptures(state.items, q, "capture");
  const parked = Stats.searchCaptures(state.items, q, "parked_idea");
  const total = Stats.searchCaptures(state.items, "").length;

  let html = `<div class="card"><h2>Capture a thought</h2>
      <textarea id="capture-text" placeholder="Anything — a task, an idea, a name. Saved locally; syncs to the graph when you're home."></textarea>
      <button class="primary" data-act="capture">Capture</button>
      <p class="hint">A new-project idea gets parked, not planned — captured so it's not lost, but the current gate keeps priority.</p></div>`;

  // Search only appears once there's a pile worth searching — a filter over four notes
  // is furniture, not a feature.
  if (total >= 8) {
    html += `<div class="card"><div class="search-row">
        <input class="field" id="capture-search" type="search" placeholder="Search everything you've captured"
               value="${esc(q)}" autocomplete="off">
        <span class="count-chip">${recent.length + parked.length}/${total}</span>
      </div></div>`;
  }

  html += `<div class="card"><h2>Recent captures</h2>
      ${recent.length ? recent.map((r) => delRow(r.key, highlight(r.attrs.text, q))).join("")
                      : `<p class="empty">${q ? "Nothing matches that." : "Nothing captured yet."}</p>`}
    </div>`;
  html += `<div class="card"><h2>Parked ideas</h2>
      ${parked.length ? parked.map((r) => delRow(r.key, `<div class="kind">parked</div>` + highlight(r.attrs.text, q))).join("")
                      : `<p class="empty">${q ? "Nothing parked matches that." : "Distraction-free. New-project ideas you park land here."}</p>`}</div>`;
  return html;
}

/* The Journey tab — the pile made legible.
 *
 * Everything here is a count of something that actually happened. No score, no grade, no
 * projection: the point is that a graph you keep adding to is worth more every week, and
 * that is only motivating if you can see it. */
function journeyView() {
  const t = Stats.totals(state.items, today());
  if (!t.daysShownUp) {
    return `<div class="card"><h2>Your journey</h2>
      <p class="empty">Nothing to show yet — log a task or capture a thought and this fills in.</p>
      <p class="hint">Everything on this tab is counted from what's on this phone. Nothing is estimated,
      and nothing is sent anywhere.</p></div>`;
  }

  const s = Stats.streak(state.items, today());
  const heat = Stats.heatmap(state.items, today(), 84);
  const weeks = Stats.weekHistory(state.items, 8);
  const recall = Stats.onThisDay(state.items, today());

  let html = `<div class="card hero"><h2>Your journey</h2>
    <p class="big">${t.spanDays} day${t.spanDays === 1 ? "" : "s"} in · showed up on ${t.daysShownUp} of them</p>
    <div class="stat-grid">
      <div class="stat grow"><div class="n">${t.tasksDone}</div><div class="l">tasks finished</div></div>
      <div class="stat warm"><div class="n">${s.best}</div><div class="l">longest run (days)</div></div>
      <div class="stat"><div class="n">${t.captures}</div><div class="l">thoughts captured</div></div>
      <div class="stat"><div class="n">${t.retros}</div><div class="l">weeks reviewed</div></div>
    </div></div>`;

  html += `<div class="card"><h2>Last 12 weeks</h2>
    <div class="heat">${'<i data-pad="1"></i>'.repeat(heat.pad)}${heat.cells.map((c) => `<i data-l="${c.level}"${c.day === today() ? ' data-today="1"' : ""}
      title="${c.day}: ${c.count} thing${c.count === 1 ? "" : "s"}"></i>`).join("")}</div>
    <p class="hint">One dot per day, newest at the right — a column is a week, Monday at the top.
    Gaps are just gaps; you were living.</p></div>`;

  if (weeks.length) {
    html += `<div class="card"><h2>How the weeks went</h2>
      <div class="bars">${weeks.map((w) => `
        <div class="bar" title="${esc(w.week)}: ${w.done}/${w.planned}">
          <div class="track"><div class="fill ${w.rate ? "" : "none"}" style="height:${Math.max(w.rate, 3)}%"></div></div>
          <div class="wk">${esc(w.week.slice(-3))}</div>
        </div>`).join("")}</div>
      <p class="hint">Planned versus finished, per week. Only weeks you planned appear — a week you
      never planned isn't a week you failed.</p></div>`;
  }

  if (recall) {
    const when = recall.ts.slice(0, 10);
    html += `<div class="card"><h2>You wrote this</h2>
      <div class="recall"><div class="when">${esc(when)}</div>
      <div class="what">${esc(recall.attrs.text)}</div></div>
      <p class="hint">Same day of the month, a while back. This is what the pile is for.</p></div>`;
  }

  if (t.parked) {
    html += `<div class="card"><div class="kv" style="border:none"><span>Ideas parked, not lost</span>
      <span class="v">${t.parked}</span></div>
      <p class="hint">${esc(Core.PARK_MESSAGE)}</p></div>`;
  }
  return html;
}

function gateView() {
  const g = computeGate();
  return `<div class="card"><h2>v0.1 gate</h2>
      <div class="retro-text">${esc(g.text)}</div>
      <p class="hint">Real counts from this phone. When doubt shows up while tired, check the metric — don't re-decide.</p></div>`;
}

/* ---------- wiring ---------- */

function wire(root) {
  const on = (sel, handler) => root.querySelectorAll(sel).forEach((el) =>
    el.addEventListener("click", () => handler(el)));

  on("[data-act=vision]", () => act(async () => {
    const text = $("#vision-text").value.trim();
    if (!text) return toast("Write the vision first.");
    const result = await doVision(text);
    if (result.status === "questions") {
      $("#vision-text").value = text + "\n\n" + result.questions.map((q) => "? " + q).join("\n");
      return toast("A few questions first…");
    }
    render();
  }, "Plan created ✔"));

  on("[data-act=plan]", () => act(async () => { await doPlan(weekId()); render(); }, "Week planned ✔"));

  on("[data-focus]", (el) => act(async () => {
    if (state.editing) await flushEdits(root);
    const g = state.items.find((i) => i.key === el.dataset.focus);
    if (g) await patchEntity(g, { focus: !g.attrs.focus });
    render();
  }));

  on("[data-act=edit]", () => { state.editing = true; render(); });

  on("[data-act=add-goal]", () => act(async () => {
    const t = $("#new-goal").value.trim();
    if (!t) return toast("Name the goal.");
    await flushEdits(root);
    await addGoal(t);
    render();
  }, "Goal added ✔"));

  on("[data-goal-del]", (el) => act(async () => {
    await flushEdits(root);
    await removeItem(el.dataset.goalDel);
    render();
  }, "Goal removed"));

  on("[data-act=save-goals]", () => act(async () => {
    await flushEdits(root);
    state.editing = false;
    render();
  }, "Saved ✔"));

  on("[data-del-content]", (el) => act(async () => { await removeItem(el.dataset.delContent); render(); }, "Removed"));

  root.querySelectorAll(".task").forEach((el) => el.addEventListener("click", () => act(async () => {
    const before = Stats.weekProgress(state.items, weekId());
    await toggleLog(el.dataset.log);
    const after = Stats.weekProgress(state.items, weekId());
    const finished = after.done > before.done;
    state.justDone = finished ? el.dataset.log : null;   // one-shot: the pop plays once
    buzz(finished ? 14 : 8);
    render();
    state.justDone = null;
    // The last task of the week is the only moment that gets a flare. Rationing it is
    // what keeps it meaning something.
    if (finished && after.complete && !before.complete) {
      flare();
      buzz([18, 60, 26]);
      toast("Week's plan is done ✔");
    }
  })));

  const search = root.querySelector("#capture-search");
  if (search) {
    search.addEventListener("input", () => {
      state.query = search.value;
      render();
      // Re-focus and restore the caret: re-rendering the list must not eject you
      // from the box you're typing in.
      const next = $("#capture-search");
      if (next) { next.focus(); next.setSelectionRange(next.value.length, next.value.length); }
    });
  }

  on("[data-act=retro]", () => act(async () => { await doRetro(weekId()); render(); }));

  on("[data-act=shared-save]", () => act(async () => {
    const text = state.shared;
    state.shared = "";
    const r = await doCapture(text);
    state.tab = "capture";
    document.querySelectorAll("nav .tab").forEach((x) => x.classList.toggle("active", x.dataset.tab === "capture"));
    buzz(12);
    render();
    toast(r.parked ? "Parked ✔" : "Captured ✔");
  }));

  on("[data-act=shared-drop]", () => { state.shared = ""; render(); });

  on("[data-act=capture]", () => act(async () => {
    const text = $("#capture-text").value.trim();
    if (!text) return toast("Nothing to capture.");
    const r = await doCapture(text);
    render();
    toast(r.parked ? r.message : "Captured ✔");
  }));
}

/* ---------- tabs, settings, boot ---------- */

document.querySelectorAll("nav .tab").forEach((b) => b.addEventListener("click", () => {
  state.tab = b.dataset.tab;
  state.enter = true;
  document.querySelectorAll("nav .tab").forEach((x) => x.classList.toggle("active", x === b));
  render();
}));

$("#settings-btn").addEventListener("click", () => $("#settings").showModal());
$("#set-close").addEventListener("click", () => $("#settings").close());
$("#set-export").addEventListener("click", () => { exportBundle(); toast("Bundle downloaded — import it at home."); });
$("#set-share").addEventListener("click", () => act(async () => {
  const how = await shareBundle();
  if (how !== "cancelled") toast(how === "shared" ? "Sent ✔" : "Bundle downloaded — import it at home.");
}));
$("#set-reset").addEventListener("click", () => act(async () => {
  if (!confirm("Erase all Travel Mode data on this phone? Export first if you want to keep it.")) return;
  await dbClear();
  state.items = [];
  state.editing = false;
  $("#settings").close();
  render();
}, "Local data cleared."));

if ("serviceWorker" in navigator && location.protocol.startsWith("http")) {
  navigator.serviceWorker.register("travel-sw.js").catch(() => {});
}

/* Read anything the launch URL carried — a share payload, or the manifest shortcut's tab —
 * then scrub it with replaceState so a reload or a task restore cannot capture the same
 * thing twice. */
function readLaunchUrl() {
  const shared = Stats.parseShare(location.search);
  const tab = new URLSearchParams(location.search.replace(/^\?/, "")).get("tab");
  if (shared) state.shared = shared;
  if (tab && ["today", "capture", "journey", "gate"].includes(tab)) {
    state.tab = tab;
    document.querySelectorAll("nav .tab").forEach((x) => x.classList.toggle("active", x.dataset.tab === tab));
  }
  if ((shared || tab) && window.history && history.replaceState) {
    history.replaceState({}, "", location.pathname);
  }
}

async function boot() {
  try {
    state.items = await dbAll();
  } catch (e) {
    toast("⚠ Local storage unavailable: " + e.message);
  }
  readLaunchUrl();
  render();
}

boot();
