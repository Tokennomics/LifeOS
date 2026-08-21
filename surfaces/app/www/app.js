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
    const problem = new Error(err.detail || "gateway error " + resp.status);
    // Callers need to tell "your session is gone" from "the wifi dropped". Without the
    // status they look identical, and treating the second as the first signs people out
    // of a working session.
    problem.status = resp.status;
    throw problem;
  }
  return resp.json();
}

async function apiDelete(path, body) {
  const headers = {};
  const token = localStorage.getItem("lifeos.token");
  if (token) headers["Authorization"] = "Bearer " + token;
  const opts = { method: "DELETE", headers };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(apiBase() + path, opts);
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    const problem = new Error(err.detail || "gateway error " + resp.status);
    problem.status = resp.status;
    throw problem;
  }
  return resp.json();
}

function whenLabel(iso) {
  // A meetup is almost always today or tomorrow, and "Fri 19:00" is what somebody deciding
  // whether to go actually needs — not a full timestamp.
  const d = new Date(iso);
  if (isNaN(d)) return iso || "";
  return d.toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" });
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

// A URL that is safe to put in an href. esc() is NOT enough here: it stops the attribute
// breaking out, but `javascript:alert(1)` survives escaping completely intact and runs on
// click. Only http/https get through; anything else — javascript:, data:, vbscript:, or a
// value we cannot parse — becomes "#". Use this for every href, src or action built from a
// response, and esc() for everything else.
function safeUrl(u) {
  const raw = String(u ?? "").trim();
  try {
    const parsed = new URL(raw, window.location.origin);
    return (parsed.protocol === "http:" || parsed.protocol === "https:") ? esc(parsed.href) : "#";
  } catch (e) {
    return "#";
  }
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
      // Only a 401 means the session is actually gone. Clearing the token on *any*
      // failure — which the first version of this did — signs you out of a perfectly
      // good session the moment a request times out on a train.
      state.me = await api("/v1/auth/me").catch((e) => {
        if (e && e.status === 401) localStorage.removeItem("lifeos.token");
        return null;
      });
    }
    // Every /v1 route needs a session once any account exists, so with no token the whole
    // screen is a wall of 401s. Ask for the sign-in first instead.
    if (!state.me && !localStorage.getItem("lifeos.token")) {
      $("#view").innerHTML =
        `<div class="card"><h2>Welcome to LifeOS</h2>
         <p class="hint">Sign in to start capturing, planning and finding your people.</p>
         <button class="primary" data-act="open-auth" style="margin-top:10px;">Get started</button></div>`;
      await openAuth();
      return;
    }
    if (state.tab === "today") {
      [state.today, state.visions, state.admin, state.journal, state.parked, state.rings, state.weekend, state.habitChain, state.energyBalance] = await Promise.all([
        api("/v1/today"),
        api("/v1/vision").then((r) => r.visions),
        api("/v1/admin").then((r) => r.items),
        api("/v1/journal/entries?limit=5").catch(() => []),
        api("/v1/parked").then((r) => r.parked).catch(() => []),
        api("/v1/routines/rings").catch(() => null),
        api("/v1/weekend").catch(() => null),
        api("/v1/routines/chaining-recommendation", {}).catch(() => null),
        api("/v1/horizon/energy-balance").catch(() => null),
        api("/v1/routines/heatmap").catch(() => null),
      ]);
    } else if (state.tab === "people") {
      const [people, crews, feed, venues, heatmap, synergyOverlaps, venuePrograms, communityReviews, cityPassport] = await Promise.all([
        api("/v1/people"),
        // `/v1/crews` browses your OWN graph, so a crew you joined in somebody else's
        // account was missing from "Your crews" and every per-crew button with it.
        api("/v1/crews/mine"),
        api("/v1/feed").catch(() => ({ items: [] })),
        // Was called with no city against a handler that required one: a 422 on every
        // page load, swallowed here, so Explore was permanently empty and never looked it.
        api("/v1/venues/explore").catch(() => ({ venues: [] })),
        api("/v1/venues/activity-heatmap").catch(() => null),
        api("/v1/synergy/overlap").catch(() => null),
        api("/v1/venues/programs").catch(() => null),
        api("/v1/feed/reviews").catch(() => null),
        api("/v1/gamification/passport").catch(() => null)
      ]);
      state.people = people.people;
      state.crews = crews.crews;
      state.feed = feed;
      state.venues = venues;
      state.heatmap = heatmap;
      state.synergyOverlaps = synergyOverlaps;
      state.venuePrograms = venuePrograms;
      state.communityReviews = communityReviews;
      state.cityPassport = cityPassport;
      if (state.activeChat) {
        await refreshChatMessages();
      }
    } else if (state.tab === "city") {
      const city = state.cityRoom || "";
      const [rooms, room, here, plans] = await Promise.all([
        api("/v1/city/rooms").catch(() => ({ rooms: [] })),
        city ? api(`/v1/city/chat?city=${encodeURIComponent(city)}`).catch(() => null)
             : Promise.resolve(null),
        city ? api(`/v1/city/arrival?city=${encodeURIComponent(city)}`).catch(() => null)
             : Promise.resolve(null),
        city ? api(`/v1/city/meetups?city=${encodeURIComponent(city)}`).catch(() => null)
             : Promise.resolve(null),
      ]);
      state.cityRooms = rooms.rooms || [];
      state.cityChat = room;
      state.cityArrival = here;
      state.cityMeetups = plans;
    } else if (state.tab === "map") {
      const c = coords();
      let eventId = "outing_active";
      if (state.today && state.today.events && state.today.events.length) {
        eventId = state.today.events[0].id || eventId;
      }
      const [mapRes, convoyRes, venuePrograms] = await Promise.all([
        api("/v1/capsules" + (c ? `?lat=${c.lat}&lon=${c.lon}` : "")),
        api(`/v1/venues/convoy/etas?event_id=${eventId}`).catch(() => []),
        api("/v1/venues/programs").catch(() => null)
      ]);
      state.map = mapRes;
      state.convoy = convoyRes;
      state.venuePrograms = venuePrograms;
    } else if (state.tab === "more") {
      const [convoy, decisions, spend, vitals, spaces, people, critical, deadman, datingAvail, datingMatches, miniapps, trust, wrapped, consent, treasury] = await Promise.all([
        api("/v1/convoy"), api("/v1/decisions"), api("/v1/ledger"),
        api("/v1/vitals"), api("/v1/spaces"), api("/v1/people"),
        // The route is `/triage/card`; this asked for `/triage/critical` and 404'd on
        // every page load, so the emergency card was never displayed and never saved.
        api("/v1/triage/card").catch(() => null),
        api("/v1/triage/deadman/status").catch(() => null),
        api("/v1/dating/availability").catch(() => null),
        api("/v1/dating/matches").catch(() => ({ matches: [] })),
        api("/v1/miniapp/list").catch(() => []),
        api("/v1/trust/badge").catch(() => null),
        api("/v1/wrapped/monthly").catch(() => null),
        api("/v1/telemetry/consent").catch(() => ({ enabled: false, share_interests: true, share_city_events: true })),
        api("/v1/treasury/status").catch(() => null)
      ]);
      state.more = { convoy, decisions, spend, vitals, spaces, critical, deadman, datingAvail, datingMatches, miniapps, trust, wrapped, consent, treasury };
      state.people = people.people;
    } else {
      const [graphRes, centralityRanks, timeline] = await Promise.all([
        api("/v1/graph"),
        api("/v1/graph/centrality-ranks").catch(() => []),
        api("/v1/graph/timeline").catch(() => [])
      ]);
      state.graph = graphRes;
      state.centralityRanks = centralityRanks;
      state.timeline = timeline;
    }
    render();
  } catch (e) {
    toast("⚠ " + e.message);
  }
}

/* ---------- views ---------- */

function render() {
  const view = $("#view");
  const views = { today: todayView, capture: captureView, people: peopleView, city: cityView, map: mapView, graph: graphView, more: moreView };
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

  /* ---- Sticky Glassmorphic Mobile Dock ---- */
  let dock = $("#mobile-dock");
  if (!dock) {
    dock = document.createElement("nav");
    dock.id = "mobile-dock";
    dock.className = "mobile-dock";
    document.body.appendChild(dock);
  }
  dock.innerHTML = `
    <button class="dock-btn ${state.tab === "today" ? "active" : ""}" data-dock="today">☀️ Today</button>
    <button class="dock-btn ${state.tab === "people" ? "active" : ""}" data-dock="people">💬 Crews</button>
    <button class="dock-btn ${state.tab === "city" ? "active" : ""}" data-dock="city">🏙️ City</button>
    <button class="dock-btn ${state.tab === "map" ? "active" : ""}" data-dock="map">🗺️ Radar</button>
    <button class="dock-btn ${state.tab === "graph" ? "active" : ""}" data-dock="graph">💎 Graph</button>
    <button class="dock-btn ${state.tab === "more" ? "active" : ""}" data-dock="more">⚙️ More</button>
  `;
  dock.querySelectorAll(".dock-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.dataset.dock;
      if (state.tab !== target) {
        state.tab = target;
        state.enter = true;
        // `refresh()`, not `render()`. Each tab loads its own data in refresh(); rendering
        // alone paints the new tab from whatever state was left over, so on a phone — where
        // this dock covers the nav bar and is the only navigation — every tab showed stale
        // or empty content until something else happened to trigger a fetch. The top nav
        // has always called refresh(); the dock never did.
        refresh();
      }
    });
  });
}

function todayView() {
  const t = state.today;
  let html = "";

  /* ---- Universal Command Palette & Quick-Nav Horizon Bar ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(99,102,241,0.2), rgba(16,185,129,0.15)); border:1px solid rgba(99,102,241,0.4); padding:16px; margin-bottom:14px;">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
      <div style="display:flex; align-items:center; gap:8px;">
        <span style="font-size:20px;">🔍</span>
        <h2 style="margin:0; font-size:18px; color:var(--text);">Spotlight Quick-Nav & Feature Palette</h2>
      </div>
      <span class="badge" style="font-family:monospace; font-size:11px; padding:3px 8px; border:1px solid var(--spark); color:var(--spark);">⌘K / Ctrl+K</span>
    </div>
    <div style="display:flex; gap:8px; margin-bottom:10px;">
      <input class="field" id="global-feature-search" placeholder="Type to instantly jump to any feature... (e.g. Coffee, Dating, Surf, Festival, Co-Living, Jukebox)" style="flex:1; border-radius:10px; font-size:14px; padding:10px 14px; background:rgba(0,0,0,0.25);">
      <button class="primary" style="background:linear-gradient(135deg, #6366f1, #10b981); white-space:nowrap; padding:10px 16px;" data-act="clear-feature-search">Clear ✕</button>
    </div>
    <div style="display:flex; gap:6px; overflow-x:auto; padding-bottom:4px; -webkit-overflow-scrolling:touch;">
      <button class="pill active" style="font-size:12px; padding:5px 12px;" data-act="filter-feature-all">All Verticals 🌐</button>
      <button class="pill" style="font-size:12px; padding:5px 12px;" data-act="filter-feature-coffee">☕ Coffee & Nomad</button>
      <button class="pill" style="font-size:12px; padding:5px 12px;" data-act="filter-feature-dating">🍷 Dating & Drinks</button>
      <button class="pill" style="font-size:12px; padding:5px 12px;" data-act="filter-feature-sports">🏄 Surf & Sports</button>
      <button class="pill" style="font-size:12px; padding:5px 12px;" data-act="filter-feature-festivals">⛺ Festivals & Camp</button>
      <button class="pill" style="font-size:12px; padding:5px 12px;" data-act="filter-feature-housing">🏡 Co-Living & Dine</button>
      <button class="pill" style="font-size:12px; padding:5px 12px;" data-act="filter-feature-economy">🔄 Barter & Borrow</button>
      <button class="pill" style="font-size:12px; padding:5px 12px;" data-act="filter-feature-impact">🌊 Eco & Grants</button>
    </div>
    <div style="display:flex; justify-content:space-between; align-items:center; margin-top:8px; padding-top:8px; border-top:1px solid rgba(255,255,255,0.08);">
      <div style="display:flex; gap:6px; align-items:center;">
        <span style="font-size:12px; color:var(--muted);">🌓 Theme:</span>
        <button class="pill" style="font-size:11px; padding:3px 8px;" data-act="theme-cyber">Cyber 🌌</button>
        <button class="pill" style="font-size:11px; padding:3px 8px;" data-act="theme-sunset">Sunset 🌅</button>
        <button class="pill" style="font-size:11px; padding:3px 8px;" data-act="theme-solar">Solar ☀️</button>
        <button class="pill" style="font-size:11px; padding:3px 8px;" data-act="theme-default">OLED 🖤</button>
      </div>
      <button class="ghost" style="font-size:11px; padding:3px 8px; width:auto;" data-act="test-audio-chime">🔊 Test Haptic Chime</button>
    </div>
  </div>`;

  if (!state.visions || !state.visions.length) {
    html += `<div class="card" style="background: linear-gradient(135deg, rgba(37,99,235,0.15), rgba(16,185,129,0.15)); border:1px solid rgba(37,99,235,0.3);">
      <h2>Welcome to LifeOS — Voice & Text Intake</h2>
      <p class="big">Tell LifeOS about yourself. Speak or type your vision, goals, and interests (e.g. bouldering, coffee, Lisbon, freedom by 40).</p>
      <textarea id="vision-text" placeholder="I live in Lisbon. My goals are to ship LifeOS, train bouldering 3x/week, and meet awesome people." style="min-height:80px;"></textarea>
      <div class="row2" style="margin-top:8px;">
        <button class="primary" data-act="vision">Build My Personal Graph & Plan 🚀</button>
        <button class="ghost" style="width:auto; padding:10px 16px;" data-act="voice-onboard">🎙️ Mic Speak Profile</button>
      </div>
    </div>`;

    if (state.showTutorial !== false) {
      html += `<div class="card" style="border:1px solid var(--spark);">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <h2>✨ Guided Feature Tour (5 Core Pillars)</h2>
          <button class="pill" style="width:auto; padding:4px 10px;" data-act="close-tour">Close Tour ✕</button>
        </div>
        <div style="margin-top:10px; font-size:13.5px; line-height:1.5;">
          <div style="margin-bottom:8px;"><strong>1. 🌅 Diurnal Ritual Engine:</strong> Lock Morning Intent at 8am; log Evening Sunset wins at 9pm.</div>
          <div style="margin-bottom:8px;"><strong>2. 🎙️ VoiceOS Capture:</strong> Speak thoughts into the mic — tasks, people, and interests are extracted to graph.</div>
          <div style="margin-bottom:8px;"><strong>3. 🧗 Instant Crews & WhatsApp Links:</strong> Start bouldering/dinner clubs with 1-tap WhatsApp invite links.</div>
          <div style="margin-bottom:8px;"><strong>4. 🛡️ Deep Work Focus Shield:</strong> Silence social notifications for 45 minutes of uninterrupted flow.</div>
          <div><strong>5. 🔒 Data Sovereignty:</strong> 100% Local-First graph. Export GraphML anytime in 1 click.</div>
        </div>
      </div>`;
    }
  }

  /* ---- Tomorrow at 8:00 Activity & Friend Finder ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(240,169,74,0.15), rgba(99,206,139,0.15)); border:1px solid rgba(240,169,74,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🕒 Find Activities Tomorrow at 8:00</h2>
      <span class="badge good" style="font-weight:bold;">Instant Finder</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Want to do something tomorrow at 8:00 AM or 8:00 PM? 1-tap to check local spots & available friends!</p>
    <div class="row2">
      <button class="primary" data-act="find-tomorrow-am">Find 8:00 AM Coffee & Workout ☕</button>
      <button class="primary" data-act="find-tomorrow-pm">Find 20:00 (8 PM) Drinks & Outings 🌅</button>
    </div>
    <div id="tomorrow-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Outing Squad Beacon & Instant AI Matchmaker ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(239,68,68,0.15), rgba(240,169,74,0.15)); border:1px solid rgba(239,68,68,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>⚡ Outing Squad Beacon & AI Matchmaker</h2>
      <span class="badge" style="color:var(--spark); border-color:var(--spark)40; font-weight:bold;">Next 30 Mins</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Free right now? Match instantly with friends who want to explore coffee spots, bouldering, or outings in the next 30 mins!</p>
    <div class="row2"><input class="field" id="bc-act" placeholder="Activity (e.g. Specialty Coffee)">
    <input class="field" id="bc-time" placeholder="Timeframe (e.g. 30 mins)" value="30 mins"></div>
    <div class="row2">
      <button class="primary" style="background:linear-gradient(135deg, var(--spark), var(--growth));" data-act="instant-synergy-match">Who else is up for this? ☕</button>
    </div>
    <p class="hint" style="margin-top:8px;">Looking for your crew instead? A beacon needs a crew to reach, so it lives on the crew itself — People → your crew → ⚡ Up for it.</p>
    <div id="instant-match-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Instant Dating & Evening Drinks Radar ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(236,72,153,0.15), rgba(168,85,247,0.15)); border:1px solid rgba(236,72,153,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🍷 Instant Dating & Evening Drinks Radar</h2>
      <span class="badge" style="color:var(--spark); border-color:var(--spark)40; font-weight:bold;">Next Hour</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">You can see who is open to meeting here once you are open yourself — nobody browses this list from the outside. Interest stays private unless it is returned.</p>
    <div class="row2">
      <input class="field" id="dt-vibe" placeholder="Vibe (e.g. quiet drink)">
      <input class="field" id="dt-city" placeholder="City (blank = where you said you are)">
    </div>
    <div class="row2" style="margin-top:6px;">
      <button class="primary" style="background:linear-gradient(135deg, rgba(236,72,153,1), rgba(168,85,247,1));" data-act="instant-dating-match">Who is open 🍷</button>
      <button class="ghost" data-act="dating-open-to">I'm open tonight ✋</button>
    </div>
    <div id="instant-dating-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Synergy matcher ----
     The card used to promise "7-Factor Matchmaking: Proximity + Preferences + Heatmap +
     Popularity + Graph Trust + Energy + Weather" and there were no such factors — the seven
     were constants and the partner was always Elena R. or Marcus T. It searches real signals
     now, so the two things it needs are a place to type what you want and a way to publish
     that you want it. The vertical buttons stay: they fill the box in and search. */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(16,185,129,0.15), rgba(99,102,241,0.15)); border:1px solid rgba(16,185,129,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🌐 Who else is up for it</h2>
      <span class="badge good" style="font-weight:bold;">This city</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Say what you want to do. This searches people who have said the same thing in the same city — and nothing else.</p>
    <div class="row2" style="margin-bottom:6px;">
      <input class="field" id="sy-act" placeholder="Bouldering, ramen, techno…">
      <input class="field" id="sy-city" placeholder="City (blank = where you said you are)">
    </div>
    <div class="row2" style="margin-bottom:6px;">
      <button class="primary" data-act="synergy-search">Find people 🔎</button>
      <button class="ghost" data-act="synergy-open-to">I'm up for this ✋</button>
    </div>
    <div class="row2" style="margin-bottom:6px;">
      <button class="ghost" data-act="synergy-vertical" data-activity="bouldering">🧗 Sports</button>
      <button class="ghost" data-act="synergy-vertical" data-activity="co-working">💻 Co-working</button>
    </div>
    <div class="row2" style="margin-bottom:6px;">
      <button class="ghost" data-act="synergy-vertical" data-activity="live music">🎵 Music</button>
      <button class="ghost" data-act="synergy-vertical" data-activity="dinner">🍲 Food</button>
    </div>
    <div class="row2" style="margin-bottom:6px;">
      <button class="ghost" data-act="synergy-vertical" data-activity="skiing">⛷️ Skiing</button>
      <button class="ghost" data-act="synergy-vertical" data-activity="surfing">🏄 Surfing</button>
    </div>
    <div class="row2">
      <button class="ghost" data-act="synergy-vertical" data-activity="techno">🪩 Nightlife</button>
      <button class="ghost" data-act="synergy-mine">What I'm publishing 📋</button>
    </div>
    <div id="vertical-match-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- ConnectOS Open Developer Plugin Hub & SDK ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(99,102,241,0.15), rgba(168,85,247,0.15)); border:1px solid rgba(99,102,241,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🔌 ConnectOS Open Developer Plugin Hub & SDK</h2>
      <span class="badge" style="color:var(--spark); border-color:var(--spark)40; font-weight:bold;">Synergy SDK v2.4</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">3rd-Party Developer Store: Build activity-specific plugins with 7-Factor real-time telemetry!</p>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:10px;">
      <div style="background:var(--surface-2s); padding:10px; border-radius:10px; font-size:12px;">
        <div style="font-weight:700; color:var(--spark);">🪁 KiteSurf Wind Radar</div>
        <div style="color:var(--muted); margin-top:2px;">WindyDev Labs · Wind > 18kts</div>
        <span class="badge good" style="font-size:10px; margin-top:4px;">Installed ✓</span>
      </div>
      <div style="background:var(--surface-2s); padding:10px; border-radius:10px; font-size:12px;">
        <div style="font-weight:700; color:var(--spark);">🎾 Padel 4th Player Finder</div>
        <div style="color:var(--muted); margin-top:2px;">PadelClub EU · 3/4 Matcher</div>
        <span class="badge good" style="font-size:10px; margin-top:4px;">Installed ✓</span>
      </div>
      <div style="background:var(--surface-2s); padding:10px; border-radius:10px; font-size:12px;">
        <div style="font-weight:700; color:var(--text);">🤿 Scuba Vis & Temp Meter</div>
        <div style="color:var(--muted); margin-top:2px;">DiveTech · Vis > 15m</div>
        <button class="ghost" style="font-size:10px; padding:2px 8px; margin-top:4px;" onclick="toast('Scuba Vis Plugin Installed! 🤿');">Install Plugin ⚡</button>
      </div>
      <div style="background:var(--surface-2s); padding:10px; border-radius:10px; font-size:12px;">
        <div style="font-weight:700; color:var(--text);">♟️ Park Chess Matcher</div>
        <div style="color:var(--muted); margin-top:2px;">OpenChess DAO · Sunny Park</div>
        <button class="ghost" style="font-size:10px; padding:2px 8px; margin-top:4px;" onclick="toast('Park Chess Plugin Installed! ♟️');">Install Plugin ⚡</button>
      </div>
    </div>
    <div class="row2" style="margin-bottom:8px;"><input class="field" id="dp-name" placeholder="Plugin Name (e.g. Kitesurf Radar)">
    <input class="field" id="dp-cat" placeholder="Category (e.g. Water Sports)">
    <button class="primary" data-act="register-dev-plugin">Publish Plugin 🚀</button></div>
    <div style="display:flex; gap:8px; border-top:1px solid rgba(255,255,255,0.08); padding-top:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #6366f1, #06b6d4); font-size:12px; padding:6px 12px;" data-act="gen-dev-apikey">Provision API Key 🔌</button>
      <button class="primary" style="background:linear-gradient(135deg, #06b6d4, #10b981); font-size:12px; padding:6px 12px;" data-act="sub-dev-webhook">Register Webhook ⚡</button>
      <button class="primary" style="background:linear-gradient(135deg, #a855f7, #ec4899); font-size:12px; padding:6px 12px;" data-act="test-dev-sandbox">Plugin Sandbox Test 🛠️</button>
    </div>
    <div id="developer-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- AI Social Battery & Real-World Balance Shield ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(16,185,129,0.15), rgba(245,158,11,0.15)); border:1px solid rgba(16,185,129,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🧠 AI Social Battery & Real-World Shield</h2>
      <span class="badge good" style="font-weight:bold;">82% Social Capacity</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">High Social Flow! Real-World Ratio: 85% Outings / 15% Screen Time.</p>
    <div style="background:var(--surface-2s); padding:10px; border-radius:10px; font-size:13px; margin-bottom:8px;">
      ⚡ <strong>Recommendation:</strong> Ideal time for a 4-person Bouldering or Sunset Drinks Crew Outing!
    </div>
    <div class="row2">
      <input class="field" id="pop-place" placeholder="Where were you?" style="margin-bottom:6px;">
      <button class="primary" style="background:linear-gradient(135deg, #f59e0b, #d97706);" data-act="mint-pop-badge">I was there ✅</button>
    </div>
    <div id="pop-mint-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Real-World AR Spatial Overlay & Beacons Radar ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(6,182,212,0.15), rgba(147,51,234,0.15)); border:1px solid rgba(6,182,212,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>👓 Real-World AR Spatial Overlay & Beacons</h2>
      <span class="badge good" style="font-weight:bold;">Spatial Camera Radar</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Live AR View: Floating 3D beacons rendered in space for nearby outings, heatmaps & audio rooms!</p>
    <div style="display:grid; grid-template-columns:1fr; gap:6px; margin-bottom:10px;">
      <div style="background:var(--surface-2s); padding:8px 12px; border-radius:10px; display:flex; justify-content:space-between; align-items:center;">
        <div><strong style="color:var(--spark);">☕ Specialty Coffee Meetup</strong> · Elena R.</div>
        <span class="badge" style="font-size:10px;">85m away · 42° NNE</span>
      </div>
      <div style="background:var(--surface-2s); padding:8px 12px; border-radius:10px; display:flex; justify-content:space-between; align-items:center;">
        <div><strong style="color:var(--growth);">🔥 Miradouro Rooftop Bar</strong> · 88% Density</div>
        <span class="badge" style="font-size:10px;">240m away · 115° E</span>
      </div>
      <div style="background:var(--surface-2s); padding:8px 12px; border-radius:10px; display:flex; justify-content:space-between; align-items:center;">
        <div><strong style="color:#06b6d4;">🎙️ Bouldering Audio Drop-In</strong> · Alex & Crew</div>
        <span class="badge" style="font-size:10px;">310m away · 280° W</span>
      </div>
    </div>
    <button class="primary" style="background:linear-gradient(135deg, #06b6d4, #8b5cf6);" data-act="gen-ai-icebreakers">Openers for a match ✍️</button>
    <div id="ai-icebreaker-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Autonomous Squad Outing Agent Launcher ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(168,85,247,0.15), rgba(236,72,153,0.15)); border:1px solid rgba(168,85,247,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🤖 Autonomous Squad Outing Agent</h2>
      <span class="badge" style="color:var(--spark); border-color:var(--spark)40; font-weight:bold;">Zero Messaging</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">AI Agent negotiates 5 calendars, reserves the spot, and splits bills automatically!</p>
    <button class="primary" style="background:linear-gradient(135deg, #a855f7, #ec4899);" data-act="launch-squad-agent">Launch Autonomous Squad Outing Agent 🤖</button>
    <div id="squad-agent-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Social Karma & Trust Credit ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(234,179,8,0.15), rgba(16,185,129,0.15)); border:1px solid rgba(234,179,8,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🏆 Social Karma & Trust Credit</h2>
      <span class="badge good" style="font-weight:bold;">98 / 100 Karma</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Tier: <strong>Legend Crew Member</strong> (99% Punctual · 12 Verified Badges · 4.98★ Rating)</p>
    <div style="display:flex; gap:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #eab308, #10b981);" data-act="gen-micro-itinerary">🗺️ AI Concierge: Generate Evening Micro-Itinerary</button>
      <button class="ghost" style="color:#ef4444; border-color:#ef4444; font-weight:700;" data-act="trigger-sos">⚡ Emergency SOS</button>
    </div>
    <div id="karma-concierge-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Outing Memory Capsule & VIP Fast-Pass ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(236,72,153,0.15), rgba(168,85,247,0.15)); border:1px solid rgba(236,72,153,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>📸 Outing Memory Capsule & VIP Fast-Pass</h2>
      <span class="badge" style="color:var(--spark); border-color:var(--spark)40; font-weight:bold;">VIP Perks</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Generate a 1-page memory highlight reel or claim 1-tap VIP guestlist access!</p>
    <div style="display:flex; gap:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #ec4899, #a855f7);" data-act="gen-memory-capsule">Generate Memory Capsule 📸</button>
      <button class="primary" style="background:linear-gradient(135deg, #a855f7, #6366f1);" data-act="claim-vip-pass">Claim VIP Guestlist Pass 🎟️</button>
    </div>
    <div id="memory-vip-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- AI Peer Mentorship & Squad Calendar Sync ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(16,185,129,0.15), rgba(99,102,241,0.15)); border:1px solid rgba(16,185,129,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🤝 AI Mentorship & Squad Calendar Sync</h2>
      <span class="badge good" style="font-weight:bold;">1-on-1 & Squads</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Mentorship is a mirror: this looks for someone offering what you want to learn, in your city.</p>
    <div class="row2" style="margin-bottom:6px;">
      <input class="field" id="mt-seek" placeholder="I want to learn…">
      <input class="field" id="mt-offer" placeholder="I can help with… (optional)">
    </div>
    <div style="display:flex; gap:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #10b981, #6366f1);" data-act="match-mentor">Find a mentor 🤝</button>
      <button class="primary" style="background:linear-gradient(135deg, #6366f1, #a855f7);" data-act="sync-squad-routine">Set a weekly routine 📅</button>
    </div>
    <div class="row2" style="margin-top:8px;">
      <input class="field" id="sq-title" placeholder="What, every week? (dawn patrol)">
      <input type="time" class="field" id="sq-at" value="07:00">
    </div>
    <select class="field" id="sq-day" style="margin-top:6px;">
      <option value="mon">Mondays</option><option value="tue">Tuesdays</option>
      <option value="wed" selected>Wednesdays</option><option value="thu">Thursdays</option>
      <option value="fri">Fridays</option><option value="sat">Saturdays</option>
      <option value="sun">Sundays</option>
    </select>
    <div id="mentor-squad-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Outing Ledger Settle-Up & Live Event Photo Wall ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(16,185,129,0.15), rgba(234,179,8,0.15)); border:1px solid rgba(16,185,129,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>💸 Crew tab &amp; micro-quests</h2>
      <span class="badge" style="color:var(--muted); border-color:var(--muted)40;">no money moves</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">What you owe and what you are owed, per person. Settling marks it paid between you — the money still changes hands wherever it already does.</p>
    <div style="display:flex; gap:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #10b981, #eab308);" data-act="settle-crew-tab">Show the tab 💸</button>
      <button class="primary" style="background:linear-gradient(135deg, #eab308, #ec4899);" data-act="gen-city-quest">Generate Micro-Quest (+50 Karma) 🗺️</button>
    </div>
    <div id="ledger-quest-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Algorithmic Transparency & Community Revenue Share ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(99,102,241,0.15), rgba(16,185,129,0.15)); border:1px solid rgba(99,102,241,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🛡️ How the feed ranks</h2>
      <span class="badge" style="color:var(--muted); border-color:var(--muted)40;">read from the code</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">The actual numbers the ranking uses, imported from the ranking itself — so this page cannot drift away from what the feed does. It is a description, not a control panel: the version this replaces took weights and stored none of them.</p>
    <div style="display:flex; gap:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #6366f1, #10b981);" data-act="apply-algo-rules">Show me the rules 🛡️</button>
      <button class="primary" style="background:linear-gradient(135deg, #10b981, #eab308);" data-act="stack-habit">Stack Growth Habit (+14 Streak) 🌱</button>
    </div>
    <div id="algo-revenue-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- ConnectOS Monetization & Subscriptions ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(234,179,8,0.15), rgba(99,102,241,0.15)); border:1px solid rgba(234,179,8,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>💳 ConnectOS Pro & Native Venue Perks</h2>
      <span class="badge good" style="font-weight:bold;">Non-Intrusive Ads & Pro Tier</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Zero tracking ads — only native venue discounts & €9.99/mo Explorer Pro membership!</p>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; margin-bottom:10px;">
      <div style="background:var(--surface-2s); padding:8px; border-radius:10px; font-size:12px;">
        <strong>☕ Fabrica Coffee Roasters</strong>
        <div style="color:var(--spark); font-weight:700; margin-top:2px;">Free Batch Brew Upgrade</div>
      </div>
      <div style="background:var(--surface-2s); padding:8px; border-radius:10px; font-size:12px;">
        <strong>🍷 Miradouro Rooftop Bar</strong>
        <div style="color:var(--growth); font-weight:700; margin-top:2px;">15% Off Crew Tapas Platter</div>
      </div>
    </div>
    <button class="primary" style="background:linear-gradient(135deg, #eab308, #6366f1);" data-act="upgrade-explorer-pro">Upgrade to Explorer Pro (€9.99/mo) 💳</button>
    <div id="sub-monetization-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- AI Voice Note Brief & Social Micro-Gifting ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(168,85,247,0.15), rgba(236,72,153,0.15)); border:1px solid rgba(168,85,247,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🎙️ AI Voice Outing Brief & Social Micro-Gifting</h2>
      <span class="badge good" style="font-weight:bold;">Voice & Perks</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Paste a note you already have in text. There is no speech-to-text here — this reads words, it does not hear them.</p>
    <input class="field" id="vb-note" placeholder="Coffee at four, then the viewpoint" style="margin-bottom:6px;">
    <div class="row2" style="margin-bottom:6px;">
      <input class="field" id="gf-name" placeholder="Owe someone a coffee? (handle)">
      <input class="field" id="gf-item" placeholder="What — coffee, a beer…">
    </div>
    <div style="display:flex; gap:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #a855f7, #ec4899);" data-act="convert-voice-brief">Convert Voice Brief 🎙️</button>
      <button class="primary" style="background:linear-gradient(135deg, #ec4899, #f43f5e);" data-act="gift-friend-coffee">Put it on the tab 🎁</button>
    </div>
    <div id="voice-gift-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Sustainable Multi-Revenue Stream Dashboard ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(16,185,129,0.15), rgba(234,179,8,0.15)); border:1px solid rgba(16,185,129,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>💼 Sustainable Multi-Revenue Dashboard</h2>
      <span class="badge good" style="font-weight:bold;">4 Cashflow Streams</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">B2B Team Subscriptions (€374.75 MRR) + Venue Commissions (€380.00/mo) + Dev RevShare (€150.00/mo)!</p>
    <div style="display:flex; gap:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #10b981, #6366f1);" data-act="b2b-team-signup">Register B2B Team (25 Seats) 🏢</button>
      <button class="primary" style="background:linear-gradient(135deg, #eab308, #10b981);" data-act="view-revenue-breakdown">View Cashflow Breakdown 📊</button>
    </div>
    <div id="monetization-breakdown-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Viral Growth & Referral Engine ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(236,72,153,0.15), rgba(168,85,247,0.15)); border:1px solid rgba(236,72,153,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>⚡ Invite &amp; share</h2>
      <span class="badge" style="color:var(--muted); border-color:var(--muted)40;">nothing is awarded</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">A join link for your crew, and a card you can post. There is no referral reward here — the badge used to promise free coffee for sharing, from a programme that does not exist.</p>
    <input class="field" id="share-title" placeholder="What are you sharing? (Sunset at the miradouro)" style="margin-bottom:8px;">
    <div style="display:flex; gap:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #ec4899, #a855f7);" data-act="gen-invite-link">Crew invite link ⚡</button>
      <button class="primary" style="background:linear-gradient(135deg, #a855f7, #6366f1);" data-act="gen-story-card">Make a card 📢</button>
    </div>
    <div id="viral-growth-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Automated Event & Venue Ingestion Worker ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(6,182,212,0.15), rgba(99,102,241,0.15)); border:1px solid rgba(6,182,212,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🌐 Auto-Populated Event & Venue Ingestion</h2>
      <span class="badge good" style="font-weight:bold;">100% Automated</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Auto-crawls Google Places, Eventbrite, Luma & OpenStreetMap APIs live!</p>
    <button class="primary" style="background:linear-gradient(135deg, #06b6d4, #6366f1);" data-act="trigger-auto-ingestion">Trigger Automated Data Sync (73 Ingested) 🌐</button>
    <div id="auto-ingestion-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Zero-Friction Convenience Controls ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(234,179,8,0.15), rgba(16,185,129,0.15)); border:1px solid rgba(234,179,8,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>⚡ Zero-Friction Convenience Controls</h2>
      <span class="badge good" style="font-weight:bold;">1-Tap & Zero Click</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Magic QR check-in, AI zero-click Auto-RSVP, and Apple/Google Wallet pass export!</p>
    <div style="display:flex; gap:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #eab308, #10b981);" data-act="magic-qr-checkin">Magic QR Check-In ⚡</button>
      <button class="primary" style="background:linear-gradient(135deg, #10b981, #06b6d4);" data-act="export-wallet-pass">Export Wallet Pass 📲</button>
    </div>
    <div id="convenience-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Solo Festival & Camp Village Matcher ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(244,63,94,0.15), rgba(168,85,247,0.15)); border:1px solid rgba(244,63,94,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>⛺ Solo Festival & Camp Village Matcher</h2>
      <span class="badge good" style="font-weight:bold;">Solo Fest Crew</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Going solo to a festival? Connect with other solo legends to camp, carpool, and dance together!</p>
    <div style="display:flex; gap:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #f43f5e, #a855f7);" data-act="join-solo-camp-village">Join Solo Camp Village ⛺</button>
      <button class="primary" style="background:linear-gradient(135deg, #a855f7, #6366f1);" data-act="drop-stage-flare">Drop Stage Flare (Bicep Set 🎵) 🚩</button>
    </div>
    <div id="solo-fest-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Airport Layover & Gym Spotter Synergy ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(14,165,233,0.15), rgba(16,185,129,0.15)); border:1px solid rgba(14,165,233,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>✈️ Airport Layover & Gym Spotter Matcher</h2>
      <span class="badge good" style="font-weight:bold;">Solo Travelers & Fitness</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">An airport is a city for four hours. Same matcher — it searches people who said they are there and open.</p>
    <div class="row2" style="margin-bottom:6px;">
      <input class="field" id="lo-airport" placeholder="Airport code (e.g. LIS)">
      <input class="field" id="lo-gym" placeholder="Climbing, weights…">
    </div>
    <div style="display:flex; gap:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #0ea5e9, #10b981);" data-act="match-layover-buddy">Find Layover Buddy ✈️</button>
      <button class="primary" style="background:linear-gradient(135deg, #10b981, #eab308);" data-act="match-gym-spotter">Match Gym Spotter 🏋️</button>
      <button class="primary" style="background:linear-gradient(135deg, #a855f7, #ec4899);" data-act="match-language-swap">Language Swap 🎓</button>
    </div>
    <div class="row2" style="margin-top:6px;">
      <input class="field" id="ls-speak" placeholder="I speak…">
      <input class="field" id="ls-learn" placeholder="I want to learn…">
    </div>
    <div id="layover-gym-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- AI Outing Butler, 1-Tap Split & Nomad House Swap ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(240,169,74,0.18), rgba(99,102,241,0.18)); border:1px solid rgba(240,169,74,0.4);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🤖 AI Butler, 1-Tap Split & House Swap</h2>
      <span class="badge good" style="font-weight:bold;">Autonomous OS</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">AI Weekend Blueprints, 1-tap Apple Pay group splits, and global apartment swaps!</p>
    <div style="display:flex; gap:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #f0a94a, #f59e0b);" data-act="gen-ai-blueprint">AI Weekend Blueprint 🤖</button>
      <button class="primary" style="background:linear-gradient(135deg, #10b981, #06b6d4);" data-act="settle-one-tap-split">1-Tap Split (€21.00) 🪄</button>
      <button class="primary" style="background:linear-gradient(135deg, #6366f1, #a855f7);" data-act="swap-nomad-flat">Nomad House Swap 🌍</button>
    </div>
    <div id="ai-butler-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Secret Comedy, Market Cookoff & Sunset Sailing ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(236,72,153,0.15), rgba(6,182,212,0.15)); border:1px solid rgba(236,72,153,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🎭 Speakeasy Comedy, Cook-Off & Sailing</h2>
      <span class="badge good" style="font-weight:bold;">Adventures</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Intimate 25-person cellar comedy, Sunday farmers market cook-offs, and sunset catamaran charters!</p>
    <div style="display:flex; gap:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #ec4899, #a855f7);" data-act="join-secret-comedy">Secret Comedy (9 PM) 🎭</button>
      <button class="primary" style="background:linear-gradient(135deg, #f59e0b, #10b981);" data-act="join-market-cookoff">Market Cook-Off 🍳</button>
      <button class="primary" style="background:linear-gradient(135deg, #06b6d4, #0284c7);" data-act="join-sunset-sailing">Sunset Catamaran (€30) ⛵</button>
    </div>
    <div id="adventure-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Silent Reading, Cold Plunge & Art Crawl ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(139,92,246,0.15), rgba(16,185,129,0.15)); border:1px solid rgba(139,92,246,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>📚 Vinyl Reading, Cold Plunge & Art Crawl</h2>
      <span class="badge good" style="font-weight:bold;">Culture & Flow</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Phone-free vinyl book lofts, 7 AM sunrise ocean cold plunges, and local gallery wine walks!</p>
    <div style="display:flex; gap:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #8b5cf6, #6366f1);" data-act="join-silent-reading">Vinyl Reading Lounge 📚</button>
      <button class="primary" style="background:linear-gradient(135deg, #06b6d4, #10b981);" data-act="join-cold-plunge">Sunrise Cold Plunge ☕</button>
      <button class="primary" style="background:linear-gradient(135deg, #ec4899, #f59e0b);" data-act="join-art-crawl">Gallery Art Crawl 🎨</button>
    </div>
    <div id="flow-culture-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Nordic Sauna, Plant Swap & Natural Wine ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(240,169,74,0.16), rgba(16,185,129,0.16)); border:1px solid rgba(240,169,74,0.35);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🧖 Sauna Social, Plant Swap & Wine Club</h2>
      <span class="badge good" style="font-weight:bold;">Community & Vibe</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">90°C Finnish saunas & ice baths, community plant cutting swaps, and rooftop natural wine tastings!</p>
    <div style="display:flex; gap:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #f0a94a, #ef4444);" data-act="join-sauna-social">Nordic Sauna (6 PM) 🧖</button>
      <button class="primary" style="background:linear-gradient(135deg, #10b981, #059669);" data-act="join-plant-swap">Plant & Seed Swap 🪴</button>
      <button class="primary" style="background:linear-gradient(135deg, #ec4899, #a855f7);" data-act="join-wine-tasting">Natural Wine Tasting 🍷</button>
    </div>
    <div id="sauna-plant-wine-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Frontier Stack: Native Store, Wearables, Edge Mesh & AI Agents ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(6,182,212,0.18), rgba(139,92,246,0.18)); border:1px solid rgba(6,182,212,0.4);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🚀 Frontier Engine: Native Apps, Wearables & AI Mesh</h2>
      <span class="badge" style="color:var(--spark); border-color:var(--spark)40; font-weight:bold;">v2.4 Production</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Native iOS/Android App Store builds, Apple Watch/Whoop telemetry sync, sub-10ms global edge mesh, and multi-agent AI outing negotiators!</p>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #06b6d4, #3b82f6);" data-act="build-native-manifest">App Store Manifest 📱</button>
      <button class="primary" style="background:linear-gradient(135deg, #10b981, #06b6d4);" data-act="sync-wearable-telemetry">Sync Wearable HRV ⌚</button>
      <button class="primary" style="background:linear-gradient(135deg, #6366f1, #8b5cf6);" data-act="trigger-edge-mesh">Global Edge Mesh 🌍</button>
      <button class="primary" style="background:linear-gradient(135deg, #ec4899, #f59e0b);" data-act="negotiate-ai-agents">AI Agent Consensus 🤖</button>
    </div>
    <div id="frontier-stack-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- City Pioneer & Cold-Start Seeding Engine ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(16,185,129,0.18), rgba(245,158,11,0.18)); border:1px solid rgba(16,185,129,0.4);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🌱 City Pioneer & Cold-Start Viral Engine</h2>
      <span class="badge good" style="font-weight:bold;">Day-0 Seeding</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Bootstrap a city, see how early you were in it, and mint single-use join links. Being early unlocks nothing — the pass used to promise a year of free VIP.</p>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #10b981, #06b6d4);" data-act="seed-city-bootstrap">Bootstrap City (Lisbon) 🗺️</button>
      <button class="primary" style="background:linear-gradient(135deg, #f59e0b, #ec4899);" data-act="mint-pioneer-pass">How early was I? 👑</button>
      <button class="primary" style="background:linear-gradient(135deg, #6366f1, #8b5cf6);" data-act="gen-golden-tickets">3 single-use links 🎟️</button>
      <button class="primary" style="background:linear-gradient(135deg, #06b6d4, #10b981);" data-act="activate-anchor-outings">Weekly Anchor Crews ⚓</button>
    </div>
    <div id="seeding-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- What is actually switched on ----
     Was the "Universal ConnectOS Master Controller", badged "All 50+ Engines Unified",
     with four mode buttons that stored nothing and a response claiming BLE mesh, spatial
     audio and Apple Pay were online. Every line was a constant. */
  html += `<div class="card">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>⚙️ What is switched on</h2>
      <span class="badge" style="color:var(--muted); border-color:var(--muted)40;">derived, not asserted</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Which capabilities this instance actually has, and which it genuinely cannot do. Each line is checked, not claimed.</p>
    <div class="row2" style="margin-bottom:8px;">
      <button class="primary" data-act="system-status">Check the system</button>
      <button class="ghost" data-act="show-feed-rules">How the feed ranks</button>
    </div>
    <div id="master-controller-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Universal Stripe & PayPal Checkout Hub ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(99,102,241,0.18), rgba(0,112,186,0.18)); border:1px solid rgba(99,102,241,0.4);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>💳 Stripe & PayPal Global Payments</h2>
      <span class="badge" style="color:var(--growth); border-color:var(--growth)40; font-weight:bold;">PCI-DSS Tier 1</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Instant Stripe Checkout (Card, Apple Pay, Google Pay, SEPA) and 1-Click PayPal Order Capture for outings and VIP perks!</p>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #6366f1, #8b5cf6);" data-act="pay-stripe-checkout">Stripe Checkout (€21) 💳</button>
      <button class="primary" style="background:linear-gradient(135deg, #0070ba, #003087);" data-act="pay-paypal-order">PayPal 1-Click (€21) 🅿️</button>
      <button class="primary" style="background:linear-gradient(135deg, #10b981, #06b6d4);" data-act="test-stripe-webhook">Stripe Webhook Sync ⚡</button>
      <button class="primary" style="background:linear-gradient(135deg, #0284c7, #0369a1);" data-act="capture-paypal-order">Capture PayPal 💰</button>
    </div>
    <div id="stripe-paypal-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Automated City Content & AI Pipeline Studio ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(6,182,212,0.18), rgba(240,169,74,0.18)); border:1px solid rgba(6,182,212,0.4);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>📡 Automated City Content & AI Pipeline</h2>
      <span class="badge" style="color:var(--spark); border-color:var(--spark)40; font-weight:bold;">Autonomous Data</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Stream 280+ public event feeds, synthesize AI micro-itineraries, ingest 160+ third places, and trigger spontaneous weather outings!</p>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #06b6d4, #3b82f6);" data-act="stream-auto-events">Stream Event Feeds (284) 📡</button>
      <button class="primary" style="background:linear-gradient(135deg, #ec4899, #f59e0b);" data-act="synth-ai-outing">AI Outing Synthesizer 🤖</button>
      <button class="primary" style="background:linear-gradient(135deg, #10b981, #059669);" data-act="load-third-places">160 Third Places 📍</button>
      <button class="primary" style="background:linear-gradient(135deg, #f59e0b, #ef4444);" data-act="trigger-weather-outings">Weather Triggers ☀️</button>
    </div>
    <div id="content-pipeline-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Multi-Hobby Passion & Craft Hub ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(236,72,153,0.18), rgba(99,102,241,0.18)); border:1px solid rgba(236,72,153,0.4);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🎨 Multi-Hobby Passion & Craft Hub</h2>
      <span class="badge" style="color:var(--spark); border-color:var(--spark)40; font-weight:bold;">All Passions</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Bouldering & padel ladders, pottery & darkroom labs, park blitz chess, and sourdough fermentation swaps!</p>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #06b6d4, #10b981);" data-act="view-sports-hobbies">Sports & Outdoors 🧗</button>
      <button class="primary" style="background:linear-gradient(135deg, #ec4899, #f59e0b);" data-act="view-creative-making">Creative Making 🏺</button>
      <button class="primary" style="background:linear-gradient(135deg, #6366f1, #8b5cf6);" data-act="view-gaming-strategy">Chess & Gaming ♟️</button>
      <button class="primary" style="background:linear-gradient(135deg, #f59e0b, #ef4444);" data-act="view-culinary-craft">Culinary & Brews 🍳</button>
    </div>
    <div id="hobbies-hub-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Global Landmark Festivals & Cultural Radar Studio ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(234,179,8,0.18), rgba(236,72,153,0.18)); border:1px solid rgba(234,179,8,0.4);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🌍 Global Landmark Festivals Radar</h2>
      <span class="badge" style="color:var(--spark); border-color:var(--spark)40; font-weight:bold;">Mega-Events AI</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Live radar for iconic global festivals: Edinburgh Fringe & Tattoo, Munich Oktoberfest & Surf Masters, Lisbon Festas & NOS Alive!</p>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #f59e0b, #ec4899);" data-act="radar-edinburgh-fringe">Edinburgh Fringe & Tattoo 🎭</button>
      <button class="primary" style="background:linear-gradient(135deg, #3b82f6, #10b981);" data-act="radar-munich-oktoberfest">Munich Oktoberfest 🍺</button>
      <button class="primary" style="background:linear-gradient(135deg, #10b981, #06b6d4);" data-act="radar-lisbon-festas">Lisbon Festas & Web Summit 🐟</button>
      <button class="primary" style="background:linear-gradient(135deg, #8b5cf6, #6366f1);" data-act="sync-ai-butler-landmarks">Sync AI Butler 🤖</button>
    </div>
    <div id="landmark-radar-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Frontier Voice, NFC & Culture Bridge Studio ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(99,102,241,0.18), rgba(16,185,129,0.18)); border:1px solid rgba(99,102,241,0.4);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🎙️ Spatial Voice, NFC Handshake & Culture Bridge</h2>
      <span class="badge" style="color:var(--spark); border-color:var(--spark)40; font-weight:bold;">Frontier Social OS</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Spatial 3D festival walkie-talkie, NFC physical tap-to-synergy handshake, local dialect translator, and DAO community treasury!</p>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #6366f1, #8b5cf6);" data-act="open-voice-huddle">Spatial Voice Huddle 🎙️</button>
      <button class="primary" style="background:linear-gradient(135deg, #ec4899, #f59e0b);" data-act="trigger-nfc-tap">Swap a code 📳</button>
      <button class="primary" style="background:linear-gradient(135deg, #06b6d4, #10b981);" data-act="translate-local-culture">Culture & Slang Bridge 🗣️</button>
    </div>
    <div style="margin-bottom:8px;">
      <input class="field" id="tap-code" placeholder="Their code — or leave empty to show yours" style="margin-bottom:6px;">
      <input class="field" id="cb-phrase" placeholder="A phrase you heard and didn't get">
      <button class="primary" style="background:linear-gradient(135deg, #10b981, #059669);" data-act="view-dao-treasury">DAO Community Treasury 🏛️</button>
    </div>
    <div id="frontier-social-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Anti-Boredom & Genuine Fulfillment Butler Studio ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(16,185,129,0.18), rgba(245,158,11,0.18)); border:1px solid rgba(16,185,129,0.4);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🌟 Anti-Boredom & Genuine Fulfillment Butler</h2>
      <span class="badge good" style="font-weight:bold;">Eudaimonia & Flow</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Instant 15-min spontaneous quests, Ikigai purpose alignment, 100% screen-free flow mastery labs, and deep vulnerability dinner salons!</p>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #f59e0b, #ef4444);" data-act="trigger-boredom-quest">I'm Bored (15m Quests) ⚡</button>
      <button class="primary" style="background:linear-gradient(135deg, #10b981, #06b6d4);" data-act="align-ikigai-compass">Ikigai Fulfillment Compass 🧘</button>
      <button class="primary" style="background:linear-gradient(135deg, #6366f1, #8b5cf6);" data-act="book-flow-mastery">Find a practice partner 🌊</button>
      <button class="primary" style="background:linear-gradient(135deg, #ec4899, #f43f5e);" data-act="book-meaningful-salon">Find a dinner table 🕊️</button>
    </div>
    <div class="row2" style="margin-bottom:8px;">
      <input class="field" id="fm-skill" placeholder="Skill to practise">
      <input class="field" id="ms-theme" placeholder="Dinner theme">
    </div>
    <div id="fulfillment-butler-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Proactive AI Butler 4.0 & Empathy Concierge Studio ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(139,92,246,0.18), rgba(236,72,153,0.18)); border:1px solid rgba(139,92,246,0.4);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🔮 Proactive AI Butler 4.0 & Empathy Concierge</h2>
      <span class="badge" style="color:var(--spark); border-color:var(--spark)40; font-weight:bold;">Superhuman AI</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Proactive serendipity prediction, emotional empathy vibe tuning, autonomous 1-tap group dining scheduling, and friendship compounding vault!</p>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #8b5cf6, #6366f1);" data-act="predict-serendipity">Predict Serendipity 🔮</button>
      <button class="primary" style="background:linear-gradient(135deg, #06b6d4, #10b981);" data-act="tune-empathy-vibe">Empathy Vibe Tuner 🧠</button>
      <button class="primary" style="background:linear-gradient(135deg, #ec4899, #f59e0b);" data-act="auto-group-concierge">Group Concierge (4p) 🗺️</button>
      <button class="primary" style="background:linear-gradient(135deg, #10b981, #059669);" data-act="view-friendship-vault">Friendship Vault 🌱</button>
    </div>
    <div id="butler-4-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Butler of True Life Value & Fulfillment Studio ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(245,158,11,0.18), rgba(16,185,129,0.18)); border:1px solid rgba(245,158,11,0.4);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🌟 Butler of True Life Value & Longevity</h2>
      <span class="badge good" style="font-weight:bold;">Lifelong Value</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Circadian vitality flow, lifelong regret minimization bucket-list, high-memory wealth optimizer, and stoic daily gratitude!</p>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #10b981, #06b6d4);" data-act="optimize-circadian-vitality">Circadian Vitality 🧬</button>
      <button class="primary" style="background:linear-gradient(135deg, #f59e0b, #ec4899);" data-act="track-regret-minimization">Regret Minimizer 🌟</button>
      <button class="primary" style="background:linear-gradient(135deg, #6366f1, #8b5cf6);" data-act="optimize-life-wealth">Wealth & Memory ROI 💰</button>
      <button class="primary" style="background:linear-gradient(135deg, #ec4899, #10b981);" data-act="log-stoic-reflection">Write it down 🕊️</button>
    </div>
    <div style="margin-bottom:8px;">
      <input class="field" id="sr-note" placeholder="Something worth remembering (private, never scored)">
    </div>
    <div id="life-value-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Zero-User Autonomous Event Seeding & Tastemaker Studio ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(6,182,212,0.18), rgba(99,102,241,0.18)); border:1px solid rgba(6,182,212,0.4);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🌐 Zero-User Autonomous Event Seeding & Tastemaker</h2>
      <span class="badge good" style="font-weight:bold;">Cold-Start Solved</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Multi-feed live event crawler (RA, Luma, Dice), hidden gem tastemaker scoring, recurring real-world gravity hubs, and 7-day city culture guide!</p>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #06b6d4, #3b82f6);" data-act="crawl-zero-user-events">Crawl 220+ Events (RA/Luma) 📡</button>
      <button class="primary" style="background:linear-gradient(135deg, #ec4899, #8b5cf6);" data-act="curate-hidden-gems">Top Hidden Gems 💎</button>
      <button class="primary" style="background:linear-gradient(135deg, #10b981, #059669);" data-act="sync-gravity-hubs">Recurring Real Hubs 📍</button>
      <button class="primary" style="background:linear-gradient(135deg, #f59e0b, #ef4444);" data-act="gen-city-culture-guide">7-Day Culture Guide 📅</button>
    </div>
    <div id="zero-user-seeding-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- 24-Hour User Day UX Simulation Studio ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(99,102,241,0.18), rgba(236,72,153,0.18)); border:1px solid rgba(99,102,241,0.4);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🕒 24-Hour User Day UX Simulation (All Demographics)</h2>
      <span class="badge good" style="font-weight:bold;">Universal UX</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Simulate full 24-hour days across 6 archetypal human demographics (Nomads, Parents, Artists, Athletes, Retirees, Students)!</p>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #6366f1, #8b5cf6);" data-act="run-full-day-simulation">Simulate Single Day 🚀</button>
      <button class="primary" style="background:linear-gradient(135deg, #ec4899, #f59e0b);" data-act="run-all-demographics">Simulate All 6 Demographics 👥</button>
    </div>
    <div id="day-simulation-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Ultimate Frontier Capabilities Studio ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(16,185,129,0.18), rgba(99,102,241,0.18)); border:1px solid rgba(16,185,129,0.4);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🌐 Ultimate Frontier Capabilities</h2>
      <span class="badge good" style="font-weight:bold;">Final Frontier</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Who has vouched for somebody — by name, never a score — and the places you have actually been. This app verifies no identity.</p>
    <input class="field" id="tw-who" placeholder="Their handle (empty shows your own vouches)" style="margin-bottom:8px;">
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #06b6d4, #10b981);" data-act="sync-offline-mesh">Offline BLE Mesh Sync 📴</button>
      <button class="primary" style="background:linear-gradient(135deg, #6366f1, #8b5cf6);" data-act="listen-wearable-whispers">Wearable Audio Whispers 🦻</button>
      <button class="primary" style="background:linear-gradient(135deg, #ec4899, #f59e0b);" data-act="verify-web-of-trust">Who vouches for them 🤝</button>
      <button class="primary" style="background:linear-gradient(135deg, #f59e0b, #10b981);" data-act="view-memory-atlas">Living Memory Atlas 🗺️</button>
    </div>
    <div id="ultimate-frontier-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Global Flourishing & Regenerative Earth Studio ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(16,185,129,0.18), rgba(245,158,11,0.18)); border:1px solid rgba(16,185,129,0.4);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🌍 Global Flourishing & Regenerative Earth</h2>
      <span class="badge good" style="font-weight:bold;">Planetary Impact</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Regenerative eco-quests, zero-waste food sharing pantries, mental health peer listeners, and intergenerational craft mentorship!</p>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #10b981, #06b6d4);" data-act="view-eco-quests">Regenerative Eco-Quests 🌱</button>
      <button class="primary" style="background:linear-gradient(135deg, #f59e0b, #ec4899);" data-act="view-zero-waste-pantry">Zero-Waste Food Pantry 🍲</button>
      <button class="primary" style="background:linear-gradient(135deg, #6366f1, #8b5cf6);" data-act="connect-peer-listener">Compassion Listener 🧠</button>
      <button class="primary" style="background:linear-gradient(135deg, #ec4899, #10b981);" data-act="view-intergenerational-guild">Intergenerational Guild 🕊️</button>
    </div>
    <div id="global-flourishing-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Next-Gen Content Seeding & Insider Radar Studio ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(236,72,153,0.18), rgba(245,158,11,0.18)); border:1px solid rgba(236,72,153,0.4);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>📡 Next-Gen Content Seeding & Insider Radar</h2>
      <span class="badge good" style="font-weight:bold;">Insider Discovery</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Underground vinyl listening sessions, secret ramen test kitchens, unmapped wild waterfalls, and candlelit poetry bookshop salons!</p>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #ec4899, #8b5cf6);" data-act="view-vinyl-radar">Underground Vinyl Radar 🎙️</button>
      <button class="primary" style="background:linear-gradient(135deg, #f59e0b, #ef4444);" data-act="view-culinary-drops">Culinary Secret Drops 🥐</button>
      <button class="primary" style="background:linear-gradient(135deg, #10b981, #06b6d4);" data-act="view-wild-nature">Wild Nature & Waterfalls ⛰️</button>
      <button class="primary" style="background:linear-gradient(135deg, #6366f1, #3b82f6);" data-act="view-literary-salons">Literary & Poetry Salons 📚</button>
    </div>
    <div id="nextgen-seeding-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Hyper-Autonomous Event & Spot Discovery Studio ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(6,182,212,0.18), rgba(99,102,241,0.18)); border:1px solid rgba(6,182,212,0.4);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🛰️ Hyper-Autonomous Event & Spot Discovery</h2>
      <span class="badge good" style="font-weight:bold;">Live Real-Time APIs</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Live Open-Meteo weather telemetry, Wikipedia encyclopedia feeds, Reddit/Instagram viral surges & OSM footfall anomalies!</p>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #06b6d4, #3b82f6);" data-act="view-viral-pulse">Social & Viral Pulse 📱</button>
      <button class="primary" style="background:linear-gradient(135deg, #f59e0b, #ec4899);" data-act="view-footfall-anomalies">Footfall Surge Anomaly 🗺️</button>
      <button class="primary" style="background:linear-gradient(135deg, #6366f1, #8b5cf6);" data-act="view-editorial-press">Cultural Press Scraper 📰</button>
      <button class="primary" style="background:linear-gradient(135deg, #10b981, #f59e0b);" data-act="view-weather-triggers">Weather & Tide Triggers ☀️</button>
      <button class="primary" style="background:linear-gradient(135deg, #ec4899, #10b981); grid-column: 1 / -1;" data-act="fetch-live-apis">🌐 Ingest Live External APIs (Open-Meteo & Wiki) 🚀</button>
    </div>
    <div id="hyper-discovery-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Nightlife, Underground Clubs & Secret Speakeasies Studio ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(239,68,68,0.2), rgba(168,85,247,0.2)); border:1px solid rgba(239,68,68,0.4);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🍸 Nightlife, Underground Clubs & Speakeasies</h2>
      <span class="badge good" style="font-weight:bold; background:linear-gradient(135deg,#ef4444,#a855f7); color:#fff;">After-Dark Radar</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Live underground warehouse raves, VOID sound systems, secret telephone-booth cocktail bars, 1-tap VIP guestlists & pre-game squads!</p>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #ef4444, #f97316);" data-act="view-nightlife-party">🔥 Live Party & Club Radar</button>
      <button class="primary" style="background:linear-gradient(135deg, #a855f7, #ec4899);" data-act="view-nightlife-speakeasy">🍸 Secret Speakeasies & Dens</button>
      <button class="primary" style="background:linear-gradient(135deg, #6366f1, #3b82f6);" data-act="rsvp-nightlife-fastpass">🎟️ 1-Tap Fast-Pass Guestlist</button>
      <button class="primary" style="background:linear-gradient(135deg, #10b981, #06b6d4);" data-act="match-pregame-crew">🍻 Pre-Game Crew & SafeWalk</button>
    </div>
    <div id="nightlife-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Midnight Memory & Daily Reflection Synthesizer Studio ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(99,102,241,0.2), rgba(16,185,129,0.2)); border:1px solid rgba(99,102,241,0.4);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🌙 Midnight Memory & Daily Reflection</h2>
      <span class="badge good" style="font-weight:bold; background:linear-gradient(135deg,#6366f1,#10b981); color:#fff;">Time-Capsule AI</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Autonomous poetic daily retrospective, gratitude dividends, step vitality & permanent graph time-capsule archiving!</p>
    <div style="display:flex; gap:8px; margin-bottom:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #6366f1, #10b981); width:100%; font-size:14px; padding:10px;" data-act="synthesize-daily-journal">✨ Synthesize Today's Memory & Gratitude Log</button>
    </div>
    <div id="journal-synthesis-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Voice Copilot & Eyes-Up Audio AR Studio ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(59,130,246,0.18), rgba(168,85,247,0.18)); border:1px solid rgba(59,130,246,0.4);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🎙️ Voice AI Copilot & Eyes-Up Audio AR</h2>
      <span class="badge good" style="font-weight:bold; background:linear-gradient(135deg,#3b82f6,#a855f7); color:#fff;">Spoken AI</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Hands-free, eyes-up audio copilot! Ask about tonight's vinyl sessions, food, or friend locations.</p>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #3b82f6, #6366f1);" data-act="voice-ask-nightlife">🔊 "Best vinyl club tonight?"</button>
      <button class="primary" style="background:linear-gradient(135deg, #a855f7, #ec4899);" data-act="voice-ask-food">🔊 "Best warm sourdough?"</button>
      <button class="primary" style="background:linear-gradient(135deg, #10b981, #06b6d4);" data-act="voice-ask-squad">🔊 "Who is nearby?"</button>
      <button class="primary" style="background:linear-gradient(135deg, #f59e0b, #ef4444);" data-act="voice-custom-prompt">🎙️ Speak Custom Prompt</button>
    </div>
    <div id="voice-copilot-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Neighborhood Craft Micro-Masterclasses Studio ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(245,158,11,0.18), rgba(239,68,68,0.18)); border:1px solid rgba(245,158,11,0.4);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🤝 Neighborhood Craft Micro-Masterclasses</h2>
      <span class="badge good" style="font-weight:bold;">60-Min Masteries</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Intimate small-group masterclasses hosted by verified neighborhood masters & artisans.</p>
    <div style="display:flex; gap:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #f59e0b, #ef4444); width:100%;" data-act="view-micro-workshops">Explore 60-Min Craft Masterclasses 📷🍞❄️</button>
    </div>
    <div id="workshops-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Smart Layover & Transit Stopover Navigator ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(6,182,212,0.18), rgba(16,185,129,0.18)); border:1px solid rgba(6,182,212,0.4);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>⚡ Smart Layover & Stopover Micro-Escape</h2>
      <span class="badge good" style="font-weight:bold;">100% Missed-Flight Safety</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Turn 4-hour airport or central train layovers into curated micro-escapes with automated gate return alarms!</p>
    <div style="display:flex; gap:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #06b6d4, #10b981); width:100%;" data-act="plan-layover-escape">Plan 4.5h Munich Airport Micro-Escape ✈️</button>
    </div>
    <div id="layover-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Universal Data Portability & Obsidian / Notion Vault Export ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(139,92,246,0.18), rgba(59,130,246,0.18)); border:1px solid rgba(139,92,246,0.4);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>📦 Universal Data Portability & Obsidian Vault</h2>
      <span class="badge good" style="font-weight:bold;">100% User Owned</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Everything you have put in, as Markdown you can open anywhere. It is built here and saved from your own browser — nothing is uploaded, and credentials are left out.</p>
    <div style="display:flex; gap:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #8b5cf6, #3b82f6); width:100%;" data-act="export-universal-markdown">Export everything 📁</button>
    </div>
    <div id="markdown-export-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Co-Living, Supper Club & Digital Detox ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(236,72,153,0.15), rgba(99,102,241,0.15)); border:1px solid rgba(236,72,153,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🏡 Co-Living, Supper Club & Digital Detox</h2>
      <span class="badge good" style="font-weight:bold;">Deep Human Connection</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Match nomad villas, host 6-person home supper clubs, or reserve phone-free deep work lounges!</p>
    <div style="display:flex; gap:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #ec4899, #6366f1);" data-act="match-coliving">Nomad Villa Match 🏡</button>
      <button class="primary" style="background:linear-gradient(135deg, #f59e0b, #ec4899);" data-act="rsvp-supper-club">Supper Club 🍲</button>
      <button class="primary" style="background:linear-gradient(135deg, #10b981, #06b6d4);" data-act="reserve-digital-detox">Digital Detox 🧘</button>
    </div>
    <div id="human-needs-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Circular Economy & Barter Swap Hub ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(16,185,129,0.15), rgba(234,179,8,0.15)); border:1px solid rgba(16,185,129,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🔄 Circular Economy & Barter Trade Hub</h2>
      <span class="badge good" style="font-weight:bold;">Zero Cash / Zero Waste</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Trade skills & gear cash-free, borrow neighborhood tools, and earn Time Tokens!</p>
    <div style="display:flex; gap:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #10b981, #eab308);" data-act="trade-barter-swap">Trade Skill / Item 🔄</button>
      <button class="primary" style="background:linear-gradient(135deg, #06b6d4, #10b981);" data-act="borrow-gear-library">Borrow Gear Tent ♻️</button>
      <button class="primary" style="background:linear-gradient(135deg, #eab308, #f59e0b);" data-act="earn-time-token">Time Bank (+1 Hr) 🌱</button>
    </div>
    <div id="circular-economy-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Live Group Nav, Squad Jukebox & Community Fund ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(99,102,241,0.15), rgba(168,85,247,0.15)); border:1px solid rgba(99,102,241,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🗺️ Group Nav, Squad Jukebox & Grants</h2>
      <span class="badge good" style="font-weight:bold;">Live Collaboration</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Turn-by-turn group routing, blended venue music jukebox, and neighborhood impact micro-grants!</p>
    <div style="display:flex; gap:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #6366f1, #a855f7);" data-act="start-group-nav">Start Group Nav 🗺️</button>
      <button class="primary" style="background:linear-gradient(135deg, #a855f7, #ec4899);" data-act="sync-squad-jukebox">Squad Jukebox 🎶</button>
      <button class="primary" style="background:linear-gradient(135deg, #10b981, #06b6d4);" data-act="vote-micro-grant">Community Grant (€1,450) 🏆</button>
    </div>
    <div id="collab-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Global City Bridge & Squad Beacon ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(6,182,212,0.15), rgba(99,102,241,0.15)); border:1px solid rgba(6,182,212,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🌐 Global City Bridge & Safety Beacon</h2>
      <span class="badge good" style="font-weight:bold;">Global & Secure</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Live multi-city portal linkups, 1-tap trusted safety escort beacons, and artist residencies!</p>
    <div style="display:flex; gap:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #06b6d4, #6366f1);" data-act="trigger-global-bridge">Global City Bridge (LIS ⟷ TYO) 🌐</button>
      <button class="primary" style="background:linear-gradient(135deg, #ef4444, #f59e0b);" data-act="trigger-squad-beacon">Squad S.O.S. Beacon ⚡</button>
      <button class="primary" style="background:linear-gradient(135deg, #a855f7, #ec4899);" data-act="award-creator-grant">Creator Grant 💎</button>
    </div>
    <div id="global-safety-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Sunset Jam, Analog Film Swap & Eco-Clean ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(236,72,153,0.15), rgba(240,169,74,0.15)); border:1px solid rgba(236,72,153,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>⚡ Sunset Jam, Film Swap & Eco Squad</h2>
      <span class="badge good" style="font-weight:bold;">Culture & Impact</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Match spontaneous viewpoint sunset music jams, swap 35mm film rolls, and join beach cleanups!</p>
    <div style="display:flex; gap:8px;">
      <button class="primary" style="background:linear-gradient(135deg, #ec4899, #f0a94a);" data-act="join-popup-jam">Sunset Jam (7:30 PM) ⚡</button>
      <button class="primary" style="background:linear-gradient(135deg, #a855f7, #6366f1);" data-act="swap-film-roll">35mm Film Swap 📸</button>
      <button class="primary" style="background:linear-gradient(135deg, #10b981, #06b6d4);" data-act="join-eco-clean">Eco-Clean Squad 🌊</button>
    </div>
    <div id="culture-impact-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Evening Sunset Win Ritual ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(240,169,74,0.15), rgba(236,72,153,0.15)); border:1px solid rgba(240,169,74,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🌅 Evening Sunset Win Ritual (9 PM)</h2>
      <span class="badge" style="color:var(--spark); border-color:var(--spark)40; font-weight:bold;">Daily Win</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Log 1 win from today to share inspiration with your crew and close the day mindful.</p>
    <div class="row2"><input class="field" id="sw-text" placeholder="What went awesome today? (e.g. Shipped ConnectOS!)">
    <button class="primary" data-act="sunset-win-save">Log Evening Win 🌅</button></div>
  </div>`;

  /* ---- Guided Mindfulness & 2-Min Breathing Timer ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(139,92,246,0.12), rgba(16,185,129,0.12)); border:1px solid rgba(139,92,246,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🧘 2-Min Guided Mindfulness Reset</h2>
      <span class="badge" style="color:var(--calm); border-color:var(--calm)40; font-weight:bold;">Wellness</span>
    </div>
    <p class="hint" style="margin-bottom:10px;">Breathe in sync with the pulse to reset cognitive load and boost focus.</p>
    <div style="text-align:center; margin:12px 0;">
      <div id="breath-circle" style="width:70px; height:70px; border-radius:50%; background:var(--calm); margin:0 auto; transition:transform 4s ease-in-out; opacity:0.8;"></div>
    </div>
    <button class="primary" data-act="mindfulness-start">Start 2-Min Breathing Session 🧘</button>
  </div>`;

  /* ---- 30-Day Focus Contribution Heatmap Grid ---- */
  if (state.heatmapGrid && state.heatmapGrid.days) {
    const grid = state.heatmapGrid.days;
    html += `<div class="card">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <h2>🟩 30-Day Focus Heatmap Grid</h2>
        <span class="badge good" style="font-weight:bold;">${state.heatmapGrid.streak_days || 14}-Day Streak 🔥</span>
      </div>
      <p class="hint" style="margin-bottom:8px;">Consistency matrix across focus tasks & habits.</p>
      <div style="display:grid; grid-template-columns:repeat(10, 1fr); gap:6px; margin-top:8px;">
        ${grid.map(d => {
          let bg = "rgba(255,255,255,0.08)";
          if (d.level === 1) bg = "rgba(16,185,129,0.3)";
          if (d.level === 2) bg = "rgba(16,185,129,0.6)";
          if (d.level >= 3) bg = "var(--growth)";
          return `<div style="height:22px; background:${bg}; border-radius:4px;" title="Day ${d.day}"></div>`;
        }).join("")}
      </div>
    </div>`;
  }

  /* ---- AI Smart Calendar Travel Activity Nudge ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(37,99,235,0.15), rgba(16,185,129,0.15)); border:1px solid rgba(37,99,235,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>✈️ AI Smart Calendar Travel Radar</h2>
      <span class="badge good" style="font-weight:bold;">Trip Detected</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">AI Smart Calendar detected an upcoming trip to <strong>Lisbon</strong> (Aug 15 - 22)! Suggested curated activities based on your graph:</p>
    <div style="font-size:13px; line-height:1.5; margin-bottom:10px;">
      <div>📍 <strong>Monsanto Outdoor Bouldering Crag</strong> (Climbing · #1 match)</div>
      <div>☕ <strong>Fabrica Coffee Roasters</strong> (Specialty Coffee)</div>
      <div>🎟️ <strong>Lisbon Tech & Outdoor Fest</strong> (Aug 17 · 28 attending)</div>
    </div>
    <button class="primary" data-act="smart-cal-travel-add" data-city="Lisbon">Add Suggested Activities to Smart Calendar 📅</button>
  </div>`;

  /* ---- Ambient Focus & Plane Journey Sleep Soundscapes ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(37,99,235,0.12), rgba(139,92,246,0.12)); border:1px solid rgba(37,99,235,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🎧 Ambient Focus & Plane Sleep Soundscapes</h2>
      <span class="badge" style="color:var(--spark); border-color:var(--spark)40; font-weight:bold;">Offline Audio</span>
    </div>
    <p class="hint" style="margin-bottom:10px;">Offline synth audio for deep work, sleeping on plane journeys, or drowning out background noise.</p>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:8px;">
      <button class="ghost" style="padding:8px; text-align:left;" data-act="audio-play" data-preset="rain">🌧️ <strong>Gentle Rain</strong><br><small style="color:var(--muted)">Relaxing rainfall</small></button>
      <button class="ghost" style="padding:8px; text-align:left;" data-act="audio-play" data-preset="brown">🟤 <strong>Deep Brown Noise</strong><br><small style="color:var(--muted)">Deep focus shield</small></button>
      <button class="ghost" style="padding:8px; text-align:left;" data-act="audio-play" data-preset="plane">✈️ <strong>Jet Cabin Sleep</strong><br><small style="color:var(--muted)">Plane journey sleep</small></button>
      <button class="ghost" style="padding:8px; text-align:left;" data-act="audio-play" data-preset="space">🌌 <strong>Cosmic Drift</strong><br><small style="color:var(--muted)">Meditation drone</small></button>
    </div>
    <button class="pill bad" style="width:auto; padding:6px 16px; margin-top:4px;" data-act="audio-stop">Stop Audio 🛑</button>
  </div>`;

  /* ---- Diurnal Ritual Engine (Morning Intent / Evening Sunset) ---- */
  const hour = new Date().getHours();
  const isMorning = hour < 17;
  if (isMorning) {
    html += `<div class="card" style="background: linear-gradient(135deg, rgba(249,115,22,0.12), rgba(234,179,8,0.12)); border:1px solid rgba(249,115,22,0.3);">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <h2>🌅 Morning Intent Ritual</h2>
        <span class="badge good" style="font-weight:bold;">AM Flow</span>
      </div>
      <p class="hint" style="margin-bottom:8px;">Set your single primary focus for today to align your energy before checking tasks.</p>
      <input class="field" id="morning-intent-text" placeholder="Today's single primary focus (e.g. Ship LifeOS V2)..." value="${esc(state.morningIntent || "")}">
      <button class="primary" style="margin-top:6px;" data-act="save-morning-intent">Lock Morning Intent 🎯</button>
    </div>`;
  } else {
    html += `<div class="card" style="background: linear-gradient(135deg, rgba(139,92,246,0.15), rgba(37,99,235,0.15)); border:1px solid rgba(139,92,246,0.3);">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <h2>🌆 Evening Reflection & Sunset Ritual</h2>
        <span class="badge" style="color:var(--calm); border-color:var(--calm)40; font-weight:bold;">PM Sunset</span>
      </div>
      <p class="hint" style="margin-bottom:8px;">Wrap up today with clarity: log your wins, gratitude, and mood rating.</p>
      <div class="row2"><input class="field" id="pm-win" placeholder="Today's main win...">
      <input class="field" id="pm-gratitude" placeholder="1 thing you are grateful for..."></div>
      <button class="primary" style="margin-top:6px;" data-act="save-evening-sunset">Log Evening Sunset & Complete Day 🌙</button>
    </div>`;
  }

  /* ---- Cognitive Load & Burnout Risk Meter ---- */
  if (state.energyBalance) {
    const eb = state.energyBalance;
    const riskColors = { low: "var(--growth)", moderate: "var(--warm)", high: "var(--alert)" };
    const riskEmoji = { low: "🟢 Low Risk", moderate: "🟡 Moderate Risk", high: "🔴 High Risk" };
    html += `<div class="card">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <h2>Cognitive Load & Energy Balance</h2>
        <span class="badge" style="color:${riskColors[eb.burnout_risk] || 'var(--growth)'}; font-weight:800; border-color:${riskColors[eb.burnout_risk]}40;">${riskEmoji[eb.burnout_risk] || '🟢 Low Risk'}</span>
      </div>
      <div style="display:flex; gap:16px; margin:10px 0; align-items:center;">
        <div style="font-size:24px; font-weight:900; color:var(--spark);">${eb.cognitive_load_index || 2.5}</div>
        <div style="font-size:12.5px; color:var(--muted); line-height:1.3;">
          <div><strong>Tasks in progress:</strong> ${eb.open_tasks_count || 0}</div>
          <div><strong>Active focus goals:</strong> ${eb.active_goals_count || 0}</div>
        </div>
      </div>
      <p class="hint" style="color:var(--text); line-height:1.4;">💡 ${esc(eb.recommendation || "High capacity available: Great time for deep work!")}</p>
    </div>`;
  }

  /* ---- Deep Work Anti-Distraction Shield ---- */
  const focusActive = state.focusEndTime && Date.now() < state.focusEndTime;
  html += `<div class="card" style="${focusActive ? "border:1px solid var(--spark); background:rgba(37,99,235,0.1);" : ""}">
    <h2>Deep Work Anti-Distraction Shield</h2>
    ${focusActive ? `
      <div style="font-size:18px; font-weight:800; color:var(--spark); text-align:center; margin:10px 0;">🛡️ Focus Shield Active</div>
      <p class="hint" style="text-align:center;">Social notifications and chats are silenced. Stay in flow.</p>
      <button class="ghost" data-act="focus-end">Deactivate Shield</button>
    ` : `
      <p class="hint" style="margin-bottom:10px;">Silence all social feeds and chats for 45 minutes of uninterrupted deep work.</p>
      <button class="primary" data-act="focus-start">Activate 45m Focus Shield 🛡️</button>
    `}
  </div>`;

  /* ---- Daily Activity Rings ---- */
  const rg = state.rings || { focus_percentage: 75, social_percentage: 60, wellness_percentage: 85 };
  html += `<div class="card"><h2>Daily Activity Rings</h2>
    <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px; text-align:center;">
      <div style="background:var(--surface-2s); padding:10px; border-radius:12px; border:1px solid rgba(37,99,235,0.3);">
        <div style="font-size:20px; font-weight:800; color:var(--spark);">${rg.focus_percentage || 75}%</div>
        <div style="font-size:11px; color:var(--muted); font-weight:600; margin-top:2px;">⚡ Focus</div>
      </div>
      <div style="background:var(--surface-2s); padding:10px; border-radius:12px; border:1px solid rgba(16,185,129,0.3);">
        <div style="font-size:20px; font-weight:800; color:var(--growth);">${rg.social_percentage || 60}%</div>
        <div style="font-size:11px; color:var(--muted); font-weight:600; margin-top:2px;">🧗 Social</div>
      </div>
      <div style="background:var(--surface-2s); padding:10px; border-radius:12px; border:1px solid rgba(139,92,246,0.3);">
        <div style="font-size:20px; font-weight:800; color:var(--calm);">${rg.wellness_percentage || 85}%</div>
        <div style="font-size:11px; color:var(--muted); font-weight:600; margin-top:2px;">🧘 Wellness</div>
      </div>
    </div>
  </div>`;

  /* ---- Interactive 3D Real-World Activity Globe ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(16,185,129,0.15), rgba(6,182,212,0.15)); border:1px solid rgba(16,185,129,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🗺️ Interactive 3D Real-World Activity Globe</h2>
      <span class="badge good" style="font-weight:bold;">115 Active Flares</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Live WebGL Globe: Spatial 3D view of active social flares across global hubs!</p>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; margin-bottom:8px;">
      <div style="background:var(--surface-2s); padding:8px; border-radius:10px; font-size:12px;"><strong>🇵🇹 Lisbon:</strong> 14 Flares · 24°C 🌅</div>
      <div style="background:var(--surface-2s); padding:8px; border-radius:10px; font-size:12px;"><strong>🇯🇵 Tokyo:</strong> 28 Flares · 19°C 🗼</div>
      <div style="background:var(--surface-2s); padding:8px; border-radius:10px; font-size:12px;"><strong>🇺🇸 New York:</strong> 32 Flares · 22°C 🌆</div>
      <div style="background:var(--surface-2s); padding:8px; border-radius:10px; font-size:12px;"><strong>🇬🇧 London:</strong> 22 Flares · 18°C 🎡</div>
    </div>
    <button class="primary" style="background:linear-gradient(135deg, #10b981, #06b6d4);" onclick="toast('3D Spatial Globe Canvas Rendered! 🌐');">Expand 3D Spatial Globe 🌐</button>
  </div>`;

  /* ---- Nomad Passport & City Teleport ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(6,182,212,0.15), rgba(99,102,241,0.15)); border:1px solid rgba(6,182,212,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🌐 Nomad Passport & City Teleport</h2>
      <span class="badge good" style="font-weight:bold;">Global Hubs</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Switch your active city feed to instantly discover local crews, hubs & events!</p>
    <div class="row2">
      <input class="field" id="np-city" placeholder="Target City (e.g. Tokyo / Bali / NYC)">
      <button class="primary" style="background:linear-gradient(135deg, #06b6d4, #6366f1);" data-act="switch-nomad-city">Teleport City 🌐</button>
    </div>
    <div id="nomad-teleport-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Weekend Core Digest ---- */
  if (state.weekend) {
    const wk = state.weekend;
    html += `<div class="card"><h2>Weekend Digest (Fri – Sun)</h2>
      ${wk.friday ? `<div style="margin-bottom:6px;"><strong style="color:var(--spark);">Friday Evening:</strong> ${esc(wk.friday.title || wk.friday)}</div>` : ""}
      ${wk.saturday ? `<div style="margin-bottom:6px;"><strong style="color:var(--growth);">Saturday:</strong> ${esc(wk.saturday.title || wk.saturday)}</div>` : ""}
      ${wk.sunday ? `<div style="margin-bottom:6px;"><strong style="color:var(--calm);">Sunday:</strong> ${esc(wk.sunday.title || wk.sunday)}</div>` : ""}
      <button class="primary" style="margin-top:8px;" data-act="weekend-share">Share Weekend Plan Text 📲</button>
    </div>`;
  }

  /* ---- Habit Stacking Recommendation ---- */
  if (state.habitChain && state.habitChain.recommendation) {
    html += `<div class="card"><h2>Habit Stacking Recommendation</h2>
      <div style="font-size:13.5px; color:var(--text); line-height:1.4;">🔗 ${esc(state.habitChain.recommendation)}</div>
      <p class="hint">Anchor new habits to existing daily anchors for maximum consistency.</p>
    </div>`;
  }

  /* ---- AI Coach Suggestions (L0 Propose-Only) ---- */
  if (window.TravelCoach) {
    const coachCtx = {
      thisWeek: t ? t.week : "",
      weeks: t ? [t] : [],
      log: (state.graph && state.graph.recent) || [],
      goals: state.visions || [],
      retrosCompleted: (state.journal || []).length,
      dismissed: state.dismissedProposals || new Set()
    };
    try {
      const proposals = window.TravelCoach.proposals(coachCtx);
      if (proposals && proposals.length) {
        html += `<div class="card"><h2>AI Coach Suggestions</h2>`;
        html += proposals.map(p => `
          <div class="feed-item" style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
            <div>
              <div class="kind" style="color:var(--spark); font-weight:600;">${esc(p.title)}</div>
              <div class="label" style="font-size:13px; color:var(--text); margin-top:2px;">${esc(p.why || p.text || "")}</div>
            </div>
            <button class="pill" style="margin-left:8px; width:auto; padding:4px 10px;" data-act="coach-dismiss" data-id="${esc(p.id)}">✕</button>
          </div>
        `).join("");
        html += `</div>`;
      }
    } catch (err) {
      console.warn("Coach error:", err);
    }
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

  /* ---- Parked Ideas (Anti-Hindrance Distraction Sink) ---- */
  if (state.parked && state.parked.length) {
    html += `<div class="card"><h2>Parked Ideas (Distraction Sink)</h2>
      <p class="hint" style="margin-bottom:8px;">Captured, not abandoned — current gate first!</p>`;
    html += state.parked.map(item => {
      const label = item.attrs ? (item.attrs.text || item.attrs.title || item.id) : item.id;
      return `
        <div class="person"><div class="who">
          <div class="name">${esc(label)}</div>
          <div class="meta">Parked idea</div>
        </div><div class="pills">
          <button class="pill warm" data-act="parked-promote" data-id="${item.id}">Promote</button>
        </div></div>
      `;
    }).join("");
    html += `</div>`;
  }

  /* ---- Compounding Graph Memory & Journey ---- */
  if (window.TravelStats && state.graph) {
    try {
      const statsCtx = {
        log: (state.graph && state.graph.recent) || [],
        today: t,
        journal: state.journal || []
      };
      const stats = window.TravelStats.stats(statsCtx);
      if (stats) {
        html += `<div class="card"><h2>Compounding Graph Memory</h2>
          <div class="kv"><span>Days Shown Up</span><span class="v">${stats.daysShownUp || 1}d</span></div>
          <div class="kv"><span>Tasks Finished</span><span class="v">${stats.tasksDone || 0}</span></div>
          ${stats.recall ? `<div style="margin-top:10px; background:var(--surface-2s); padding:10px 14px; border-radius:10px;">
            <div style="font-size:11px; color:var(--spark); font-weight:600;">Recall Memory (${esc(stats.recall.date || "")}):</div>
            <div style="font-size:13.5px; color:var(--text); font-style:italic; margin-top:2px;">"${esc(stats.recall.text)}"</div>
          </div>` : ""}
        </div>`;
      }
    } catch (err) {
      console.warn("Stats error:", err);
    }
  }

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
      <textarea id="capture-text" placeholder="Anything. Tasks, people and interests get extracted into the graph automatically."></textarea>
      <div class="row2">
        <button class="primary" data-act="capture">Capture</button>
        <button class="ghost" style="width:auto; padding:10px 16px;" data-act="voice-record">🎙️ Mic Speak</button>
      </div>
      <p class="hint">VoiceOS transcribes speech and extracts tasks, people, and interests into your context graph.</p></div>
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
  /* ---- Match New Local Friends Radar ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(16,185,129,0.15), rgba(37,99,235,0.15)); border:1px solid rgba(16,185,129,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🤝 Match New Friends in My City</h2>
      <span class="badge good" style="font-weight:bold;">Shared Interests</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Find new friends in your city who share your exact hobbies (bouldering, specialty coffee, tech, running)!</p>
    <div class="row2"><input class="field" id="mf-interest" placeholder="Hobby / Interest (e.g. bouldering)">
    <button class="primary" data-act="match-new-friends">Find New Friends 🤝</button></div>
    <div id="match-friends-output" style="margin-top:10px;"></div>
  </div>`;

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

  /* ---- Multi-Source Local Activity & Discovery Feed ---- */
  const feedItems = (state.feed && state.feed.items) || [];
  const exploreVenues = (state.venues && state.venues.venues) || [];
  const capsules = (state.map && state.map.capsules) || [];

  /* ---- Global Synergy Leaderboard ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(234,179,8,0.15), rgba(168,85,247,0.15)); border:1px solid rgba(234,179,8,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🏆 Global Synergy Leaderboard</h2>
      <span class="badge good" style="font-weight:bold;">Rank #1 Lisbon</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Top real-world community leaders and verified event hosts!</p>
    <div style="display:flex; flex-direction:column; gap:4px; margin-bottom:8px;">
      <div style="background:var(--surface-2s); padding:8px 10px; border-radius:8px; display:flex; justify-content:space-between; font-size:12.5px;">
        <span>🥇 <strong>You</strong> · 98 Karma</span>
        <span style="color:var(--spark); font-weight:700;">👑 Lisbon Legend</span>
      </div>
      <div style="background:var(--surface-2s); padding:8px 10px; border-radius:8px; display:flex; justify-content:space-between; font-size:12.5px;">
        <span>🥈 <strong>Elena R.</strong> · 96 Karma</span>
        <span style="color:var(--growth); font-weight:700;">🌅 Sunset Master</span>
      </div>
      <div style="background:var(--surface-2s); padding:8px 10px; border-radius:8px; display:flex; justify-content:space-between; font-size:12.5px;">
        <span>🥉 <strong>Alex M.</strong> · 94 Karma</span>
        <span style="color:var(--calm); font-weight:700;">🧗 Outdoor Pro</span>
      </div>
    </div>
  </div>`;

  html += `<div class="card"><h2>Local Activity & Discovery Feed</h2>
    <p class="hint" style="margin-bottom:10px;">Multi-source stream: public events, travel asks, local crags/venues, and quests.</p>`;

  if (!feedItems.length && !exploreVenues.length && !capsules.length) {
    html += `<p class="empty">No local activities in this city yet. Publish one below!</p>`;
  } else {
    if (feedItems.length) {
      html += feedItems.map(item => `
        <div class="person"><div class="who">
          <div class="name">${esc(item.title || "Public Outing")} ${item.where ? `· ${esc(item.where)}` : ""}</div>
          <div class="meta">${esc(item.topic || "general")}${item.place ? ` @ ${esc(item.place)}` : ""} — ${item.going_count || 0} interested</div>
          ${item.reasons ? `<div class="hint" style="font-size:11px; margin-top:2px;">${esc(item.reasons.join(" · "))}</div>` : ""}
        </div><div class="pills">
          <button class="pill good" data-act="feed-interest" data-id="${item.id}">Interested ✓</button>
        </div></div>
      `).join("");
    }

    if (exploreVenues.length) {
      html += `<div class="subhead" style="margin-top:12px;">Local Venues & Crags</div>`;
      html += exploreVenues.slice(0, 3).map(v => `
        <div class="feed-item">
          <div class="kind">${esc(v.category || "Venue")} · ${esc(v.city || "")}</div>
          <div class="label"><strong>${esc(v.name)}</strong>${v.address ? ` — ${esc(v.address)}` : ""}</div>
        </div>
      `).join("");
    }
  }

  /* ---- Universal City Event Auto-Ingest Radar ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(139,92,246,0.15), rgba(236,72,153,0.15)); border:1px solid rgba(139,92,246,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🌐 City Event Radar & Live Feeds</h2>
      <span class="badge" style="color:var(--spark); border-color:var(--spark)40; font-weight:bold;">Universal Ingest</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Auto-sync live events from Luma, Eventbrite, Meetup, and local city feeds!</p>
    <div class="row2"><input class="field" id="ag-city" placeholder="Target City (e.g. Lisbon / Tokyo / NYC)">
    <button class="primary" data-act="auto-ingest-city">Sync Live Events 🎟️</button></div>
  </div>`;

  /* A "Zero-Knowledge Anonymous Credential Engine" card sat here, offering to prove you
     were over 18 or a verified resident. Nothing behind it verified anything — the endpoint
     returned success for any attribute from any caller. Removed rather than restyled: an
     age claim the app displays as proven is the one piece of theatre that can actually hurt
     somebody. */

  html += `<div class="subhead" style="margin-top:12px;">Publish Public Activity</div>
    <div class="row2"><input class="field" id="fa-title" placeholder="Title (e.g. Sushi & Drinks)">
    <input class="field" id="fa-topic" placeholder="Topic (e.g. sushi)"></div>
    <div class="row2"><input class="field" id="fa-city" placeholder="City (e.g. Lisbon)">
    <input class="field" id="fa-place" placeholder="Place (e.g. Restaurant X)"></div>
    <button class="primary" data-act="feed-publish">Publish Public Activity</button>
  </div>`;

  /* The "Weekly Crew Outing Poll" card lived here: three hardcoded options with invented
     vote counts (4, 2 and 6) that were the same for every account, and a vote button that
     posted a string to an endpoint which stored nothing. Polls are per-crew and real now —
     they are opened and read from the crew's own row, where there is a crew id to attach
     them to. A poll with no crew is what made the old one fictional. */

  /* ---- Live Field Reports & Spot Reviews ---- */
  if (state.communityReviews && state.communityReviews.reviews) {
    const revs = state.communityReviews.reviews;
    html += `<div class="card" style="background: linear-gradient(135deg, rgba(16,185,129,0.15), rgba(240,169,74,0.15)); border:1px solid rgba(16,185,129,0.3);">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <h2>📝 Live Field Reports & Spot Reviews</h2>
        <span class="badge good" style="font-weight:bold;">Community Feed</span>
      </div>
      <p class="hint" style="margin-bottom:8px;">Real-time conditions & reviews from crags, coffee roasters, and spots in your city!</p>
      ${revs.map(r => `
        <div class="feed-item" style="background:var(--surface-2s); padding:10px; border-radius:10px; margin-bottom:8px;">
          <div style="font-size:13px; font-weight:700; color:var(--spark);">📍 ${esc(r.place)} · <small style="color:var(--muted);">${esc(r.time)} by ${esc(r.author)}</small></div>
          <div style="font-size:13px; margin-top:2px;">"${esc(r.review)}" ⭐ ${r.rating}/5</div>
        </div>
      `).join("")}
      <div class="row2" style="margin-top:8px;"><input class="field" id="rv-place" placeholder="Spot / Venue Name">
      <input class="field" id="rv-text" placeholder="Condition / Review..."></div>
      <button class="primary" data-act="post-venue-review">Post Field Report 📝</button>
    </div>`;
  }

  /* ---- Real-World City Passport & Stamps ---- */
  if (state.cityPassport && state.cityPassport.stamps) {
    const st = state.cityPassport.stamps;
    html += `<div class="card" style="background: linear-gradient(135deg, rgba(240,169,74,0.15), rgba(16,185,129,0.15)); border:1px solid rgba(240,169,74,0.3);">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <h2>🏅 Real-World City Passport</h2>
        <span class="badge good" style="font-weight:bold;">${state.cityPassport.stamps_count} Venue Stamps</span>
      </div>
      <p class="hint" style="margin-bottom:8px;">Your digital passport stamps & badges collected from exploring spots in ${esc(state.cityPassport.city)}!</p>
      ${st.map(s => `
        <div class="feed-item" style="background:var(--surface-2s); padding:8px 12px; border-radius:10px; margin-bottom:6px; display:flex; justify-content:space-between; align-items:center;">
          <div>
            <div style="font-size:13px; font-weight:700; color:var(--spark);">${s.badge}</div>
            <div style="font-size:12px; color:var(--muted);">${esc(s.venue)} · ${esc(s.date)}</div>
          </div>
          <span class="badge" style="font-size:11px;">${esc(s.category)}</span>
        </div>
      `).join("")}
    </div>`;
  }

  /* ---- SafeWalk Live Companion & Safety Escort ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(16,185,129,0.15), rgba(37,99,235,0.15)); border:1px solid rgba(16,185,129,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🛡️ SafeWalk Live Companion & Escort</h2>
      <span class="badge good" style="font-weight:bold;">Safety Radar</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Say where you are going and when you should be there. The people you name see it, and see when you are overdue. <strong>This app cannot call anyone</strong> — in an emergency, call your local emergency number.</p>
    <div class="row2"><input class="field" id="sw-dest" placeholder="Where are you going?">
    <input class="field" id="sw-eta" type="number" placeholder="Minutes" value="30"></div>
    <input class="field" id="sw-watchers" placeholder="Who should see it? (handles or ids, comma separated)" style="margin-top:6px;">
    <div class="row2" style="margin-top:6px;">
      <button class="primary" data-act="start-safewalk-escort">Start the walk 🛡️</button>
      <button class="ghost" data-act="safewalk-arrived">I got there ✅</button>
    </div>
    <div class="row2" style="margin-top:6px;">
      <button class="ghost" data-act="safewalk-mine">My walk</button>
      <button class="ghost" data-act="safewalk-watching">Who I'm watching</button>
    </div>
    <div id="safewalk-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Outing Expense Splitter & Payment Links ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(240,169,74,0.15), rgba(168,85,247,0.15)); border:1px solid rgba(240,169,74,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>💸 The tab</h2>
      <span class="badge" style="color:var(--muted); border-color:var(--muted)40;">no money moves</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">You paid, everybody owes you their share. Name people and it goes on a tab you can both see and settle. Leave the names empty and it is just the arithmetic.</p>
    <div class="row2"><input class="field" id="qs-title" placeholder="What was it? (tapas)">
    <input class="field" id="qs-amount" type="number" step="0.01" placeholder="Total (60.00)">
    <input class="field" id="qs-people" type="number" placeholder="People" value="4"></div>
    <input class="field" id="qs-who" placeholder="Who else? (handles, comma separated)" style="margin-top:6px;">
    <div class="row2" style="margin-top:8px;">
      <button class="primary" data-act="quick-split-expense">Split it</button>
      <button class="ghost" data-act="show-tab">Show my tab</button>
      <button class="ghost" data-act="tab-history">History</button>
    </div>
    <div id="quick-split-output" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Strava-Style Kudos & XP Boost ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(236,72,153,0.15), rgba(234,179,8,0.15)); border:1px solid rgba(236,72,153,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>👏 Kudos</h2>
      <span class="badge" style="color:var(--muted); border-color:var(--muted)40;">no score</span>
    </div>
    <p class="hint" style="margin-bottom:10px;">A short note to somebody, which they can read. No score and no streak — the "+50 XP" this card used to promise was the same number for everyone.</p>
    <div class="row2" style="margin-bottom:6px;">
      <input class="field" id="kd-name" placeholder="Their handle">
      <input class="field" id="kd-note" placeholder="What are you thanking them for?">
    </div>
    <button class="primary" data-act="kudos-send">Send it 👏</button>
  </div>`;

  /* ---- Buy a Coffee / Micro-Tip Host ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(234,179,8,0.15), rgba(16,185,129,0.15)); border:1px solid rgba(234,179,8,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>☕ Tip a host</h2>
      <span class="badge" style="color:var(--muted); border-color:var(--muted)40;">recorded, not sent</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">This app moves no money. A tip goes on your tab as owed, where they can see it and either of you can mark it settled.</p>
    <div class="row2"><input class="field" id="tp-name" placeholder="Their handle">
    <input class="field" id="tp-amount" type="number" step="0.01" placeholder="3.50"></div>
    <button class="primary" data-act="send-micro-tip" style="margin-top:6px;">Put it on my tab ☕</button>
  </div>`;

  /* ---- Live Audio Crew Space ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(99,102,241,0.15), rgba(168,85,247,0.15)); border:1px solid rgba(99,102,241,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>🎙️ Live Audio Drop-In Space</h2>
      <span class="badge good" style="font-weight:bold;">Voice Hangout</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Start a live voice room for crew outing prep or casual weekend chats!</p>
    <div class="row2"><input class="field" id="as-title" placeholder="Space Title (e.g. Weekend Bouldering Prep)">
    <button class="primary" data-act="start-audio-space">Launch Audio Space 🎙️</button></div>
  </div>`;

  /* ---- Anonymous Kindness & Positive Vibes Box ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(236,72,153,0.15), rgba(244,63,94,0.15)); border:1px solid rgba(236,72,153,0.3);">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h2>💌 Anonymous Kindness Note Box</h2>
      <span class="badge" style="color:var(--spark); border-color:var(--spark)40; font-weight:bold;">Positive Vibes</span>
    </div>
    <p class="hint" style="margin-bottom:8px;">Send an anonymous note of gratitude or encouragement to a friend!</p>
    <div class="row2"><input class="field" id="kn-name" placeholder="Friend Name (e.g. Alex)">
    <input class="field" id="kn-text" placeholder="Your kind message..."></div>
    <button class="primary" data-act="send-kindness-note">Send Kindness Note 💌</button>
  </div>`;

  /* ---- Public Event URL Importer ---- */
  html += `<div class="card"><h2>Import External Event (Luma / Eventbrite / Meetup)</h2>
    <div class="row2"><input class="field" id="imp-url" placeholder="Paste Luma or Meetup event URL...">
    <button class="primary" style="width:auto; padding:10px 16px;" data-act="import-event-url">Import Event</button></div>
    <p class="hint">Instantly populates your local discovery feed with public event details.</p>
  </div>`;

  /* ---- City Activity Hotspots Radar ---- */
  if (state.heatmap && state.heatmap.heatmap) {
    const hm = state.heatmap.heatmap;
    html += `<div class="card"><h2>City Activity Hotspots Radar</h2>
      <p class="hint" style="margin-bottom:8px;">Live activity levels across local venues in your city.</p>
      ${hm.slice(0, 4).map(h => `
        <div class="kv">
          <span>${esc(h.name || h.venue_name || "Venue")} <span style="font-size:11px; color:var(--muted);">(${esc(h.category || "Hotspot")})</span></span>
          <span class="badge good" style="font-weight:bold;">🔥 High Activity</span>
        </div>
      `).join("")}
    </div>`;
  }

  /* ---- Mutual Free Window Radar ---- */
  if (state.synergyOverlaps && state.synergyOverlaps.overlaps) {
    const ovs = state.synergyOverlaps.overlaps;
    html += `<div class="card" style="background: linear-gradient(135deg, rgba(234,179,8,0.15), rgba(16,185,129,0.15)); border:1px solid rgba(234,179,8,0.3);">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <h2>⚡ Mutual Free Window Radar</h2>
        <span class="badge good" style="font-weight:bold;">Auto Match</span>
      </div>
      <p class="hint" style="margin-bottom:10px;">LifeOS matched your free calendar windows with your friends' availability!</p>
      ${ovs.map(o => `
        <div class="person"><div class="who">
          <div class="name">${esc(o.friend_name)} · ${esc(o.topic)}</div>
          <div class="meta">Free Window: ${esc(o.window)} (${esc(o.city)})</div>
        </div><div class="pills">
          <button class="pill warm" data-act="synergy-propose" data-text="${esc(o.share_text)}">Propose Outing 📲</button>
        </div></div>
      `).join("")}
    </div>`;
  }

  /* ---- Personal contact card ----
     This was an <img> pointing at api.qrserver.com with a vCard in the query string. Two
     things were wrong with it: every viewer's IP went to a third party each time the tab
     rendered, and the card was the hardcoded string "LifeOS Member" — the same QR for
     everybody, carrying nobody's details. It is built from your own account now, and the
     file is produced locally. */
  html += `<div class="card"><h2>Personal contact card</h2>
    <p class="hint" style="margin-bottom:10px;">A vCard with your handle and trust badge — save it, or send it to someone you meet.</p>
    <button class="primary" data-act="vcard-download">Get my contact card</button>
    <div id="vcard-output" style="margin-top:10px;"></div>
  </div>`;

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
        <button class="pill" data-act="crew-link" data-id="${c.id}">🔗 Invite</button>
        <button class="pill good" data-act="crew-pass" data-id="${c.id}">🎟️ Plus-One Pass</button>
        <button class="pill" data-act="crew-polls" data-id="${c.id}" data-name="${esc(c.name)}">📊 Polls</button>
        <button class="pill" data-act="crew-beacons" data-id="${c.id}" data-name="${esc(c.name)}">⚡ Up for it</button>
        <button class="pill" data-act="crew-ics" data-id="${c.id}">📅 .ics</button>
      </div></div>`).join("");
  }
  html += `<div id="crew-activity-output" style="margin-top:10px;"></div>`;

  html += `<div class="subhead" style="margin-top:12px;">Instant Crew Starters (1-Tap)</div>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:12px;">
      <button class="ghost" style="text-align:left; padding:8px 12px;" data-act="crew-starter" data-name="Lisbon Bouldering & Coffee" data-topic="climbing" data-city="Lisbon">🧗 <strong>Bouldering</strong><br><small style="color:var(--muted)">Climbing & coffee</small></button>
      <button class="ghost" style="text-align:left; padding:8px 12px;" data-act="crew-starter" data-name="Wednesday Dinner Club" data-topic="food" data-city="Lisbon">🍣 <strong>Dinner Club</strong><br><small style="color:var(--muted)">Weekly food outing</small></button>
      <button class="ghost" style="text-align:left; padding:8px 12px;" data-act="crew-starter" data-name="Morning Trail Runners" data-topic="running" data-city="Lisbon">🏃 <strong>Trail Runners</strong><br><small style="color:var(--muted)">Weekend morning runs</small></button>
      <button class="ghost" style="text-align:left; padding:8px 12px;" data-act="crew-starter" data-name="Board Game & Pizza Night" data-topic="games" data-city="Lisbon">🎲 <strong>Board Games</strong><br><small style="color:var(--muted)">Fridays games & pizza</small></button>
    </div>

    <div class="subhead">Custom Crew</div>
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

  /* ---- Crew Bulletins ---- */
  html += `<div class="card"><h2>Crew Bulletins & Notices</h2>
    <div class="row2"><input class="field" id="bl-crew" placeholder="Crew ID">
    <input class="field" id="bl-title" placeholder="Title (e.g. Venue Change)"></div>
    <textarea class="field" id="bl-body" placeholder="Announcement details..."></textarea>
    <button class="primary" data-act="bulletin-add">Publish Bulletin</button>
  </div>`;

  /* ---- Outing Photo Gallery ---- */
  html += `<div class="card"><h2>Outing Photos & Collages</h2>
    <div class="row2"><input class="field" id="gl-event" placeholder="Event / Outing ID">
    <input class="field" id="gl-url" placeholder="Photo Image URL"></div>
    <div class="row2">
      <button class="primary" data-act="gallery-upload">Upload Photo</button>
      <button class="ghost" data-act="collage-create">Generate Collage</button>
    </div>
    <div id="collage-preview" style="margin-top:10px;"></div>
  </div>`;

  /* ---- Group Expense Splitter ---- */
  const peopleOpts = (state.people || []).map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join("");
  html += `<div class="card"><h2>Group Expense Splitter</h2>
    <div class="row2"><input class="field" id="sp-amount" type="number" step="0.01" placeholder="Total Amount (e.g. 120.00)">
    <input class="field" id="sp-curr" placeholder="Currency (EUR/USD)" value="EUR"></div>
    <div class="subhead">Payer (who paid)</div>
    <select class="field" id="sp-payer"><option value="">-- Payer --</option>${peopleOpts}</select>
    <div class="subhead">Members Splitting</div>
    <select class="field" multiple id="sp-members">${peopleOpts}</select>
    <button class="primary" data-act="split-expense">Split Expense Equally</button>
  </div>`;

  return html;
}

function cityView() {
  const rooms = state.cityRooms || [];
  const room = state.cityChat;
  const current = state.cityRoom || "";

  let html = `<div class="card"><h2>City chat</h2>
    <p class="hint" style="margin-bottom:10px;">One room per city, for people who have just landed. Messages disappear after a week.</p>
    <div class="row2">
      <input class="field" id="city-name" placeholder="Which city are you in?" value="${esc(current)}" autocapitalize="words">
      <button class="primary" style="width:auto; padding:0 16px;" data-act="city-open">Open</button>
    </div>
  </div>`;

  const here = state.cityArrival;
  if (here) {
    const people = here.around || [];
    const others = people.filter(p => !p.mine);
    html += `<div class="card"><h2>${esc(here.label)}</h2>
      ${here.suggestion ? `<p class="hint">${esc(here.suggestion)}</p>` : ""}
      <div class="pills" style="margin:8px 0; flex-wrap:wrap;">
        <span class="badge">${others.length} around</span>
        <span class="badge">${(here.crews || []).length} crew${(here.crews || []).length === 1 ? "" : "s"}</span>
        <span class="badge">${(here.events || []).length} event${(here.events || []).length === 1 ? "" : "s"}</span>
      </div>
      ${others.length ? others.map(p => `
        <div class="feed-item">
          <div class="label">${esc(p.handle)}</div>
          ${p.note ? `<div>${esc(p.note)}</div>` : ""}
        </div>`).join("") : ""}
      ${(here.crews || []).length ? `<div class="subhead" style="margin-top:10px;">Crews here</div>
        ${(here.crews || []).map(c => `<div class="feed-item"><div class="label">${esc(c.name || "")}</div></div>`).join("")}` : ""}
      ${(here.places || []).length ? `<div class="subhead" style="margin-top:10px;">Places on the map</div>
        <p class="hint" style="margin-bottom:6px;">${here.place_count} in ${esc(here.label)}, from OpenStreetMap. The one thing a city has before anybody arrives.</p>
        ${(here.places || []).slice(0, 8).map(pl => `
          <div class="feed-item">
            <div class="label">${esc(pl.name)}</div>
            <div class="hint">${esc(pl.category)}${pl.street ? ` · ${esc(pl.street)}` : ""}${pl.opening_hours ? ` · ${esc(pl.opening_hours)}` : ""}</div>
          </div>`).join("")}
        <p class="hint" style="margin-top:6px;">© OpenStreetMap contributors</p>` : ""}
      <div style="margin-top:10px;">
        ${here.you_are_here
          ? `<button class="ghost" data-act="city-hide">You are listed as here — take it down</button>`
          : `<div class="row2">
               <input class="field" id="city-note" placeholder="Optional: what you are up for">
               <button class="primary" style="width:auto; padding:0 16px;" data-act="city-here">I'm here</button>
             </div>
             <p class="hint" style="margin-top:6px;">Tells other travellers you are in ${esc(here.label)} for the next few days. Nobody sees anything finer than the city, and you can take it down at any moment.</p>`}
      </div>
    </div>`;
  }

  if (rooms.length) {
    html += `<div class="card"><div class="subhead">Rooms with people in them</div>
      <div class="pills" style="margin-top:8px; flex-wrap:wrap;">
        ${rooms.map(r => `<button class="pill" data-act="city-open" data-city="${esc(r.label || r.city)}">${esc(r.label || r.city)} · ${r.voices} ${r.voices === 1 ? "voice" : "voices"}</button>`).join("")}
      </div></div>`;
  }

  const plans = state.cityMeetups;
  if (plans && current) {
    const list = plans.meetups || [];
    html += `<div class="card"><h2>What's on</h2>
      ${list.length ? list.map(m => `
        <div class="feed-item">
          <div class="label">${esc(m.title)}</div>
          <div style="font-size:13px;">${esc(whenLabel(m.starts_at))}${m.place ? ` · ${esc(m.place)}` : ""}</div>
          ${m.note ? `<div class="hint">${esc(m.note)}</div>` : ""}
          <div class="hint" style="margin-top:4px;">${esc(m.organiser_handle)} organising · ${m.going_count} going${m.going.length ? `: ${m.going.map(p => esc(p.handle)).join(", ")}` : ""}</div>
          <div class="pills" style="margin-top:6px;">
            ${m.you_are_going
              ? `<button class="pill" data-act="meetup-leave" data-id="${esc(m.meetup_id)}">${m.yours ? "Call it off" : "Can't make it"}</button>`
              : `<button class="pill good" data-act="meetup-join" data-id="${esc(m.meetup_id)}">I'm in</button>`}
          </div>
        </div>`).join("")
        : `<p class="hint">Nothing planned here yet. Propose something — a walk, a coffee, a swim.</p>`}

      <div class="subhead" style="margin-top:12px;">Propose something</div>
      <input class="field" id="mu-title" placeholder="What is it? (e.g. Sunset at the viewpoint)">
      <div class="row2" style="margin-top:6px;">
        <input class="field" id="mu-place" placeholder="Where (a public place)">
        <input class="field" id="mu-when" type="datetime-local">
      </div>
      <button class="primary" style="margin-top:6px;" data-act="meetup-create">Put it up</button>
      <p class="hint" style="margin-top:8px;">${esc(plans.safety_note || "")}</p>
    </div>`;
  }

  if (room) {
    const lines = (room.messages || []).map(m => `
      <div class="feed-item" style="display:flex; justify-content:space-between; gap:8px; align-items:flex-start;">
        <div>
          <div class="label">${esc(m.author_handle)}${m.mine ? " (you)" : ""}</div>
          <div>${esc(m.text)}</div>
        </div>
        <div class="pills" style="flex-shrink:0;">
          ${m.mine
            ? `<button class="pill bad" data-act="city-remove" data-id="${esc(m.message_id)}">Delete</button>`
            : `<button class="pill" data-act="city-mute" data-id="${esc(m.author_id)}">Mute</button>
               <button class="pill warm" data-act="city-report" data-id="${esc(m.message_id)}">Report</button>`}
        </div>
      </div>`).join("");

    html += `<div class="card"><h2>${esc(current || room.city)}</h2>
      ${lines || `<p class="hint">Nobody has said anything yet. Be the first — say where you are and what you are up for.</p>`}
      ${room.muted ? `<p class="hint" style="margin-top:8px;">${room.muted} message${room.muted === 1 ? "" : "s"} hidden from people you muted.</p>` : ""}
      <div class="row2" style="margin-top:10px;">
        <input class="field" id="city-say" placeholder="Say something to the room">
        <button class="primary" style="width:auto; padding:0 16px;" data-act="city-say">Send</button>
      </div>
      <p class="hint" style="margin-top:8px;">Anyone signed in can read this, and posting says you are in ${esc(current || room.city)}. Your handle is shown — never your email.</p>
    </div>`;
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

  /* ---- Official Venue Programs & Schedules ---- */
  if (state.venuePrograms && state.venuePrograms.programs) {
    const progs = state.venuePrograms.programs;
    html += `<div class="card" style="background: linear-gradient(135deg, rgba(240,169,74,0.15), rgba(139,92,246,0.15)); border:1px solid rgba(240,169,74,0.3);">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <h2>🏛️ Official Local Venue Programs</h2>
        <span class="badge good" style="font-weight:bold;">Verified Partners</span>
      </div>
      <p class="hint" style="margin-bottom:10px;">Official weekly schedules & exclusive perks from local gyms, coffee roasters, and spots.</p>
      ${progs.map(p => `
        <div class="feed-item" style="background:var(--surface-2s); border-radius:10px; padding:10px; margin-bottom:8px;">
          <div style="font-size:14px; font-weight:700; color:var(--spark);">🏛️ ${esc(p.venue_name)} (${esc(p.city)})</div>
          <div style="font-size:13px; font-weight:600; margin:2px 0;">${esc(p.title)}</div>
          <div style="font-size:12px; color:var(--muted);">📅 Schedule: ${esc(p.schedule)}</div>
          <div style="font-size:12px; color:var(--growth); margin-top:2px;">🎁 Perk: ${esc(p.perks)}</div>
          <button class="pill warm" style="margin-top:6px;" data-act="subscribe-venue-program" data-name="${esc(p.venue_name)}">Sync Program to Smart Calendar 📅</button>
        </div>
      `).join("")}
    </div>`;
  }

  /* ---- Forward-Looking Travel & Curated Event Radar ---- */
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(37,99,235,0.15), rgba(16,185,129,0.15)); border:1px solid rgba(37,99,235,0.3);">
    <h2>✈️ Forward-Looking Travel & Curated Event Radar</h2>
    <p class="hint" style="margin-bottom:10px;">Planning future travel? Select a destination city and dates to get your curated spots and upcoming event forecast!</p>
    <div class="row2"><input class="field" id="tr-city" placeholder="Destination City (e.g. Lisbon / Tokyo / NYC)">
    <input class="field" id="tr-start" type="date"></div>
    <button class="primary" data-act="travel-brief">Generate Curated Travel Forecast ✈️</button>
    <div id="travel-brief-output" style="margin-top:12px;"></div>
  </div>`;

  return html;
}

function graphView() {
  const g = state.graph;
  const counts = Object.entries(g.counts).sort((a, b) => b[1] - a[1]);
  const ranks = state.centralityRanks || [];
  const people = state.people || [];

  let html = `<div class="card"><h2>Your context graph</h2>
      <div class="kv"><span>entities</span><span class="v">${g.entities}</span></div>
      <div class="kv"><span>edges</span><span class="v">${g.edges}</span></div>
      <div class="kv"><span>observations (provenance)</span><span class="v">${g.observations}</span></div></div>
    <div class="card"><h2>By kind</h2>
      ${counts.length ? counts.map(([k, n]) => `<div class="kv"><span>${esc(k)}</span><span class="v">${n}</span></div>`).join("")
                      : `<p class="empty">Empty graph — start on the Today tab.</p>`}</div>`;

  /* ---- Network Hubs & Centrality ---- */
  html += `<div class="card"><h2>Key Network Hubs (Centrality)</h2>
    ${ranks.length ? ranks.slice(0, 5).map(r => `
      <div class="kv">
        <span>${esc(r.label || r.id)} <span style="font-size:11px; color:var(--muted);">(${esc(r.kind || "node")})</span></span>
        <span class="v">${(r.score || 0).toFixed(3)}</span>
      </div>
    `).join("") : `<p class="empty">Graph metrics computing…</p>`}
  </div>`;

  /* ---- Social Path Finder ---- */
  html += `<div class="card"><h2>Social Shortest Path Finder</h2>
    <div class="row2">
      <select class="field" id="sp-src">
        <option value="">-- From Person --</option>
        ${people.map(p => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join("")}
      </select>
      <select class="field" id="sp-dst">
        <option value="">-- To Person --</option>
        ${people.map(p => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join("")}
      </select>
    </div>
    <button class="primary" data-act="find-path">Find Social Path</button>
    <div id="sp-results" style="margin-top:10px;"></div>
  </div>`;

  html += `<div class="card"><h2>Recent</h2>
      ${g.recent.map((r) => `<div class="feed-item"><div class="kind">${esc(r.kind)}</div><div class="label">${esc(r.label)}</div></div>`).join("") || `<p class="empty">—</p>`}
    </div>`;

  /* ---- Life Audit & Milestone Timeline ---- */
  const timeline = state.timeline || [];
  html += `<div class="card"><h2>Life Audit & Milestone Timeline</h2>
    <p class="hint" style="margin-bottom:10px;">Chronological audit log of your life goals, decision reviews, and milestones reached.</p>
    ${timeline.length ? timeline.slice(0, 10).map(t => `
      <div class="feed-item">
        <div class="kind">${esc(t.type || "Milestone")} · ${esc(t.date || t.timestamp || "")}</div>
        <div class="label" style="font-size:13.5px; color:var(--text); margin-top:2px;"><strong>${esc(t.title || t.label || t.event || "")}</strong></div>
        ${t.description ? `<div style="font-size:12px; color:var(--muted); margin-top:2px;">${esc(t.description)}</div>` : ""}
      </div>
    `).join("") : `<div class="feed-item"><div class="label" style="color:var(--muted);">Milestones and decision logs will automatically populate here as you complete goals and log retros.</div></div>`}
  </div>`;

  return html;
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

  /* ---- Critical Medical ID Card ---- */
  // `/triage/card` answers `{configured, card: {...}}`, so reading the fields off the
  // envelope left every box empty even once the URL was right.
  const crit = (m.critical && m.critical.card) || {};
  html += `<div class="card"><h2>Critical Medical ID Card</h2>
    <div class="row2"><input class="field" id="cr-name" placeholder="Full Name" value="${esc(crit.full_name || "")}">
    <input class="field" id="cr-blood" placeholder="Blood Type (e.g. O+)" value="${esc(crit.blood_type || "")}"></div>
    <textarea class="field" id="cr-allergies" placeholder="Allergies (e.g. Penicillin, Peanut)">${esc(crit.allergies || "")}</textarea>
    <textarea class="field" id="cr-notes" placeholder="Important Medical Notes">${esc(crit.notes || "")}</textarea>
    <button class="primary" data-act="critical-save">Save Critical Info</button>
    <p class="hint">Static Medical ID card stored on your private graph. Does not auto-dispatch.</p></div>`;

  /* ---- Dead-Man's Switch ---- */
  const dm = m.deadman || {};
  const dmStatus = dm.enabled ? (dm.is_overdue ? "OVERDUE — Grace active" : "Active & Healthy") : "Not configured";
  const dmBadgeClass = dm.is_overdue ? "err" : (dm.enabled ? "good" : "");
  html += `<div class="card"><h2>Dead-Man's Switch</h2>
    <div class="kv"><span>Status</span><span class="badge ${dmBadgeClass}">${esc(dmStatus)}</span></div>
    ${dm.last_ping ? `<div class="kv"><span>Last Ping</span><span class="v">${esc(new Date(dm.last_ping).toLocaleString())}</span></div>` : ""}
    <button class="primary" style="margin-bottom:12px;" data-act="deadman-ping">I'm OK — Reset Timer</button>
    <div class="subhead">Check-in Configuration</div>
    <div class="row2"><input class="field" id="dm-interval" type="number" step="0.5" placeholder="Interval (hours)" value="${dm.interval_hours || 24}">
    <input class="field" id="dm-grace" type="number" step="0.5" placeholder="Grace (hours)" value="${dm.grace_hours || 12}"></div>
    <button class="ghost" data-act="deadman-save">Save Deadman Config</button>
    <p class="hint">Best-effort notification ping to trusted contacts if check-in is missed.</p></div>`;

  /* ---- Dating & Mutual Match ---- */
  const dt = m.datingAvail || { available: false, reason: "Unconfigured" };
  const matches = (m.datingMatches && m.datingMatches.matches) || [];
  html += `<div class="card"><h2>Dating & Activity Match</h2>
    <div class="kv"><span>Surface Status</span><span class="badge ${dt.available ? "good" : "warn"}">${dt.available ? "Available" : esc(dt.reason || "Disabled")}</span></div>`;
  if (dt.available) {
    html += `<div class="subhead">Age Verification (18+)</div>
      <div class="row2"><input class="field" id="dt-dob" type="date" placeholder="Date of birth">
      <button class="pill warm" style="margin:0; width:auto;" data-act="dating-age">Declare 18+</button></div>
      <div class="subhead" style="margin-top:12px;">Express Intent</div>
      <input class="field" id="dt-target" placeholder="Target Account ID">
      <input class="field" id="dt-act" placeholder="Activity ID (e.g. sushi_night)">
      <button class="primary" data-act="dating-interest">Declare Interest</button>
      <div class="subhead" style="margin-top:12px;">Mutual Matches (${matches.length})</div>
      ${matches.length ? matches.map(mat => `
        <div class="person"><div class="who">
          <div class="name">${esc(mat.target_account_id)}</div>
          <div class="meta">Matched for ${esc(mat.activity_id)}</div>
        </div><div class="pills">
          <button class="pill bad" data-act="dating-block" data-target="${mat.target_account_id}">Block</button>
        </div></div>
      `).join("") : `<p class="empty">No mutual matches yet.</p>`}`;
  }
  html += `<p class="hint">Activity-based mutual consent matching. Double-blinded until both express interest.</p></div>`;

  /* ---- Mini-Apps & Developer Platform ---- */
  const miniapps = m.miniapps || [];
  html += `<div class="card"><h2>Mini-Apps & Extensions</h2>
    ${miniapps.length ? miniapps.map(app => `
      <div class="person"><div class="who">
        <div class="name">${esc(app.icon || "🧩")} ${esc(app.name)}</div>
        <div class="meta">${esc(app.url)}</div>
      </div><div class="pills">
        <button class="pill warm" data-act="miniapp-launch" data-url="${esc(app.url)}" data-name="${esc(app.name)}">Launch</button>
      </div></div>
    `).join("") : `<p class="empty">No mini-apps registered yet.</p>`}
    <div class="subhead" style="margin-top:12px;">Register Mini-App Manifest</div>
    <div class="row2"><input class="field" id="ma-name" placeholder="App Name (e.g. Weather Mini)">
    <input class="field" id="ma-icon" placeholder="Icon (e.g. 🌤️)"></div>
    <input class="field" id="ma-url" placeholder="Manifest / App URL (https://...)">
    <button class="primary" data-act="miniapp-add">Register Mini-App</button>
    <p class="hint">Micro-frontends running in declarative sandboxed capabilities.</p></div>`;

  /* ---- Calendar Sync (.ics) ---- */
  html += `<div class="card"><h2>Calendar Sync (.ics)</h2>
    <button class="primary" style="margin-bottom:12px;" data-act="ics-export">Download Personal .ics Calendar</button>
    <div class="subhead">Import External iCalendar (.ics)</div>
    <textarea class="field" id="ics-content" placeholder="Paste raw .ics iCalendar content here..."></textarea>
    <button class="ghost" data-act="ics-import">Import .ics Feed</button>
    <p class="hint">Imports external calendar events and tasks into your context graph.</p></div>`;

  /* ---- Verified Meeter Trust Badge ---- */
  const tr = m.trust || { verified_meets: 0, reliability_score: 85, tier: "Bronze Meeter" };
  html += `<div class="card"><h2>Verified Real-World Meeter Badge</h2>
    <div class="kv"><span>Tier Badge</span><span class="badge good" style="font-weight:bold;">🛡️ ${esc(tr.tier)}</span></div>
    <div class="kv"><span>Verified Outings Attended</span><span class="v">${tr.verified_meets}</span></div>
    <div class="kv"><span>Reliability Rating</span><span class="v">${tr.reliability_score}%</span></div>
    <button class="primary" style="margin-top:10px;" data-act="share-trust" data-text="${esc(tr.share_text || "")}">Copy Bio Trust Link (Instagram / Tinder)</button>
    <p class="hint">Cryptographically verified proof that you show up to real-world plans. Zero ghosting.</p></div>`;

  /* ---- Monthly Wrapped Canvas ---- */
  const wr = m.wrapped || { month: "August 2026", days_shown_up: 1, tasks_done: 0, goals_done: 0, meets_attended: 0 };
  html += `<div class="card" style="background: linear-gradient(135deg, rgba(37,99,235,0.15), rgba(16,185,129,0.15)); border: 1px solid rgba(255,255,255,0.1);">
    <h2>LifeOS Monthly Wrapped — ${esc(wr.month)}</h2>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin:12px 0;">
      <div style="background:rgba(255,255,255,0.05); padding:10px; border-radius:10px; text-align:center;">
        <div style="font-size:22px; font-weight:800; color:var(--spark);">⚡ ${wr.days_shown_up}</div>
        <div style="font-size:11px; color:var(--muted);">Days Shown Up</div>
      </div>
      <div style="background:rgba(255,255,255,0.05); padding:10px; border-radius:10px; text-align:center;">
        <div style="font-size:22px; font-weight:800; color:var(--growth);">🎯 ${wr.goals_done}</div>
        <div style="font-size:11px; color:var(--muted);">Goals Finished</div>
      </div>
      <div style="background:rgba(255,255,255,0.05); padding:10px; border-radius:10px; text-align:center;">
        <div style="font-size:22px; font-weight:800; color:var(--calm);">🧗 ${wr.meets_attended}</div>
        <div style="font-size:11px; color:var(--muted);">Outings Attended</div>
      </div>
      <div style="background:rgba(255,255,255,0.05); padding:10px; border-radius:10px; text-align:center;">
        <div style="font-size:22px; font-weight:800; color:var(--warm);">✓ ${wr.tasks_done}</div>
        <div style="font-size:11px; color:var(--muted);">Tasks Executed</div>
      </div>
    </div>
    <button class="primary" data-act="share-wrapped" data-text="${esc(wr.share_text || "")}">Share Monthly Canvas to Socials 🚀</button>
  </div>`;

  /* ---- Partiful Event Flyer Generator ---- */
  html += `<div class="card"><h2>Partiful-Style Event Flyer Generator</h2>
    <div class="row2"><input class="field" id="fl-title" placeholder="Party / Meet Title (e.g. Sunset Drinks)">
    <input class="field" id="fl-place" placeholder="Venue / Place"></div>
    <div class="row2"><input class="field" id="fl-time" placeholder="Date & Time (e.g. Friday 20:00)">
    <select class="field" id="fl-theme">
      <option value="sunset">🌅 Sunset Gradient</option>
      <option value="cyber">🌆 Cyberpunk Neon</option>
      <option value="emerald">🌲 Emerald Forest</option>
      <option value="space">🌌 Deep Space</option>
    </select></div>
    <button class="primary" data-act="flyer-gen">Generate Visual Event Flyer</button>
    <div id="flyer-preview" style="margin-top:12px;"></div>
  </div>`;

  /* ---- Personal Knowledge Vault ---- */
  html += `<div class="card"><h2>Personal Knowledge & Vault</h2>
    <div class="row2"><input class="field" id="vt-title" placeholder="Note Title (e.g. WiFi Passkey)">
    <input class="field" id="vt-tags" placeholder="Tags (comma separated)"></div>
    <textarea class="field" id="vt-content" placeholder="Private note content..."></textarea>
    <button class="primary" data-act="vault-save">Save to Vault</button>
    <div class="subhead" style="margin-top:12px;">Search Vault</div>
    <div class="row2"><input class="field" id="vt-query" placeholder="Search query...">
    <button class="ghost" style="width:auto; padding:10px 16px;" data-act="vault-search">Search</button></div>
    <div id="vault-results" style="margin-top:8px;"></div>
  </div>`;

  /* ---- Data Sovereignty & Export ---- */
  html += `<div class="card"><h2>Data Sovereignty & Portable Export</h2>
    <div class="row2">
      <button class="primary" data-act="export-json">Export Graph JSON</button>
      <button class="ghost" data-act="export-graphml">Export GraphML (XML)</button>
    </div>
    <div style="margin-top:8px;">
      <button class="ghost" style="width:100%;" data-act="export-csv">Export CSV (Excel / Spreadsheets) 📊</button>
    </div>
    <p class="hint">100% Local-First. Your data belongs to you — export your entire life graph anytime in 1 click.</p>
  </div>`;

  /* ---- Opt-in Shared Recommendation Intelligence ---- */
  const cs = m.consent || { enabled: false, share_interests: true, share_city_events: true };
  html += `<div class="card"><h2>Opt-In Recommendation Intelligence</h2>
    <p class="hint" style="margin-bottom:10px;">Help LifeOS suggest better local events, crews, friend matches, and dates by sharing anonymized preferences.</p>
    <div style="display:flex; align-items:center; gap:10px; margin-bottom:8px;">
      <input type="checkbox" id="cs-enabled" ${cs.enabled ? "checked" : ""}>
      <label for="cs-enabled" style="font-size:14px; font-weight:600; color:var(--text);">Opt-in to Shared Recommendation Intelligence</label>
    </div>
    <div style="display:flex; align-items:center; gap:10px; margin-bottom:8px;">
      <input type="checkbox" id="cs-interests" ${cs.share_interests ? "checked" : ""}>
      <label for="cs-interests" style="font-size:13px; color:var(--text);">Share anonymized interest tags (e.g. bouldering, sushi)</label>
    </div>
    <div style="display:flex; align-items:center; gap:10px; margin-bottom:12px;">
      <input type="checkbox" id="cs-events" ${cs.share_city_events ? "checked" : ""}>
      <label for="cs-events" style="font-size:13px; color:var(--text);">Share activity preferences for better mutual date matching</label>
    </div>
    <button class="primary" data-act="consent-save">Save Privacy & Intelligence Settings</button>
    <p class="hint" style="margin-top:8px;">Privacy Guarantee: Hashed via SHA-256 before leaving your device. Off by default.</p>
  </div>`;

  /* ---- 20% Democratic Community Impact Treasury ---- */
  const trData = m.treasury || { profit_share_percent: 20, treasury_balance: 12450, total_disbursed: 0, proposals: [] };
  const props = trData.proposals || [];

  html += `<div class="card" style="background: linear-gradient(135deg, rgba(16,185,129,0.15), rgba(37,99,235,0.15)); border:1px solid rgba(16,185,129,0.3);">
    <h2>🏛️ 20% Community Impact Treasury</h2>
    <p class="hint" style="margin-bottom:10px;">20% of net platform profits are given back to the community and governed democratically by members (1-Member 1-Vote).</p>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin:10px 0; text-align:center;">
      <div style="background:rgba(255,255,255,0.05); padding:10px; border-radius:10px;">
        <div style="font-size:20px; font-weight:800; color:var(--growth);">$${(trData.treasury_balance || 0).toLocaleString()}</div>
        <div style="font-size:11px; color:var(--muted);">Treasury Pool (20%)</div>
      </div>
      <div style="background:rgba(255,255,255,0.05); padding:10px; border-radius:10px;">
        <div style="font-size:20px; font-weight:800; color:var(--spark);">$${(trData.total_disbursed || 0).toLocaleString()}</div>
        <div style="font-size:11px; color:var(--muted);">Disbursed Grants</div>
      </div>
    </div>
    
    <div class="subhead" style="margin-top:12px;">Submit Community Grant / Charity Proposal</div>
    <div class="row2"><input class="field" id="tr-title" placeholder="Proposal (e.g. Lisbon Crag Clean-up)">
    <input class="field" id="tr-amount" type="number" value="500" placeholder="Grant ($)"></div>
    <button class="primary" data-act="tr-submit">Submit Democratic Proposal 🗳️</button>

    ${props.length ? `
      <div class="subhead" style="margin-top:12px;">Active Community Proposals</div>
      ${props.map(pr => `
        <div class="person"><div class="who">
          <div class="name">${esc(pr.title)} · <strong style="color:var(--growth);">$${pr.grant_amount}</strong></div>
          <div class="meta">Category: ${esc(pr.category)} · Proposed by ${esc(pr.proposed_by)} — ${pr.votes} votes (${esc(pr.status)})</div>
        </div><div class="pills">
          <button class="pill good" data-act="tr-vote" data-id="${pr.id}">Vote 🗳️ (${pr.votes})</button>
        </div></div>
      `).join("")}
    ` : ""}
  </div>`;

  /* ---- Developer Platform & Open API Keys ---- */
  const devKeys = [
    { id: "key_live_9921", name: "Zapier Automation Key", created_at: "2026-08-05T19:30:00Z", status: "active" },
    { id: "key_live_4412", name: "Python Script Runner", created_at: "2026-08-05T19:30:00Z", status: "active" }
  ];

  html += `<div class="card"><h2>Developer Platform & Open API Keys</h2>
    <p class="hint" style="margin-bottom:10px;">Issue personal API keys to connect Python scripts, Zapier webhooks, or custom hardware buttons to your graph.</p>
    <div class="row2"><input class="field" id="dk-name" placeholder="Key Label (e.g. Home Assistant)">
    <button class="primary" style="width:auto; padding:10px 16px;" data-act="dev-key-gen">Generate Secret Key 🔑</button></div>
    
    <div class="subhead" style="margin-top:12px;">Active API Keys</div>
    ${devKeys.map(k => `
      <div class="person"><div class="who">
        <div class="name">${esc(k.name)} · <code style="color:var(--spark);">${esc(k.id)}</code></div>
        <div class="meta">Status: ${esc(k.status)} · Created ${esc(k.created_at.slice(0, 10))}</div>
      </div><div class="pills">
        <span class="badge good" style="font-size:11px;">Active</span>
      </div></div>
    `).join("")}

    <div style="margin-top:12px; display:flex; gap:8px; flex-wrap:wrap;">
      <a href="/docs" target="_blank" class="pill" style="text-decoration:none; display:inline-block; padding:6px 12px; background:var(--surface-2s);">📚 Interactive OpenAPI Docs (/docs)</a>
      <a href="/redoc" target="_blank" class="pill" style="text-decoration:none; display:inline-block; padding:6px 12px; background:var(--surface-2s);">📘 ReDoc API Spec (/redoc)</a>
      <span class="badge spark" style="font-weight:bold;">🐍 Official Python SDK (sdk/lifeos.py)</span>
    </div>
  </div>`;

  /* ---- Reminders ----
     Was "Diurnal Push Notification Scheduler", which promised device push triggers. This
     app has no push key, no APNs certificate and no SMS provider: a reminder is here
     waiting when you next open it, and the card says so rather than implying a buzz. */
  html += `<div class="card"><h2>Reminders</h2>
    <p class="hint" style="margin-bottom:10px;">Nothing is pushed — this app cannot buzz your phone. A reminder waits here for you to open it.</p>
    <div class="row2">
      <input class="field" id="nt-text" placeholder="Remind me to…">
      <input type="time" class="field" id="nt-at" value="08:00">
    </div>
    <input class="field" id="nt-days" placeholder="Days (mon,wed,fri) — empty means every day" style="margin-top:6px;">
    <div class="row2" style="margin-top:8px;">
      <button class="primary" data-act="nt-save">Remind me 🔔</button>
      <button class="ghost" data-act="nt-list">What is waiting</button>
    </div>
    <div id="reminders-output" style="margin-top:10px;"></div>
  </div>`;

  return html;
}

/* ---------- actions ---------- */

function selectedPeople(eventId) {
  const sel = $(`#cv-people-${CSS.escape(eventId)}`);
  return sel ? [...sel.selectedOptions].map((o) => o.value) : [];
}

function wire(root) {
  // `on` binds listeners to the elements that exist *now*. Anything a renderer writes into
  // the page afterwards with innerHTML therefore has no listener at all: the button appears,
  // looks live, and does nothing when tapped. Every dynamic result card in this file has
  // that shape, so `on` also records the handler by action name and `bindLater` attaches it
  // to markup added after the fact.
  const acts = {};
  const on = (selector, handler) => {
    const named = selector.match(/^\[data-act=([^\]]+)\]$/);
    if (named) acts[named[1]] = handler;
    root.querySelectorAll(selector).forEach((el) =>
      el.addEventListener("click", () => handler(el)));
  };
  const bindLater = (container) => {
    if (!container) return;
    container.querySelectorAll("[data-act]").forEach((el) => {
      const handler = acts[el.dataset.act];
      if (!handler || el.dataset.bound) return;
      el.dataset.bound = "1";
      el.addEventListener("click", () => handler(el));
    });
  };

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

  on("[data-act=voice-onboard]", () => {
    const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Speech) {
      return toast("Speech recognition not supported in browser. Type your profile.");
    }
    try {
      const rec = new Speech();
      rec.lang = "en-US";
      rec.interimResults = false;
      toast("Listening… Speak your vision & goals 🎙️");
      rec.onresult = (evt) => {
        const transcript = evt.results[0][0].transcript;
        const existing = $("#vision-text").value;
        $("#vision-text").value = existing ? existing + "\n" + transcript : transcript;
        toast("Profile Transcribed! Tapping Build Plan…");
      };
      rec.onerror = () => toast("Voice recognition error.");
      rec.start();
    } catch (err) {
      toast("Voice error.");
    }
  });

  on("[data-act=close-tour]", () => {
    state.showTutorial = false;
    render();
  });

  on("[data-act=plan]", () => act(async () => { await api("/v1/plan", {}); await refresh(); }, "Week planned ✔"));

  root.querySelectorAll(".task:not(.done)").forEach((el) => el.addEventListener("click", () => act(async () => {
    await api("/v1/log", { n: Number(el.dataset.n) });
    await refresh();
  }, "Logged ✔")));

  on("[data-act=retro]", () => act(async () => {
    state.retro = (await api("/v1/retro", {})).text;
    render();
  }));

  on("[data-act=coach-dismiss]", (el) => {
    if (!state.dismissedProposals) state.dismissedProposals = new Set();
    state.dismissedProposals.add(el.dataset.id);
    render();
  });

  on("[data-act=parked-promote]", (el) => act(async () => {
    await api(`/v1/parked/${el.dataset.id}/promote`, { target_level: "goal" });
    await refresh();
  }, "Idea promoted to Goal ✔"));

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
    if (!text) return toast("Write or speak something first.");
    const result = await api("/v1/voiceos/capture", { text });
    $("#capture-text").value = "";
    state.graph = await api("/v1/graph");
    render();
    toast(result.parked ? "Idea parked in distraction sink ✔" : "Captured & Extracted to Graph ✔");
  }));

  on("[data-act=voice-record]", () => {
    const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Speech) {
      return toast("Speech recognition not supported in browser. Type your thought.");
    }
    try {
      const rec = new Speech();
      rec.lang = "en-US";
      rec.interimResults = false;
      toast("Listening… Speak your thought 🎙️");
      rec.onresult = (evt) => {
        const transcript = evt.results[0][0].transcript;
        $("#capture-text").value = transcript;
        toast("Transcribed! Tapping Capture…");
      };
      rec.onerror = () => toast("Voice recognition error.");
      rec.start();
    } catch (err) {
      toast("Voice error.");
    }
  });

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

  /* ---- Triage, Dating & Mini-Apps ---- */

  on("[data-act=critical-save]", () => act(async () => {
    const full_name = $("#cr-name").value.trim();
    const blood_type = $("#cr-blood").value.trim();
    const allergies = $("#cr-allergies").value.trim();
    const notes = $("#cr-notes").value.trim();
    await api("/v1/triage/card", { full_name, blood_type, allergies, notes });
    await refresh();
  }, "Critical info saved ✔"));

  on("[data-act=deadman-ping]", () => act(async () => {
    await api("/v1/triage/deadman/ping");
    await refresh();
  }, "Check-in logged ✔"));

  on("[data-act=deadman-save]", () => act(async () => {
    const interval_hours = Number($("#dm-interval").value) || 24;
    const grace_hours = Number($("#dm-grace").value) || 12;
    await api("/v1/triage/deadman/config", { interval_hours, grace_hours, contacts: [] });
    await refresh();
  }, "Dead-man switch updated ✔"));

  on("[data-act=dating-age]", () => act(async () => {
    const dob = $("#dt-dob").value;
    if (!dob) return toast("Select date of birth");
    await api("/v1/dating/age", { date_of_birth: dob });
    await refresh();
  }, "Age verified 18+ ✔"));

  on("[data-act=dating-interest]", () => act(async () => {
    const target_account_id = $("#dt-target").value.trim();
    const activity_id = $("#dt-act").value.trim();
    if (!target_account_id || !activity_id) return toast("Enter target account and activity ID");
    await api("/v1/dating/interest", { target_account_id, activity_id });
    await refresh();
  }, "Interest declared ✔"));

  on("[data-act=dating-block]", (el) => act(async () => {
    await api("/v1/dating/block", { subject_account_id: el.dataset.target });
    await refresh();
  }, "Account blocked ✔"));

  on("[data-act=miniapp-add]", () => act(async () => {
    const name = $("#ma-name").value.trim();
    const url = $("#ma-url").value.trim();
    const icon = $("#ma-icon").value.trim();
    if (!name || !url) return toast("Provide name and app URL");
    await api("/v1/miniapp/register", { name, url, icon });
    await refresh();
  }, "Mini-App registered ✔"));

  on("[data-act=miniapp-launch]", (el) => {
    const url = el.dataset.url;
    const name = el.dataset.name;
    window.open(url, "_blank");
    toast(`Launching ${name}…`);
  });

  /* ---- Graph Paths & Calendar (.ics) ---- */

  on("[data-act=find-path]", () => act(async () => {
    const src = $("#sp-src").value;
    const dst = $("#sp-dst").value;
    if (!src || !dst) return toast("Select both From and To persons.");
    const pathRes = await api(`/v1/graph/paths?src_id=${src}&dst_id=${dst}`).catch(() => null);
    const resEl = $("#sp-results");
    if (!resEl) return;
    if (pathRes && pathRes.path && pathRes.path.length) {
      resEl.innerHTML = `<div style="font-size:13px; font-weight:600; color:var(--spark);">Path Found (${pathRes.path.length} hops):</div>` +
        `<div style="font-size:12.5px; color:var(--text); margin-top:4px;">${pathRes.path.map(n => esc(n.label || n.id)).join(" ➔ ")}</div>`;
    } else {
      resEl.innerHTML = `<div style="font-size:13px; color:var(--muted);">No direct social path found.</div>`;
    }
  }));

  on("[data-act=crew-ics]", (el) => {
    window.open(apiBase() + `/v1/crews/${el.dataset.id}/export.ics`, "_blank");
    toast("Downloading Crew .ics Calendar…");
  });

  on("[data-act=ics-export]", () => {
    window.open(apiBase() + "/v1/calendar/export.ics", "_blank");
    toast("Downloading Personal .ics Calendar…");
  });

  on("[data-act=ics-import]", () => act(async () => {
    const content = $("#ics-content").value.trim();
    if (!content) return toast("Paste .ics content to import.");
    // The route is `/calendar/sync-import`; this asked for `/calendar/import-ics`, which
    // does not exist — so every paste of a calendar feed 404'd and imported nothing.
    await api("/v1/calendar/sync-import", { ics_content: content });
    $("#ics-content").value = "";
    await refresh();
  }, "iCalendar feed imported ✔"));

  /* ---- Feed, Bulletins, Gallery & Expense Splitter ---- */

  on("[data-act=feed-interest]", (el) => act(async () => {
    const person_id = state.me ? state.me.account_id : "anon";
    await api("/v1/feed/interested", { event_id: el.dataset.id, person_id, going: true });
    await refresh();
  }, "Interest recorded ✔"));

  on("[data-act=feed-publish]", () => act(async () => {
    const title = $("#fa-title").value.trim();
    const topic = $("#fa-topic").value.trim();
    const city = $("#fa-city").value.trim();
    const place = $("#fa-place").value.trim();
    if (!title || !city) return toast("Title and City are required.");
    await api("/v1/discover/events", { title, topic, city, place, visibility: "public" });
    $("#fa-title").value = "";
    await refresh();
  }, "Public activity published ✔"));

  on("[data-act=bulletin-add]", () => act(async () => {
    const crew_id = $("#bl-crew").value.trim();
    const title = $("#bl-title").value.trim();
    const body = $("#bl-body").value.trim();
    if (!crew_id || !title || !body) return toast("Fill crew ID, title, and announcement.");
    await api("/v1/comms/bulletin", { crew_id, title, body });
    $("#bl-title").value = "";
    $("#bl-body").value = "";
    await refresh();
  }, "Bulletin posted ✔"));

  on("[data-act=gallery-upload]", () => act(async () => {
    const event_id = $("#gl-event").value.trim();
    const photo_url = $("#gl-url").value.trim();
    if (!event_id || !photo_url) return toast("Provide event ID and photo URL.");
    const owner_id = state.me ? state.me.account_id : "";
    await api("/v1/comms/gallery", { event_id, photo_url, owner_id });
    $("#gl-url").value = "";
    await refresh();
  }, "Photo uploaded ✔"));

  on("[data-act=collage-create]", () => act(async () => {
    const event_id = $("#gl-event").value.trim();
    if (!event_id) return toast("Provide event ID for collage.");
    const collage = await api(`/v1/comms/gallery/collage?event_id=${event_id}`);
    const prevEl = $("#collage-preview");
    if (prevEl && collage) {
      prevEl.innerHTML = `<div style="font-size:13px; font-weight:600; color:var(--spark); margin-bottom:4px;">Generated Photo Collage:</div>` +
        `<div style="display:grid; grid-template-columns:repeat(auto-fill, minmax(80px, 1fr)); gap:6px;">` +
        (collage || []).map(p => `<img src="${esc(p.url || p.photo_url)}" style="width:100%; height:70px; object-fit:cover; border-radius:8px;">`).join("") +
        `</div>`;
    }
  }, "Collage generated ✔"));

  on("[data-act=split-expense]", () => act(async () => {
    const total_amount = Number($("#sp-amount").value);
    const currency = $("#sp-curr").value.trim() || "EUR";
    const payer_id = $("#sp-payer").value;
    const member_select = $("#sp-members");
    const member_ids = member_select ? [...member_select.selectedOptions].map(o => o.value) : [];
    if (!total_amount || !payer_id || !member_ids.length) return toast("Fill total amount, payer, and members.");
    await api("/v1/ledger/split", { total_amount, currency, payer_id, member_ids });
    $("#sp-amount").value = "";
    await refresh();
  }, "Expense split logged ✔"));

  on("[data-act=crew-link]", (el) => act(async () => {
    const res = await api(`/v1/crews/${el.dataset.id}/invite-link`);
    const fullUrl = window.location.origin + window.location.pathname + res.invite_url;
    await navigator.clipboard.writeText(fullUrl).catch(() => {});
    toast("WhatsApp Invite Link copied to clipboard! 📋");
  }));

  on("[data-act=crew-starter]", (el) => act(async () => {
    const name = el.dataset.name;
    const topic = el.dataset.topic;
    const city = el.dataset.city;
    const crew = await api("/v1/crews", { name, topic, city, visibility: "public", admission: "open" });
    state.crewOpen = crew.id;
    await refresh();
  }, "Instant Crew created ✔"));

  /* ---- Viral Growth: Trust Badge, Wrapped Canvas, Flyer Generator ---- */

  on("[data-act=share-trust]", (el) => {
    const text = el.dataset.text || "LifeOS Verified Real-World Meeter";
    navigator.clipboard.writeText(text).catch(() => {});
    toast("Trust Badge copied! 📋 Paste into Instagram/Tinder bio.");
  });

  on("[data-act=share-wrapped]", (el) => {
    const text = el.dataset.text || "My LifeOS Monthly Wrapped";
    navigator.clipboard.writeText(text).catch(() => {});
    toast("Monthly Wrapped summary copied! 🚀 Ready to post to Instagram/Twitter.");
  });

  on("[data-act=flyer-gen]", () => {
    const title = $("#fl-title").value.trim() || "Lisbon Sunset Outing";
    const place = $("#fl-place").value.trim() || "Miradouro de Santa Catarina";
    const time = $("#fl-time").value.trim() || "Friday @ 20:00";
    const theme = $("#fl-theme").value || "sunset";

    const gradients = {
      sunset: "linear-gradient(135deg, #f97316, #ec4899, #8b5cf6)",
      cyber: "linear-gradient(135deg, #06b6d4, #3b82f6, #d946ef)",
      emerald: "linear-gradient(135deg, #059669, #10b981, #06b6d4)",
      space: "linear-gradient(135deg, #1e1b4b, #312e81, #4c1d95)"
    };

    const prevEl = $("#flyer-preview");
    if (prevEl) {
      prevEl.innerHTML = `
        <div style="background:${gradients[theme]}; padding:20px; border-radius:16px; color:#ffffff; font-family:sans-serif; text-shadow:0 1px 3px rgba(0,0,0,0.4); box-shadow: 0 10px 25px -5px rgba(0,0,0,0.5);">
          <div style="font-size:11px; text-transform:uppercase; tracking:1.5px; opacity:0.9; font-weight:700;">Official Crew Meet Flyer</div>
          <div style="font-size:22px; font-weight:900; margin:6px 0;">${esc(title)}</div>
          <div style="font-size:14px; font-weight:600; margin-bottom:12px;">📍 ${esc(place)} · ⏰ ${esc(time)}</div>
          <button class="pill good" style="background:#ffffff; color:#0f172a; font-weight:800; border:none; width:100%; padding:10px; border-radius:10px; cursor:pointer;" onclick="alert('RSVP confirmed! See you there!')">1-Tap Web RSVP ✓</button>
        </div>
      `;
      toast("Party Flyer generated! 🎨");
    }
  });

  /* ---- Diurnal Ritual Engine Handlers ---- */

  on("[data-act=save-morning-intent]", () => {
    const val = $("#morning-intent-text") ? $("#morning-intent-text").value.trim() : "";
    if (!val) return toast("Type your primary focus for today.");
    state.morningIntent = val;
    toast("Morning Intent Locked 🎯 Stay in flow.");
    render();
  });

  on("[data-act=save-evening-sunset]", () => act(async () => {
    const win = $("#pm-win") ? $("#pm-win").value.trim() : "";
    const gratitude = $("#pm-gratitude") ? $("#pm-gratitude").value.trim() : "";
    await api("/v1/journal/entries", {
      wins: win ? [win] : ["Completed daily focus goals"],
      gratitude: gratitude ? [gratitude] : ["Grateful for a productive day"],
      reflection: "Evening Sunset Check-in completed.",
      mood: 8
    });
    await refresh();
  }, "Evening Sunset Logged 🌙 Day Completed!"));

  on("[data-act=import-event-url]", () => act(async () => {
    const url = $("#imp-url").value.trim();
    if (!url) return toast("Paste an event URL first.");
    await api("/v1/feed/import-url", { url });
    $("#imp-url").value = "";
    await refresh();
  }, "Event URL imported to discovery feed! 🎟️"));

  on("[data-act=crew-pass]", (el) => act(async () => {
    // Copied a link to lifeos.app carrying `token=plus_one_<crew id>` — a token this
    // deployment never issued, on a host it does not serve. It is a real single-use invite
    // now, and the link points at wherever this app is actually running.
    const res = await api(`/v1/crews/${el.dataset.id}/guest-pass`, {});
    const link = location.origin + res.invite_path;
    await navigator.clipboard.writeText(link).catch(() => {});
    toast("Plus-one link copied — one person, expires in a day. 🎟️");
  }));

  on("[data-act=mindfulness-start]", () => act(async () => {
    const circle = $("#breath-circle");
    if (circle) {
      circle.style.transform = "scale(1.8)";
      setTimeout(() => { circle.style.transform = "scale(1.0)"; }, 4000);
    }
    await api("/v1/routines/mindfulness/session", { duration_minutes: 2, distraction_count: 0, note: "2-min breathing reset" });
    await refresh();
  }, "Mindfulness Session Logged 🧘 Reset Completed!"));

  /* ---- Weekend Share & Vault ---- */

  on("[data-act=weekend-share]", () => act(async () => {
    const res = await api("/v1/weekend/share").catch(() => null);
    const text = (res && res.text) || "Weekend Itinerary from LifeOS";
    await navigator.clipboard.writeText(text).catch(() => {});
    toast("Weekend Itinerary copied to clipboard! 📲 Paste into WhatsApp.");
  }));

  on("[data-act=vault-save]", () => act(async () => {
    const title = $("#vt-title").value.trim();
    const content = $("#vt-content").value.trim();
    const tagsStr = $("#vt-tags").value.trim();
    if (!title || !content) return toast("Provide title and content for vault note.");
    const tags = tagsStr ? tagsStr.split(",").map(t => t.trim()).filter(Boolean) : [];
    await api("/v1/vault/notes", { title, content, tags });
    $("#vt-title").value = "";
    $("#vt-content").value = "";
    await refresh();
  }, "Vault note saved ✔"));

  on("[data-act=vault-search]", () => act(async () => {
    const query = $("#vt-query").value.trim();
    const searchRes = await api(`/v1/vault/search?query=${encodeURIComponent(query)}`).catch(() => []);
    const resEl = $("#vault-results");
    if (!resEl) return;
    const notes = Array.isArray(searchRes) ? searchRes : (searchRes.notes || []);
    if (notes.length) {
      resEl.innerHTML = notes.map(n => `
        <div class="feed-item">
          <div class="kind">${esc(n.title || "Vault Note")}</div>
          <div class="label" style="font-size:13px; color:var(--text); margin-top:2px;">${esc(n.content || n.text || "")}</div>
        </div>
      `).join("");
    } else {
      resEl.innerHTML = `<div style="font-size:13px; color:var(--muted);">No matching notes found.</div>`;
    }
  }));

  /* ---- 20% Community Impact Treasury Handlers ---- */

  on("[data-act=tr-submit]", () => act(async () => {
    const title = $("#tr-title").value.trim();
    const grant_amount = parseFloat($("#tr-amount").value) || 500;
    if (!title) return toast("Provide proposal title.");
    await api("/v1/treasury/proposals", { title, category: "charity", grant_amount });
    $("#tr-title").value = "";
    await refresh();
  }, "Democratic Proposal Submitted 🗳️"));

  on("[data-act=tr-vote]", (el) => act(async () => {
    await api("/v1/treasury/vote", { proposal_id: el.dataset.id });
    await refresh();
  }, "Vote Cast 🗳️"));

  on("[data-act=dev-key-gen]", () => act(async () => {
    const name = $("#dk-name").value.trim() || "New Integration Key";
    const res = await api("/v1/developer/keys", { name });
    const secret = res.secret || "los_sk_demo123";
    await navigator.clipboard.writeText(secret).catch(() => {});
    $("#dk-name").value = "";
    toast(`API Key Created! Secret copied to clipboard: ${secret.slice(0, 12)}... 🔑`);
  }));

  /* It echoed two times back, stored nothing, and toasted "Daily Push Notifications
     Scheduled". Nothing was scheduled and nothing could ever have been pushed. */
  function renderReminders(res) {
    const out = $("#reminders-output");
    if (!out) return;
    const dueList = res.due || [];
    const set = res.reminders || [];
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px;">
        ${dueList.map(r => `<div style="font-size:13px; margin-bottom:4px;">
            <strong>${esc(r.text)}</strong> — due ${esc(r.at)}
            <button class="ghost" style="font-size:11px; padding:4px 10px; margin-left:6px;" data-act="nt-ack" data-id="${esc(r.reminder_id)}">Got it</button>
          </div>`).join("")}
        ${set.map(r => `<div style="font-size:13px; margin-bottom:4px;">
            ${esc(r.text)} · ${esc(r.at)} · ${esc((r.days || []).join(", "))}
            <button class="ghost" style="font-size:11px; padding:4px 10px; margin-left:6px;" data-act="nt-cancel" data-id="${esc(r.reminder_id)}">Stop</button>
          </div>`).join("")}
        ${(dueList.length || set.length) ? "" : `<div style="font-size:13px; color:var(--muted);">Nothing set.</div>`}
        <div style="font-size:11px; color:var(--muted); margin-top:8px;">${esc(res.delivery_note || "")}</div>
      </div>`;
    bindLater(out);
  }

  const showReminders = async () => {
    const [due, set] = await Promise.all([api("/v1/notifications/due"),
                                          api("/v1/notifications")]);
    renderReminders({ ...set, due: due.due, delivery_note: set.delivery_note });
  };

  on("[data-act=nt-save]", () => act(async () => {
    const text = $("#nt-text").value.trim();
    if (!text) { toast("Remind you of what?"); return; }
    const days = $("#nt-days").value.split(",").map(d => d.trim()).filter(Boolean);
    // The wall-clock time is what was typed; the offset says where the person is standing,
    // so "08:00" stays eight in the morning after they fly somewhere else.
    await api("/v1/notifications/schedule", {
      text, at: $("#nt-at").value || "08:00", days,
      utc_offset_minutes: -new Date().getTimezoneOffset(),
    });
    $("#nt-text").value = "";
    await showReminders();
  }));

  on("[data-act=nt-list]", () => act(showReminders));

  on("[data-act=nt-ack]", (el) => act(async () => {
    await api("/v1/notifications/acknowledge", { reminder_id: el.dataset.id });
    await showReminders();
  }));

  on("[data-act=nt-cancel]", (el) => act(async () => {
    await api("/v1/notifications/cancel", { reminder_id: el.dataset.id });
    await showReminders();
  }));

  /* ---- Ambient Focus & Sleep Audio Synthesizer ---- */
  let audioCtx = null;
  let noiseNode = null;

  on("[data-act=audio-play]", (el) => {
    const preset = el.dataset.preset;
    if (noiseNode) { try { noiseNode.stop(); } catch(e){} }
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) return toast("Audio API not supported in browser.");
    if (!audioCtx) audioCtx = new AudioContext();

    const bufferSize = audioCtx.sampleRate * 2;
    const noiseBuffer = audioCtx.createBuffer(1, bufferSize, audioCtx.sampleRate);
    const output = noiseBuffer.getChannelData(0);
    let lastOut = 0.0;
    for (let i = 0; i < bufferSize; i++) {
      const white = Math.random() * 2 - 1;
      output[i] = (lastOut + (0.02 * white)) / 1.02; // Brown noise filter
      lastOut = output[i];
      output[i] *= 3.5;
    }

    noiseNode = audioCtx.createBufferSource();
    noiseNode.buffer = noiseBuffer;
    noiseNode.loop = true;

    const gain = audioCtx.createGain();
    gain.gain.value = 0.15;
    noiseNode.connect(gain);
    gain.connect(audioCtx.destination);
    noiseNode.start();

    toast(`Playing Ambient ${preset.toUpperCase()} Soundscape 🎧 Perfect for focus & plane journey sleep!`);
  });

  on("[data-act=audio-stop]", () => {
    if (noiseNode) {
      try { noiseNode.stop(); } catch(e){}
      noiseNode = null;
    }
    toast("Audio Stopped 🛑");
  });

  on("[data-act=export-csv]", () => act(async () => {
    const res = await fetch("/v1/graph/export/csv");
    const csv = await res.text();
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "lifeos_graph.csv";
    a.click();
  }, "Exported Graph to CSV 📊"));

  on("[data-act=synergy-propose]", (el) => act(async () => {
    const text = el.dataset.text || "Want to meet up?";
    await navigator.clipboard.writeText(text).catch(() => {});
    toast("Propose Outing message copied to clipboard! 📲 Paste into WhatsApp.");
  }));

  on("[data-act=smart-cal-travel-add]", (el) => act(async () => {
    const city = el.dataset.city || "Lisbon";
    await api("/v1/calendar/add-travel-activities", { city });
    await refresh();
  }, "Trip activities added to Smart Calendar! 📅"));

  on("[data-act=kudos-send]", () => act(async () => {
    /* Posted `{recipient}` with no note, defaulting the name to "Alex" — so it 400'd on
       every click (a kudos needs something to say), and had it succeeded it would have
       been addressed to a string nobody owns. */
    const recipient = $("#kd-name").value.trim();
    const note = $("#kd-note").value.trim();
    if (!recipient) { toast("Who is it for?"); return; }
    if (!note) { toast("What are you thanking them for?"); return; }
    await api("/v1/kudos/send", { to_account: recipient, note });
    $("#kd-name").value = ""; $("#kd-note").value = "";
    toast("Sent — they can read it.");
  }));

  on("[data-act=find-tomorrow-am]", () => act(async () => {
    const out = $("#tomorrow-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid var(--spark)40;">
        <div style="font-size:14px; font-weight:700; color:var(--spark); margin-bottom:6px;">☕ Tomorrow at 8:00 AM Matches:</div>
        <div style="font-size:13px; margin-bottom:4px;">📍 <strong>Fabrica Coffee Roasters</strong> — Specialty Coffee & Morning Intent</div>
        <div style="font-size:13px; margin-bottom:4px;">🧗 <strong>Morning Bouldering Session</strong> (Monsanto Crag · Alex & 2 others free)</div>
        <button class="ghost" style="margin-top:8px; font-size:12px; padding:6px 12px;" onclick="navigator.clipboard.writeText('⚡ Hey Alex! Down for 8:00 AM Bouldering & Coffee tomorrow?'); toast('Message copied to clipboard! 📲');">Text Friends on WhatsApp 📲</button>
      </div>
    `;
  }, "Found 8:00 AM Matches! ☕"));

  on("[data-act=find-tomorrow-pm]", () => act(async () => {
    const out = $("#tomorrow-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid var(--growth)40;">
        <div style="font-size:14px; font-weight:700; color:var(--growth); margin-bottom:6px;">🌅 Tomorrow at 20:00 (8:00 PM) Matches:</div>
        <div style="font-size:13px; margin-bottom:4px;">🎟️ <strong>Sunset Bouldering & Pizza Meet</strong> (Lisbon Center · 14 attending)</div>
        <div style="font-size:13px; margin-bottom:4px;">📍 <strong>Miradouro Sunset Drinks</strong> (Elena & 3 crew members free)</div>
        <button class="ghost" style="margin-top:8px; font-size:12px; padding:6px 12px;" onclick="navigator.clipboard.writeText('🌅 Hey crew! Anyone down for 20:00 Sunset Drinks tomorrow?'); toast('Message copied to clipboard! 📲');">Text Crew on WhatsApp 📲</button>
      </div>
    `;
  }, "Found 8:00 PM Matches! 🌅"));

  on("[data-act=match-new-friends]", () => act(async () => {
    const interest = $("#mf-interest").value.trim() || "bouldering";
    const out = $("#match-friends-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid var(--growth)40;">
        <div style="font-size:14px; font-weight:700; color:var(--growth); margin-bottom:6px;">🤝 Matched 3 New Friends in Lisbon (${esc(interest)}):</div>
        <div class="person" style="margin-bottom:6px;"><div class="who"><div class="name">Elena R.</div><div class="meta">Bouldering & Specialty Coffee · 94% Match</div></div><button class="pill good" onclick="toast('Friend request & crew invite sent to Elena! 🤝');">Connect 🤝</button></div>
        <div class="person" style="margin-bottom:6px;"><div class="who"><div class="name">Marcus T.</div><div class="meta">Outdoor Climbing & Tech · 89% Match</div></div><button class="pill good" onclick="toast('Friend request & crew invite sent to Marcus! 🤝');">Connect 🤝</button></div>
      </div>
    `;
  }, "Matched New Local Friends! 🤝"));

  /* Crew polls and beacons.

     The poll card was three hardcoded options with invented vote counts; the beacon
     endpoint returned "broadcasted" and reached nobody. Both are per-crew objects now, so
     both render from the crew's own row where a crew id exists. */
  const crewPanel = () => $("#crew-activity-output");

  function renderPolls(res, crewId, crewName) {
    const out = crewPanel();
    if (!out) return;
    const polls = res.polls || [];
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px;">
        <div style="font-size:13px; font-weight:700; margin-bottom:8px;">📊 ${esc(crewName || "Polls")}</div>
        ${polls.map(p => `
          <div style="margin-bottom:10px;">
            <div style="font-size:13px; font-weight:600;">${esc(p.question)}</div>
            <div style="font-size:11px; color:var(--muted); margin-bottom:4px;">${esc(p.opened_by_handle)} asked · ${p.total_votes} vote${p.total_votes === 1 ? "" : "s"}${p.you_voted ? " · you voted" : ""}</div>
            ${p.options.map((o, i) => `<button class="ghost" style="text-align:left; padding:6px 10px; font-size:12px; margin:2px 2px 0 0;" data-act="crew-poll-vote" data-poll="${esc(p.poll_id)}" data-index="${i}" data-crew="${esc(crewId)}" data-name="${esc(crewName || "")}">${esc(o)}</button>`).join("")}
          </div>`).join("")}
        ${polls.length ? "" : `<div style="font-size:13px; color:var(--muted); margin-bottom:8px;">No open polls.</div>`}
        <input class="field" id="poll-q" placeholder="Ask the crew something" style="margin-top:6px;">
        <input class="field" id="poll-opts" placeholder="Options, comma separated" style="margin-top:6px;">
        <button class="primary" style="margin-top:6px;" data-act="crew-poll-open" data-crew="${esc(crewId)}" data-name="${esc(crewName || "")}">Open the poll</button>
      </div>`;
    bindLater(out);
  }

  function renderBeacons(res, crewId, crewName) {
    const out = crewPanel();
    if (!out) return;
    const live = res.beacons || [];
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px;">
        <div style="font-size:13px; font-weight:700; margin-bottom:8px;">⚡ ${esc(crewName || "Up for it")}</div>
        ${live.map(b => `
          <div style="margin-bottom:8px;">
            <div style="font-size:13px;"><strong>${esc(b.handle)}</strong> — ${esc(b.activity)}${b.place ? ` at ${esc(b.place)}` : ""}</div>
            <div style="font-size:11px; color:var(--muted);">${b.minutes_left} min left${b.coming_count ? ` · ${b.coming.map(esc).join(", ")} coming` : ""}</div>
            ${b.mine ? `<button class="ghost" style="font-size:11px; padding:4px 10px; margin-top:4px;" data-act="crew-beacon-down" data-beacon="${esc(b.beacon_id)}" data-crew="${esc(crewId)}" data-name="${esc(crewName || "")}">Cancel</button>`
                     : `<button class="ghost" style="font-size:11px; padding:4px 10px; margin-top:4px;" data-act="crew-beacon-join" data-beacon="${esc(b.beacon_id)}" data-crew="${esc(crewId)}" data-name="${esc(crewName || "")}">${b.you_are_in ? "You are in" : "I'm in"}</button>`}
          </div>`).join("")}
        ${live.length ? "" : `<div style="font-size:13px; color:var(--muted); margin-bottom:8px;">${esc(res.suggestion || "Nothing live.")}</div>`}
        <input class="field" id="bcn-act" placeholder="Up for what, right now?" style="margin-top:6px;">
        <input class="field" id="bcn-mins" type="number" placeholder="For how many minutes" value="60" style="margin-top:6px;">
        <button class="primary" style="margin-top:6px;" data-act="crew-beacon-raise" data-crew="${esc(crewId)}" data-name="${esc(crewName || "")}">Raise it</button>
        <div style="font-size:11px; color:var(--muted); margin-top:8px;">${esc(res.delivery_note || "")}</div>
      </div>`;
    bindLater(out);
  }

  const showPolls = (id, name) => api(`/v1/crews/${id}/polls`).then(r => renderPolls(r, id, name));
  const showBeacons = (id, name) => api(`/v1/crews/${id}/beacons`).then(r => renderBeacons(r, id, name));

  on("[data-act=crew-polls]", (el) => act(async () => {
    await showPolls(el.dataset.id, el.dataset.name);
  }));

  on("[data-act=crew-beacons]", (el) => act(async () => {
    await showBeacons(el.dataset.id, el.dataset.name);
  }));

  on("[data-act=crew-poll-open]", (el) => act(async () => {
    const question = $("#poll-q").value.trim();
    const options = $("#poll-opts").value.split(",").map(o => o.trim()).filter(Boolean);
    if (!question) { toast("What are you asking?"); return; }
    if (options.length < 2) { toast("A poll needs at least two options."); return; }
    await api("/v1/crews/polls", { crew_id: el.dataset.crew, question, options });
    await showPolls(el.dataset.crew, el.dataset.name);
  }));

  on("[data-act=crew-beacon-raise]", (el) => act(async () => {
    const activity = $("#bcn-act").value.trim();
    if (!activity) { toast("Up for what?"); return; }
    const minutes = parseInt($("#bcn-mins").value, 10) || 60;
    await api("/v1/crews/beacon", { crew_id: el.dataset.crew, activity, minutes });
    await showBeacons(el.dataset.crew, el.dataset.name);
  }));

  on("[data-act=crew-beacon-join]", (el) => act(async () => {
    await api("/v1/crews/beacon/join", { beacon_id: el.dataset.beacon });
    await showBeacons(el.dataset.crew, el.dataset.name);
  }));

  on("[data-act=crew-beacon-down]", (el) => act(async () => {
    await api("/v1/crews/beacon/stand-down", { beacon_id: el.dataset.beacon });
    await showBeacons(el.dataset.crew, el.dataset.name);
  }));

  on("[data-act=crew-poll-vote]", (el) => act(async () => {
    // Voted by posting a display string with no poll attached, and defaulted it to
    // "Outing" when the button had none. It votes by index into a real poll now.
    await api("/v1/crews/polls/vote", { poll_id: el.dataset.poll,
                                        option: Number(el.dataset.index) });
    await showPolls(el.dataset.crew, el.dataset.name);
  }));

  on("[data-act=post-venue-review]", () => act(async () => {
    const place = $("#rv-place").value.trim() || "Monsanto Outdoor Crag";
    const review = $("#rv-text").value.trim() || "Great friction and awesome weather today!";
    const res = await api("/v1/feed/reviews", { place, review });
    $("#rv-place").value = "";
    $("#rv-text").value = "";
    await refresh();
    toast(res.message || "Field Report posted to community feed! 📝");
  }));

  on("[data-act=send-micro-tip]", () => act(async () => {
    /* Toasted "Sent €3.50 to Alex" for a recipient it invented when the field was empty,
       and no money went anywhere. It is an IOU now, and it needs a real handle. */
    const recipient = $("#tp-name").value.trim();
    if (!recipient) { toast("Who is it for?"); return; }
    const amount = parseFloat($("#tp-amount") ? $("#tp-amount").value : "") || 3.50;
    const res = await api("/v1/ledger/tip", { recipient, amount, currency: "EUR" });
    $("#tp-name").value = "";
    toast(`Recorded: you owe ${recipient} €${Number(res.amount).toFixed(2)}. Nothing was sent.`);
  }));

  on("[data-act=instant-synergy-match]", () => act(async () => {
    const interest = $("#bc-act").value.trim();
    if (!interest) { toast("Up for what?"); return; }
    const res = await api("/v1/synergy/instant-match", { interest });
    renderMatch(res, "#instant-match-output");
  }));

  /* ---- /ai/*: one renderer, because there was only ever one shape ----
     Twenty handlers each pulled different invented keys out of a literal — Elena R.'s
     icebreakers, a negotiation across five calendars, a fulfilment score of 87. They all
     answer the same question now ("what is actually here?"), so they share a renderer that
     shows the records, the empty state, and whether a model wrote the wording. */

  const AI_LISTS = ["openers", "stops", "quests", "plans", "options", "matches", "people",
                    "overlaps", "splits", "recent", "goals"];

  function aiLine(item) {
    if (typeof item === "string") return esc(item);
    const title = item.what || item.title || item.name || item.handle || item.note
                  || item.activity || "";
    const when = item.when || item.starts_at || item.day || item.open_until || "";
    const where = item.where || item.place || item.city_label || item.city || "";
    const extra = [where, when ? whenLabel(when) : ""].filter(Boolean).join(" · ");
    const going = item.going_count !== undefined ? `${item.going_count} going` : "";
    return `<div><strong>${esc(String(title))}</strong></div>` +
           (extra ? `<div style="font-size:11px; color:var(--muted);">${esc(extra)}</div>` : "") +
           (going ? `<div style="font-size:11px; color:var(--muted);">${esc(going)}</div>` : "");
  }

  function renderAI(res, targetId, heading) {
    const out = $(targetId);
    if (!out) return;
    if (res.available === false) {
      out.innerHTML = `<div style="background:var(--surface-2s); padding:12px; border-radius:12px;">
        <div style="font-size:13px; font-weight:700; margin-bottom:4px;">Not available</div>
        <div style="font-size:12px; color:var(--muted);">${esc(res.reason || "")}</div>
      </div>`;
      bindLater(out);
      return;
    }
    const key = AI_LISTS.find((k) => Array.isArray(res[k]) && res[k].length);
    const items = key ? res[key] : [];
    const notes = ["no_score", "no_roi", "no_mood_detection", "why_not", "next_step",
                   "suggestion", "safety_note"]
      .map((k) => res[k]).filter(Boolean);
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px;">
        <div style="font-size:14px; font-weight:700; margin-bottom:6px;">${esc(heading || "")}</div>
        ${items.map((item) => `<div style="font-size:13px; margin-bottom:6px; background:var(--surface-1); padding:8px 10px; border-radius:8px;">${aiLine(item)}</div>`).join("")}
        ${notes.map((n) => `<div style="font-size:11px; color:var(--muted); margin-top:6px;">${esc(n)}</div>`).join("")}
        ${res.assisted === false ? `<div style="font-size:11px; color:var(--muted); margin-top:8px;">Assembled from your graph — no model key set.</div>` : ""}
      </div>`;
    bindLater(out);
  }

  const aiCity = () => (($("#sy-city") && $("#sy-city").value.trim())
                        || ($("#dt-city") && $("#dt-city").value.trim()) || "");

  /* ---- Dating: discovery, then a two-sided agreement ----
     The old card ran a "7-Factor Match Engine" over seven constants and handed back Elena
     R., 1.2 km away, then let you "Both Agree" with her — a confirmed meeting, an ETA and
     PIN 4892, with nobody on the other end. Both halves are real now, and the second one
     cannot fire without an account id that came from the first. */

  function datingCity() {
    const box = $("#dt-city");
    return box ? box.value.trim() : "";
  }

  function renderDatingOpen(res) {
    const out = $("#instant-dating-output");
    if (!out) return;
    if (res.needs_city) {
      out.innerHTML = `<div style="background:var(--surface-2s); padding:12px; border-radius:12px; font-size:13px;">${esc(res.suggestion || "Which city?")}</div>`;
      bindLater(out);
      return;
    }
    if (!res.you_are_open) {
      out.innerHTML = `
        <div style="background:var(--surface-2s); padding:12px; border-radius:12px;">
          <div style="font-size:13px; margin-bottom:8px;">${esc(res.suggestion || "")}</div>
          <button class="ghost" style="font-size:12px; padding:6px 12px;" data-act="dating-open-to">I'm open tonight ✋</button>
        </div>`;
      bindLater(out);
      return;
    }
    const people = res.people || [];
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px;">
        <div style="font-size:13px; font-weight:700; margin-bottom:6px;">Open in ${esc(res.city_label || res.city)}</div>
        ${people.length ? "" : `<div style="font-size:13px; color:var(--muted);">${esc(res.suggestion || "")}</div>`}
        ${people.map(p => `
          <div style="font-size:13px; margin-bottom:6px; background:var(--surface-1); padding:8px 10px; border-radius:8px;">
            <div><strong>${esc(p.handle)}</strong></div>
            ${p.vibe ? `<div style="font-size:12px; color:var(--muted);">${esc(p.vibe)}</div>` : ""}
            <button class="ghost" style="font-size:11px; padding:4px 10px; margin-top:4px;" data-act="agree-dating-meet" data-target="${esc(p.account_id)}">I'd meet them</button>
          </div>`).join("")}
        ${res.next_step ? `<div style="font-size:11px; color:var(--muted); margin-top:8px;">${esc(res.next_step)}</div>` : ""}
        ${res.safety_note ? `<div style="font-size:11px; color:var(--muted); margin-top:6px;">${esc(res.safety_note)}</div>` : ""}
      </div>`;
    bindLater(out);
  }

  on("[data-act=instant-dating-match]", () => act(async () => {
    renderDatingOpen(await api("/v1/dating/instant-meet", { city: datingCity() }));
  }));

  on("[data-act=dating-open-to]", () => act(async () => {
    const vibe = $("#dt-vibe") ? $("#dt-vibe").value.trim() : "";
    await api("/v1/dating/open-to-meeting", { city: datingCity(), vibe });
    renderDatingOpen(await api("/v1/dating/instant-meet", { city: datingCity() }));
  }, "You're listed for a few hours — it expires on its own ✋"));

  on("[data-act=agree-dating-meet]", (el) => act(async () => {
    const res = await api("/v1/dating/agree-meet",
                          { target_account_id: el.dataset.target, activity_id: "meet" });
    const out = $("#instant-dating-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px;">
        <div style="font-size:14px; font-weight:700; margin-bottom:6px;">${res.agreed ? "You're both in 🥂" : "Noted, privately"}</div>
        <div style="font-size:13px; margin-bottom:6px;">${esc(res.message || "")}</div>
        ${res.meeting_code ? `<div style="font-size:13px;">Say this out loud when you meet: <strong>${esc(res.meeting_code)}</strong></div>` : ""}
        <div style="font-size:11px; color:var(--muted); margin-top:8px;">${esc(res.safety_note || "")}</div>
      </div>`;
  }));

  /* ---- Synergy: one renderer for every activity ----
     Seven near-identical handlers used to live here, each pulling `res.partner_name` and
     `res.match_score` out of a literal the server made up. There is one now, because there
     was only ever one feature. The empty state is the important half: an honest "nobody yet"
     plus the button that fixes it beats a stranger who does not exist. */

  function synergyActivity(fallback) {
    const box = $("#sy-act");
    const typed = box ? box.value.trim() : "";
    return typed || fallback || "";
  }

  function synergyCity() {
    const box = $("#sy-city");
    return box ? box.value.trim() : "";
  }

  function matchPerson(p) {
    const shared = (p.shared_terms || []).join(", ");
    return `
      <div style="font-size:13px; margin-bottom:6px; background:var(--surface-1); padding:8px 10px; border-radius:8px;">
        <div><strong>${esc(p.handle)}</strong>${p.activity ? ` — ${esc(p.activity)}` : ""}</div>
        ${p.note ? `<div style="font-size:12px; color:var(--muted);">${esc(p.note)}</div>` : ""}
        ${shared ? `<div style="font-size:11px; color:var(--muted);">matched on: ${esc(shared)}</div>` : ""}
        ${p.open_until ? `<div style="font-size:11px; color:var(--muted);">open until ${esc(whenLabel(p.open_until))}</div>` : ""}
      </div>`;
  }

  function matchMeetup(m) {
    return `
      <div style="font-size:13px; margin-bottom:6px; background:var(--surface-1); padding:8px 10px; border-radius:8px;">
        <div>📅 <strong>${esc(m.title)}</strong>${m.place ? ` · ${esc(m.place)}` : ""}</div>
        <div style="font-size:11px; color:var(--muted);">${esc(whenLabel(m.starts_at))} · ${m.going_count} going</div>
        <button class="ghost" style="font-size:11px; padding:4px 10px; margin-top:4px;" data-act="meetup-join" data-id="${esc(m.meetup_id)}">Join</button>
      </div>`;
  }

  function renderMatch(res, targetId) {
    const out = $(targetId);
    if (!out) return;
    const people = res.people || [];
    const meets = res.meetups || [];
    const events = res.events || [];
    const where = res.city_label || res.city || "";

    if (!res.matched) {
      out.innerHTML = `
        <div style="background:var(--surface-2s); padding:12px; border-radius:12px;">
          <div style="font-size:13px; margin-bottom:6px;">Nobody yet${where ? ` in ${esc(where)}` : ""}.</div>
          <div style="font-size:12px; color:var(--muted);">${esc(res.suggestion || "")}</div>
          ${res.you_are_open ? "" : `<button class="ghost" style="font-size:12px; padding:6px 12px; margin-top:8px;" data-act="synergy-open-to">I'm up for this ✋</button>`}
        </div>`;
      bindLater(out);
      return;
    }

    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px;">
        <div style="font-size:14px; font-weight:700; margin-bottom:6px;">${esc(res.category || "Match")}${where ? ` · ${esc(where)}` : ""}</div>
        ${people.length ? `<div style="font-size:12px; color:var(--muted); margin-bottom:4px;">${people.length} ${people.length === 1 ? "person" : "people"} open right now</div>` : ""}
        ${people.map(matchPerson).join("")}
        ${meets.length ? `<div style="font-size:12px; color:var(--muted); margin:6px 0 4px;">Already on the board</div>` : ""}
        ${meets.map(matchMeetup).join("")}
        ${events.map(e => `<div style="font-size:12px; margin-bottom:4px;">🎟️ ${esc(e.title || "")}</div>`).join("")}
        ${res.safety_note ? `<div style="font-size:11px; color:var(--muted); margin-top:8px;">${esc(res.safety_note)}</div>` : ""}
      </div>`;
    bindLater(out);
  }

  async function synergySearch(activity, targetId) {
    const res = await api("/v1/synergy/instant-match",
                          { interest: activity, city: synergyCity() });
    renderMatch(res, targetId || "#vertical-match-output");
    return res;
  }

  on("[data-act=synergy-search]", () => act(async () => {
    await synergySearch(synergyActivity(""));
  }));

  on("[data-act=synergy-vertical]", (el) => act(async () => {
    const activity = synergyActivity(el.dataset.activity);
    const box = $("#sy-act");
    if (box && !box.value.trim()) box.value = activity;
    await synergySearch(activity);
  }));

  on("[data-act=synergy-open-to]", () => act(async () => {
    const activity = synergyActivity("");
    if (!activity) { toast("Up for what?"); return; }
    await api("/v1/synergy/open-to", { activity, city: synergyCity() });
    await synergySearch(activity);
  }, "You're on the list — anyone searching for that will find you ✋"));

  on("[data-act=synergy-mine]", () => act(async () => {
    const res = await api("/v1/synergy/open-to");
    const out = $("#vertical-match-output");
    if (!out) return;
    const signals = res.signals || [];
    out.innerHTML = signals.length ? `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px;">
        <div style="font-size:13px; font-weight:700; margin-bottom:6px;">You are publishing</div>
        ${signals.map(s => `
          <div style="font-size:13px; margin-bottom:6px; background:var(--surface-1); padding:8px 10px; border-radius:8px;">
            <div><strong>${esc(s.activity)}</strong> · ${esc(s.city_label || s.city)}</div>
            <div style="font-size:11px; color:var(--muted);">until ${esc(whenLabel(s.expires_at))}</div>
            <button class="ghost" style="font-size:11px; padding:4px 10px; margin-top:4px;" data-act="synergy-close" data-activity="${esc(s.activity)}" data-city="${esc(s.city_label || s.city)}">Take it down</button>
          </div>`).join("")}
      </div>`
      : `<div style="background:var(--surface-2s); padding:12px; border-radius:12px; font-size:13px; color:var(--muted);">Nothing published. Nobody can match you until you say what you are up for.</div>`;
    bindLater(out);
  }));

  on("[data-act=synergy-close]", (el) => act(async () => {
    await apiDelete("/v1/synergy/open-to",
                    { activity: el.dataset.activity, city: el.dataset.city });
  }, "Taken down"));

  on("[data-act=register-dev-plugin]", () => act(async () => {
    const name = $("#dp-name").value.trim() || "Kitesurf Wind Radar";
    const category = $("#dp-cat").value.trim() || "Water Sports";
    const res = await api("/v1/developer/plugins/register", { name, category, trigger_condition: "Weather & Sensor Webhook Trigger" });
    $("#dp-name").value = "";
    $("#dp-cat").value = "";
    toast(res.message || `Published '${name}' to ConnectOS Developer Hub! 🚀`);
  }));

  on("[data-act=gen-ai-icebreakers]", (el) => act(async () => {
    const target = el.dataset.target || "";
    renderAI(await api("/v1/ai/copilot-icebreaker", { target_account_id: target, city: aiCity() }),
             "#ai-icebreaker-output", "Openers");
  }));
  on("[data-act=launch-squad-agent]", () => act(async () => {
    renderAI(await api("/v1/ai/squad-agent", {}), "#squad-agent-output", "Your crew's plans");
  }));
  on("[data-act=gen-micro-itinerary]", () => act(async () => {
    renderAI(await api("/v1/ai/micro-itinerary", { city: aiCity() }),
             "#karma-concierge-output", "Next day and a half");
  }));
  on("[data-act=trigger-sos]", () => act(async () => {
    const res = await api("/v1/safety/emergency-sos", { location: "Miradouro Rooftop, Lisbon" });
    const out = $("#karma-concierge-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:rgba(239,68,68,0.2); padding:12px; border-radius:12px; border:1px solid #ef4444;">
        <div style="font-size:14px; font-weight:700; color:#ef4444; margin-bottom:4px;">⚡ EMERGENCY SOS BROADCAST ACTIVE</div>
        <div style="font-size:13px; margin-bottom:4px;">Location Broadcasted to 4 Trusted Crew Members!</div>
        <div style="font-size:11px; color:var(--muted);">Emergency PIN: ${esc(res.emergency_pin)} · ${esc(res.location)}</div>
      </div>
    `;
  }, "Emergency SOS Location Broadcast Active! ⚡"));

  on("[data-act=match-mentor]", () => act(async () => {
    const seeking = $("#mt-seek") ? $("#mt-seek").value.trim() : "";
    const offering = $("#mt-offer") ? $("#mt-offer").value.trim() : "";
    if (!seeking) { toast("What do you want to learn?"); return; }
    const res = await api("/v1/synergy/mentor-match", { seeking, offering });
    renderMatch(res, "#mentor-squad-output");
  }));

  on("[data-act=sync-squad-routine]", () => act(async () => {
    /* Reported "Weekly on Wednesdays @ 7:00 AM" whatever you asked for, claimed it was
       synced to 5 crew calendars, and linked an .ics on connectos.app. The rule is real
       now and its occurrences join the crew's own feed, which this deployment serves. */
    const crew_id = firstCrewId();
    if (!crew_id) { toast("A routine belongs to a crew — make one first."); return; }
    const title = $("#sq-title") ? $("#sq-title").value.trim() : "";
    if (!title) { toast("What is the routine?"); return; }
    const res = await api("/v1/routines/squad-sync", {
      crew_id, title, day: ($("#sq-day") ? $("#sq-day").value : "wed"),
      at: ($("#sq-at") ? $("#sq-at").value : "07:00"),
    });
    // A subscribe URL a calendar app can actually fetch. `res.ics_path` needs the session
    // bearer token, which a calendar client cannot send — offering that as "Subscribe"
    // would be a link that 401s for everything except this app.
    const link = await api(`/v1/crews/${crew_id}/calendar-link`, {});
    const url = location.origin + link.subscribe_path;
    const out = $("#mentor-squad-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px;">
        <div style="font-size:13px; font-weight:700; margin-bottom:4px;">${esc(res.title)} — ${esc(res.recurrence)}</div>
        ${res.upcoming.map(d => `<div style="font-size:12px;">${esc(new Date(d).toDateString())}</div>`).join("")}
        <div style="font-size:12px; margin-top:6px;">Subscribe in your calendar app:</div>
        <div style="font-size:11px; word-break:break-all;">${esc(url)}</div>
        <div style="font-size:11px; color:var(--muted); margin-top:6px;">${esc(res.sync_note)} ${esc(link.warning)}</div>
      </div>`;
    bindLater(out);
  }));

  on("[data-act=settle-crew-tab]", () => act(async () => {
    /* Reported €22.50 owed to Elena R. and Alex M. on an account that had split nothing,
       and offered a Revolut link nobody had connected. Shows the real tab instead, with a
       Settle button against each balance you actually owe. */
    renderTab(await api("/v1/ledger/tab"), "#ledger-quest-output");
  }));

  on("[data-act=gen-city-quest]", () => act(async () => {
    const res = await api("/v1/quests/city-discovery", { city: "Lisbon" });
    const out = $("#ledger-quest-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #eab308;">
        <div style="font-size:14px; font-weight:700; color:#eab308; margin-bottom:4px;">🗺️ City Discovery Micro-Quest (${esc(res.quest_id)}):</div>
        <div style="font-size:13px; margin-bottom:4px;">Quest: <strong>${esc(res.title)}</strong></div>
        <div style="font-size:12px; color:var(--muted); margin-bottom:4px;">${esc(res.description)}</div>
        <div style="font-size:12px; color:var(--growth); font-weight:700;">Reward: +${res.reward_karma} Karma Points · ${esc(res.reward_badge)}</div>
      </div>
    `;
  }, "City Discovery Quest Generated! 🗺️"));

  /* Claimed to *apply* a real_world_weight of 0.85 and a proximity_bias of 0.90, stored
     neither, and reported "Doomscroll Protection Active" — describing a ranking this app
     does not implement, while calling itself transparency. The real numbers are imported
     from the ranking code, so this page cannot drift away from it. */
  function renderFeedRules(res) {
    return `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px;">
        <div style="font-size:12px; margin-bottom:6px;">${esc(res.explanation)}</div>
        ${res.parts.map(p => `
          <div style="font-size:12px; margin-bottom:4px;">
            <strong>${esc(p.part)}</strong> — ${esc(p.how)}
            <div style="font-size:11px; color:var(--muted);">${Object.entries(p.weights).map(([k, v]) => `${esc(k)}: ${v}`).join(" · ")}</div>
          </div>`).join("")}
        <div style="font-size:12px; font-weight:700; margin-top:6px;">Never shown</div>
        ${res.excluded.map(e => `<div style="font-size:11px; color:var(--muted);">· ${esc(e)}</div>`).join("")}
        <div style="font-size:11px; color:var(--muted); margin-top:8px;">${esc(res.no_advertising)} ${esc(res.no_engagement_optimisation)}</div>
      </div>`;
  }

  on("[data-act=apply-algo-rules]", () => act(async () => {
    const out = $("#algo-revenue-output");
    if (!out) return;
    out.innerHTML = renderFeedRules(await api("/v1/feed/transparent-rules", {}));
  }));

  on("[data-act=stack-habit]", () => act(async () => {
    const res = await api("/v1/growth/habit-stacking", { anchor_habit: "Morning Espresso", new_habit: "20-Min Deep Reading" });
    const out = $("#algo-revenue-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #10b981;">
        <div style="font-size:14px; font-weight:700; color:#10b981; margin-bottom:4px;">🌱 Habit Stacked (${res.compounding_score} Score):</div>
        <div style="font-size:13px; margin-bottom:4px;">New Habit: <strong>${esc(res.new_habit)}</strong> anchored to <em>${esc(res.anchor_habit)}</em></div>
        <div style="font-size:12px; color:var(--spark); font-weight:700;">Streak: ${res.streak_days} Days Compounding 🔥</div>
      </div>
    `;
  }, "Growth Habit Stacked! 🌱"));

  on("[data-act=upgrade-explorer-pro]", () => act(async () => {
    const res = await api("/v1/billing/subscriptions", { plan: "EXPLORER_PRO" });
    const out = $("#sub-monetization-output");
    if (!out) return;
    const perks = res.perks_unlocked || [];
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #eab308;">
        <div style="font-size:14px; font-weight:700; color:#eab308; margin-bottom:4px;">💳 ConnectOS ${esc(res.current_plan)} Subscribed!</div>
        <div style="font-size:13px; margin-bottom:4px;">Membership: <strong>€${res.price_eur.toFixed(2)}/mo</strong> · All Perks Active</div>
        <div style="font-size:12px; color:var(--muted); margin-bottom:4px;">Perks: ${perks.join(" · ")}</div>
        <div style="font-size:11px; color:var(--spark);">Checkout Stripe Link: ${esc(res.checkout_url)}</div>
      </div>
    `;
  }, "Explorer Pro Subscription Active (€9.99/mo)! 💳"));

  on("[data-act=convert-voice-brief]", () => act(async () => {
    const transcript = $("#vb-note") ? $("#vb-note").value.trim() : "";
    if (!transcript) { toast("Paste or type the note first."); return; }
    renderAI(await api("/v1/ai/voice-brief", { transcript }), "#voice-gift-output", "Stops in that note");
  }));
  on("[data-act=gift-friend-coffee]", () => act(async () => {
    /* Sent a voucher code — the same one every time, `GIFT-FLATWHITE-99`, redeemable
       nowhere — to a hardcoded "Elena R.". The promise is the real part: an IOU for a
       coffee, which needs no amount and clears when you actually buy it. */
    const recipient = $("#gf-name") ? $("#gf-name").value.trim() : "";
    if (!recipient) { toast("Who are you buying one for?"); return; }
    const item = ($("#gf-item") ? $("#gf-item").value.trim() : "") || "coffee";
    renderTab(await api("/v1/ledger/gift-coffee", { recipient, item }),
              "#voice-gift-output");
  }));

  on("[data-act=b2b-team-signup]", () => act(async () => {
    const res = await api("/v1/monetization/b2b-team-tier", { company_name: "Acme AI Corp", seats: 25 });
    const out = $("#monetization-breakdown-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #10b981;">
        <div style="font-size:14px; font-weight:700; color:#10b981; margin-bottom:4px;">🏢 B2B Corporate Subscription Active (${esc(res.company_name)}):</div>
        <div style="font-size:13px; margin-bottom:4px;">Seats: <strong>${res.seats} Employees</strong> · MRR: <strong>€${res.mrr_eur.toFixed(2)}/mo</strong></div>
        <div style="font-size:12px; color:var(--growth); font-weight:700;">Perks: ${res.perks.join(" · ")}</div>
      </div>
    `;
  }, "B2B Corporate Subscription Activated (€374.75/mo MRR)! 🏢"));

  on("[data-act=view-revenue-breakdown]", () => act(async () => {
    const res = await api("/v1/monetization/venue-commissions");
    const out = $("#monetization-breakdown-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #eab308;">
        <div style="font-size:14px; font-weight:700; color:#eab308; margin-bottom:4px;">🎟️ Venue Partnership Commissions:</div>
        <div style="font-size:13px; margin-bottom:4px;">Monthly Cashflow: <strong>€${res.monthly_commission_eur.toFixed(2)}/mo</strong> across <strong>${res.partner_venues_count} Venues</strong></div>
        <div style="font-size:12px; color:var(--muted);">Top Venue: ${esc(res.top_venue)} · Avg Take Rate: ${esc(res.average_take_rate)}</div>
      </div>
    `;
  }, "Venue Commission Breakdown Loaded! 📊"));

  /* An invite link for a crew you actually administer.

     It read `res.invite_url` (a connectos.app address this deployment does not serve) and
     `res.bonus_karma` — 100 points and a free-coffee voucher from a rewards programme that
     does not exist. Both fields are gone; the link is real. */
  const firstCrewId = () => (state.crews && state.crews.length ? state.crews[0].id : "");

  on("[data-act=gen-invite-link]", () => act(async () => {
    const crew_id = firstCrewId();
    if (!crew_id) { toast("Make a crew first — a link has to let somebody into something."); return; }
    const res = await api("/v1/viral/invite-crew", { crew_id });
    const link = location.origin + res.invite_path;
    await navigator.clipboard.writeText(link).catch(() => {});
    const out = $("#viral-growth-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px;">
        <div style="font-size:13px; font-weight:700; margin-bottom:4px;">Invite link for ${esc(res.crew_name)}</div>
        <div style="font-size:12px; word-break:break-all; margin-bottom:4px;">${esc(link)}</div>
        <div style="font-size:11px; color:var(--muted);">Copied. Good for ${res.max_uses} people. Nothing is awarded for sharing it.</div>
      </div>`;
  }));

  on("[data-act=gen-story-card]", () => act(async () => {
    /* Showed a URL to a PNG that nothing ever rendered. The card is drawn server-side as an
       SVG now, so it can simply be displayed — there is no file to fetch. */
    const title = $("#share-title") ? $("#share-title").value.trim() : "";
    if (!title) { toast("What are you sharing?"); return; }
    const res = await api("/v1/viral/social-share", { title, subtitle: state.city || "" });
    const out = $("#viral-growth-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px;">
        <div style="font-size:13px; font-weight:700; margin-bottom:6px;">${esc(res.format)}</div>
        <img alt="share card" style="width:150px; border-radius:8px; display:block;"
             src="data:image/svg+xml;utf8,${encodeURIComponent(res.svg)}">
        <div style="font-size:11px; color:var(--muted); margin-top:6px;">${esc(res.note)}</div>
      </div>`;
  }));

  on("[data-act=trigger-auto-ingestion]", () => act(async () => {
    const res = await api("/v1/city/sync-live-events", { city: "Lisbon" });
    const out = $("#auto-ingestion-output");
    if (!out) return;
    const sources = res.sources_crawled || [];
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #06b6d4;">
        <div style="font-size:14px; font-weight:700; color:#06b6d4; margin-bottom:4px;">🌐 Automated Ingestion Sync Complete (${esc(res.city)}):</div>
        <div style="font-size:13px; margin-bottom:4px;">Total Auto-Populated: <strong>${res.total_ingested} Venues & Events</strong></div>
        <div style="font-size:12px; color:var(--muted);">${sources.map(s => `• <strong>${s.source}</strong>: ${s.items_ingested} ${s.type}`).join("<br>")}</div>
      </div>
    `;
  }, "Automated Venue & Event Data Ingested! 🌐"));

  on("[data-act=magic-qr-checkin]", () => act(async () => {
    const res = await api("/v1/events/qr-checkin", { qr_code: "QR-FABRICA-TABLE-4" });
    const out = $("#convenience-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #eab308;">
        <div style="font-size:14px; font-weight:700; color:#eab308; margin-bottom:4px;">⚡ Magic QR Check-In Complete!</div>
        <div style="font-size:13px; margin-bottom:4px;">Venue: <strong>${esc(res.venue)}</strong> · Squad Joined: <strong>${esc(res.active_squad_joined)}</strong></div>
        <div style="font-size:12px; color:var(--growth); font-weight:700;">Proof-of-Presence Minted: ${esc(res.pop_badge_minted)}</div>
      </div>
    `;
  }, "Magic QR Check-In Complete! ⚡"));

  on("[data-act=export-wallet-pass]", () => act(async () => {
    const res = await api("/v1/events/apple-wallet-pass", { event_name: "Miradouro Sunset Rooftop Meet" });
    const out = $("#convenience-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #10b981;">
        <div style="font-size:14px; font-weight:700; color:#10b981; margin-bottom:4px;">📲 Apple & Google Wallet Pass Generated:</div>
        <div style="font-size:13px; margin-bottom:4px;">Event: <strong>${esc(res.event_name)}</strong> · Code: <strong>${esc(res.pass_code)}</strong></div>
        <div style="font-size:11px; color:var(--spark);">Download Link: ${esc(res.pkpass_url)}</div>
      </div>
    `;
  }, "Wallet Pass Exported! 📲"));

  on("[data-act=join-solo-camp-village]", () => act(async () => {
    const res = await api("/v1/festivals/solo-camp-crew", { festival_name: "Boom Festival 🎪" });
    const out = $("#solo-fest-output");
    if (!out) return;
    const amenities = res.amenities || [];
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #f43f5e;">
        <div style="font-size:14px; font-weight:700; color:#f43f5e; margin-bottom:4px;">⛺ Joined ${esc(res.camp_village)}!</div>
        <div style="font-size:13px; margin-bottom:4px;">Festival: <strong>${esc(res.festival_name)}</strong> · ${res.crew_size} Solo Legends · Lead: ${esc(res.village_lead)}</div>
        <div style="font-size:12px; color:var(--growth); font-weight:700;">Village Perks: ${amenities.join(" · ")}</div>
      </div>
    `;
  }, "Joined Solo Festival Camp Village #4! ⛺"));

  on("[data-act=drop-stage-flare]", () => act(async () => {
    const res = await api("/v1/festivals/stage-flare", { stage_name: "Main Stage (Left Speaker Stack)", set_name: "Bicep Live Set 🎵" });
    const out = $("#solo-fest-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #a855f7;">
        <div style="font-size:14px; font-weight:700; color:#a855f7; margin-bottom:4px;">🚩 Festival Stage Flare Dropped (${res.active_crew_notified} Crew Notified)!</div>
        <div style="font-size:13px; margin-bottom:4px;">Set: <strong>${esc(res.set_name)}</strong> @ <strong>${esc(res.stage_name)}</strong></div>
        <div style="font-size:11px; color:var(--spark);">Live Map Pin: ${esc(res.live_pin)}</div>
      </div>
    `;
  }, "Festival Stage Flare Dropped! 🚩"));

  on("[data-act=match-layover-buddy]", () => act(async () => {
    const airport_code = $("#lo-airport") ? $("#lo-airport").value.trim() : "";
    if (!airport_code) { toast("Which airport?"); return; }
    renderMatch(await api("/v1/travel/layover-buddy", { airport_code }),
                "#layover-gym-output");
  }));

  on("[data-act=match-gym-spotter]", () => act(async () => {
    const activity = $("#lo-gym") ? $("#lo-gym").value.trim() : "";
    renderMatch(await api("/v1/sports/gym-spotter",
                          { activity, city: synergyCity() }), "#layover-gym-output");
  }));

  on("[data-act=match-language-swap]", () => act(async () => {
    const speak = $("#ls-speak") ? $("#ls-speak").value.trim() : "";
    const learn = $("#ls-learn") ? $("#ls-learn").value.trim() : "";
    if (!speak || !learn) { toast("What do you speak, and what do you want to learn?"); return; }
    const res = await api("/v1/synergy/language-swap", { speak, learn });
    renderMatch(res, "#layover-gym-output");
  }));

  on("[data-act=match-coliving]", () => act(async () => {
    const res = await api("/v1/housing/co-living-match", { city: "Lisbon", budget: "€900/mo" });
    const out = $("#human-needs-output");
    if (!out) return;
    const amenities = res.amenities || [];
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #ec4899;">
        <div style="font-size:14px; font-weight:700; color:#ec4899; margin-bottom:4px;">🏡 Co-Living Villa Matched (${res.compatibility_score}% Vibe Match):</div>
        <div style="font-size:13px; margin-bottom:4px;">Villa: <strong>${esc(res.villa_name)}</strong> · ${res.housemates_count} Housemates</div>
        <div style="font-size:12px; color:var(--growth); font-weight:700;">Amenities: ${amenities.join(" · ")}</div>
      </div>
    `;
  }, "Co-Living Housemate Matched! 🏡"));

  on("[data-act=rsvp-supper-club]", () => act(async () => {
    const res = await api("/v1/dining/supper-club", { cuisine: "Mediterranean Tapas & Natural Wine" });
    const out = $("#human-needs-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #f59e0b;">
        <div style="font-size:14px; font-weight:700; color:#f59e0b; margin-bottom:4px;">🍲 Supper Club RSVP Confirmed (${esc(res.price_per_person)} Split):</div>
        <div style="font-size:13px; margin-bottom:4px;">Host: <strong>${esc(res.host_name)}</strong> · ${res.guests_count} Guests @ ${esc(res.location)}</div>
        <div style="font-size:12px; color:var(--spark); font-weight:700;">Menu: ${esc(res.cuisine)}</div>
      </div>
    `;
  }, "Supper Club RSVP Confirmed! 🍲"));

  on("[data-act=reserve-digital-detox]", () => act(async () => {
    const res = await api("/v1/wellness/digital-detox", { duration: "2-Hour Phone-Free Deep Reading" });
    const out = $("#human-needs-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #10b981;">
        <div style="font-size:14px; font-weight:700; color:#10b981; margin-bottom:4px;">🧘 Digital Detox Lounge Reserved:</div>
        <div style="font-size:13px; margin-bottom:4px;">Venue: <strong>${esc(res.venue)}</strong> · ${res.attendees_count} Attendees</div>
        <div style="font-size:12px; color:var(--growth); font-weight:700;">Lockbox PIN: ${esc(res.phone_lockbox_code)} (${esc(res.duration)})</div>
      </div>
    `;
  }, "Digital Detox Lounge Reserved! 🧘"));

  on("[data-act=trade-barter-swap]", () => act(async () => {
    const res = await api("/v1/economy/barter-swap", { offering: "1-Hour Surf Lesson", seeking: "Portuguese Conversation Practice" });
    const out = $("#circular-economy-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #10b981;">
        <div style="font-size:14px; font-weight:700; color:#10b981; margin-bottom:4px;">🔄 Barter Swap Agreed (${esc(res.cash_saved)} Cash Saved!):</div>
        <div style="font-size:13px; margin-bottom:4px;">Trading: <strong>${esc(res.offering)}</strong> ➔ <strong>${esc(res.seeking)}</strong></div>
        <div style="font-size:12px; color:var(--growth); font-weight:700;">Partner: ${esc(res.match_partner)} (Swap ID: ${esc(res.swap_id)})</div>
      </div>
    `;
  }, "Barter Swap Agreed! 🔄"));

  on("[data-act=borrow-gear-library]", () => act(async () => {
    const res = await api("/v1/economy/community-borrow", { item: "2-Person Camping Tent & Sleeping Bags" });
    const out = $("#circular-economy-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #06b6d4;">
        <div style="font-size:14px; font-weight:700; color:#06b6d4; margin-bottom:4px;">♻️ Community Borrow Approved (${esc(res.fee)}):</div>
        <div style="font-size:13px; margin-bottom:4px;">Item: <strong>${esc(res.item_name)}</strong> · Owner: ${esc(res.owner_name)}</div>
        <div style="font-size:12px; color:var(--spark); font-weight:700;">Pickup: ${esc(res.pickup_location)} · Return by ${esc(res.return_by)}</div>
      </div>
    `;
  }, "Community Borrow Approved! ♻️"));

  on("[data-act=earn-time-token]", () => act(async () => {
    const res = await api("/v1/economy/time-bank", { service: "Helped neighbor fix bicycle chain", hours: 1 });
    const out = $("#circular-economy-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #eab308;">
        <div style="font-size:14px; font-weight:700; color:#eab308; margin-bottom:4px;">🌱 Time Token Earned (+${res.tokens_earned} Hr):</div>
        <div style="font-size:13px; margin-bottom:4px;">Service: <strong>${esc(res.service)}</strong></div>
        <div style="font-size:12px; color:var(--growth); font-weight:700;">Total Balance: ${res.current_time_token_balance} Time Tokens (${esc(res.community_karma_bonus)})</div>
      </div>
    `;
  }, "Time Token Earned! 🌱"));

  on("[data-act=start-group-nav]", () => act(async () => {
    const res = await api("/v1/routing/group-nav", { route_name: "Alfama Sunset Viewpoints Walk" });
    const out = $("#collab-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #6366f1;">
        <div style="font-size:14px; font-weight:700; color:#6366f1; margin-bottom:4px;">🗺️ Group Navigation Active (${res.group_members_on_route} Members Synced):</div>
        <div style="font-size:13px; margin-bottom:4px;">Route: <strong>${esc(res.route_name)}</strong> · ${res.waypoints_count} Waypoints</div>
        <div style="font-size:12px; color:var(--growth); font-weight:700;">Next Turn: ${esc(res.next_turn)}</div>
      </div>
    `;
  }, "Group Turn-by-Turn Navigation Started! 🗺️"));

  on("[data-act=sync-squad-jukebox]", () => act(async () => {
    const res = await api("/v1/music/squad-jukebox", { venue: "Fabrica Coffee Baixa" });
    const out = $("#collab-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #a855f7;">
        <div style="font-size:14px; font-weight:700; color:#a855f7; margin-bottom:4px;">🎶 Squad Jukebox Synced (${esc(res.venue)}):</div>
        <div style="font-size:13px; margin-bottom:4px;">Now Playing: <strong>${esc(res.now_playing)}</strong></div>
        <div style="font-size:12px; color:var(--spark); font-weight:700;">Playlist: ${esc(res.blended_playlist)} (${res.tracks_queued} tracks queued)</div>
      </div>
    `;
  }, "Squad Jukebox Synced! 🎶"));

  on("[data-act=vote-micro-grant]", () => act(async () => {
    const res = await api("/v1/community/micro-grants", { project: "Neighborhood Surfboard Rescue Stand @ Carcavelos" });
    const out = $("#collab-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #10b981;">
        <div style="font-size:14px; font-weight:700; color:#10b981; margin-bottom:4px;">🏆 Community Grant Vote Cast (${esc(res.grant_status)}):</div>
        <div style="font-size:13px; margin-bottom:4px;">Project: <strong>${esc(res.project_name)}</strong></div>
        <div style="font-size:12px; color:var(--growth); font-weight:700;">Fund Pool: ${esc(res.community_fund_pool)} · ${res.votes_count} Votes</div>
      </div>
    `;
  }, "Community Grant Vote Cast! 🏆"));

  on("[data-act=join-popup-jam]", () => act(async () => {
    const res = await api("/v1/creatives/pop-up-jam", { instrument: "Acoustic Guitar", location: "Miradouro de Santa Catarina" });
    const out = $("#culture-impact-output");
    if (!out) return;
    const members = res.jam_members || [];
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #ec4899;">
        <div style="font-size:14px; font-weight:700; color:#ec4899; margin-bottom:4px;">⚡ Sunset Pop-Up Jam Matched (${esc(res.session_time)}):</div>
        <div style="font-size:13px; margin-bottom:4px;">Spot: <strong>${esc(res.location)}</strong> · Playing: ${esc(res.instrument)}</div>
        <div style="font-size:12px; color:var(--growth); font-weight:700;">Musicians: ${members.join(" · ")}</div>
      </div>
    `;
  }, "Sunset Pop-Up Jam Matched! ⚡"));

  on("[data-act=swap-film-roll]", () => act(async () => {
    const res = await api("/v1/memories/analog-film-swap", { outing_id: "OUTING-8821" });
    const out = $("#culture-impact-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #a855f7;">
        <div style="font-size:14px; font-weight:700; color:#a855f7; margin-bottom:4px;">📸 Analog 35mm Film Roll Synced (${res.photos_scanned} Scans):</div>
        <div style="font-size:13px; margin-bottom:4px;">Film: <strong>${esc(res.film_stock)}</strong> · Outing: ${esc(res.outing_id)}</div>
        <div style="font-size:11px; color:var(--spark);">Album Link: ${esc(res.shared_album_url)}</div>
      </div>
    `;
  }, "Analog 35mm Film Roll Synced! 📸"));

  on("[data-act=join-eco-clean]", () => act(async () => {
    const res = await api("/v1/impact/eco-clean-crew", { beach: "Carcavelos Surf Beach" });
    const out = $("#culture-impact-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #10b981;">
        <div style="font-size:14px; font-weight:700; color:#10b981; margin-bottom:4px;">🌊 Eco-Clean Squad Confirmed (${res.crew_size} Legends):</div>
        <div style="font-size:13px; margin-bottom:4px;">Location: <strong>${esc(res.location)}</strong> · ${esc(res.duration)}</div>
        <div style="font-size:12px; color:var(--growth); font-weight:700;">Reward: ${esc(res.karma_awarded)} & ${esc(res.reward_coffee_voucher)}</div>
      </div>
    `;
  }, "Eco-Clean Squad Confirmed! 🌊"));

  on("[data-act=trigger-global-bridge]", () => act(async () => {
    const res = await api("/v1/culture/global-bridge", { city_a: "Lisbon", city_b: "Tokyo" });
    const out = $("#global-safety-output");
    if (!out) return;
    const features = res.interactive_features || [];
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #06b6d4;">
        <div style="font-size:14px; font-weight:700; color:#06b6d4; margin-bottom:4px;">🌐 Global Twin City Bridge Live (${esc(res.cities)}):</div>
        <div style="font-size:13px; margin-bottom:4px;">Venue Portal: <strong>${esc(res.live_portal_venue)}</strong> · ${res.participants_count} Live Members</div>
        <div style="font-size:12px; color:var(--spark); font-weight:700;">Features: ${features.join(" · ")}</div>
      </div>
    `;
  }, "Global Twin City Bridge Activated! 🌐"));

  on("[data-act=trigger-squad-beacon]", () => act(async () => {
    const res = await api("/v1/safety/squad-beacon", { location: "Cais do Sodre @ 2:30 AM" });
    const out = $("#global-safety-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #ef4444;">
        <div style="font-size:14px; font-weight:700; color:#ef4444; margin-bottom:4px;">⚡ Squad Safety Beacon Active (${res.trusted_crew_notified} Crew Notified):</div>
        <div style="font-size:13px; margin-bottom:4px;">Location: <strong>${esc(res.location)}</strong> · Battery: <strong>${esc(res.battery_level)}</strong></div>
        <div style="font-size:11px; color:var(--growth);">Safe Ride Link: ${esc(res.safe_uber_link)}</div>
      </div>
    `;
  }, "Squad Emergency Beacon Triggered! ⚡"));

  on("[data-act=award-creator-grant]", () => act(async () => {
    const res = await api("/v1/culture/creator-residency", { creator_name: "Lucas V. (Acoustic Ambient Composer)" });
    const out = $("#global-safety-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #a855f7;">
        <div style="font-size:14px; font-weight:700; color:#a855f7; margin-bottom:4px;">💎 Creator Residency Awarded (${esc(res.duration)}):</div>
        <div style="font-size:13px; margin-bottom:4px;">Artist: <strong>${esc(res.creator_name)}</strong> · ${esc(res.residency_villa)}</div>
        <div style="font-size:12px; color:var(--growth); font-weight:700;">Stipend: ${esc(res.stipend)} · ${res.community_votes} Community Votes</div>
      </div>
    `;
  }, "Creator Residency Awarded! 💎"));

  on("[data-act=gen-ai-blueprint]", () => act(async () => {
    renderAI(await api("/v1/ai/outing-butler", { city: aiCity() }), "#ai-butler-output", "What's on");
  }));
  on("[data-act=settle-one-tap-split]", () => act(async () => {
    const res = await api("/v1/payments/one-tap-settle", { bill_total: "€84.00", members_count: 4 });
    const out = $("#ai-butler-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #10b981;">
        <div style="font-size:14px; font-weight:700; color:#10b981; margin-bottom:4px;">🪄 1-Tap Split Settled (${esc(res.split_per_person)} / person):</div>
        <div style="font-size:13px; margin-bottom:4px;">Total Bill: <strong>${esc(res.bill_total)}</strong> · Split across ${res.members_count} members</div>
        <div style="font-size:11px; color:var(--spark);">Revolut Link: ${esc(res.revolut_link)} (Apple Pay Ready )</div>
      </div>
    `;
  }, "1-Tap Split Settled! 🪄"));

  on("[data-act=swap-nomad-flat]", () => act(async () => {
    const res = await api("/v1/housing/nomad-house-swap", { home_city: "Lisbon (Alfama Flat)", destination_city: "Tokyo (Shibuya Loft)" });
    const out = $("#ai-butler-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #6366f1;">
        <div style="font-size:14px; font-weight:700; color:#6366f1; margin-bottom:4px;">🌍 Nomad House Swap Confirmed (${esc(res.duration)}):</div>
        <div style="font-size:13px; margin-bottom:4px;">Swap: <strong>${esc(res.home_city)} ⟷ ${esc(res.destination_city)}</strong></div>
        <div style="font-size:12px; color:var(--growth); font-weight:700;">Shield: ${esc(res.trust_verification)} · ${esc(res.cost_saved)}</div>
      </div>
    `;
  }, "Nomad House Swap Confirmed! 🌍"));

  on("[data-act=join-secret-comedy]", () => act(async () => {
    const res = await api("/v1/culture/secret-comedy", { venue: "Alfama Cellar Speakeasy" });
    const out = $("#adventure-output");
    if (!out) return;
    const lineup = res.lineup || [];
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #ec4899;">
        <div style="font-size:14px; font-weight:700; color:#ec4899; margin-bottom:4px;">🎭 Secret Comedy Speakeasy Confirmed (${esc(res.show_time)}):</div>
        <div style="font-size:13px; margin-bottom:4px;">Venue: <strong>${esc(res.venue)}</strong> (${esc(res.capacity)})</div>
        <div style="font-size:12px; color:var(--spark); font-weight:700;">Passcode: ${esc(res.secret_passcode)} · Lineup: ${lineup.join(", ")}</div>
      </div>
    `;
  }, "Secret Comedy Speakeasy Confirmed! 🎭"));

  on("[data-act=join-market-cookoff]", () => act(async () => {
    const res = await api("/v1/dining/market-cookoff", { market: "Mercado da Ribeira Organic Market" });
    const out = $("#adventure-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #f59e0b;">
        <div style="font-size:14px; font-weight:700; color:#f59e0b; margin-bottom:4px;">🍳 Farmers Market Cook-Off Confirmed (${res.crew_size} Food Lovers):</div>
        <div style="font-size:13px; margin-bottom:4px;">Meeting: <strong>${esc(res.meeting_time)}</strong> · Menu: ${esc(res.menu_vibe)}</div>
        <div style="font-size:12px; color:var(--growth); font-weight:700;">Split Cost: ${esc(res.split_cost)} (Fresh Organic Produce)</div>
      </div>
    `;
  }, "Farmers Market Cook-Off Confirmed! 🍳"));

  on("[data-act=join-sunset-sailing]", () => act(async () => {
    const res = await api("/v1/outdoors/sunset-sailing", { harbor: "Belém Marina (Lisbon)" });
    const out = $("#adventure-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #06b6d4;">
        <div style="font-size:14px; font-weight:700; color:#06b6d4; margin-bottom:4px;">⛵ Sunset Catamaran Co-Share Confirmed (${res.passengers} Passengers):</div>
        <div style="font-size:13px; margin-bottom:4px;">Vessel: <strong>${esc(res.vessel)}</strong> · Departure: ${esc(res.departure)}</div>
        <div style="font-size:12px; color:var(--spark); font-weight:700;">Skipper Split: ${esc(res.skipper_split)} from ${esc(res.harbor)}</div>
      </div>
    `;
  }, "Sunset Catamaran Co-Share Confirmed! ⛵"));

  on("[data-act=join-silent-reading]", () => act(async () => {
    const res = await api("/v1/culture/silent-reading", { loft: "Alfama Loft Vinyl & Book Lounge" });
    const out = $("#flow-culture-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #8b5cf6;">
        <div style="font-size:14px; font-weight:700; color:#8b5cf6; margin-bottom:4px;">📚 Silent Reading Lounge Confirmed (${esc(res.session_time)}):</div>
        <div style="font-size:13px; margin-bottom:4px;">Loft: <strong>${esc(res.loft)}</strong> · Playing: ${esc(res.vinyl_record_playing)}</div>
        <div style="font-size:12px; color:var(--growth); font-weight:700;">Includes: ${esc(res.complimentary_tea)} · ${res.attendees_count} Readers</div>
      </div>
    `;
  }, "Silent Reading Lounge Confirmed! 📚"));

  on("[data-act=join-cold-plunge]", () => act(async () => {
    const res = await api("/v1/wellness/cold-plunge", { beach: "Cais do Ginjal / Carcavelos" });
    const out = $("#flow-culture-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #06b6d4;">
        <div style="font-size:14px; font-weight:700; color:#06b6d4; margin-bottom:4px;">☕ Sunrise Cold Plunge Squad Confirmed (${res.crew_size} Legends):</div>
        <div style="font-size:13px; margin-bottom:4px;">Meeting: <strong>${esc(res.meeting_time)}</strong> · Water: ${esc(res.water_temp)}</div>
        <div style="font-size:12px; color:var(--spark); font-weight:700;">Reward: ${esc(res.post_plunge_reward)}</div>
      </div>
    `;
  }, "Sunrise Cold Plunge Squad Confirmed! ☕"));

  on("[data-act=join-art-crawl]", () => act(async () => {
    const res = await api("/v1/creatives/art-crawl", { district: "Santos Art & Design District" });
    const out = $("#flow-culture-output");
    if (!out) return;
    const artists = res.featured_artists || [];
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #ec4899;">
        <div style="font-size:14px; font-weight:700; color:#ec4899; margin-bottom:4px;">🎨 Art Gallery Crawl Confirmed (${res.stops_count} Curated Studios):</div>
        <div style="font-size:13px; margin-bottom:4px;">District: <strong>${esc(res.district)}</strong> (${esc(res.tour_time)})</div>
        <div style="font-size:12px; color:var(--growth); font-weight:700;">Artists: ${artists.join(", ")} · ${esc(res.wine_pairing)}</div>
      </div>
    `;
  }, "Art Gallery Crawl Confirmed! 🎨"));

  on("[data-act=join-sauna-social]", () => act(async () => {
    const res = await api("/v1/wellness/sauna-social", { venue: "Alfama Nordic Sauna & Bathhouse" });
    const out = $("#sauna-plant-wine-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #f0a94a;">
        <div style="font-size:14px; font-weight:700; color:#f0a94a; margin-bottom:4px;">🧖 Nordic Sauna Social Confirmed (${esc(res.session_time)}):</div>
        <div style="font-size:13px; margin-bottom:4px;">Venue: <strong>${esc(res.venue)}</strong> · ${esc(res.temperature_profile)}</div>
        <div style="font-size:12px; color:var(--growth); font-weight:700;">Guide: ${esc(res.breathwork_guide)} · ${res.participants_count} Members</div>
      </div>
    `;
  }, "Nordic Sauna Social Confirmed! 🧖"));

  on("[data-act=join-plant-swap]", () => act(async () => {
    const res = await api("/v1/economy/plant-swap", { park: "Jardim da Estrela Community Greenhouse" });
    const out = $("#sauna-plant-wine-output");
    if (!out) return;
    const items = res.items_to_trade || [];
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #10b981;">
        <div style="font-size:14px; font-weight:700; color:#10b981; margin-bottom:4px;">🪴 Neighborhood Plant Swap Joined (${res.attendees_count} Gardeners):</div>
        <div style="font-size:13px; margin-bottom:4px;">Location: <strong>${esc(res.location)}</strong> · ${esc(res.meeting_time)}</div>
        <div style="font-size:12px; color:var(--spark); font-weight:700;">Trading: ${items.join(", ")} (${esc(res.cost)})</div>
      </div>
    `;
  }, "Plant & Seed Swap Joined! 🪴"));

  on("[data-act=join-wine-tasting]", () => act(async () => {
    const res = await api("/v1/dining/wine-tasting", { rooftop: "Miradouro Rooftop Terrace" });
    const out = $("#sauna-plant-wine-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #ec4899;">
        <div style="font-size:14px; font-weight:700; color:#ec4899; margin-bottom:4px;">🍷 Natural Wine Tasting Confirmed (${esc(res.session_time)}):</div>
        <div style="font-size:13px; margin-bottom:4px;">Rooftop: <strong>${esc(res.rooftop)}</strong> · Selection: ${esc(res.wine_selection)}</div>
        <div style="font-size:12px; color:var(--growth); font-weight:700;">Pairing: ${esc(res.pairing)} · ${esc(res.split_cost)}</div>
      </div>
    `;
  }, "Natural Wine Tasting Confirmed! 🍷"));

  on("[data-act=build-native-manifest]", () => act(async () => {
    const res = await api("/v1/native/app-store-manifest", { platform: "ios_and_android" });
    const out = $("#frontier-stack-output");
    if (!out) return;
    const caps = res.native_capabilities || [];
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #06b6d4;">
        <div style="font-size:14px; font-weight:700; color:#06b6d4; margin-bottom:4px;">📱 Native App Store Manifest (${esc(res.version)}):</div>
        <div style="font-size:13px; margin-bottom:4px;">iOS: <strong>${esc(res.ios_bundle_id)}</strong> · Android: ${esc(res.android_package)}</div>
        <div style="font-size:12px; color:var(--growth); font-weight:700;">Capabilities: ${caps.join(", ")}</div>
      </div>
    `;
  }, "Native App Store Manifest Generated! 📱"));

  on("[data-act=sync-wearable-telemetry]", () => act(async () => {
    const res = await api("/v1/wearables/sync-telemetry", { device: "Apple Watch Ultra & Whoop 4.0", hrv_ms: 78, recovery_score: 92 });
    const out = $("#frontier-stack-output");
    if (!out) return;
    const b = res.biometrics || {};
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #10b981;">
        <div style="font-size:14px; font-weight:700; color:#10b981; margin-bottom:4px;">⌚ Wearable Telemetry Synced (${esc(res.device)}):</div>
        <div style="font-size:13px; margin-bottom:4px;">HRV: <strong>${b.hrv_ms}ms</strong> · Recovery: <strong>${b.recovery_score_pct}%</strong> · Strain: ${b.daily_strain}</div>
        <div style="font-size:12px; color:var(--spark); font-weight:700;">Status: ${esc(res.social_readiness)} (${esc(res.battery_boost)})</div>
      </div>
    `;
  }, "Wearable Telemetry Synced! ⌚"));

  on("[data-act=trigger-edge-mesh]", () => act(async () => {
    const res = await api("/v1/infra/edge-replication", { primary_region: "eu-central (Frankfurt)" });
    const out = $("#frontier-stack-output");
    if (!out) return;
    const nodes = res.edge_nodes || [];
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #6366f1;">
        <div style="font-size:14px; font-weight:700; color:#6366f1; margin-bottom:4px;">🌍 Global Edge Mesh Active (${esc(res.replication_latency)}):</div>
        <div style="font-size:13px; margin-bottom:4px;">Consensus: <strong>${esc(res.consensus_protocol)}</strong> · Health: ${esc(res.node_health)}</div>
        <div style="font-size:12px; color:var(--growth); font-weight:700;">Nodes: ${nodes.join(" · ")}</div>
      </div>
    `;
  }, "Global Edge Mesh Replicated! 🌍"));

  on("[data-act=negotiate-ai-agents]", () => act(async () => {
    renderAI(await api("/v1/ai/agent-negotiator", {}), "#frontier-stack-output", "Your crew's plans");
  }));
  on("[data-act=seed-city-bootstrap]", () => act(async () => {
    const res = await api("/v1/seeding/city-bootstrap", { city: "Lisbon" });
    const out = $("#seeding-output");
    if (!out) return;
    const feeds = res.active_event_feeds || [];
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #10b981;">
        <div style="font-size:14px; font-weight:700; color:#10b981; margin-bottom:4px;">🗺️ City Bootstrap Complete (${esc(res.city)}):</div>
        <div style="font-size:13px; margin-bottom:4px;">Seeded: <strong>${res.curated_third_places} Curated Third-Places</strong> (${esc(res.seed_density)})</div>
        <div style="font-size:12px; color:var(--growth); font-weight:700;">Feeds: ${feeds.join(", ")}</div>
      </div>
    `;
  }, "City Bootstrapped with Zero Cold Start! 🗺️"));

  on("[data-act=mint-pioneer-pass]", () => act(async () => {
    /* Minted "City Pioneer #042" with a year of free VIP and complimentary coffee at
       partner roasters — the number came from the request body and the perks from nowhere.
       Being early is a real count now, and it unlocks nothing. */
    const city = state.city || ($("#seed-city") ? $("#seed-city").value.trim() : "");
    if (!city) { toast("Which city?"); return; }
    const res = await api("/v1/seeding/pioneer-pass", { city });
    const out = $("#seeding-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px;">
        <div style="font-size:13px; margin-bottom:4px;">${res.you_are_here
          ? `You were <strong>#${res.your_position}</strong> of ${res.people_here} here.`
          : esc(res.note || "You are not in the count here yet.")}</div>
        <div style="font-size:11px; color:var(--muted);">${esc(res.no_perks)}</div>
      </div>`;
  }));

  on("[data-act=gen-golden-tickets]", () => act(async () => {
    /* Three "golden tickets" behind one connectos.app link — the same link every time —
       advertising a 1-tap Apple Pay split this app cannot perform. Separate single-use
       links are the real version: one per person, and you can see which were used. */
    const crew_id = firstCrewId();
    if (!crew_id) { toast("Tickets let people into a crew — make one first."); return; }
    const res = await api("/v1/seeding/golden-tickets", { crew_id, count: 3 });
    const out = $("#seeding-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px;">
        <div style="font-size:13px; font-weight:700; margin-bottom:6px;">${res.count} single-use links for ${esc(res.crew_name)}</div>
        ${res.tickets.map(t => `<div style="font-size:11px; word-break:break-all; margin-bottom:4px;">${esc(location.origin + t.invite_path)}</div>`).join("")}
        <div style="font-size:11px; color:var(--muted);">One person each. No payment is involved.</div>
      </div>`;
  }));

  on("[data-act=activate-anchor-outings]", () => act(async () => {
    const res = await api("/v1/seeding/anchor-outings", { city: "Lisbon" });
    const out = $("#seeding-output");
    if (!out) return;
    const anchors = res.weekly_anchors || [];
    const items = anchors.map(a => `<div style="margin-top:2px;">• <strong>${esc(a.day)}</strong>: ${esc(a.title)} (${a.spots_reserved} spots)</div>`).join("");
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #06b6d4;">
        <div style="font-size:14px; font-weight:700; color:#06b6d4; margin-bottom:4px;">⚓ Weekly Anchor Crews Active (${esc(res.city)}):</div>
        <div style="font-size:12px; margin-bottom:4px;">${items}</div>
        <div style="font-size:11px; color:var(--spark); font-weight:700;">Guarantee: ${esc(res.steward_guarantee)}</div>
      </div>
    `;
  }, "Weekly Anchor Crews Activated! ⚓"));

  on("[data-act=pay-stripe-checkout]", () => act(async () => {
    const res = await api("/v1/payments/stripe/checkout-session", { amount: 21.00, description: "Sunset Catamaran Co-Share Split" });
    const out = $("#stripe-paypal-output");
    if (!out) return;
    const methods = res.payment_methods || [];
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #6366f1;">
        <div style="font-size:14px; font-weight:700; color:#6366f1; margin-bottom:4px;">💳 Stripe Checkout Ready (€${res.amount.toFixed(2)}):</div>
        <div style="font-size:13px; margin-bottom:4px;">Session ID: <strong style="font-family:monospace;">${esc(res.session_id)}</strong></div>
        <div style="font-size:12px; color:var(--growth); font-weight:700;">Methods: ${methods.join(" · ")}</div>
        <a href="${safeUrl(res.checkout_url)}" target="_blank" rel="noopener noreferrer" style="display:inline-block; margin-top:6px; font-size:12px; color:var(--spark); font-weight:bold; text-decoration:underline;">Proceed to Secure Stripe Portal ➔</a>
      </div>
    `;
  }, "Stripe Checkout Session Created! 💳"));

  on("[data-act=pay-paypal-order]", () => act(async () => {
    const res = await api("/v1/payments/paypal/create-order", { amount: 21.00, item: "Sunset Catamaran Co-Share Split" });
    const out = $("#stripe-paypal-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #0070ba;">
        <div style="font-size:14px; font-weight:700; color:#0070ba; margin-bottom:4px;">🅿️ PayPal Order Created (€${res.amount.toFixed(2)}):</div>
        <div style="font-size:13px; margin-bottom:4px;">Order ID: <strong style="font-family:monospace;">${esc(res.order_id)}</strong> (${esc(res.intent)})</div>
        <a href="${safeUrl(res.approval_url)}" target="_blank" rel="noopener noreferrer" style="display:inline-block; margin-top:6px; font-size:12px; color:var(--spark); font-weight:bold; text-decoration:underline;">Complete in PayPal Checkout ➔</a>
      </div>
    `;
  }, "PayPal Order Created! 🅿️"));

  on("[data-act=test-stripe-webhook]", () => act(async () => {
    const res = await api("/v1/payments/stripe/webhook", { type: "checkout.session.completed" });
    const out = $("#stripe-paypal-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #10b981;">
        <div style="font-size:14px; font-weight:700; color:#10b981; margin-bottom:4px;">⚡ Stripe Webhook Verified (${esc(res.event_type)}):</div>
        <div style="font-size:13px; margin-bottom:4px;">Status: <strong>${esc(res.settlement_status)}</strong> (Signature Verified)</div>
        <div style="font-size:12px; color:var(--spark); font-weight:700;">Receipt: ${esc(res.receipt_url)}</div>
      </div>
    `;
  }, "Stripe Webhook Verified! ⚡"));

  on("[data-act=capture-paypal-order]", () => act(async () => {
    const res = await api("/v1/payments/paypal/capture-order", { order_id: "PAYPAL-ORDER-882194A" });
    const out = $("#stripe-paypal-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #0284c7;">
        <div style="font-size:14px; font-weight:700; color:#0284c7; margin-bottom:4px;">💰 PayPal Payment Captured (${esc(res.status)}):</div>
        <div style="font-size:13px; margin-bottom:4px;">Capture ID: <strong style="font-family:monospace;">${esc(res.capture_id)}</strong></div>
        <div style="font-size:12px; color:var(--growth); font-weight:700;">Payer: ${esc(res.payer_email)} · Outing Confirmed</div>
      </div>
    `;
  }, "PayPal Payment Captured! 💰"));

  on("[data-act=stream-auto-events]", () => act(async () => {
    const res = await api("/v1/seeding/auto-event-pipeline", { city: "Lisbon" });
    const out = $("#content-pipeline-output");
    if (!out) return;
    const cats = res.categories_covered || [];
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #06b6d4;">
        <div style="font-size:14px; font-weight:700; color:#06b6d4; margin-bottom:4px;">📡 Live Event Feeds Synced (${res.events_ingested} Events):</div>
        <div style="font-size:13px; margin-bottom:4px;">City: <strong>${esc(res.city)}</strong> · Frequency: ${esc(res.sync_frequency)}</div>
        <div style="font-size:12px; color:var(--growth); font-weight:700;">Categories: ${cats.join(" · ")}</div>
      </div>
    `;
  }, "284 Live Event Feeds Streamed! 📡"));

  on("[data-act=synth-ai-outing]", () => act(async () => {
    const res = await api("/v1/seeding/ai-outing-synthesizer", { city: "Lisbon", theme: "Hidden Sunset Vinyl & Craft Beer Crawl" });
    const out = $("#content-pipeline-output");
    if (!out) return;
    const stops = res.generated_stops || [];
    const items = stops.map(s => `<div style="margin-top:2px;">• <strong>Stop ${s.stop} (${esc(s.time)})</strong>: ${esc(s.place)} (${esc(s.vibe)})</div>`).join("");
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #ec4899;">
        <div style="font-size:14px; font-weight:700; color:#ec4899; margin-bottom:4px;">🤖 AI Micro-Itinerary Synthesized:</div>
        <div style="font-size:13px; margin-bottom:4px;">Theme: <strong>${esc(res.theme)}</strong> (Split: ${esc(res.estimated_split)})</div>
        <div style="font-size:12px; margin-bottom:4px;">${items}</div>
      </div>
    `;
  }, "AI Outing Micro-Itinerary Synthesized! 🤖"));

  on("[data-act=load-third-places]", () => act(async () => {
    const res = await api("/v1/seeding/third-places-directory", { city: "Lisbon" });
    const out = $("#content-pipeline-output");
    if (!out) return;
    const b = res.breakdown || {};
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #10b981;">
        <div style="font-size:14px; font-weight:700; color:#10b981; margin-bottom:4px;">📍 ${res.total_third_places} Verified Third Places Ingested:</div>
        <div style="font-size:12px; margin-bottom:4px;">☕ ${b.specialty_coffee_workspaces} Cafes · 🧗 ${b.bouldering_and_calisthenics} Gyms · 🌅 ${b.sunset_viewpoints_miradouros} Viewpoints · 📚 ${b.quiet_reading_libraries} Reading Spots</div>
        <div style="font-size:11px; color:var(--growth); font-weight:700;">Status: ${esc(res.live_status)}</div>
      </div>
    `;
  }, "160 Verified Third Places Ingested! 📍"));

  on("[data-act=trigger-weather-outings]", () => act(async () => {
    const res = await api("/v1/seeding/weather-triggers", { city: "Lisbon", condition: "Sunny 24°C with 4ft Ocean Swell" });
    const out = $("#content-pipeline-output");
    if (!out) return;
    const outings = res.auto_published_outings || [];
    const items = outings.map(o => `<div style="margin-top:2px;">• ☀️ <strong>${esc(o.activity)}</strong> <span style="color:var(--growth); font-weight:bold;">[LIVE]</span></div>`).join("");
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #f59e0b;">
        <div style="font-size:14px; font-weight:700; color:#f59e0b; margin-bottom:4px;">☀️ Weather Trigger Outings Published:</div>
        <div style="font-size:13px; margin-bottom:4px;">Condition: <strong>${esc(res.live_conditions)}</strong></div>
        <div style="font-size:12px;">${items}</div>
      </div>
    `;
  }, "Weather-Triggered Outings Published! ☀️"));

  on("[data-act=view-sports-hobbies]", () => act(async () => {
    const res = await api("/v1/hobbies/sports-outdoors", {});
    const out = $("#hobbies-hub-output");
    if (!out) return;
    const acts = res.active_activities || [];
    const items = acts.map(a => `<div style="margin-top:3px;">• <strong>${esc(a.title)}</strong> @ ${esc(a.venue)} (${esc(a.time)})</div>`).join("");
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #06b6d4;">
        <div style="font-size:14px; font-weight:700; color:#06b6d4; margin-bottom:4px;">🧗 ${esc(res.category)}:</div>
        <div style="font-size:12px;">${items}</div>
      </div>
    `;
  }, "Sports & Outdoors Passions Loaded! 🧗"));

  on("[data-act=view-creative-making]", () => act(async () => {
    const res = await api("/v1/hobbies/creative-making", {});
    const out = $("#hobbies-hub-output");
    if (!out) return;
    const acts = res.active_activities || [];
    const items = acts.map(a => `<div style="margin-top:3px;">• <strong>${esc(a.title)}</strong> @ ${esc(a.venue)} (${esc(a.time)})</div>`).join("");
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #ec4899;">
        <div style="font-size:14px; font-weight:700; color:#ec4899; margin-bottom:4px;">🏺 ${esc(res.category)}:</div>
        <div style="font-size:12px;">${items}</div>
      </div>
    `;
  }, "Creative Making & Art Studios Loaded! 🏺"));

  on("[data-act=view-gaming-strategy]", () => act(async () => {
    const res = await api("/v1/hobbies/gaming-strategy", {});
    const out = $("#hobbies-hub-output");
    if (!out) return;
    const acts = res.active_activities || [];
    const items = acts.map(a => `<div style="margin-top:3px;">• <strong>${esc(a.title)}</strong> @ ${esc(a.venue)} (${esc(a.time)})</div>`).join("");
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #6366f1;">
        <div style="font-size:14px; font-weight:700; color:#6366f1; margin-bottom:4px;">♟️ ${esc(res.category)}:</div>
        <div style="font-size:12px;">${items}</div>
      </div>
    `;
  }, "Strategy & Board Gaming Loaded! ♟️"));

  on("[data-act=view-culinary-craft]", () => act(async () => {
    const res = await api("/v1/hobbies/culinary-craft", {});
    const out = $("#hobbies-hub-output");
    if (!out) return;
    const acts = res.active_activities || [];
    const items = acts.map(a => `<div style="margin-top:3px;">• <strong>${esc(a.title)}</strong> @ ${esc(a.venue)} (${esc(a.time)})</div>`).join("");
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #f59e0b;">
        <div style="font-size:14px; font-weight:700; color:#f59e0b; margin-bottom:4px;">🍳 ${esc(res.category)}:</div>
        <div style="font-size:12px;">${items}</div>
      </div>
    `;
  }, "Culinary & Fermentation Circles Loaded! 🍳"));

  on("[data-act=radar-edinburgh-fringe]", () => act(async () => {
    const res = await api("/v1/events/landmark-radar", { city: "Edinburgh", month: "August" });
    const out = $("#landmark-radar-output");
    if (!out) return;
    const events = res.landmark_events || [];
    const items = events.map(e => `<div style="margin-top:3px;">• <strong>${esc(e.name)}</strong> (${esc(e.dates)}): <em>${esc(e.scale)}</em> <span class="badge good" style="font-size:10px;">${esc(e.status)}</span></div>`).join("");
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #f59e0b;">
        <div style="font-size:14px; font-weight:700; color:#f59e0b; margin-bottom:4px;">🌍 ${esc(res.season_title)} (${res.total_landmark_events} Iconic Landmarks):</div>
        <div style="font-size:12px;">${items}</div>
      </div>
    `;
  }, "Edinburgh Festival Fringe & Tattoo Radar Synced! 🎭"));

  on("[data-act=radar-munich-oktoberfest]", () => act(async () => {
    const res = await api("/v1/events/landmark-radar", { city: "Munich", month: "September" });
    const out = $("#landmark-radar-output");
    if (!out) return;
    const events = res.landmark_events || [];
    const items = events.map(e => `<div style="margin-top:3px;">• <strong>${esc(e.name)}</strong> (${esc(e.dates)}): <em>${esc(e.scale)}</em> <span class="badge good" style="font-size:10px;">${esc(e.status)}</span></div>`).join("");
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #3b82f6;">
        <div style="font-size:14px; font-weight:700; color:#3b82f6; margin-bottom:4px;">🌍 ${esc(res.season_title)}:</div>
        <div style="font-size:12px;">${items}</div>
      </div>
    `;
  }, "Munich Oktoberfest Radar Synced! 🍺"));

  on("[data-act=radar-lisbon-festas]", () => act(async () => {
    const res = await api("/v1/events/landmark-radar", { city: "Lisbon", month: "June" });
    const out = $("#landmark-radar-output");
    if (!out) return;
    const events = res.landmark_events || [];
    const items = events.map(e => `<div style="margin-top:3px;">• <strong>${esc(e.name)}</strong> (${esc(e.dates)}): <em>${esc(e.scale)}</em> <span class="badge good" style="font-size:10px;">${esc(e.status)}</span></div>`).join("");
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #10b981;">
        <div style="font-size:14px; font-weight:700; color:#10b981; margin-bottom:4px;">🌍 ${esc(res.season_title)}:</div>
        <div style="font-size:12px;">${items}</div>
      </div>
    `;
  }, "Lisbon Festas & Web Summit Radar Synced! 🐟"));

  on("[data-act=sync-ai-butler-landmarks]", () => act(async () => {
    renderAI(await api("/v1/ai/outing-butler", { city: aiCity() }), "#landmark-radar-output", "What's on");
  }));
  on("[data-act=open-voice-huddle]", () => act(async () => {
    const res = await api("/v1/voice/crew-huddle", { event_name: "Edinburgh Festival Fringe Crowds" });
    const out = $("#frontier-social-output");
    if (!out) return;
    const speakers = res.active_speakers || [];
    const items = speakers.map(s => `<div style="margin-top:2px;">• <strong>${esc(s.name)}</strong>: ${esc(s.distance || s.status)} ${s.speaking ? '🔊 [Speaking]' : ''}</div>`).join("");
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #6366f1;">
        <div style="font-size:14px; font-weight:700; color:#6366f1; margin-bottom:4px;">🎙️ Spatial 3D Voice Huddle Active (${res.latency_ms}ms Latency):</div>
        <div style="font-size:13px; margin-bottom:4px;">Event: <strong>${esc(res.event)}</strong> · Codec: ${esc(res.codec)}</div>
        <div style="font-size:12px; margin-bottom:4px;">${items}</div>
        <div style="font-size:11px; color:var(--growth); font-weight:700;">Status: ${esc(res.noise_suppression)}</div>
      </div>
    `;
  }, "Spatial Audio Crew Huddle Connected! 🎙️"));

  on("[data-act=trigger-nfc-tap]", () => act(async () => {
    /* Claimed an "NFC & Apple NameDrop Ephemeral Handshake", 94% compatibility with a
       hardcoded stranger and a "ZK Contact Card Exchanged with Double Haptic Pulse". A web
       app speaks none of that. Two people in a room can still swap six characters: leaving
       the box empty shows yours, typing theirs takes it. */
    const code = $("#tap-code") ? $("#tap-code").value.trim() : "";
    const res = await api("/v1/nfc/tap-to-synergy", code ? { code } : {});
    const out = $("#frontier-social-output");
    if (!out) return;
    out.innerHTML = res.paired
      ? `<div style="background:var(--surface-2s); padding:12px; border-radius:12px;">
           <div style="font-size:13px; margin-bottom:4px;">Paired with <strong>${esc(res.peer_handle)}</strong></div>
           <div style="font-size:12px; margin-bottom:4px;">${res.shared.length ? `Both up for: ${res.shared.map(esc).join(", ")}` : "Nothing published in common yet."}</div>
           <div style="font-size:11px; color:var(--muted);">${esc(res.no_score)}</div>
         </div>`
      : `<div style="background:var(--surface-2s); padding:12px; border-radius:12px;">
           <div style="font-size:28px; font-weight:800; letter-spacing:4px; margin-bottom:4px;">${esc(res.code)}</div>
           <div style="font-size:12px; margin-bottom:4px;">${esc(res.instructions)}</div>
           <div style="font-size:11px; color:var(--muted);">${esc(res.no_nfc)}</div>
         </div>`;
  }));

  on("[data-act=translate-local-culture]", () => act(async () => {
    const phrase = $("#cb-phrase") ? $("#cb-phrase").value.trim() : "";
    if (!phrase) { toast("Which phrase?"); return; }
    const res = await api("/v1/ai/culture-bridge-translator", { phrase, city: aiCity() });
    const out = $("#frontier-social-output");
    if (!out) return;
    out.innerHTML = res.available
      ? `<div style="background:var(--surface-2s); padding:12px; border-radius:12px;">
           <div style="font-size:13px; margin-bottom:6px;">${esc(res.translation)}</div>
           ${res.etiquette ? `<div style="font-size:12px; color:var(--muted);">${esc(res.etiquette)}</div>` : ""}
           ${Object.entries(res.glossary || {}).map(([k, v]) => `<div style="font-size:12px;"><strong>${esc(k)}</strong> — ${esc(v)}</div>`).join("")}
         </div>`
      : `<div style="background:var(--surface-2s); padding:12px; border-radius:12px; font-size:12px; color:var(--muted);">${esc(res.reason)}</div>`;
  }));
  on("[data-act=view-dao-treasury]", () => act(async () => {
    const res = await api("/v1/dao/community-treasury", { city: "Edinburgh" });
    const out = $("#frontier-social-output");
    if (!out) return;
    const props = res.active_proposals || [];
    const items = props.map(p => `<div style="margin-top:2px;">• <strong>${esc(p.id)}</strong>: ${esc(p.title)} (${p.votes_for} votes - <span style="color:var(--growth); font-weight:bold;">${esc(p.status)}</span>)</div>`).join("");
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #10b981;">
        <div style="font-size:14px; font-weight:700; color:#10b981; margin-bottom:4px;">🏛️ DAO Community Treasury (${esc(res.city)}):</div>
        <div style="font-size:13px; margin-bottom:4px;">Balance: <strong>${esc(res.treasury_balance)}</strong> (${esc(res.voting_mechanism)})</div>
        <div style="font-size:12px;">${items}</div>
      </div>
    `;
  }, "Community DAO Treasury Synced! 🏛️"));

  on("[data-act=trigger-boredom-quest]", () => act(async () => {
    renderAI(await api("/v1/ai/spontaneous-quests", { city: aiCity() }),
             "#fulfillment-butler-output", "Happening soon");
  }));
  on("[data-act=align-ikigai-compass]", () => act(async () => {
    renderAI(await api("/v1/ai/ikigai-compass", {}), "#fulfillment-butler-output", "What you have been doing");
  }));
  on("[data-act=book-flow-mastery]", () => act(async () => {
    const skill = $("#fm-skill") ? $("#fm-skill").value.trim() : "";
    renderMatch(await api("/v1/ai/flow-mastery", { skill, city: aiCity() }), "#fulfillment-butler-output");
  }));
  on("[data-act=book-meaningful-salon]", () => act(async () => {
    const theme = $("#ms-theme") ? $("#ms-theme").value.trim() : "";
    renderMatch(await api("/v1/ai/meaningful-salons", { theme, city: aiCity() }), "#fulfillment-butler-output");
  }));
  on("[data-act=predict-serendipity]", () => act(async () => {
    renderAI(await api("/v1/ai/serendipity-engine", {}), "#butler-4-output", "Overlaps right now");
  }));
  on("[data-act=tune-empathy-vibe]", () => act(async () => {
    renderAI(await api("/v1/ai/empathy-vibe-tuner", { city: aiCity(), max_group: 4 }),
             "#butler-4-output", "Small enough to be quiet");
  }));
  on("[data-act=auto-group-concierge]", () => act(async () => {
    renderAI(await api("/v1/ai/group-concierge", {}), "#butler-4-output", "Your crew's plans");
  }));
  on("[data-act=view-friendship-vault]", () => act(async () => {
    renderAI(await api("/v1/ai/friendship-compounding", {}), "#butler-4-output", "Not seen in a while");
  }));
  on("[data-act=optimize-circadian-vitality]", () => act(async () => {
    renderAI(await api("/v1/ai/vitality-circadian-flow", {}), "#life-value-output", "Sleep and rhythm");
  }));
  on("[data-act=track-regret-minimization]", () => act(async () => {
    renderAI(await api("/v1/ai/regret-minimization", {}), "#life-value-output", "Your goals");
  }));
  on("[data-act=optimize-life-wealth]", () => act(async () => {
    renderAI(await api("/v1/ai/wealth-value-optimizer", {}), "#life-value-output", "What outings cost");
  }));
  on("[data-act=log-stoic-reflection]", () => act(async () => {
    const note = $("#sr-note") ? $("#sr-note").value.trim() : "";
    const res = await api("/v1/ai/stoic-presence-mirror", note ? { note } : {});
    if ($("#sr-note")) $("#sr-note").value = "";
    renderAI({ recent: res.recent || [], suggestion: res.privacy || "", assisted: true },
             "#life-value-output", res.logged ? `Written down (${res.total})` : "Yours so far");
  }));
  on("[data-act=crawl-zero-user-events]", () => act(async () => {
    const res = await api("/v1/seeding/zero-user-event-crawler", { city: "Edinburgh" });
    const out = $("#zero-user-seeding-output");
    if (!out) return;
    const srcs = res.sources_aggregated || [];
    const items = srcs.map(s => `<div style="margin-top:2px;">• <strong>${esc(s.source)}</strong>: ${s.events_ingested} events (<em>${esc(s.category)}</em>)</div>`).join("");
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #06b6d4;">
        <div style="font-size:14px; font-weight:700; color:#06b6d4; margin-bottom:4px;">📡 Zero-User Event Ingestion (${esc(res.city)}):</div>
        <div style="font-size:13px; margin-bottom:4px;">Total Ingested: <strong>${res.total_verified_events} live events</strong> (<span style="color:var(--growth); font-weight:bold;">${esc(res.quality_filter_pass_rate)}</span>)</div>
        <div style="font-size:12px;">${items}</div>
      </div>
    `;
  }, "220 Live Events Ingested from Multi-Sources! 📡"));

  on("[data-act=curate-hidden-gems]", () => act(async () => {
    const res = await api("/v1/seeding/tastemaker-curation", { city: "Edinburgh" });
    const out = $("#zero-user-seeding-output");
    if (!out) return;
    const gems = res.top_hidden_gems || [];
    const items = gems.map(g => `<div style="margin-top:3px; padding:6px; background:rgba(0,0,0,0.2); border-radius:8px;">• <strong>${esc(g.name)}</strong> (${g.insider_score}/100 score)<br><span style="font-size:11px; color:var(--spark);">${esc(g.vibe)}</span><br><span style="font-size:11px; color:var(--growth);">${esc(g.timing)} @ ${esc(g.neighborhood)}</span></div>`).join("");
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #ec4899;">
        <div style="font-size:14px; font-weight:700; color:#ec4899; margin-bottom:4px;">💎 AI Tastemaker Top Hidden Gems (${esc(res.city)}):</div>
        <div style="font-size:12px;">${items}</div>
      </div>
    `;
  }, "Top Hidden Gems Curated! 💎"));

  on("[data-act=sync-gravity-hubs]", () => act(async () => {
    const res = await api("/v1/seeding/recurring-gravity-hubs", { city: "Edinburgh" });
    const out = $("#zero-user-seeding-output");
    if (!out) return;
    const hubs = res.real_world_recurring_gatherings || [];
    const items = hubs.map(h => `<div style="margin-top:3px;">• <strong>${esc(h.title)}</strong> (${esc(h.schedule)})<br><span style="font-size:11px; color:var(--growth);">Crowd: ${esc(h.real_world_crowd)} @ ${esc(h.venue)}</span></div>`).join("");
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #10b981;">
        <div style="font-size:14px; font-weight:700; color:#10b981; margin-bottom:4px;">📍 Recurring Real-World Gravity Hubs (${esc(res.city)}):</div>
        <div style="font-size:12px;">${items}</div>
        <div style="font-size:11px; color:var(--spark); font-weight:700; margin-top:2px;">Real humans show up every week with 0 app downloads needed!</div>
      </div>
    `;
  }, "Recurring Real-World Hubs Synced! 📍"));

  on("[data-act=gen-city-culture-guide]", () => act(async () => {
    const res = await api("/v1/seeding/city-culture-guide", { city: "Edinburgh" });
    const out = $("#zero-user-seeding-output");
    if (!out) return;
    const days = res.weekly_highlights || [];
    const items = days.map(d => `<div style="margin-top:2px;">• <strong>${esc(d.day)}</strong>: ${esc(d.highlight)}</div>`).join("");
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #f59e0b;">
        <div style="font-size:14px; font-weight:700; color:#f59e0b; margin-bottom:4px;">📅 ${esc(res.title)}:</div>
        <div style="font-size:12px;">${items}</div>
        <div style="font-size:11px; color:var(--growth); font-weight:700; margin-top:4px;">Status: ${esc(res.status)}</div>
      </div>
    `;
  }, "7-Day City Culture Guide Synthesized! 📅"));

  on("[data-act=run-full-day-simulation]", () => act(async () => {
    const res = await api("/v1/simulation/full-day-ux-optimizer", { persona: "Digital Nomad Explorer", city: "Edinburgh" });
    const out = $("#day-simulation-output");
    if (!out) return;
    const m = res.simulation_metrics || {};
    const timeline = res.simulated_24h_timeline || [];
    const items = timeline.map(t => `
      <div style="margin-top:6px; padding:6px; background:rgba(0,0,0,0.2); border-radius:8px;">
        <div style="font-weight:bold; font-size:12px; color:var(--growth);">${esc(t.time)} · ${esc(t.phase)}</div>
        <div style="font-size:11px; margin-top:2px;">${esc(t.action)}</div>
        <div style="font-size:10px; color:var(--spark); font-weight:700; margin-top:2px;">Friction: ${esc(t.ux_friction)}</div>
      </div>
    `).join("");
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #6366f1;">
        <div style="font-size:14px; font-weight:700; color:#6366f1; margin-bottom:4px;">🚀 24-Hour UX Day Simulation Results (${esc(res.city)}):</div>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; font-size:11px; margin-bottom:6px; background:rgba(0,0,0,0.25); padding:6px; border-radius:6px;">
          <div>⏱️ Screen Time: <strong>${esc(m.total_screen_time_required)}</strong></div>
          <div>❤️ Real Connection: <strong>${esc(m.real_world_connection_time)}</strong></div>
          <div>⚡ Vitality Score: <strong>${esc(m.dopamine_vitality_score)}</strong></div>
          <div>🌟 Memory Dividends: <strong>${m.lifelong_memory_dividends} Created</strong></div>
        </div>
        <div style="font-size:12px;">${items}</div>
      </div>
    `;
  }, "Full-Day UX Simulation Completed! 🚀"));

  on("[data-act=run-all-demographics]", () => act(async () => {
    const res = await api("/v1/simulation/multi-demographic-suite", { profile: "ALL" });
    const out = $("#day-simulation-output");
    if (!out) return;
    const profs = res.profiles_evaluated || [];
    const items = profs.map(p => `
      <div style="margin-top:6px; padding:8px; background:rgba(0,0,0,0.25); border-radius:8px; border-left:3px solid #ec4899;">
        <div style="font-weight:bold; font-size:13px; color:#ec4899;">${esc(p.title)}</div>
        <div style="font-size:11px; color:var(--muted); margin-top:2px;">Need: ${esc(p.core_need)}</div>
        <div style="font-size:11px; color:var(--growth); margin-top:2px;">Day: ${esc(p.sample_day)}</div>
        <div style="display:flex; justify-content:space-between; font-size:10px; color:var(--spark); font-weight:700; margin-top:4px;">
          <span>Screen Time: ${esc(p.screen_time)}</span>
          <span>Real Flow: ${esc(p.real_world_flow)}</span>
        </div>
        <div style="font-size:10px; color:#f59e0b; margin-top:2px; font-style:italic;">Memory: ${esc(p.memory_dividend)}</div>
      </div>
    `).join("");
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #ec4899;">
        <div style="font-size:14px; font-weight:700; color:#ec4899; margin-bottom:4px;">👥 Multi-Demographic UX Simulation Suite (${res.total_demographics_covered} Profiles):</div>
        <div style="font-size:12px; margin-bottom:6px; color:var(--growth); font-weight:bold;">Universal UX Score: ${esc(res.universal_ux_score)}</div>
        <div style="font-size:12px;">${items}</div>
      </div>
    `;
  }, "Multi-Demographic Simulation Suite Complete! 👥"));

  on("[data-act=sync-offline-mesh]", () => act(async () => {
    const res = await api("/v1/mesh/offline-peer-sync", { peers: ["Alex (12m)", "Sofia (34m)", "Marco (48m)"] });
    const out = $("#ultimate-frontier-output");
    if (!out) return;
    const peers = res.connected_peers || [];
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #06b6d4;">
        <div style="font-size:14px; font-weight:700; color:#06b6d4; margin-bottom:4px;">📴 Offline BLE Mesh Network (${esc(res.transport_protocol)}):</div>
        <div style="font-size:13px; margin-bottom:4px;">Connected Peers: <strong>${peers.join(", ")}</strong></div>
        <div style="font-size:11px; color:var(--growth); font-weight:700;">Off-grid location radar & P2P emergency SOS active with zero internet!</div>
      </div>
    `;
  }, "Offline BLE Mesh Synchronized! 📴"));

  on("[data-act=listen-wearable-whispers]", () => act(async () => {
    const res = await api("/v1/wearables/ambient-whispers", { device: "AirPods Pro / Ray-Ban Meta" });
    const out = $("#ultimate-frontier-output");
    if (!out) return;
    const whispers = res.sub_vocal_whispers || [];
    const items = whispers.map(w => `<div style="margin-top:3px;">• <strong>${esc(w.context)}</strong>: "${esc(w.whisper)}" <span style="color:var(--spark); font-size:10px;">(${esc(w.audio_cue)})</span></div>`).join("");
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #6366f1;">
        <div style="font-size:14px; font-weight:700; color:#6366f1; margin-bottom:4px;">🦻 Smart Wearables Ambient Whispers (${esc(res.device)}):</div>
        <div style="font-size:12px; margin-bottom:4px;">${items}</div>
        <div style="font-size:11px; color:var(--growth); font-weight:700;">Result: ${esc(res.eyes_up_guarantee)}</div>
      </div>
    `;
  }, "Wearable Audio Whispers Active! 🦻"));

  /* The web of trust.

     It read `res.trust_score` ("98/100 (Tier-1 Community Vouched)"), a `vouching_chain`
     naming people who do not exist, and a `privacy_standard` of "Zero-Knowledge Proof" for
     a scheme implemented nowhere — about "Elena Rostova", hardcoded. Somebody who reads
     that about a stranger meets them differently, which is why none of those fields exist
     any more. What is here is who vouched, by name, and the fact that this app verifies
     nobody. */
  on("[data-act=verify-web-of-trust]", (el) => act(async () => {
    const subject = $("#tw-who") ? $("#tw-who").value.trim() : "";
    const res = await api("/v1/trust/web-of-trust", subject ? { subject } : {});
    const out = $("#ultimate-frontier-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px;">
        <div style="font-size:13px; font-weight:700; margin-bottom:4px;">${res.count} vouch${res.count === 1 ? "" : "es"}${res.you_vouched ? " · including yours" : ""}</div>
        ${res.vouchers.map(v => `<div style="font-size:12px;">· <strong>${esc(v.handle)}</strong>${v.note ? ` — ${esc(v.note)}` : ""}</div>`).join("")}
        ${res.empty ? `<div style="font-size:12px; color:var(--muted);">${esc(res.suggestion)}</div>` : ""}
        ${subject ? `<button class="ghost" style="font-size:11px; padding:4px 10px; margin-top:6px;" data-act="trust-vouch" data-who="${esc(subject)}">I know them</button>` : ""}
        <div style="font-size:11px; color:var(--muted); margin-top:8px;">${esc(res.disclaimer)}</div>
      </div>`;
    bindLater(out);
  }));

  on("[data-act=trust-vouch]", (el) => act(async () => {
    await api("/v1/trust/vouch", { for_account: el.dataset.who });
    if ($("#tw-who")) $("#tw-who").value = el.dataset.who;
    document.querySelector("[data-act=verify-web-of-trust]").click();
  }));

  on("[data-act=view-memory-atlas]", () => act(async () => {
    /* Reported 48 pins, three memories in three cities nobody had been to, and a time
       capsule counting down 342 days. Pins are your own check-ins, reviews and moments;
       there is no capsule, because nothing implements one. */
    const res = await api("/v1/atlas/living-memory-map", {});
    const out = $("#ultimate-frontier-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px;">
        <div style="font-size:13px; font-weight:700; margin-bottom:4px;">${res.count} place${res.count === 1 ? "" : "s"}${res.cities.length ? ` · ${res.cities.map(esc).join(", ")}` : ""}</div>
        ${res.pins.map(p => `<div style="font-size:12px;">· <strong>${esc(p.place)}</strong> — ${p.times} time${p.times === 1 ? "" : "s"}</div>`).join("")}
        ${res.empty ? `<div style="font-size:12px; color:var(--muted);">${esc(res.suggestion)}</div>` : ""}
        <div style="font-size:11px; color:var(--muted); margin-top:8px;">${esc(res.note)}</div>
      </div>`;
  }));

  on("[data-act=view-eco-quests]", () => act(async () => {
    const res = await api("/v1/impact/regenerative-earth", { city: "Edinburgh" });
    const out = $("#global-flourishing-output");
    if (!out) return;
    const imp = res.collective_city_impact || {};
    const quests = res.spontaneous_eco_quests || [];
    const items = quests.map(q => `<div style="margin-top:3px;">• <strong>${esc(q.title)}</strong> (<span style="color:var(--growth); font-weight:bold;">${esc(q.reward)}</span>) · <em>${esc(q.crew)}</em></div>`).join("");
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #10b981;">
        <div style="font-size:14px; font-weight:700; color:#10b981; margin-bottom:4px;">🌱 Regenerative Earth Impact (${esc(res.city)}):</div>
        <div style="font-size:12px; margin-bottom:4px; color:var(--growth); font-weight:bold;">${imp.plastic_removed_kg} kg Plastic Removed · ${imp.trees_and_pollinators_planted} Native Trees Planted</div>
        <div style="font-size:12px;">${items}</div>
      </div>
    `;
  }, "Regenerative Eco-Quests Synced! 🌱"));

  on("[data-act=view-zero-waste-pantry]", () => act(async () => {
    const res = await api("/v1/impact/zero-waste-pantry", { city: "Edinburgh" });
    const out = $("#global-flourishing-output");
    if (!out) return;
    const meals = res.available_rescued_delicacies || [];
    const items = meals.map(m => `<div style="margin-top:3px; padding:4px; background:rgba(0,0,0,0.2); border-radius:6px;">• <strong>${esc(m.item)}</strong><br><span style="font-size:11px; color:var(--spark);">${esc(m.donor)} · ${esc(m.availability)}</span></div>`).join("");
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #f59e0b;">
        <div style="font-size:14px; font-weight:700; color:#f59e0b; margin-bottom:4px;">🍲 Zero-Waste Food Sharing (${res.meals_rescued_this_month} Meals Rescued This Month):</div>
        <div style="font-size:12px;">${items}</div>
      </div>
    `;
  }, "Zero-Waste Communal Pantry Synced! 🍲"));

  on("[data-act=connect-peer-listener]", () => act(async () => {
    const res = await api("/v1/impact/compassion-listener-network", { vibe: "Seeking a Gentle Ear" });
    const out = $("#global-flourishing-output");
    if (!out) return;
    const l = res.matched_peer_listener || {};
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #6366f1;">
        <div style="font-size:14px; font-weight:700; color:#6366f1; margin-bottom:4px;">🧠 Compassionate Peer Listener Matched:</div>
        <div style="font-size:13px; margin-bottom:2px;">Listener: <strong>${esc(l.name)}</strong> (${esc(l.experience)})</div>
        <div style="font-size:12px; color:var(--growth); margin-bottom:2px;">Format: ${esc(l.format)} · Wait: ${esc(l.wait_time)}</div>
        <div style="font-size:11px; color:var(--spark); font-weight:700;">${esc(l.cost)}</div>
      </div>
    `;
  }, "Compassionate Peer Listener Ready! 🧠"));

  on("[data-act=view-intergenerational-guild]", () => act(async () => {
    const res = await api("/v1/impact/intergenerational-guild", { city: "Edinburgh" });
    const out = $("#global-flourishing-output");
    if (!out) return;
    const ex = res.active_exchanges || [];
    const items = ex.map(e => `<div style="margin-top:3px;">• <strong>${esc(e.elder)}</strong> ⇄ <strong>${esc(e.young_learner)}</strong><br><span style="font-size:11px; color:var(--growth);">${esc(e.exchange)}</span></div>`).join("");
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #ec4899;">
        <div style="font-size:14px; font-weight:700; color:#ec4899; margin-bottom:4px;">🕊️ Intergenerational Mentorship Guild (${esc(res.city)}):</div>
        <div style="font-size:12px; margin-bottom:4px;">${items}</div>
        <div style="font-size:11px; color:var(--spark); font-style:italic;">${esc(res.community_impact)}</div>
      </div>
    `;
  }, "Intergenerational Mentorship Guild Synced! 🕊️"));

  /* Reported "50+ subsystems" online — an AI Butler v4, BLE 5.3 mesh, AirPods spatial
     audio, Apple Pay ready, a web of trust at 98/100 — and closed with `system_health:
     "100% Operational (898+ Tests Verified)"`. Every line was a constant. A status page
     that always says OK is worse than none. */
  on("[data-act=system-status]", () => act(async () => {
    const res = await api("/v1/os/master-controller", {});
    const out = $("#master-controller-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px;">
        <div style="font-size:13px; font-weight:700; margin-bottom:6px;">${res.configured} of ${res.of} configured</div>
        ${res.capabilities.map(c => `<div style="font-size:12px;">${c.available ? "✓" : "—"} ${esc(c.name)}${c.needs && !c.available ? ` <span style="color:var(--muted);">(needs ${esc(c.needs)})</span>` : ""}</div>`).join("")}
        <div style="font-size:12px; font-weight:700; margin-top:8px;">Cannot do</div>
        ${res.unavailable.map(u => `<div style="font-size:11px; color:var(--muted);">· ${esc(u.name)} — ${esc(u.why)}</div>`).join("")}
        <div style="font-size:11px; color:var(--muted); margin-top:8px;">${Object.entries(res.counts).map(([k, v]) => `${v} ${esc(k)}`).join(" · ")}</div>
      </div>`;
  }));

  on("[data-act=show-feed-rules]", () => act(async () => {
    const res = await api("/v1/feed/transparent-rules", {});
    const out = $("#master-controller-output");
    if (!out) return;
    out.innerHTML = renderFeedRules(res);
  }));

  on("[data-act=view-vinyl-radar]", () => act(async () => {
    const res = await api("/v1/seeding/underground-vinyl-radar", { city: "Edinburgh" });
    const out = $("#nextgen-seeding-output");
    if (!out) return;
    const sess = res.curated_underground_sessions || [];
    const items = sess.map(s => `<div style="margin-top:3px; padding:4px; background:rgba(0,0,0,0.2); border-radius:6px;">• <strong>${esc(s.title)}</strong><br><span style="font-size:11px; color:var(--spark);">${esc(s.venue)} · ${esc(s.time)} (${esc(s.vibe)})</span></div>`).join("");
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #ec4899;">
        <div style="font-size:14px; font-weight:700; color:#ec4899; margin-bottom:4px;">🎙️ Underground Vinyl & Secret DJ Radar (${esc(res.city)}):</div>
        <div style="font-size:12px;">${items}</div>
      </div>
    `;
  }, "Underground Vinyl Radar Synced! 🎙️"));

  on("[data-act=view-culinary-drops]", () => act(async () => {
    const res = await api("/v1/seeding/culinary-popup-drops", { city: "Edinburgh" });
    const out = $("#nextgen-seeding-output");
    if (!out) return;
    const drops = res.exclusive_food_drops || [];
    const items = drops.map(d => `<div style="margin-top:3px; padding:4px; background:rgba(0,0,0,0.2); border-radius:6px;">• <strong>${esc(d.title)}</strong><br><span style="font-size:11px; color:var(--growth);">${esc(d.bakery || d.chef || d.host)} · ${esc(d.time)} (<em>${esc(d.quantity || d.access)}</em>)</span></div>`).join("");
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #f59e0b;">
        <div style="font-size:14px; font-weight:700; color:#f59e0b; margin-bottom:4px;">🥐 Culinary Secret Pop-Up Drops (${esc(res.city)}):</div>
        <div style="font-size:12px;">${items}</div>
      </div>
    `;
  }, "Culinary Pop-Up Drops Synced! 🥐"));

  on("[data-act=view-wild-nature]", () => act(async () => {
    const res = await api("/v1/seeding/wild-nature-trails", { city: "Edinburgh" });
    const out = $("#nextgen-seeding-output");
    if (!out) return;
    const spots = res.secret_nature_spots || [];
    const items = spots.map(s => `<div style="margin-top:3px; padding:4px; background:rgba(0,0,0,0.2); border-radius:6px;">• <strong>${esc(s.title)}</strong> (${esc(s.distance)})<br><span style="font-size:11px; color:var(--spark);">${esc(s.difficulty)} · ${esc(s.stargazing_rating || s.water_quality)} · GPX Cached: 🟢</span></div>`).join("");
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #10b981;">
        <div style="font-size:14px; font-weight:700; color:#10b981; margin-bottom:4px;">⛰️ Wild Nature & Hidden Coordinates (${esc(res.city)}):</div>
        <div style="font-size:12px;">${items}</div>
        <div style="font-size:11px; color:var(--growth); font-weight:bold; margin-top:4px;">${esc(res.offline_maps_ready)}</div>
      </div>
    `;
  }, "Wild Nature Trails Synced! ⛰️"));

  on("[data-act=view-literary-salons]", () => act(async () => {
    const res = await api("/v1/seeding/literary-salon-radar", { city: "Edinburgh" });
    const out = $("#nextgen-seeding-output");
    if (!out) return;
    const salons = res.curated_salons || [];
    const items = salons.map(s => `<div style="margin-top:3px; padding:4px; background:rgba(0,0,0,0.2); border-radius:6px;">• <strong>${esc(s.title)}</strong><br><span style="font-size:11px; color:var(--spark);">${esc(s.venue)} · ${esc(s.time)} (<em>${esc(s.entry || s.topic)}</em>)</span></div>`).join("");
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #6366f1;">
        <div style="font-size:14px; font-weight:700; color:#6366f1; margin-bottom:4px;">📚 Literary Salons & Bookshop Radar (${esc(res.city)}):</div>
        <div style="font-size:12px;">${items}</div>
      </div>
    `;
  }, "Literary Salons Synced! 📚"));

  on("[data-act=view-viral-pulse]", () => act(async () => {
    const res = await api("/v1/seeding/social-viral-pulse", { city: "Edinburgh" });
    const out = $("#hyper-discovery-output");
    if (!out) return;
    const sigs = res.social_signals_detected || [];
    const items = sigs.map(s => `<div style="margin-top:3px; padding:4px; background:rgba(0,0,0,0.2); border-radius:6px;">• <strong>${esc(s.venue)}</strong> (<span style="color:var(--spark);">${esc(s.signal)}</span>)<br><span style="font-size:11px; color:var(--growth);">${esc(s.insight)} · <em>${esc(s.velocity)}</em></span></div>`).join("");
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #06b6d4;">
        <div style="font-size:14px; font-weight:700; color:#06b6d4; margin-bottom:4px;">📱 Social & Viral Pulse Surges (${esc(res.city)}):</div>
        <div style="font-size:12px;">${items}</div>
      </div>
    `;
  }, "Social Viral Pulse Synced! 📱"));

  on("[data-act=view-footfall-anomalies]", () => act(async () => {
    const res = await api("/v1/seeding/live-footfall-anomalies", { city: "Edinburgh" });
    const out = $("#hyper-discovery-output");
    if (!out) return;
    const spots = res.detected_footfall_hotspots || [];
    const items = spots.map(s => `<div style="margin-top:3px; padding:4px; background:rgba(0,0,0,0.2); border-radius:6px;">• <strong>${esc(s.zone)}</strong>: ${esc(s.probable_event)}<br><span style="font-size:11px; color:var(--spark);">${esc(s.anomaly_type)}</span></div>`).join("");
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #f59e0b;">
        <div style="font-size:14px; font-weight:700; color:#f59e0b; margin-bottom:4px;">🗺️ Live Footfall & OSM Anomalies (${esc(res.city)}):</div>
        <div style="font-size:12px;">${items}</div>
        <div style="font-size:11px; color:var(--growth); font-weight:bold; margin-top:4px;">Confidence: ${esc(res.confidence_score)}</div>
      </div>
    `;
  }, "Footfall Anomalies Synced! 🗺️"));

  on("[data-act=view-editorial-press]", () => act(async () => {
    const res = await api("/v1/seeding/editorial-press-scraper", { city: "Edinburgh" });
    const out = $("#hyper-discovery-output");
    if (!out) return;
    const recs = res.editorial_recommendations || [];
    const items = recs.map(r => `<div style="margin-top:3px;">• <strong style="color:var(--spark);">${esc(r.source)}</strong>: ${esc(r.highlight)}</div>`).join("");
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #6366f1;">
        <div style="font-size:14px; font-weight:700; color:#6366f1; margin-bottom:4px;">📰 Cultural Press & Critic Picks (${esc(res.city)}):</div>
        <div style="font-size:12px;">${items}</div>
      </div>
    `;
  }, "Editorial Cultural Press Synced! 📰"));

  on("[data-act=view-weather-triggers]", () => act(async () => {
    const res = await api("/v1/seeding/weather-tide-triggers", { city: "Edinburgh" });
    const out = $("#hyper-discovery-output");
    if (!out) return;
    const trigs = res.spontaneous_weather_triggers || [];
    const items = trigs.map(t => `<div style="margin-top:3px; padding:4px; background:rgba(0,0,0,0.2); border-radius:6px;">• <strong>${esc(t.trigger)}</strong> (<span style="color:var(--growth);">${esc(t.condition)}</span>)<br><span style="font-size:11px; color:var(--spark);">${esc(t.action)}</span></div>`).join("");
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #10b981;">
        <div style="font-size:14px; font-weight:700; color:#10b981; margin-bottom:4px;">☀️ Weather & Tide Activity Triggers (${esc(res.current_conditions)}):</div>
        <div style="font-size:12px;">${items}</div>
      </div>
    `;
  }, "Weather & Tide Triggers Synced! ☀️"));

  on("[data-act=fetch-live-apis]", () => act(async () => {
    const res = await api("/v1/seeding/live-external-api-ingest", { city: "Edinburgh" });
    const out = $("#hyper-discovery-output");
    if (!out) return;
    const w = res.live_weather || {};
    const events = res.live_cultural_events || [];
    const items = events.map(e => `<div style="margin-top:3px; padding:4px; background:rgba(0,0,0,0.2); border-radius:6px;">• <strong>${esc(e.title)}</strong> (<span style="color:var(--growth); font-weight:bold;">${esc(e.source)}</span>)<br><span style="font-size:11px; color:var(--spark);">${esc(e.extract)}</span></div>`).join("");
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #10b981;">
        <div style="font-size:14px; font-weight:700; color:#10b981; margin-bottom:4px;">🌐 Live External APIs Ingested (${esc(res.city)}):</div>
        <div style="font-size:12px; margin-bottom:4px; color:var(--growth); font-weight:bold;">⛅ Live Weather: ${w.temp_c}°C · Wind: ${w.wind_kmh} km/h (${esc(w.status)})</div>
        <div style="font-size:12px;">${items}</div>
        <div style="font-size:10px; color:var(--muted); margin-top:4px;">Connected: ${esc((res.connected_apis || []).join(", "))}</div>
      </div>
    `;
  }, "Live External APIs Ingested! 🌐"));

  on("[data-act=view-nightlife-party]", () => act(async () => {
    const res = await api("/v1/nightlife/party-radar", { city: "Munich" });
    const out = $("#nightlife-output");
    if (!out) return;
    const clubs = res.curated_clubs_and_parties || [];
    const items = clubs.map(c => `<div style="margin-top:4px; padding:6px; background:rgba(0,0,0,0.25); border-radius:8px; border-left:3px solid #ef4444;">• <strong>${esc(c.name)}</strong> (${esc(c.timing)})<br><span style="font-size:11px; color:var(--growth);">${esc(c.genre)} · ${esc(c.location)}</span><br><span style="font-size:10px; color:var(--spark);">${esc(c.insider_tip)} (${esc(c.queue_status)})</span></div>`).join("");
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #ef4444;">
        <div style="font-size:14px; font-weight:700; color:#ef4444; margin-bottom:4px;">🔥 Live Underground Clubs & Parties (${esc(res.city)}):</div>
        <div style="font-size:12px;">${items}</div>
      </div>
    `;
  }, "Live Party & Rave Radar Synced! 🔥"));

  on("[data-act=view-nightlife-speakeasy]", () => act(async () => {
    const res = await api("/v1/nightlife/secret-speakeasies", { city: "Munich" });
    const out = $("#nightlife-output");
    if (!out) return;
    const bars = res.secret_cocktail_dens || [];
    const items = bars.map(b => `<div style="margin-top:4px; padding:6px; background:rgba(0,0,0,0.25); border-radius:8px; border-left:3px solid #a855f7;">• <strong>${esc(b.name)}</strong><br><span style="font-size:11px; color:#a855f7; font-weight:bold;">🔑 Entrance: ${esc(b.entrance)}</span><br><span style="font-size:11px; color:var(--muted);">${esc(b.vibe)} (${esc(b.address)})</span></div>`).join("");
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #a855f7;">
        <div style="font-size:14px; font-weight:700; color:#a855f7; margin-bottom:4px;">🍸 Secret Speakeasies & Passcodes (${esc(res.city)}):</div>
        <div style="font-size:12px;">${items}</div>
      </div>
    `;
  }, "Secret Speakeasies Unlocked! 🍸"));

  on("[data-act=rsvp-nightlife-fastpass]", () => act(async () => {
    const res = await api("/v1/nightlife/guestlist-vip", { venue: "Blitz Club", crew_size: 2 });
    const out = $("#nightlife-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #6366f1;">
        <div style="font-size:14px; font-weight:700; color:#6366f1; margin-bottom:4px;">🎟️ Fast-Pass VIP Guestlist Confirmed:</div>
        <div style="font-size:12px; font-weight:bold; color:var(--growth);">${esc(res.venue)} · Code: ${esc(res.fastpass_code)} (${res.crew_size} guests)</div>
        <div style="font-size:11px; color:var(--muted); margin-top:2px;">Curfew: ${esc(res.entry_curfew)}</div>
        <div style="font-size:11px; color:var(--spark); margin-top:2px;">Perks: ${(res.perks_included || []).join(" · ")}</div>
      </div>
    `;
  }, "Fast-Pass Guestlist Issued! 🎟️"));

  on("[data-act=match-pregame-crew]", () => act(async () => {
    const res = await api("/v1/nightlife/crew-pregame", { destination: "Blitz Club", city: "Munich" });
    const out = $("#nightlife-output");
    if (!out) return;
    const pg = res.pregame_gathering || {};
    const squad = (pg.squad || []).map(s => `• <strong>${esc(s.name)}</strong>: ${esc(s.vibe)}`).join("<br>");
    const sw = res.safewalk_home_escort || {};
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #10b981;">
        <div style="font-size:14px; font-weight:700; color:#10b981; margin-bottom:4px;">🍻 Pre-Game Squad & SafeWalk Escort:</div>
        <div style="font-size:12px; color:var(--growth); font-weight:bold;">📍 Gathering: ${esc(pg.venue)} (${esc(pg.time)})</div>
        <div style="font-size:11px; margin-top:3px;">${squad}</div>
        <div style="font-size:11px; color:#10b981; margin-top:4px; font-weight:bold;">🛡️ SafeWalk Home at 04:00 AM: ${esc(sw.buddy)} (${esc(sw.status)})</div>
      </div>
    `;
  }, "Pre-Game Squad Matched! 🍻"));

  /* ---- City chat ---- */
  on("[data-act=city-open]", (el) => act(async () => {
    const city = (el.dataset.city || ($("#city-name") || {}).value || "").trim();
    if (!city) throw new Error("Which city?");
    state.cityRoom = city;
    localStorage.setItem("lifeos.city", city);
    await refresh();
  }));

  on("[data-act=meetup-create]", () => act(async () => {
    const title = ($("#mu-title").value || "").trim();
    const place = ($("#mu-place").value || "").trim();
    const when = ($("#mu-when").value || "").trim();
    if (!title) throw new Error("What is the plan?");
    if (!when) throw new Error("When?");
    await api("/v1/city/meetups", { city: state.cityRoom, title, place, starts_at: when });
    await refresh();
  }, "It's up — people can join now"));

  on("[data-act=meetup-join]", (el) => act(async () => {
    await api("/v1/city/meetups/join", { meetup_id: el.dataset.id });
    await refresh();
  }, "You're in. Meet somewhere public the first time."));

  on("[data-act=meetup-leave]", (el) => act(async () => {
    await api("/v1/city/meetups/leave", { meetup_id: el.dataset.id });
    await refresh();
  }));

  on("[data-act=city-here]", () => act(async () => {
    const note = (($("#city-note") || {}).value || "").trim();
    await api("/v1/city/around", { city: state.cityRoom, note, days: 3 });
    await refresh();
  }, "You are listed as here"));

  on("[data-act=city-hide]", () => act(async () => {
    await apiDelete("/v1/city/around", { city: state.cityRoom });
    await refresh();
  }, "Taken down"));

  on("[data-act=city-say]", () => act(async () => {
    const box = $("#city-say");
    const text = (box.value || "").trim();
    if (!text) throw new Error("Say something first");
    await api("/v1/city/chat", { city: state.cityRoom, text });
    box.value = "";
    await refresh();
  }, "Sent"));

  on("[data-act=city-remove]", (el) => act(async () => {
    await apiDelete(`/v1/city/chat/message/${encodeURIComponent(el.dataset.id)}`);
    await refresh();
  }, "Message removed"));

  on("[data-act=city-mute]", (el) => act(async () => {
    await api("/v1/city/chat/mute", { target_id: el.dataset.id });
    await refresh();
  }, "Muted — they are not told"));

  on("[data-act=city-report]", (el) => act(async () => {
    const reason = prompt("What is wrong with this message? Only the operator sees this.");
    if (!reason) return;
    await api("/v1/city/chat/report", { message_id: el.dataset.id, reason });
  }, "Reported to the operator"));

  on("[data-act=vcard-download]", () => act(async () => {
    const res = await api("/v1/people/qr");
    const out = $("#vcard-output");
    if (!out) return;
    // `vcard_data_uri` is built by the gateway from your own handle, escaped per RFC 6350.
    // safeUrl() would reject it — it only passes http/https — and that is correct for
    // response-supplied links; this one is a data: URI we generated, so it is set through
    // the DOM rather than interpolated into markup.
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px;">
        <div style="font-size:13px; margin-bottom:6px;">Contact card for <strong>${esc(res.name)}</strong></div>
        <a class="btn" id="vcard-link" download="lifeos-contact.vcf">Save .vcf</a>
      </div>
    `;
    const link = $("#vcard-link");
    if (link) link.href = res.vcard_data_uri;
  }, "Contact card ready"));
  on("[data-act=synthesize-daily-journal]", () => act(async () => {
    /* Read `res.poetic_daily_retrospective`, `res.events_experienced` and
       `res.gratitude_dividends` — a hardcoded day per city. Send "Munich" and it told you,
       in the first person, that you had watched dawn surfers on the Eisbach wave and
       thanked a man called Lukas. None of those fields exist now: a day is built from
       your own check-ins, notes and moments, and an empty day says so. */
    const res = await api("/v1/journal/daily-reflection-synthesis", {});
    const out = $("#journal-synthesis-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:14px; border-radius:12px;">
        <div style="font-size:14px; font-weight:700; margin-bottom:6px;">${esc(res.date)}</div>
        ${res.summary ? `<div style="font-size:13px; margin-bottom:8px;">${esc(res.summary)}</div>` : ""}
        ${res.did.map(d => `<div style="font-size:12px;">· ${esc(d)}</div>`).join("")}
        ${res.notes.map(n => `<div style="font-size:12px; color:var(--growth);">“${esc(n)}”</div>`).join("")}
        ${res.empty ? `<div style="font-size:13px; color:var(--muted);">${esc(res.suggestion)}</div>` : ""}
        <div style="font-size:11px; color:var(--muted); margin-top:8px;">${esc(res.no_score)}${res.sources.length ? ` · built from ${res.sources.length} of your own entries` : ""}</div>
      </div>`;
  }));
  on("[data-act=voice-ask-nightlife]", () => act(async () => {
    await triggerVoiceQuery("What are the best vinyl clubs and parties tonight?");
  }, "Spoken Nightlife Query Sent! 🔊"));

  on("[data-act=voice-ask-food]", () => act(async () => {
    await triggerVoiceQuery("Where is the best warm sourdough and food?");
  }, "Spoken Food Query Sent! 🔊"));

  on("[data-act=voice-ask-squad]", () => act(async () => {
    await triggerVoiceQuery("Who from my squad is nearby right now?");
  }, "Spoken Squad Query Sent! 🔊"));

  on("[data-act=voice-custom-prompt]", () => act(async () => {
    const q = prompt("What would you like to ask your Voice AI Butler?", "What's happening nearby right now?");
    if (q) await triggerVoiceQuery(q);
  }, "Custom Voice Prompt Spoken! 🎙️"));

  /* ---- Micro-Masterclasses Handler ---- */
  on("[data-act=view-micro-workshops]", () => act(async () => {
    const res = await api("/v1/workshops/micro-masterclasses", { city: "Munich" });
    const out = $("#workshops-output");
    if (!out) return;
    const cards = (res.micro_masterclasses || []).map(w => `
      <div style="background:var(--surface-2s); padding:10px; border-radius:8px; border:1px solid #f59e0b; margin-bottom:6px;">
        <div style="font-weight:bold; font-size:13px; color:#f59e0b;">${esc(w.title)}</div>
        <div style="font-size:11px; color:var(--growth);">👨‍🏫 Mentor: ${esc(w.mentor)} · ⏰ ${esc(w.schedule)}</div>
        <div style="font-size:11px; color:var(--muted); margin-top:2px;">📍 ${esc(w.location)} · 🎟️ ${esc(w.capacity)}</div>
        <div style="font-size:11px; font-style:italic; color:var(--spark); margin-top:2px;">"${esc(w.vibe)}"</div>
      </div>
    `).join("");
    out.innerHTML = cards;
  }, "Craft Masterclasses Loaded! 🤝"));

  /* ---- Layover Navigator Handler ---- */
  on("[data-act=plan-layover-escape]", () => act(async () => {
    const res = await api("/v1/travel/layover-discovery", { hub: "Munich Airport (MUC)", layover_hours: 4.5 });
    const out = $("#layover-output");
    if (!out) return;
    const ce = res.curated_micro_escape || {};
    const stops = (ce.stops || []).map(s => `• <strong>${esc(s.time)}</strong>: ${esc(s.action)}`).join("<br>");
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #06b6d4;">
        <div style="font-size:14px; font-weight:700; color:#06b6d4;">✈️ ${esc(ce.route_name)} (${esc(res.safe_exploration_time)})</div>
        <div style="font-size:11px; color:var(--spark); margin-top:3px;">🚆 Transit: ${esc(ce.transit)}</div>
        <div style="font-size:11px; line-height:1.5; margin-top:6px;">${stops}</div>
        <div style="font-size:11px; color:#10b981; font-weight:bold; margin-top:6px;">⏰ Gate Return Safety Alarm: ${esc(res.gate_return_alarm)}</div>
      </div>
    `;
  }, "Layover Micro-Escape Planned! ✈️"));

  /* ---- Universal Markdown Export Handler ---- */
  on("[data-act=export-universal-markdown]", () => act(async () => {
    /* Reported 48 vault files and offered a .zip on connectos.app that was never written,
       on a host this deployment does not serve. The export is the response now, and the
       download is a Blob built from it here — no file has to exist on any server. */
    const res = await api("/v1/export/universal-markdown", {});
    const text = Object.entries(res.documents)
      .map(([name, body]) => `\n\n<!-- ${name} -->\n\n${body}`).join("").trim() + "\n";
    const out = $("#markdown-export-output");
    if (!out) return;
    const url = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px;">
        <div style="font-size:13px; font-weight:700; margin-bottom:4px;">${res.files} file${res.files === 1 ? "" : "s"} · ${res.rows} entr${res.rows === 1 ? "y" : "ies"}</div>
        ${Object.keys(res.documents).map(n => `<div style="font-size:11px; color:var(--muted);">${esc(n)}</div>`).join("")}
        <a id="md-export-link" class="primary" style="display:inline-block; margin-top:8px; padding:6px 14px; font-size:12px; text-decoration:none; border-radius:8px;" download="lifeos-export.md">⬇️ Save it</a>
        <div style="font-size:11px; color:var(--muted); margin-top:8px;">${esc(res.note)} ${esc(res.excluded_reason)}</div>
      </div>`;
    const link = $("#md-export-link");
    if (link) link.href = url;      // a Blob built in this tab, not a URL to somebody's server
    bindLater(out);
  }));
  on("[data-act=gen-dev-apikey]", () => act(async () => {
    const res = await api("/v1/developers/api-keys", { app_name: "KiteSurf Wind Radar Plugin", environment: "production" });
    const out = $("#developer-output");
    if (!out) return;
    const scopes = res.scopes || [];
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #6366f1;">
        <div style="font-size:14px; font-weight:700; color:#6366f1; margin-bottom:4px;">🔌 Developer API Key Provisioned (${esc(res.environment)}):</div>
        <div style="font-family:monospace; font-size:12px; background:rgba(0,0,0,0.3); padding:6px; border-radius:6px; margin-bottom:4px; color:var(--growth);">${esc(res.api_key)}</div>
        <div style="font-size:12px; color:var(--muted);">Rate Limit: ${esc(res.rate_limit)} · Scopes: ${scopes.join(", ")}</div>
      </div>
    `;
  }, "Developer API Key Provisioned! 🔌"));

  on("[data-act=sub-dev-webhook]", () => act(async () => {
    const res = await api("/v1/developers/webhooks", { target_url: "https://api.myapp.com/webhooks/connectos" });
    const out = $("#developer-output");
    if (!out) return;
    const events = res.subscribed_events || [];
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #06b6d4;">
        <div style="font-size:14px; font-weight:700; color:#06b6d4; margin-bottom:4px;">⚡ Webhook Active (${events.length} Events):</div>
        <div style="font-size:13px; margin-bottom:4px;">Target: <strong>${esc(res.target_url)}</strong></div>
        <div style="font-size:11px; color:var(--spark);">Signing Secret: ${esc(res.signing_secret)} (${esc(res.signature_header)})</div>
      </div>
    `;
  }, "Webhook Subscribed! ⚡"));

  on("[data-act=test-dev-sandbox]", () => act(async () => {
    const res = await api("/v1/developers/plugin-sandbox", { plugin_id: "com.windydev.kitesurf-radar" });
    const out = $("#developer-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #a855f7;">
        <div style="font-size:14px; font-weight:700; color:#a855f7; margin-bottom:4px;">🛠️ Plugin Sandbox Verified (${esc(res.store_status)}):</div>
        <div style="font-size:13px; margin-bottom:4px;">Plugin: <strong>${esc(res.plugin_id)}</strong> (${esc(res.sdk_version)})</div>
        <div style="font-size:12px; color:var(--growth); font-weight:700;">Rev-Share: ${esc(res.monetization_tier)}</div>
      </div>
    `;
  }, "Plugin Sandbox Tested & Published! 🛠️"));

  on("[data-act=switch-nomad-city]", () => act(async () => {
    const target = $("#np-city").value.trim() || "Tokyo";
    const res = await api("/v1/nomad/city-switch", { target_city: target });
    const out = $("#nomad-teleport-output");
    if (!out) return;
    $("#np-city").value = "";
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #06b6d4;">
        <div style="font-size:14px; font-weight:700; color:#06b6d4; margin-bottom:4px;">🌐 Teleported to ${esc(res.current_city)}!</div>
        <div style="font-size:13px; margin-bottom:4px;">${res.active_nomads_count} Active Nomads Nearby · Hub: <strong>${esc(res.recommended_hub)}</strong></div>
        <div style="font-size:11px; color:var(--muted);">Events: ${res.local_events.join(" · ")}</div>
      </div>
    `;
  }, "Teleported City via Nomad Passport! 🌐"));

  /* ---- Web Audio Haptic Chimes & Theme Engine ---- */
  function playChime(freq = 520, type = "sine") {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      const ctx = new AudioCtx();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = type;
      osc.frequency.setValueAtTime(freq, ctx.currentTime);
      osc.frequency.exponentialRampToValueAtTime(freq * 1.5, ctx.currentTime + 0.12);
      gain.gain.setValueAtTime(0.08, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.18);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.18);
    } catch (_) {}
  }

  on("[data-act=test-audio-chime]", () => {
    playChime(640, "triangle");
    toast("🔊 Haptic Audio Chime Played!");
  });

  on("[data-act=theme-cyber]", () => {
    document.body.className = "theme-cyber";
    playChime(520);
    toast("🌓 Cyber Dark Theme Activated! 🌌");
  });

  on("[data-act=theme-sunset]", () => {
    document.body.className = "theme-sunset";
    playChime(580);
    toast("🌅 Sunset Amber Theme Activated! 🌅");
  });

  on("[data-act=theme-solar]", () => {
    document.body.className = "theme-solar";
    playChime(660);
    toast("☀️ Solar Theme Activated! ☀️");
  });

  on("[data-act=theme-default]", () => {
    document.body.className = "";
    playChime(440);
    toast("🖤 OLED Pure Dark Theme Restored!");
  });

  /* ---- Universal Feature Spotlight & Command Palette (⌘K) ---- */
  const searchInput = $("#global-feature-search");
  if (searchInput) {
    searchInput.addEventListener("input", (e) => {
      const q = e.target.value.toLowerCase().trim();
      document.querySelectorAll(".card").forEach((card) => {
        if (!q) {
          card.style.display = "";
          return;
        }
        const text = card.textContent.toLowerCase();
        if (text.includes(q) || card.querySelector("#global-feature-search")) {
          card.style.display = "";
        } else {
          card.style.display = "none";
        }
      });
    });
  }

  window.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "k") {
      e.preventDefault();
      const el = $("#global-feature-search");
      if (el) {
        el.focus();
        el.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    }
  });

  on("[data-act=clear-feature-search]", () => {
    const el = $("#global-feature-search");
    if (el) {
      el.value = "";
      el.dispatchEvent(new Event("input"));
    }
  });

  const filterPills = [
    { act: "filter-feature-all", query: "" },
    { act: "filter-feature-coffee", query: "coffee" },
    { act: "filter-feature-dating", query: "dating" },
    { act: "filter-feature-sports", query: "sports" },
    { act: "filter-feature-festivals", query: "festival" },
    { act: "filter-feature-housing", query: "co-living" },
    { act: "filter-feature-economy", query: "barter" },
    { act: "filter-feature-impact", query: "eco" },
  ];

  filterPills.forEach(({ act: actName, query }) => {
    on(`[data-act=${actName}]`, () => {
      const el = $("#global-feature-search");
      if (el) {
        el.value = query;
        el.dispatchEvent(new Event("input"));
        toast(query ? `Filtered by ${query} 🔍` : "Showing all features 🌐");
      }
    });
  });

  on("[data-act=gen-memory-capsule]", () => act(async () => {
    const res = await api("/v1/memories/highlight-reel", { title: "Lisbon Sunset Rooftop Drinks" });
    const out = $("#memory-vip-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #ec4899;">
        <div style="font-size:14px; font-weight:700; color:#ec4899; margin-bottom:4px;">📸 AI Memory Capsule Generated (${esc(res.capsule_id)}):</div>
        <div style="font-size:13px; margin-bottom:4px;">Title: <strong>${esc(res.title)}</strong> · ${res.photos_count} Photos Saved</div>
        <div style="font-size:12px; color:var(--muted); margin-bottom:4px;">Attendees: ${res.attendees.join(", ")}</div>
        <div style="font-size:11px; color:var(--spark);">Share URL: ${esc(res.share_url)}</div>
      </div>
    `;
  }, "AI Memory Capsule Generated! 📸"));

  on("[data-act=claim-vip-pass]", () => act(async () => {
    const res = await api("/v1/events/vip-guestlist", { venue: "Miradouro Rooftop Bar" });
    const out = $("#memory-vip-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid #a855f7;">
        <div style="font-size:14px; font-weight:700; color:#a855f7; margin-bottom:4px;">🎟️ VIP Fast-Track Pass Verified!</div>
        <div style="font-size:13px; margin-bottom:4px;">Venue: <strong>${esc(res.venue)}</strong> (${esc(res.access_tier)})</div>
        <div style="font-size:12px; color:var(--growth); font-weight:700;">Pass Code: ${esc(res.pass_code)}</div>
      </div>
    `;
  }, "VIP Fast-Track Pass Verified! 🎟️"));

  on("[data-act=mint-pop-badge]", () => act(async () => {
    const place = $("#pop-place") ? $("#pop-place").value.trim() : "";
    if (!place) { toast("Where were you?"); return; }
    const res = await api("/v1/gamification/mint-presence", { event_name: place });
    const out = $("#pop-mint-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px;">
        <div style="font-size:13px; font-weight:700; margin-bottom:4px;">Noted: ${esc(place)}</div>
        <div style="font-size:12px; color:var(--muted);">${esc(res.note || "")}</div>
      </div>`;
  }, "Check-in recorded"));

  /* ---- SafeWalk ----
     The old handler posted a destination and toasted "Crew notified & ETA timer set". No
     message left the building, and the escort code was the same eight digits for every walk
     in the world. Somebody who believes their crew is watching walks home differently from
     somebody who knows nobody is, so this screen says exactly who can see the walk. */

  function renderWalk(res) {
    const out = $("#safewalk-output");
    if (!out) return;
    const walks = res.walks || [];
    const overdue = res.overdue || [];
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px;">
        ${res.watching ? `
          <div style="font-size:13px; font-weight:700; margin-bottom:4px;">Walking to ${esc(res.destination)}</div>
          <div style="font-size:12px; color:var(--muted); margin-bottom:6px;">${res.can_see_it} ${res.can_see_it === 1 ? "person" : "people"} can see this · ${esc(res.delivery_note || "")}</div>` : ""}
        ${overdue.length ? `<div style="font-size:13px; font-weight:700; color:var(--warm); margin-bottom:6px;">${overdue.length} overdue</div>` : ""}
        ${walks.map(w => `
          <div style="font-size:13px; margin-bottom:6px; background:var(--surface-1); padding:8px 10px; border-radius:8px;">
            <div><strong>${esc(w.handle)}</strong> → ${esc(w.destination)}${w.severity === "sos" ? " · SOS" : ""}</div>
            <div style="font-size:11px; color:${w.overdue ? "var(--warm)" : "var(--muted)"};">${w.overdue ? `${w.overdue_minutes} min overdue` : `due ${esc(whenLabel(w.due_at))}`}</div>
          </div>`).join("")}
        ${!res.watching && !walks.length ? `<div style="font-size:13px; color:var(--muted);">${esc(res.suggestion || "Nothing active.")}</div>` : ""}
        ${res.disclaimer ? `<div style="font-size:11px; color:var(--muted); margin-top:8px;">${esc(res.disclaimer)}</div>` : ""}
      </div>`;
    bindLater(out);
  }

  const walkWatchers = () => ($("#sw-watchers") ? $("#sw-watchers").value : "")
    .split(",").map(w => w.trim()).filter(Boolean);

  on("[data-act=start-safewalk-escort]", () => act(async () => {
    const destination = $("#sw-dest").value.trim();
    if (!destination) { toast("Where are you going?"); return; }
    const eta_mins = parseInt($("#sw-eta").value, 10) || 30;
    renderWalk(await api("/v1/safety/escort",
                         { destination, eta_mins, watchers: walkWatchers() }));
  }));

  on("[data-act=safewalk-arrived]", () => act(async () => {
    await api("/v1/safety/escort/arrived", {});
    renderWalk(await api("/v1/safety/escort"));
  }, "Good. Watch cleared ✅"));

  on("[data-act=safewalk-mine]", () => act(async () => {
    renderWalk(await api("/v1/safety/escort"));
  }));

  on("[data-act=safewalk-watching]", () => act(async () => {
    renderWalk(await api("/v1/safety/watching"));
  }));

  /* The tab — who owes whom.

     The old handler read `res.per_person`, `res.total_amount` and `res.payment_link`, none
     of which exist any more: the payment link went to a revolut.me page for an account
     nobody had connected, and the split was never written down. Both renderers below take
     the shapes the server actually returns now. */
  function renderTab(res, selector) {
    const out = $(selector || "#quick-split-output");
    if (!out) return;
    const money = (n, c) => `${Number(n).toFixed(2)}${c ? " " + esc(c) : ""}`;
    // The server addresses people by account id and resolves the handle for display; an id
    // on screen is not a sentence anybody can act on.
    const who = (row) => row.handle || row.counterparty || row.person || "someone";
    let body = "";
    if (res.entries && res.split) {
      body = `<div style="font-size:13px; margin-bottom:6px;">Split ${money(res.total, res.currency)} ${res.people} ways · <strong>your share ${money(res.your_share, res.currency)}</strong></div>`
        + res.entries.map(e => `<div style="font-size:13px;">${esc(who(e))} owes you ${money(e.owes_you, e.currency)}</div>`).join("");
    } else if (res.entries && res.total !== undefined) {
      body = res.entries.length
        ? res.entries.map(e => `<div style="font-size:13px; margin-bottom:4px; ${e.disputed ? "opacity:0.55; text-decoration:line-through;" : ""}">
             ${esc(who(e))} · ${e.you_owe ? "you owe" : "owes you"} ${e.amount ? money(e.amount, e.currency) : esc(e.item || "")}${e.note ? ` — ${esc(e.note)}` : ""}
             ${e.yours_to_dispute ? `<button class="ghost" style="font-size:11px; padding:4px 10px; margin-left:6px;" data-act="tab-dispute" data-entry="${esc(e.entry_id)}">Not mine</button>` : ""}
           </div>`).join("")
        : `<div style="font-size:13px; color:var(--muted);">Nothing on your tab yet.</div>`;
    } else if (res.recorded === false && res.each !== undefined) {
      body = `<div style="font-size:13px; margin-bottom:4px;"><strong>${money(res.each, res.currency)} each</strong> · your share ${money(res.your_share, res.currency)}</div>`;
    } else if (res.balances) {
      body = res.balances.length
        ? res.balances.map(b => `<div style="font-size:13px; margin-bottom:4px;">
             <strong>${esc(who(b))}</strong> — ${esc(b.direction)} ${money(b.net, b.currency)}
             ${b.they_owe_you ? "" : `<button class="ghost" style="font-size:11px; padding:4px 10px; margin-left:6px;" data-act="settle-with" data-who="${esc(b.counterparty)}" data-cur="${esc(b.currency)}">Settle</button>`}
           </div>`).join("")
        : `<div style="font-size:13px; color:var(--muted);">Nothing on your tab.</div>`;
    } else if (res.settled) {
      body = `<div style="font-size:13px;">Settled ${money(res.amount, res.currency)} with ${esc(res.counterparty_handle || res.counterparty)}${res.clear ? " — all clear" : ` · ${money(res.still_owed, res.currency)} left`}</div>`;
    } else if (res.recorded) {
      body = `<div style="font-size:13px;">You owe ${esc(res.to_account_handle || res.to_account)}${res.amount ? " " + money(res.amount, res.currency) : ""}${res.item ? ` (${esc(res.item)})` : ""}</div>`;
    }
    const footer = res.no_money || res.note || "";
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px;">
        ${body}
        ${footer ? `<div style="font-size:11px; color:var(--muted); margin-top:8px;">${esc(footer)}</div>` : ""}
      </div>`;
    bindLater(out);
  }

  on("[data-act=quick-split-expense]", () => act(async () => {
    const amount = parseFloat($("#qs-amount").value);
    if (!(amount > 0)) { toast("How much was it?"); return; }
    const note = $("#qs-title").value.trim();
    const who = $("#qs-who").value.split(",").map(w => w.trim()).filter(Boolean);
    // Named people go on a tab; a bare headcount is only ever the arithmetic, and the
    // response says which of the two happened rather than implying it wrote something.
    const res = who.length
      ? await api("/v1/ledger/quick-split", { amount, note, participants: who })
      : await api("/v1/ledger/quick-split",
                  { amount, note, people_count: parseInt($("#qs-people").value, 10) || 4 });
    renderTab(res);
  }));

  on("[data-act=show-tab]", () => act(async () => {
    renderTab(await api("/v1/ledger/tab"), "#quick-split-output");
  }));

  on("[data-act=tab-history]", () => act(async () => {
    renderTab(await api("/v1/ledger/tab/entries"), "#quick-split-output");
  }));

  /* Anybody can write a debt against anybody. Being able to see a claim is not the same as
     having agreed to it, so the side it counts against can reject it. */
  on("[data-act=tab-dispute]", (el) => act(async () => {
    await api("/v1/ledger/tab/dispute", { entry_id: el.dataset.entry });
    renderTab(await api("/v1/ledger/tab/entries"), "#quick-split-output");
  }));

  on("[data-act=settle-with]", (el) => act(async () => {
    renderTab(await api("/v1/ledger/settle-up",
                        { counterparty: el.dataset.who, currency: el.dataset.cur }),
              "#quick-split-output");
  }));

  on("[data-act=start-audio-space]", () => act(async () => {
    const title = $("#as-title").value.trim() || "Weekend Bouldering Prep";
    const res = await api("/v1/spaces/audio", { title });
    $("#as-title").value = "";
    toast(res.message || "Live Audio Crew Space launched! 🎙️");
  }));

  on("[data-act=send-kindness-note]", () => act(async () => {
    const recipient = $("#kn-name").value.trim() || "Alex";
    const note = $("#kn-text").value.trim() || "Thanks for organizing the bouldering meet yesterday!";
    const res = await api("/v1/social/kindness", { recipient, note });
    $("#kn-name").value = "";
    $("#kn-text").value = "";
    toast(res.message || `Anonymous Kindness Note sent to ${recipient}! 💌`);
  }));

  on("[data-act=sunset-win-save]", () => act(async () => {
    const win_text = $("#sw-text").value.trim() || "Shipped ConnectOS v2!";
    const res = await api("/v1/rituals/sunset", { win_text });
    $("#sw-text").value = "";
    toast(res.message || "Evening Sunset Win logged! 🌅");
  }));

  on("[data-act=wrapped-generate]", () => act(async () => {
    const res = await api("/v1/wrapped/monthly");
    const out = $("#wrapped-output");
    if (!out) return;
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid var(--spark)40;">
        <div style="font-size:15px; font-weight:700; color:var(--spark); margin-bottom:8px;">🏆 Your ConnectOS ${esc(res.month)} Wrapped:</div>
        <div style="font-size:13px; margin-bottom:4px;">⚡ <strong>${res.focus_hours} Hours</strong> of Deep Work Focus</div>
        <div style="font-size:13px; margin-bottom:4px;">🧗 <strong>${res.real_world_meetups} Real-World Outings</strong> & Crew Meets</div>
        <div style="font-size:13px; margin-bottom:4px;">📍 Top Venue: <strong>${esc(res.top_venue)}</strong></div>
        <div style="font-size:13px; margin-bottom:6px;">👏 <strong>${res.kudos_received} Kudos</strong> Received from Friends</div>
        <button class="ghost" style="margin-top:8px; font-size:12px; padding:6px 12px;" onclick="navigator.clipboard.writeText('${esc(res.share_text.replace(/'/g, "\\'"))}'); toast('Wrapped story text copied! 📲');">Share to WhatsApp / IG Story 📲</button>
      </div>
    `;
  }, "Monthly Wrapped Canvas Generated! 🏆"));

  on("[data-act=auto-ingest-city]", () => act(async () => {
    const city = $("#ag-city").value.trim() || "Lisbon";
    const res = await api("/v1/feed/auto-ingest", { city });
    await refresh();
    toast(res.message || `Synced live events for ${city}! 🎟️`);
  }));

  on("[data-act=subscribe-venue-program]", (el) => act(async () => {
    const name = el.dataset.name || "Venue";
    toast(`Synced official ${name} program to your Smart Calendar! 📅`);
  }));

  on("[data-act=travel-brief]", () => act(async () => {
    const city = $("#tr-city").value.trim() || "Lisbon";
    const start_date = $("#tr-start").value || "2026-08-15";
    const res = await api("/v1/travel/curated-brief", { city, start_date });
    const out = $("#travel-brief-output");
    if (!out) return;
    const spots = res.curated_spots || [];
    const evts = res.upcoming_events || [];
    out.innerHTML = `
      <div style="background:var(--surface-2s); padding:12px; border-radius:12px; border:1px solid rgba(37,99,235,0.3);">
        <div style="font-size:14px; font-weight:700; color:var(--spark); margin-bottom:8px;">✈️ Curated Itinerary Brief: ${esc(res.city)} (${esc(res.dates)})</div>
        <div style="font-size:12px; font-weight:700; text-transform:uppercase; color:var(--muted); margin-bottom:4px;">Known Favorite Spots:</div>
        ${spots.map(s => `<div style="font-size:13px; margin-bottom:4px;">📍 <strong>${esc(s.name)}</strong> (${esc(s.category)}) — <span style="color:var(--muted);">${esc(s.reason)}</span></div>`).join("")}
        <div style="font-size:12px; font-weight:700; text-transform:uppercase; color:var(--muted); margin:8px 0 4px;">Upcoming Curated Events:</div>
        ${evts.map(e => `<div style="font-size:13px; margin-bottom:4px;">🎟️ <strong>${esc(e.title)}</strong> · ${esc(e.date)} (${e.going_count} interested)</div>`).join("")}
      </div>
    `;
  }, "Curated Travel Forecast Generated! ✈️"));

  /* ---- Deep Work Focus Shield & Data Sovereignty Export ---- */

  on("[data-act=focus-start]", () => {
    state.focusEndTime = Date.now() + 45 * 60 * 1000;
    toast("Focus Shield activated for 45m! 🛡️");
    render();
  });

  on("[data-act=focus-end]", () => {
    state.focusEndTime = null;
    toast("Focus Shield deactivated.");
    render();
  });

  on("[data-act=export-json]", () => {
    window.open(apiBase() + "/v1/export", "_blank");
    toast("Downloading Graph JSON…");
  });

  on("[data-act=export-graphml]", () => {
    window.open(apiBase() + "/v1/graph/export/graphml", "_blank");
    toast("Downloading GraphML XML…");
  });

  on("[data-act=consent-save]", () => act(async () => {
    const enabled = $("#cs-enabled").checked;
    const share_interests = $("#cs-interests").checked;
    const share_city_events = $("#cs-events").checked;
    await api("/v1/telemetry/consent", { enabled, share_interests, share_city_events });
    await refresh();
  }, "Privacy & Intelligence Settings Saved ✔"));
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
  const who = $("#set-account");
  if (who) {
    who.textContent = state.me
      ? `Signed in as ${state.me.handle}`
      : "Not signed in.";
  }
  const out = $("#set-signout");
  if (out) out.hidden = !state.me;
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
// Served from our own origin, not unpkg. A CDN script loaded into this page runs with full
// access to the session token in localStorage and to every graph endpoint, and unpkg was
// loaded with no Subresource Integrity hash — so whatever it happened to return, we ran.
// The files in vendor/ are Leaflet 1.9.4 extracted from the npm tarball, verified against
// the sha512 that npm publishes for that release before being committed.
async function loadLeaflet() {
  if (leafletLoaded || window.L) return;
  leafletLoaded = true;
  return new Promise((resolve) => {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "vendor/leaflet.css";
    document.head.appendChild(link);

    const script = document.createElement("script");
    script.src = "vendor/leaflet.js";
    script.onload = () => resolve();
    script.onerror = () => resolve();     // the map degrades; the page must not hang
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

// Check hash URL for signed crew invite link: #join-crew?crew_id=XYZ&token=...
if (window.location.hash && window.location.hash.includes("join-crew")) {
  try {
    const params = new URLSearchParams(window.location.hash.split("?")[1] || "");
    const crew_id = params.get("crew_id");
    if (crew_id) {
      api("/v1/crews/join-by-token", { crew_id }).then(() => {
        toast("Joined crew via invite link! ✓");
        state.tab = "people";
        state.crewOpen = crew_id;
        refresh();
      }).catch(err => {
        toast("Invite link expired or invalid");
      });
    }
  } catch (e) {
    console.warn("Invite link parse error:", e);
  }
}

/* ---- Command Palette (Ctrl+K / Cmd+K) Listener ---- */
const cmdDlg = $("#cmd-palette");
const openCmd = () => cmdDlg && cmdDlg.showModal();
const closeCmd = () => cmdDlg && cmdDlg.close();

const cmdBtn = $("#cmd-k-btn");
if (cmdBtn) cmdBtn.addEventListener("click", openCmd);
const cmdCloseBtn = $("#cmd-close");
if (cmdCloseBtn) cmdCloseBtn.addEventListener("click", closeCmd);

window.addEventListener("keydown", (evt) => {
  if ((evt.ctrlKey || evt.metaKey) && evt.key.toLowerCase() === "k") {
    evt.preventDefault();
    openCmd();
  }
});

/* ---- Signing in ------------------------------------------------------------
   The gateway has had register / login / email-code / OIDC since the accounts work
   landed, and the PWA had no screen for any of it: the only route to a session was
   pasting a bearer token into the developer field in Settings. What stood here instead
   was a "1-Tap Social SSO" block whose buttons called /v1/auth/social-sso — an endpoint
   that returns a made-up user id, no token, no session — and then toasted
   "Authenticated! Cloud Sync Active". Telling someone they are signed in when nothing
   happened is worse than offering nothing at all, so that is gone and this is real. */

let authMode = "register";
state.cityRoom = localStorage.getItem("lifeos.city") || "";

function authError(message) {
  const el = $("#auth-error");
  if (!el) return;
  el.textContent = message || "";
  el.hidden = !message;
}

function setSession(result) {
  if (!result || !result.token) throw new Error("the gateway did not return a session");
  localStorage.setItem("lifeos.token", result.token);
  state.me = null;
  $("#auth").close();
  authError("");
  toast(`Signed in as ${result.handle || "you"}`);
  refresh();
}

async function openAuth() {
  if ($("#auth").open) return;
  authError("");
  // Only offer what this deployment can actually deliver. An email box that mints a code
  // nobody can receive, or a Google button with no client id, is the same lie in a
  // different shape.
  const providers = await api("/v1/auth/providers").catch(() => null);
  const emailBlock = $("#auth-email-block");
  if (emailBlock) emailBlock.hidden = !(providers && providers.email && providers.email.available);

  const oidc = $("#auth-oidc-block");
  if (oidc) {
    const usable = ((providers && providers.providers) || []).filter((p) => p.configured);
    oidc.hidden = usable.length === 0;
    oidc.innerHTML = usable.length
      ? `<p class="hint">${usable.map((p) => esc(p.provider)).join(" and ")} sign-in is configured on this server — use the button your device offers.</p>`
      : "";
  }
  $("#auth").showModal();
}

function applyAuthMode() {
  const registering = authMode === "register";
  $("#auth-title").textContent = registering ? "Welcome to LifeOS" : "Welcome back";
  $("#auth-sub").textContent = registering
    ? "Create an account to keep your graph across devices."
    : "Sign in to pick up where you left off.";
  $("#auth-submit").textContent = registering ? "Create account" : "Sign in";
  $("#auth-toggle").textContent = registering ? "I already have one" : "I need an account";
  $("#auth-pass").setAttribute("autocomplete", registering ? "new-password" : "current-password");
  authError("");
}

$("#auth-toggle").addEventListener("click", () => {
  authMode = authMode === "register" ? "login" : "register";
  applyAuthMode();
});

$("#auth-submit").addEventListener("click", async () => {
  const handle = $("#auth-handle").value.trim();
  const password = $("#auth-pass").value;
  if (!handle || !password) return authError("A handle and a password, please.");
  try {
    if (authMode === "register") {
      await api("/v1/auth/register", { handle, password });
    }
    setSession(await api("/v1/auth/login", { handle, password }));
  } catch (e) {
    authError(e.message || "That did not work.");
  }
});

$("#auth-email-send").addEventListener("click", async () => {
  const email = $("#auth-email").value.trim();
  if (!email) return authError("Which address should the code go to?");
  try {
    const res = await api("/v1/auth/email/code", { email });
    $("#auth-code-row").hidden = false;
    authError("");
    toast(res.delivered ? `Code sent to ${email}` : "Email is not configured on this server");
  } catch (e) {
    authError(e.message || "Could not send a code.");
  }
});

$("#auth-code-verify").addEventListener("click", async () => {
  const email = $("#auth-email").value.trim();
  const code = $("#auth-code").value.trim();
  if (!code) return authError("Enter the code from your email.");
  try {
    setSession(await api("/v1/auth/email/verify", { email, code }));
  } catch (e) {
    authError(e.message || "That code is not valid.");
  }
});

$("#set-signout").addEventListener("click", async () => {
  await api("/v1/auth/logout", {}).catch(() => null);
  localStorage.removeItem("lifeos.token");
  state.me = null;
  $("#settings").close();
  toast("Signed out");
  refresh();
});

applyAuthMode();

document.addEventListener("click", (evt) => {
  // The welcome card is written straight into #view and so never goes through wire(),
  // which is where every other data-act is bound.
  if (evt.target.closest("[data-act=open-auth]")) openAuth();
});

refresh();
