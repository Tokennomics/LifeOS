/* LifeOS app — renders only; every decision is server-side (Law 8). */
"use strict";

const $ = (sel) => document.querySelector(sel);
const state = { tab: "today", health: null, today: null, visions: [], graph: null, retro: null, busy: false };

/* ---------- API ---------- */

function apiBase() {
  return (localStorage.getItem("lifeos.base") || "").replace(/\/+$/, "");
}

async function api(path, body) {
  const headers = {};
  const token = localStorage.getItem("lifeos.token");
  if (token) headers["Authorization"] = "Bearer " + token;
  const opts = { method: body === undefined ? "GET" : "POST", headers };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(apiBase() + path, opts);
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "gateway error " + resp.status);
  }
  return resp.json();
}

/* ---------- helpers ---------- */

function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(el._t);
  el._t = setTimeout(() => { el.hidden = true; }, 2600);
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
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

/* ---------- data ---------- */

async function refresh() {
  try {
    state.health = await api("/health");
  } catch (e) {
    state.health = null;
    $("#mode-badge").textContent = "no gateway";
    $("#mode-badge").className = "badge err";
    $("#view").innerHTML =
      `<div class="card"><h2>Can't reach the gateway</h2>
       <p class="big">${esc(e.message)}</p>
       <p class="hint">Set the gateway URL in ⚙ Settings (e.g. http://nucbox:8787), and make sure it's running on your network.</p></div>`;
    return;
  }
  $("#mode-badge").textContent = state.health.claude ? "AI mode" : "offline mode";
  $("#mode-badge").className = "badge" + (state.health.claude ? " ai" : "");
  if (state.tab === "today") {
    [state.today, state.visions] = await Promise.all([api("/v1/today"), api("/v1/vision").then((r) => r.visions)]);
  } else {
    state.graph = await api("/v1/graph");
  }
  render();
}

/* ---------- views ---------- */

function render() {
  const view = $("#view");
  if (state.tab === "today") view.innerHTML = todayView();
  if (state.tab === "capture") view.innerHTML = captureView();
  if (state.tab === "graph") view.innerHTML = graphView();
  wire(view);
}

function todayView() {
  const t = state.today;
  let html = "";
  if (!state.visions.length) {
    html += `<div class="card"><h2>Start here</h2>
      <p class="big">Where do you want to be? Write the vision, add a few goal lines — LifeOS backcasts it into a plan.</p>
      <textarea id="vision-text" placeholder="Freedom by 40&#10;- Ship Life OS and run my week with it&#10;- Train 3x per week"></textarea>
      <button class="primary" data-act="vision">Create my plan</button></div>`;
  }
  html += `<div class="card"><h2>Week ${esc(t.week)}</h2>`;
  if (!t.tasks.length) {
    html += `<p class="empty">Nothing planned yet.</p><button class="primary" data-act="plan">Plan this week</button>`;
  } else {
    html += t.tasks.map((task) => `
      <div class="task ${task.status === "done" ? "done" : ""}" data-n="${task.n}">
        <div class="box">${task.status === "done" ? "✓" : ""}</div>
        <div><div class="title">${esc(task.title)}</div>
        ${task.if_then ? `<div class="ifthen">${esc(task.if_then)}</div>` : ""}</div>
      </div>`).join("");
    html += `<button class="ghost" data-act="retro">Run the weekly retro</button>`;
  }
  html += `</div>`;
  if (state.retro) {
    html += `<div class="card"><h2>Retro</h2><div class="retro-text">${esc(state.retro)}</div></div>`;
  }
  if (t.events.length) {
    html += `<div class="card"><h2>Calendar (busy)</h2>` + t.events.map((e) => {
      const d = new Date(e.start);
      return `<div class="kv"><span>${esc(e.title || "busy")}</span>
              <span class="v">${d.toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" })}</span></div>`;
    }).join("") + `</div>`;
  }
  return html;
}

function captureView() {
  const recent = (state.graph?.recent || []).filter((r) => r.kind === "content");
  return `<div class="card"><h2>Capture a thought</h2>
      <textarea id="capture-text" placeholder="Anything. Tasks, people and interests get extracted into the graph."></textarea>
      <button class="primary" data-act="capture">Capture</button></div>
    <div class="card"><h2>Recent captures</h2>
      ${recent.length ? recent.map((r) => `<div class="feed-item"><div class="label">${esc(r.label)}</div></div>`).join("")
                      : `<p class="empty">Nothing captured yet.</p>`}
    </div>`;
}

function graphView() {
  const g = state.graph;
  const counts = Object.entries(g.counts).sort((a, b) => b[1] - a[1]);
  return `<div class="card"><h2>Your context graph</h2>
      <div class="kv"><span>entities</span><span class="v">${g.entities}</span></div>
      <div class="kv"><span>edges</span><span class="v">${g.edges}</span></div>
      <div class="kv"><span>observations (provenance)</span><span class="v">${g.observations}</span></div></div>
    <div class="card"><h2>By kind</h2>
      ${counts.length ? counts.map(([k, n]) => `<div class="kv"><span>${esc(k)}</span><span class="v">${n}</span></div>`).join("")
                      : `<p class="empty">Empty graph — start on the Today tab.</p>`}</div>
    <div class="card"><h2>Recent</h2>
      ${g.recent.map((r) => `<div class="feed-item"><div class="kind">${esc(r.kind)}</div><div class="label">${esc(r.label)}</div></div>`).join("") || `<p class="empty">—</p>`}
    </div>`;
}

/* ---------- actions ---------- */

function wire(root) {
  root.querySelectorAll("[data-act=vision]").forEach((b) => b.addEventListener("click", () => act(async () => {
    const text = $("#vision-text").value.trim();
    if (!text) return toast("Write the vision first.");
    const result = await api("/v1/vision", { text });
    if (result.status === "questions") {
      toast("A few questions first…");
      $("#vision-text").value = text + "\n\n" + result.questions.map((q) => "? " + q).join("\n");
      return;
    }
    await refresh();
  }, "Plan created ✔")));

  root.querySelectorAll("[data-act=plan]").forEach((b) => b.addEventListener("click", () => act(async () => {
    await api("/v1/plan", {});
    await refresh();
  }, "Week planned ✔")));

  root.querySelectorAll(".task:not(.done)").forEach((el) => el.addEventListener("click", () => act(async () => {
    await api("/v1/log", { n: Number(el.dataset.n) });
    await refresh();
  }, "Logged ✔")));

  root.querySelectorAll("[data-act=retro]").forEach((b) => b.addEventListener("click", () => act(async () => {
    const result = await api("/v1/retro", {});
    state.retro = result.text;
    render();
  })));

  root.querySelectorAll("[data-act=capture]").forEach((b) => b.addEventListener("click", () => act(async () => {
    const text = $("#capture-text").value.trim();
    if (!text) return toast("Nothing to capture.");
    const result = await api("/v1/capture", { text });
    $("#capture-text").value = "";
    state.graph = await api("/v1/graph");
    render();
    toast(result.tasks + result.interests + result.people > 0 ? "Captured + extracted ✔" : "Captured ✔");
  })));
}

/* ---------- tabs, settings, boot ---------- */

document.querySelectorAll("nav .tab").forEach((b) => b.addEventListener("click", () => {
  state.tab = b.dataset.tab;
  document.querySelectorAll("nav .tab").forEach((x) => x.classList.toggle("active", x === b));
  refresh();
}));

$("#settings-btn").addEventListener("click", () => {
  $("#set-base").value = localStorage.getItem("lifeos.base") || "";
  $("#set-token").value = localStorage.getItem("lifeos.token") || "";
  $("#settings").showModal();
});
$("#set-save").addEventListener("click", () => {
  localStorage.setItem("lifeos.base", $("#set-base").value.trim());
  localStorage.setItem("lifeos.token", $("#set-token").value.trim());
  $("#settings").close();
  refresh();
});
$("#set-close").addEventListener("click", () => $("#settings").close());
$("#set-export").addEventListener("click", () => window.open(apiBase() + "/v1/export", "_blank"));

if ("serviceWorker" in navigator && location.protocol.startsWith("http")) {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}

refresh();
