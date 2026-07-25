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
const Core = HorizonCore; // shared, byte-identical logic (horizon-core.js) — no drift with Python.
// Travel Mode is the tired-night-owl context by definition; the planner runs the
// same anti-hindrance rules the server uses at energy_baseline: tired.
const BASELINE = "tired";

const state = { tab: "today", items: [], editing: false, busy: false, enter: true };

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

/* Distinct calendar days (UTC) with any activity — logs, captures, retros. */
function activityDays() {
  const days = new Set();
  for (const t of entities("task").filter((x) => x.attrs.status === "done")) days.add((t.attrs.done_at || t.ts || "").slice(0, 10));
  for (const c of entities("content")) days.add((c.ts || "").slice(0, 10));
  for (const r of entities("metric").filter((m) => m.attrs.type === "weekly_retro")) days.add((r.ts || "").slice(0, 10));
  days.delete("");
  return days;
}

/* Current show-up streak + whether today is already logged. Reinforces the habit
   the gate measures — the streak holds through today until you log again. */
function streakInfo() {
  const days = activityDays();
  const loggedToday = days.has(nowISO().slice(0, 10));
  const d = new Date();
  if (!loggedToday) d.setUTCDate(d.getUTCDate() - 1); // today not logged yet → count from yesterday
  let streak = 0;
  while (days.has(d.toISOString().slice(0, 10))) {
    streak++;
    d.setUTCDate(d.getUTCDate() - 1);
  }
  return { streak, loggedToday };
}

/* Doubt rule (T3): honest v0.1-gate progress from what's actually on this phone. */
function computeGate() {
  const done = entities("task").filter((t) => t.attrs.status === "done");
  const retroWeeks = new Set(entities("metric").filter((m) => m.attrs.type === "weekly_retro").map((m) => m.attrs.week));
  return Core.gateFromCounts(activityDays().size, done.length, retroWeeks.size);
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

function exportBundle() {
  const blob = new Blob([JSON.stringify(buildBundle(), null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `lifeos-travel-${weekId()}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
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
  const views = { today: todayView, capture: captureView, gate: gateView };
  view.innerHTML = (views[state.tab] || todayView)();
  view.classList.toggle("enter", state.enter);
  state.enter = false;
  wire(view);
}

function todayView() {
  const week = weekId();
  const tasks = weekTasks(week);
  const goals = planGoals();
  const v = visions()[0];
  let html = "";

  if (v) {
    const s = streakInfo();
    html += `<div class="card"><div class="kv"><span>Gate streak</span>
        <span class="v">${s.streak} day${s.streak === 1 ? "" : "s"}</span></div>
      <div class="kv" style="border:none"><span>Today</span>
        <span class="v">${s.loggedToday ? "logged ✓" : "not yet"}</span></div></div>`;
  }

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
      <div class="task ${t.attrs.status === "done" ? "done" : ""}" data-log="${t.key}" data-n="${i + 1}">
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

function captureView() {
  const recent = entities("content").filter((c) => c.attrs.type === "capture").sort(byTs).reverse();
  const parked = entities("content").filter((c) => c.attrs.type === "parked_idea").sort(byTs).reverse();
  let html = `<div class="card"><h2>Capture a thought</h2>
      <textarea id="capture-text" placeholder="Anything — a task, an idea, a name. Saved locally; syncs to the graph when you're home."></textarea>
      <button class="primary" data-act="capture">Capture</button>
      <p class="hint">A new-project idea gets parked, not planned — captured so it's not lost, but the current gate keeps priority.</p></div>
    <div class="card"><h2>Recent captures</h2>
      ${recent.length ? recent.map((r) => delRow(r.key, esc(r.attrs.text))).join("")
                      : `<p class="empty">Nothing captured yet.</p>`}
    </div>`;
  html += `<div class="card"><h2>Parked ideas</h2>
      ${parked.length ? parked.map((r) => delRow(r.key, `<div class="kind">parked</div>` + esc(r.attrs.text))).join("")
                      : `<p class="empty">Distraction-free. New-project ideas you park land here.</p>`}</div>`;
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
    await toggleLog(el.dataset.log);
    render();
  })));

  on("[data-act=retro]", () => act(async () => { await doRetro(weekId()); render(); }));

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

async function boot() {
  try {
    state.items = await dbAll();
  } catch (e) {
    toast("⚠ Local storage unavailable: " + e.message);
  }
  render();
}

boot();
