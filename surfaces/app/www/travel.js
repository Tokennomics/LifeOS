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

const state = { tab: "today", items: [], retro: null, busy: false, enter: true };

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
  for (const title of bullets) {
    const goal = await createEntity("goal", { level: "goal", title, why: "", horizon_weeks: 12 });
    await createEdge(goal.key, vision.key, "feeds");
  }
  return { status: "created", vision: visionText, goals: bullets.length };
}

/* Weekly plan via the shared anti-hindrance core (boredom + energy shaping + cap). */
async function doPlan(week) {
  const cap = Core.weeklyCap(BASELINE);
  const existing = weekTasks(week);
  if (existing.length >= cap) return { week, tasks: existing.length, method: "already-planned" };

  const goals = planGoals();
  const openTasks = entities("task").filter((t) => t.attrs.status === "open" && t.attrs.week !== week);
  const descriptors = Core.offlinePlan({
    baseline: BASELINE,
    goals: goals.map((g) => ({ title: g.attrs.title || "" })),
    open_tasks: openTasks.map((t) => ({
      id: t.key, title: t.attrs.title || "", if_then: t.attrs.if_then || "", cycles: t.attrs.cycles || 0,
    })),
  });

  const goalKeyByTitle = {};
  for (const g of goals) goalKeyByTitle[g.attrs.title || ""] = g.key;

  let count = 0;
  for (const d of descriptors) {
    const extra = { cycles: d.cycles, smallest_piece: d.smallest_piece };
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

/* planner.log_done: mark the task done (idempotent — already-done stays done). */
async function doLog(taskKey) {
  const task = state.items.find((i) => i.key === taskKey);
  if (!task) return;
  if (task.attrs.status !== "done") await patchEntity(task, { status: "done", done_at: nowISO() });
}

/* Weekly retro via the shared core: score, write the metric, compose the reflection. */
async function doRetro(week) {
  const views = weekTasks(week).map((t) => ({ title: t.attrs.title || "", status: t.attrs.status || "open" }));
  const scored = Core.retro(week, views);
  await createEntity("metric", {
    type: "weekly_retro", week, planned: scored.planned, done: scored.done, rate: scored.rate,
  });
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

/* Doubt rule (T3): honest v0.1-gate progress from what's actually on this phone. */
function computeGate() {
  const done = entities("task").filter((t) => t.attrs.status === "done");
  const retros = entities("metric").filter((m) => m.attrs.type === "weekly_retro");
  const days = new Set();
  for (const t of done) days.add((t.attrs.done_at || t.ts || "").slice(0, 10));
  for (const c of entities("content")) days.add((c.ts || "").slice(0, 10));
  for (const r of retros) days.add((r.ts || "").slice(0, 10));
  days.delete("");
  return Core.gateFromCounts(days.size, done.length, retros.length);
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

  if (!v) {
    html += `<div class="card"><h2>Start here</h2>
      <p class="big">Paste your vision and a few goal lines — Travel Mode backcasts them into a plan, all on this phone.</p>
      <textarea id="vision-text" placeholder="Freedom by 40&#10;- Ship Life OS and run my week with it&#10;- Train 3x per week"></textarea>
      <button class="primary" data-act="vision">Create my plan</button>
      <p class="hint">Line 1 is the vision; each line below becomes a goal. No account, no server — it stays in this browser.</p></div>`;
  } else {
    html += `<div class="card"><h2>Your vision</h2>
      <p class="big">${esc(v.attrs.title)}</p>
      ${goals.length ? `<div style="margin-top:10px">` + goals.map((g) =>
        `<div class="kv"><span>${esc(g.attrs.title)}</span><span class="v">goal</span></div>`).join("") + `</div>` : ""}</div>`;
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
    html += `<button class="ghost" data-act="retro">Run the weekly retro</button>`;
  }
  html += `</div>`;

  if (state.retro) {
    html += `<div class="card"><h2>Retro</h2><div class="retro-text">${esc(state.retro)}</div></div>`;
  }
  return html;
}

function captureView() {
  const recent = entities("content").filter((c) => c.attrs.type === "capture").sort(byTs).reverse();
  const parked = entities("content").filter((c) => c.attrs.type === "parked_idea").sort(byTs).reverse();
  let html = `<div class="card"><h2>Capture a thought</h2>
      <textarea id="capture-text" placeholder="Anything — a task, an idea, a name. Saved locally; syncs to the graph when you're home."></textarea>
      <button class="primary" data-act="capture">Capture</button>
      <p class="hint">A new-project idea gets parked, not planned — captured so it's not lost, but the current gate keeps priority.</p></div>
    <div class="card"><h2>Recent captures</h2>
      ${recent.length ? recent.map((r) => `<div class="feed-item"><div class="label">${esc(r.attrs.text)}</div></div>`).join("")
                      : `<p class="empty">Nothing captured yet.</p>`}
    </div>`;
  html += `<div class="card"><h2>Parked ideas</h2>
      ${parked.length ? parked.map((r) => `<div class="feed-item"><div class="kind">parked</div><div class="label">${esc(r.attrs.text)}</div></div>`).join("")
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
    state.retro = null;
    render();
  }, "Plan created ✔"));

  on("[data-act=plan]", () => act(async () => { await doPlan(weekId()); render(); }, "Week planned ✔"));

  root.querySelectorAll(".task:not(.done)").forEach((el) => el.addEventListener("click", () => act(async () => {
    await doLog(el.dataset.log);
    render();
  }, "Logged ✔")));

  on("[data-act=retro]", () => act(async () => {
    state.retro = (await doRetro(weekId())).text;
    render();
  }));

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
  state.retro = null;
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
