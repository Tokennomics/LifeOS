/* LifeOS app — renders only; every decision is server-side (Law 8). */
"use strict";

const $ = (sel) => document.querySelector(sel);
const state = {
  tab: "today", health: null, today: null, visions: [], admin: [], graph: null,
  people: [], map: null, more: null, retro: null, draft: null, invite: null,
  questEvent: "", busy: false, enter: true,
  crews: [], crewPlan: null, crewOpen: "",
};

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

function coords() {
  const lat = parseFloat(localStorage.getItem("lifeos.lat"));
  const lon = parseFloat(localStorage.getItem("lifeos.lon"));
  return Number.isFinite(lat) && Number.isFinite(lon) ? { lat, lon } : null;
}

/* ---------- data ---------- */

async function refreshChatMessages() {
  if (!state.activeChat) return;
  try {
    if (state.activeChat.type === "crew") {
      state.chatMessages = await api("/v1/comms/chatroom/list?event_id=" + state.activeChat.id);
    } else {
      state.chatMessages = await api("/v1/comms/messages?recipient_id=" + state.activeChat.id);
    }
  } catch (e) {
    toast("⚠ " + e.message);
  }
}

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
  // Local-first is a feature (Law 6), not a downgrade — show it with pride.
  $("#mode-badge").textContent = state.health.claude ? "AI" : "Local";
  $("#mode-badge").className = "badge" + (state.health.claude ? " ai" : "");
  try {
    if (!state.me && localStorage.getItem("lifeos.token")) {
      state.me = await api("/v1/auth/me").catch(() => null);
    }
    if (state.tab === "today") {
      [state.today, state.visions, state.admin, state.journal] = await Promise.all([
        api("/v1/today"),
        api("/v1/vision").then((r) => r.visions),
        api("/v1/admin").then((r) => r.items),
        api("/v1/journal/entries?limit=5").catch(() => []),
      ]);
    } else if (state.tab === "people") {
      const [people, crews] = await Promise.all([api("/v1/people"), api("/v1/crews")]);
      state.people = people.people;
      state.crews = crews.crews;
      if (state.activeChat) {
        await refreshChatMessages();
      }
    } else if (state.tab === "map") {
      const c = coords();
      let eventId = "outing_active";
      if (state.today && state.today.events && state.today.events.length) {
        eventId = state.today.events[0].id || eventId;
      }
      const [mapRes, convoyRes] = await Promise.all([
        api("/v1/capsules" + (c ? `?lat=${c.lat}&lon=${c.lon}` : "")),
        api(`/v1/venues/convoy/etas?event_id=${eventId}`).catch(() => [])
      ]);
      state.map = mapRes;
      state.convoy = convoyRes;
    } else if (state.tab === "more") {
      const [convoy, decisions, spend, vitals, spaces, people] = await Promise.all([
        api("/v1/convoy"), api("/v1/decisions"), api("/v1/ledger"),
        api("/v1/vitals"), api("/v1/spaces"), api("/v1/people"),
      ]);
      state.more = { convoy, decisions, spend, vitals, spaces };
      state.people = people.people;
    } else {
      state.graph = await api("/v1/graph");
    }
    render();
  } catch (e) {
    toast("⚠ " + e.message);
  }
}

/* ---------- views ---------- */

function render() {
  const view = $("#view");
  const views = { today: todayView, capture: captureView, people: peopleView, map: mapView, graph: graphView, more: moreView };
  view.innerHTML = views[state.tab]();
  // Entrance animation only on tab change — never on in-tab updates (no flashing).
  view.classList.toggle("enter", state.enter);
  state.enter = false;
  wire(view);

  if (state.tab === "people" && state.activeChat) {
    const el = $("#chat-messages");
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }

  if (state.tab === "map") {
    setTimeout(async () => {
      await loadLeaflet();
      initLeafletMap();
    }, 50);
  }
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
  html += `<div class="card"><h2>Steward — life admin</h2>`;
  if (state.admin.length) {
    html += state.admin.map((item) => `
      <div class="person"><div class="who">
        <div class="name">${esc(item.title)}</div>
        <div class="meta">${esc(item.suggestion)}</div></div>
      <div class="pills">
        <button class="pill good" data-admin="approve" data-id="${item.id}">✓</button>
        <button class="pill bad" data-admin="dismiss" data-id="${item.id}">✕</button>
      </div></div>`).join("");
  } else {
    html += `<p class="empty">Nothing surfaced. Sludge-free.</p>`;
  }
  html += `<button class="ghost" data-act="scan">Scan for admin now</button></div>`;
  if (t.events.length) {
    html += `<div class="card"><h2>Calendar (busy)</h2>` + t.events.map((e) => {
      const d = new Date(e.start);
      return `<div class="kv"><span>${esc(e.title || "busy")}</span>
              <span class="v">${d.toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" })}</span></div>`;
    }).join("") + `</div>`;
  }
  
  // Journal Card
  html += `<div class="card"><h2>Reflection Journal</h2>
    <div class="journal-form" style="margin-bottom: 12px;">
      <label class="hint" style="display:block; margin-top:8px;">Daily Wins (one per line)</label>
      <textarea id="jr-wins" placeholder="- Shipped ACL security fixes&#10;- Ran 5km" style="min-height: 60px; margin-top:4px;"></textarea>
      
      <label class="hint" style="display:block; margin-top:8px;">Gratitude (one per line)</label>
      <textarea id="jr-gratitude" placeholder="- Great coffee this morning&#10;- Sunshine" style="min-height: 60px; margin-top:4px;"></textarea>
      
      <label class="hint" style="display:block; margin-top:8px;">Reflection & Notes</label>
      <textarea id="jr-reflection" placeholder="How did today feel? Lessons learned..." style="min-height: 80px; margin-top:4px;"></textarea>
      
      <label class="hint" style="display:block; margin-top:8px; margin-bottom: 4px;">Mood Rating: <span id="jr-mood-val" style="font-weight:bold; color:var(--spark);">7</span> <span id="jr-mood-emoji">😊</span></label>
      <input type="range" id="jr-mood" min="1" max="10" value="7" style="width:100%; accent-color:var(--spark);" oninput="document.getElementById('jr-mood-val').innerText=this.value; const emojis=['😢','😭','🙁','😐','🙂','😊','😀','😁','😆','😎']; document.getElementById('jr-mood-emoji').innerText=emojis[this.value-1] || '😊';">
      
      <button class="primary" data-act="jr-submit" style="margin-top:12px;">Log Daily Reflection</button>
    </div>`;

  if (state.journal && state.journal.length) {
    html += `<h3 style="font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:1px; color:var(--muted); margin: 16px 0 8px;">Recent Reflections</h3>`;
    html += state.journal.map((entry) => {
      const dt = new Date(entry.timestamp);
      const formattedDate = dt.toLocaleDateString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
      const moodVal = entry.mood_rating;
      let moodColor = "var(--warn)";
      if (moodVal >= 8) moodColor = "var(--growth)";
      else if (moodVal >= 5) moodColor = "var(--spark)";
      
      let entryHtml = `
        <div style="border-top: 1px solid var(--line-soft); padding: 12px 0;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
            <span style="font-size:13px; color:var(--muted);">${esc(formattedDate)}</span>
            <span class="badge" style="color:${moodColor}; border-color:${moodColor}40;">Mood: ${moodVal}/10</span>
          </div>
      `;
      if (entry.wins && entry.wins.length) {
        entryHtml += `<div style="font-size:14px; margin-bottom:4px;"><strong style="color:var(--growth);">Wins:</strong> ${entry.wins.map(w => esc(w)).join(", ")}</div>`;
      }
      if (entry.gratitude && entry.gratitude.length) {
        entryHtml += `<div style="font-size:14px; margin-bottom:4px;"><strong style="color:var(--calm);">Gratitude:</strong> ${entry.gratitude.map(g => esc(g)).join(", ")}</div>`;
      }
      if (entry.reflection) {
        entryHtml += `<div style="font-size:14px; color:var(--text); font-style:italic; margin-top:4px; line-height:1.4;">"${esc(entry.reflection)}"</div>`;
      }
      entryHtml += `</div>`;
      return entryHtml;
    }).join("");
  }
  html += `</div>`;
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

function chatView() {
  const c = state.activeChat;
  let html = `
    <div class="card">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; border-bottom:1px solid var(--line-soft); padding-bottom:10px;">
        <button class="pill" style="width:auto; padding:6px 12px; margin:0;" data-act="chat-back">← Back</button>
        <span style="font-size:16px; font-weight:700; color:var(--text);">${esc(c.name)}</span>
        <span class="badge" style="color:var(--spark); border-color:var(--spark)40;">${esc(c.type === "crew" ? "Crew" : "Direct")}</span>
      </div>
  `;
  
  if (c.type === "crew") {
    const crew = state.crews.find(cr => cr.id === c.id);
    if (crew && crew.members && crew.members.length) {
      html += `
        <div style="margin-bottom:12px; display:flex; align-items:center; gap:8px;">
          <span class="hint">Direct message member:</span>
          <select class="field" id="chat-member-select" style="margin-top:0; min-height:36px; padding:6px; flex:1;">
            <option value="">-- Choose member --</option>
            ${crew.members.map(m => `<option value="${esc(m.id)}">${esc(m.name)}</option>`).join("")}
          </select>
          <button class="pill calm" style="margin:0; padding:6px 12px;" data-act="chat-member-go">Go</button>
        </div>
      `;
    }
  }

  html += `
    <div id="chat-messages" style="height:300px; overflow-y:auto; padding:8px 0; display:flex; flex-direction:column; gap:8px; border-bottom:1px solid var(--line-soft); margin-bottom:12px;">
  `;
  
  if (!state.chatMessages || !state.chatMessages.length) {
    html += `<p class="empty" style="text-align:center; margin:auto 0;">No messages yet. Send a message to start the conversation.</p>`;
  } else {
    const myAccountId = state.me ? state.me.account_id : null;
    html += state.chatMessages.map(msg => {
      let isMe = false;
      let senderName = "System";
      
      if (c.type === "direct") {
        isMe = (msg.sender_id === myAccountId);
        senderName = isMe ? "Me" : c.name;
      } else {
        isMe = (msg.user_id === myAccountId);
        const crew = state.crews.find(cr => cr.id === c.id);
        const member = crew ? crew.members.find(m => m.id === msg.user_id) : null;
        senderName = isMe ? "Me" : (member ? member.name : (msg.user_id ? msg.user_id.slice(0, 8) : "Anonymous"));
      }

      const bubbleBg = isMe ? "var(--spark)" : "var(--surface-2s)";
      const bubbleColor = isMe ? "var(--spark-ink)" : "var(--text)";
      const alignSelf = isMe ? "flex-end" : "flex-start";
      const textAlign = isMe ? "right" : "left";
      const borderRadius = isMe ? "14px 14px 2px 14px" : "14px 14px 14px 2px";
      const bodyText = msg.body || msg.message || "";
      const timeStr = msg.timestamp || msg.created_at || "";
      const formattedTime = timeStr ? new Date(timeStr).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : "";

      return `
        <div style="align-self:${alignSelf}; max-width:80%; display:flex; flex-direction:column; align-items:${isMe ? 'flex-end' : 'flex-start'};">
          <div style="font-size:11px; color:var(--muted); margin-bottom:2px; padding:0 4px;">${esc(senderName)}</div>
          <div style="background:${bubbleBg}; color:${bubbleColor}; padding:10px 14px; border-radius:${borderRadius}; font-size:14.5px; word-break:break-word; line-height:1.4; text-align:${textAlign}; box-shadow:0 2px 8px rgba(0,0,0,0.15);">
            ${esc(bodyText)}
          </div>
          ${formattedTime ? `<div style="font-size:10px; color:var(--faint); margin-top:2px; padding:0 4px;">${esc(formattedTime)}</div>` : ""}
        </div>
      `;
    }).join("");
  }
  
  html += `</div>`;
  
  html += `
    <div style="display:flex; gap:8px; align-items:center;">
      <input class="field" id="chat-input" placeholder="Type a message..." style="margin-top:0; flex:1; min-height:42px; padding:10px 14px;">
      <button class="primary" data-act="chat-send" style="margin-top:0; width:auto; min-height:42px; padding:0 20px;">Send</button>
    </div>
  </div>`;
  
  return html;
}

function peopleView() {
  if (state.activeChat) {
    return chatView();
  }
  let html = `<div class="card"><h2>Add someone</h2>
    <div class="row2"><input class="field" id="person-name" placeholder="Name">
    <button class="primary" style="width:auto;flex:none;padding:10px 18px" data-act="add-person">Add</button></div>
    <p class="hint">People also arrive automatically from captures. Contact refreshes when you log a reconnect or mark a convoy attended.</p></div>`;
  html += `<div class="card"><h2>Reconnect radar</h2>`;
  if (!state.people.length) {
    html += `<p class="empty">Nobody in the graph yet.</p>`;
  } else {
    html += state.people.map((p) => `
      <div class="person"><div class="who">
        <div class="name">${esc(p.name)}</div>
        <div class="meta ${p.overdue >= 1 ? "over" : ""}">${p.days_since}d since contact · cadence ${p.cadence_days}d${p.overdue >= 1 ? " · overdue" : ""}</div>
      </div><div class="pills">
        <button class="pill warm" data-draft="${p.id}">Draft</button>
        <button class="pill good" data-touch="${p.id}">Done</button>
      </div></div>`).join("");
  }
  html += `</div>`;
  if (state.draft) {
    html += `<div class="card"><h2>Invite draft — ${esc(state.draft.name)}</h2>
      <div class="draft">${esc(state.draft.text)}</div>
      <button class="ghost" data-act="copy-draft">Copy — then send it from your messages</button>
      <p class="hint">Sending stays in your hands; when you've seen them, hit Done to log it.</p></div>`;
  }
  html += crewsView();
  return html;
}

/* ---------- crews ---------- */

function crewsView() {
  let html = `<div class="card"><h2>Your crews</h2>`;
  if (!state.crews.length) {
    html += `<p class="empty">No crews yet. A crew is a named group with a topic and a home city.</p>`;
  } else {
    html += state.crews.map((c) => `
      <div class="person"><div class="who">
        <div class="name">${esc(c.name)} ${c.visibility === "public" ? "· public" : ""}</div>
        <div class="meta">${esc([c.topic, c.city].filter(Boolean).join(" · ") || "no topic")} — ${c.member_count} member${c.member_count === 1 ? "" : "s"}</div>
      </div><div class="pills">
        <button class="pill warm" data-crew-plan="${c.id}">Plan</button>
        <button class="pill calm" data-act="chat-crew" data-id="${c.id}" data-name="${esc(c.name)}">Chat</button>
      </div></div>`).join("");
  }
  html += `<div class="subhead">Start a crew</div>
    <div class="row2"><input class="field" id="crew-name" placeholder="Name (e.g. Lisbon Climbing)">
    <input class="field" id="crew-topic" placeholder="Topic"></div>
    <div class="row2"><input class="field" id="crew-city" placeholder="City">
    <select class="field" id="crew-vis"><option value="private">Invite-only</option><option value="public">Public</option></select></div>
    <button class="primary" data-act="crew-add">Create crew</button></div>`;

  const open = state.crews.find((c) => c.id === state.crewOpen);
  if (open && !state.crewPlan) {
    html += `<div class="card"><h2>Plan a meet — ${esc(open.name)}</h2>
      <input class="field" id="plan-slots" placeholder="Times, comma separated (Thu 20:00, Fri 20:00, Sat 11:00)">
      <input class="field" id="plan-places" placeholder="Places, comma separated (Gym, Crag)">
      <div class="row2"><input class="field" id="plan-quorum" type="number" min="2" value="2" title="how many people make it happen">
      <button class="primary" style="width:auto;flex:none;padding:10px 18px" data-act="plan-propose">Propose</button></div>
      <p class="hint">Ask the crew what suits, then record their answers below — the planner picks the night the most people can make.</p></div>`;
  }

  if (state.crewPlan) {
    const p = state.crewPlan;
    const crew = state.crews.find((c) => c.id === p.crew_id) || { members: [] };
    const slotOpts = (p.slots || []).map((s) => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
    html += `<div class="card"><h2>Who can make it — ${esc(p.crew_name || "")}</h2>`;
    html += crew.members.map((m) => `
      <div class="subhead">${esc(m.name)}${(p.responded || []).includes(m.id) ? " ✓" : ""} <button class="pill calm" style="padding:2px 8px; font-size:11px; margin-left:8px; width:auto; min-height:22px;" data-act="chat-direct" data-id="${m.id}" data-name="${esc(m.name)}">Chat</button></div>
      <select class="field" multiple id="avail-${m.id}">${slotOpts}</select>
      <button class="ghost" data-avail="${m.id}">Save ${esc(m.name)}'s times</button>`).join("");
    html += `</div>`;

    if ((p.candidates || []).length) {
      html += `<div class="card"><h2>Best options</h2>` + p.candidates.map((c, i) => `
        <div class="person"><div class="who">
          <div class="name">${esc(c.slot)} @ ${esc(c.place)}</div>
          <div class="meta">${c.attendee_count} coming</div>
        </div><div class="pills">
          <button class="pill good" data-lock="${i}">Lock it in</button>
        </div></div>`).join("")
        + `<p class="hint">Locking in records that these people agreed — it writes the meet and links only those coming.</p></div>`;
    } else {
      html += `<div class="card"><p class="empty">No option clears the quorum yet — record more availability.</p></div>`;
    }
  }
  return html;
}

function mapView() {
  const c = coords();
  const m = state.map || { capsules: [], quests: [] };
  let html = `<div class="card">
    <h2>Live World Map</h2>
    <div id="map-canvas" style="height: 320px; border-radius: 12px; background: #1a1f2c; border: 1px solid #2a3547; z-index: 1;"></div>
  </div>`;
  html += `<div class="card"><h2>Where you are</h2>
    <div class="row2">
      <input class="field" id="lat" inputmode="decimal" placeholder="lat" value="${c ? c.lat : ""}">
      <input class="field" id="lon" inputmode="decimal" placeholder="lon" value="${c ? c.lon : ""}">
    </div>
    <div class="row2">
      <button class="ghost" data-act="gps">Use GPS</button>
      <button class="primary" data-act="checkin">Check in / unlock</button>
    </div>
    <p class="hint">Capsules within their radius unlock when you check in. Coordinates stay on your gateway.</p></div>`;
  html += `<div class="card"><h2>Drop a capsule here</h2>
    <textarea id="capsule-text" placeholder="What should this place remember?"></textarea>
    <input class="field" id="capsule-place" placeholder="Place name (optional)">
    <button class="primary" data-act="drop" ${c ? "" : "disabled"}>${c ? "Drop capsule" : "Set your position first"}</button>
    ${state.questEvent ? `<p class="hint">This capsule completes a quest ✔</p>` : ""}</div>`;
  if (m.quests.length) {
    html += `<div class="card"><h2>Quests</h2>` + m.quests.map((q) =>
      `<div class="quest" data-quest="${q.event_id}" data-title="${esc(q.title)}">${esc(q.prompt)} <u>Tap to start.</u></div>`).join("") + `</div>`;
  }
  html += `<div class="card"><h2>Capsules</h2>`;
  if (!m.capsules.length) {
    html += `<p class="empty">None yet. Your map fills as you live.</p>`;
  } else {
    html += m.capsules.map((cap) => `
      <div class="feed-item">
        <div class="kind">${esc(cap.place)}${cap.distance_m != null ? ` · ${cap.distance_m}m away` : ""}</div>
        <div class="label ${cap.locked ? "capsule-locked" : ""}">${cap.locked ? "🔒 locked — come back to open it" : esc(cap.text)}</div>
      </div>`).join("");
  }
  html += `</div>`;
  return html;
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

function moreView() {
  const m = state.more;
  const peopleOptions = state.people.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("");
  let html = `<div class="card"><h2>Convoy — with your people</h2>
    <input class="field" id="cv-title" placeholder="Event (gig, dinner, climb…)">
    <div class="row2"><input class="field" id="cv-start" type="datetime-local">
    <input class="field" id="cv-place" placeholder="Where"></div>
    <button class="primary" data-act="cv-add">Add event</button>`;
  for (const ev of m.convoy.events) {
    const when = (ev.start || "").slice(0, 16).replace("T", " ");
    html += `<div class="subhead">${esc(ev.title)} — ${esc(when)}${ev.place ? " @ " + esc(ev.place) : ""}</div>
      <div class="hint">${ev.invited} invited · in: ${ev.yes.length ? esc(ev.yes.join(", ")) : "nobody yet"}</div>
      <select class="field" multiple id="cv-people-${ev.id}">${peopleOptions}</select>
      <div class="row2">
        <button class="pill warm" data-cv-invite="${ev.id}">Invite</button>
        <button class="pill good" data-cv-going="${ev.id}">They're in</button>
        <button class="pill" data-cv-attended="${ev.id}">Attended ✔</button>
      </div>`;
  }
  if (state.invite) {
    html += `<div class="draft">${esc(state.invite)}</div>`;
  }
  html += `<button class="ghost" data-act="cv-digest">Concierge digest</button></div>`;

  const cal = m.decisions.calibration;
  html += `<div class="card"><h2>Calibre — decision journal</h2>
    <input class="field" id="dc-title" placeholder="Decision (e.g. promote model ca81b…)">
    <input class="field" id="dc-choice" placeholder="What you chose">
    <input class="field" id="dc-pred" placeholder="Predicted outcome">
    <div class="row2"><input class="field" id="dc-conf" type="number" min="5" max="95" step="5" value="70" title="confidence %">
    <input class="field" id="dc-days" type="number" min="1" value="30" title="review in days"></div>
    <button class="primary" data-act="dc-log">Log decision (confidence % · review days)</button>
    ${cal.n ? `<p class="hint">Calibration: avg Brier ${cal.avg_brier} over ${cal.n} resolved (0 = prophet, 0.25 = coin flip).</p>` : ""}`;
  for (const d of m.decisions.decisions) {
    html += `<div class="person"><div class="who">
      <div class="name">${esc(d.title)}</div>
      <div class="meta ${d.due ? "over" : ""}">${Math.round(d.confidence * 100)}% → ${esc(d.predicted)}${d.due ? " · review due" : ""}</div>
      </div><div class="pills">
      <button class="pill good" data-dc-resolve="${d.id}" data-happened="1">Happened</button>
      <button class="pill bad" data-dc-resolve="${d.id}" data-happened="0">Didn't</button>
      </div></div>`;
  }
  html += `</div>`;

  html += `<div class="card"><h2>Ledger — ${esc(m.spend.month)}</h2>
    <div class="row2"><input class="field" id="lg-amount" type="number" step="0.01" placeholder="amount">
    <input class="field" id="lg-cat" placeholder="category"></div>
    <input class="field" id="lg-note" placeholder="note (optional)">
    <button class="primary" data-act="lg-add">Log spend</button>
    <div class="kv"><span>total</span><span class="v">${m.spend.total.toFixed(2)}</span></div>
    ${Object.entries(m.spend.by_category).map(([k, v]) => `<div class="kv"><span>${esc(k)}</span><span class="v">${v.toFixed(2)}</span></div>`).join("")}</div>`;

  html += `<div class="card"><h2>Vitals — energy windows</h2>
    ${m.vitals.windows.map((w) => `<div class="kv"><span>${esc(w.phase)}</span><span class="v">${esc(w.start)}–${esc(w.end)}</span></div>`).join("")}
    <p class="hint">The planner schedules deep work into peaks. Sleep import replaces these defaults later.</p></div>`;

  html += `<div class="card"><h2>Hearth — shared spaces</h2>
    <div class="row2"><input class="field" id="hx-name" placeholder="Space name (e.g. Home)">
    <button class="primary" style="width:auto;flex:none;padding:10px 18px" data-act="hx-add">Create</button></div>
    ${m.spaces.spaces.length
      ? m.spaces.spaces.map((s) => `<div class="kv"><span>${esc(s.name)}</span><span class="v">${s.members.length} member${s.members.length === 1 ? "" : "s"}</span></div>`).join("")
      : `<p class="empty">No shared spaces yet.</p>`}</div>`;
  return html;
}

/* ---------- actions ---------- */

function selectedPeople(eventId) {
  const sel = $(`#cv-people-${CSS.escape(eventId)}`);
  return sel ? [...sel.selectedOptions].map((o) => o.value) : [];
}

function wire(root) {
  const on = (selector, handler) => root.querySelectorAll(selector).forEach((el) =>
    el.addEventListener("click", () => handler(el)));

  on("[data-act=vision]", () => act(async () => {
    const text = $("#vision-text").value.trim();
    if (!text) return toast("Write the vision first.");
    const result = await api("/v1/vision", { text });
    if (result.status === "questions") {
      toast("A few questions first…");
      $("#vision-text").value = text + "\n\n" + result.questions.map((q) => "? " + q).join("\n");
      return;
    }
    await refresh();
  }, "Plan created ✔"));

  on("[data-act=plan]", () => act(async () => { await api("/v1/plan", {}); await refresh(); }, "Week planned ✔"));

  root.querySelectorAll(".task:not(.done)").forEach((el) => el.addEventListener("click", () => act(async () => {
    await api("/v1/log", { n: Number(el.dataset.n) });
    await refresh();
  }, "Logged ✔")));

  on("[data-act=retro]", () => act(async () => {
    state.retro = (await api("/v1/retro", {})).text;
    render();
  }));

  on("[data-act=scan]", () => act(async () => {
    const r = await api("/v1/admin/scan", {});
    await refresh();
    toast(r.created ? `${r.created} admin item${r.created === 1 ? "" : "s"} surfaced` : "Nothing new — clean.");
  }));

  on("[data-admin]", (el) => act(async () => {
    const r = await api("/v1/admin/act", { item_id: el.dataset.id, action: el.dataset.admin });
    await refresh();
    toast(r.outcome);
  }));

  on("[data-act=capture]", () => act(async () => {
    const text = $("#capture-text").value.trim();
    if (!text) return toast("Nothing to capture.");
    const result = await api("/v1/capture", { text });
    $("#capture-text").value = "";
    state.graph = await api("/v1/graph");
    render();
    toast(result.tasks + result.interests + result.people > 0 ? "Captured + extracted ✔" : "Captured ✔");
  }));

  on("[data-act=jr-submit]", () => act(async () => {
    const wins = $("#jr-wins").value.split("\n").map(w => w.trim()).filter(Boolean);
    const gratitude = $("#jr-gratitude").value.split("\n").map(g => g.trim()).filter(Boolean);
    const reflection = $("#jr-reflection").value.trim();
    const mood_rating = Number($("#jr-mood").value);
    
    await api("/v1/journal/entries", {
      wins,
      gratitude,
      reflection,
      mood_rating
    });
    
    $("#jr-wins").value = "";
    $("#jr-gratitude").value = "";
    $("#jr-reflection").value = "";
    $("#jr-mood").value = "7";
    
    await refresh();
  }, "Reflection logged ✔"));

  on("[data-act=add-person]", () => act(async () => {
    const name = $("#person-name").value.trim();
    if (!name) return toast("Give them a name.");
    await api("/v1/people", { name });
    await refresh();
  }, "Added ✔"));

  on("[data-draft]", (el) => act(async () => {
    state.draft = await api("/v1/reconnect/draft", { person_id: el.dataset.draft });
    render();
  }));

  on("[data-touch]", (el) => act(async () => {
    await api("/v1/reconnect/touch", { person_id: el.dataset.touch });
    state.draft = null;
    await refresh();
  }, "Reconnect logged ✔"));

  on("[data-act=copy-draft]", () => act(async () => {
    await navigator.clipboard.writeText(state.draft.text);
  }, "Copied — go send it."));

  /* ---- chat ---- */

  on("[data-act=chat-crew]", (el) => act(async () => {
    state.activeChat = { type: "crew", id: el.dataset.id, name: el.dataset.name };
    await refreshChatMessages();
    render();
  }));

  on("[data-act=chat-direct]", (el) => act(async () => {
    state.activeChat = { type: "direct", id: el.dataset.id, name: el.dataset.name };
    await refreshChatMessages();
    render();
  }));

  on("[data-act=chat-back]", () => {
    state.activeChat = null;
    state.chatMessages = [];
    render();
  });

  on("[data-act=chat-send]", () => act(async () => {
    const text = $("#chat-input").value.trim();
    if (!text) return;
    if (!state.me) {
      state.me = await api("/v1/auth/me").catch(() => null);
    }
    if (!state.me || !state.me.account_id) {
      return toast("You must be logged in with an account to chat.");
    }
    
    if (state.activeChat.type === "crew") {
      await api("/v1/comms/chatroom/send", {
        event_id: state.activeChat.id,
        user_id: state.me.account_id,
        message: text
      });
    } else {
      await api("/v1/comms/messages", {
        sender_id: state.me.account_id,
        recipient_id: state.activeChat.id,
        body: text
      });
    }
    
    $("#chat-input").value = "";
    await refreshChatMessages();
    render();
  }));

  on("[data-act=chat-member-go]", () => act(async () => {
    const sel = $("#chat-member-select");
    if (!sel || !sel.value) return;
    const name = sel.options[sel.selectedIndex].text;
    state.activeChat = { type: "direct", id: sel.value, name: name };
    await refreshChatMessages();
    render();
  }));

  const chatInput = root.querySelector("#chat-input");
  if (chatInput) {
    chatInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        const sendBtn = root.querySelector("[data-act=chat-send]");
        if (sendBtn) sendBtn.click();
      }
    });
  }

  /* ---- crews ---- */

  on("[data-act=crew-add]", () => act(async () => {
    const name = $("#crew-name").value.trim();
    if (!name) return toast("Name the crew.");
    await api("/v1/crews", {
      name, topic: $("#crew-topic").value.trim(), city: $("#crew-city").value.trim(),
      visibility: $("#crew-vis").value,
    });
    state.crewOpen = "";
    state.crewPlan = null;
    await refresh();
  }, "Crew created ✔"));

  on("[data-crew-plan]", (el) => {
    state.crewOpen = el.dataset.crewPlan;
    state.crewPlan = null;
    render();
  });

  on("[data-act=plan-propose]", () => act(async () => {
    const split = (id) => $(id).value.split(",").map((s) => s.trim()).filter(Boolean);
    const slots = split("#plan-slots");
    const places = split("#plan-places");
    if (!slots.length || !places.length) return toast("Add at least one time and one place.");
    const r = await api("/v1/coordinate/group/propose", {
      crew_id: state.crewOpen, slots, places, quorum: Number($("#plan-quorum").value) || 2,
    });
    state.crewPlan = { ...r, crew_id: state.crewOpen, candidates: [], responded: [] };
    render();
  }, "Proposed — now record who can make it."));

  on("[data-avail]", (el) => act(async () => {
    const sel = $(`#avail-${CSS.escape(el.dataset.avail)}`);
    const slots = {};
    [...sel.selectedOptions].forEach((o) => { slots[o.value] = 1; });
    const r = await api("/v1/coordinate/group/respond", {
      coordination_id: state.crewPlan.coordination_id, person_id: el.dataset.avail, weights: { slots },
    });
    state.crewPlan = { ...state.crewPlan, ...r };
    render();
  }, "Saved ✔"));

  on("[data-lock]", (el) => act(async () => {
    const choice = Number(el.dataset.lock);
    const pick = state.crewPlan.candidates[choice];
    let done = null;
    for (const pid of pick.attendees) {
      done = await api("/v1/coordinate/group/approve", {
        coordination_id: state.crewPlan.coordination_id, person_id: pid, choice,
      });
    }
    toast(done && done.status === "confirmed" ? "Locked in ✔" : "Recorded.");
    state.crewPlan = null;
    state.crewOpen = "";
    await refresh();
  }));

  on("[data-act=gps]", () => {
    if (!navigator.geolocation) return toast("No GPS on this device — type coordinates.");
    navigator.geolocation.getCurrentPosition((pos) => {
      localStorage.setItem("lifeos.lat", pos.coords.latitude.toFixed(6));
      localStorage.setItem("lifeos.lon", pos.coords.longitude.toFixed(6));
      refresh();
      toast("Position set ✔");
    }, () => toast("GPS denied — type coordinates instead."));
  });

  on("[data-act=checkin]", () => act(async () => {
    saveCoordsFromInputs();
    const c = coords();
    if (!c) return toast("Set your position first.");
    const r = await api("/v1/capsules/unlock", c);
    await refresh();
    toast(r.unlocked ? `✨ ${r.unlocked} capsule${r.unlocked === 1 ? "" : "s"} unlocked` : "Nothing here… yet.");
  }));

  on("[data-act=drop]", () => act(async () => {
    saveCoordsFromInputs();
    const c = coords();
    const text = $("#capsule-text").value.trim();
    if (!c || !text) return toast(c ? "Write the capsule first." : "Set your position first.");
    await api("/v1/capsules", { text, lat: c.lat, lon: c.lon, place: $("#capsule-place").value.trim(), event_id: state.questEvent });
    state.questEvent = "";
    await refresh();
  }, "Capsule dropped 📍"));

  on("[data-quest]", (el) => {
    state.questEvent = el.dataset.quest;
    $("#capsule-place").value = el.dataset.title;
    $("#capsule-text").focus();
    toast("Quest armed — drop the capsule.");
  });

  on("[data-act=cv-add]", () => act(async () => {
    const title = $("#cv-title").value.trim();
    const start = $("#cv-start").value;
    if (!title || !start) return toast("Event needs a title and a time.");
    await api("/v1/convoy/event", { title, start, place: $("#cv-place").value.trim() });
    await refresh();
  }, "Event added ✔"));

  on("[data-cv-invite]", (el) => act(async () => {
    const ids = selectedPeople(el.dataset.cvInvite);
    if (!ids.length) return toast("Select who to invite.");
    const r = await api("/v1/convoy/invite", { event_id: el.dataset.cvInvite, person_ids: ids });
    state.invite = r.text;
    await refresh().then(render);
    toast(`${r.invited} invited — copy the draft and send it.`);
  }));

  on("[data-cv-going]", (el) => act(async () => {
    const ids = selectedPeople(el.dataset.cvGoing);
    if (!ids.length) return toast("Select who's in.");
    for (const pid of ids) {
      await api("/v1/convoy/rsvp", { event_id: el.dataset.cvGoing, person_id: pid, going: true });
    }
    await refresh();
  }, "RSVPs saved ✔"));

  on("[data-cv-attended]", (el) => act(async () => {
    const r = await api("/v1/convoy/attended", { event_id: el.dataset.cvAttended });
    await refresh();
    toast(`Logged — ${r.people_touched} friendship${r.people_touched === 1 ? "" : "s"} refreshed.`);
  }));

  on("[data-act=cv-digest]", () => act(async () => {
    state.invite = (await api("/v1/convoy/digest")).text;
    render();
  }));

  on("[data-act=dc-log]", () => act(async () => {
    const title = $("#dc-title").value.trim();
    const choice = $("#dc-choice").value.trim();
    const predicted = $("#dc-pred").value.trim();
    const confidence = Number($("#dc-conf").value) / 100;
    if (!title || !choice || !predicted) return toast("Fill decision, choice and prediction.");
    await api("/v1/decisions", { title, choice, confidence, predicted, review_days: Number($("#dc-days").value) || 30 });
    await refresh();
  }, "Decision logged ✔"));

  on("[data-dc-resolve]", (el) => act(async () => {
    const r = await api("/v1/decisions/resolve", { decision_id: el.dataset.dcResolve, happened: el.dataset.happened === "1" });
    await refresh();
    toast(`Brier ${r.brier}`);
  }));

  on("[data-act=lg-add]", () => act(async () => {
    const amount = Number($("#lg-amount").value);
    const category = $("#lg-cat").value.trim();
    if (!amount || !category) return toast("Amount and category.");
    await api("/v1/ledger", { amount, category, note: $("#lg-note").value.trim() });
    await refresh();
  }, "Logged ✔"));

  on("[data-act=hx-add]", () => act(async () => {
    const name = $("#hx-name").value.trim();
    if (!name) return toast("Name the space.");
    await api("/v1/spaces", { name });
    await refresh();
  }, "Space created ✔"));
}

function saveCoordsFromInputs() {
  const lat = parseFloat($("#lat")?.value);
  const lon = parseFloat($("#lon")?.value);
  if (Number.isFinite(lat) && Number.isFinite(lon)) {
    localStorage.setItem("lifeos.lat", String(lat));
    localStorage.setItem("lifeos.lon", String(lon));
  }
}

/* ---------- tabs, settings, boot ---------- */

document.querySelectorAll("nav .tab").forEach((b) => b.addEventListener("click", () => {
  state.tab = b.dataset.tab;
  state.draft = null;
  state.invite = null;
  state.activeChat = null;
  state.enter = true;
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

let leafletLoaded = false;
async function loadLeaflet() {
  if (leafletLoaded || window.L) return;
  leafletLoaded = true;
  return new Promise((resolve) => {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
    document.head.appendChild(link);

    const script = document.createElement("script");
    script.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
    script.onload = () => resolve();
    document.head.appendChild(script);
  });
}

function initLeafletMap() {
  const container = document.getElementById("map-canvas");
  if (!container) return;
  
  const c = coords() || { lat: 37.7749, lon: -122.4194 };
  const map = L.map(container).setView([c.lat, c.lon], 13);
  
  L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
    attribution: "&copy; OpenStreetMap &copy; CARTO"
  }).addTo(map);

  // You
  L.circleMarker([c.lat, c.lon], {
    color: "#2563eb",
    fillColor: "#3b82f6",
    fillOpacity: 0.9,
    radius: 9
  }).addTo(map).bindPopup("<b>You</b>").openPopup();

  // Convoy Members
  const convoy = state.convoy || [];
  convoy.forEach((m) => {
    if (m.latitude && m.longitude) {
      L.circleMarker([m.latitude, m.longitude], {
        color: "#dc2626",
        fillColor: "#ef4444",
        fillOpacity: 0.8,
        radius: 7
      }).addTo(map).bindPopup(`<b>Member: ${esc(m.user_id)}</b><br>ETA: ${esc(m.eta)}`);
    }
  });

  // Capsules
  const m = state.map || { capsules: [] };
  (m.capsules || []).forEach((cap) => {
    if (cap.lat && cap.lon) {
      L.circleMarker([cap.lat, cap.lon], {
        color: cap.locked ? "#7c3aed" : "#059669",
        fillColor: cap.locked ? "#8b5cf6" : "#10b981",
        fillOpacity: cap.locked ? 0.5 : 0.8,
        radius: 6
      }).addTo(map).bindPopup(`<b>${esc(cap.place || "Capsule")}</b><br>${cap.locked ? "🔒 Locked" : esc(cap.text)}`);
    }
  });
}

if ("serviceWorker" in navigator && location.protocol.startsWith("http")) {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}

refresh();
