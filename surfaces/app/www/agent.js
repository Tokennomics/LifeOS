/* The agent card — the loop Meta's Muse made people expect, over this app's own rows.

   Say a goal and it becomes a plan; say "remember …" and it is kept where you can read
   and delete it; ask "what's next?" and you get what needs you, counted from rows. Anything
   the agent wants to *do* arrives here as a proposal with Approve / Reject, and nothing
   runs until you tap Approve. The server decides all of it (modules/agent/core.py); this
   file only renders and forwards taps.

   One listener on the card, delegated by `data-agent`, so the card can re-render its own
   insides after every action without the rest of Today re-rendering under your thumb. */
"use strict";

(function () {
  const LOG_KEY = "lifeos.agent.log";
  const LOG_MAX = 30;
  const A = { data: null, log: [], busy: false };

  try { A.log = JSON.parse(localStorage.getItem(LOG_KEY) || "[]").slice(-LOG_MAX); } catch (e) { A.log = []; }

  function saveLog() {
    A.log = A.log.slice(-LOG_MAX);
    try { localStorage.setItem(LOG_KEY, JSON.stringify(A.log)); } catch (e) {}
  }

  async function load() {
    const [checkin, goals, proposals, memory, push, calendars] = await Promise.all([
      api("/v1/agent/checkin").catch(() => null),
      api("/v1/agent/goals").then((r) => r.goals).catch(() => []),
      api("/v1/agent/proposals").then((r) => r.proposals).catch(() => []),
      api("/v1/agent/memory").then((r) => r.memory).catch(() => []),
      api("/v1/push/subscriptions").catch(() => null),
      api("/v1/calendar/sources").then((r) => r.sources).catch(() => []),
    ]);
    A.data = { checkin, goals, proposals, memory, push, calendars };
    return A.data;
  }

  // mailto: and sms: only, and only for a draft the server built. safeUrl() rightly
  // refuses both, so drafts get their own narrow gate rather than a hole in that one.
  function draftHref(u) {
    const raw = String(u || "");
    return /^(mailto|sms):/i.test(raw) ? esc(raw) : "#";
  }

  function bubble(m) {
    // A drafted message opens your mail app; a planned stop links to its listing (tickets
    // are yours to buy). safeUrl lets only http(s) through.
    const extra = (m.open ? `<a class="agent-open" href="${draftHref(m.open)}">Open draft</a>` : "")
      + (m.link ? `<a class="agent-open" href="${safeUrl(m.link)}" target="_blank" rel="noopener">Listing and tickets</a>` : "");
    return `<div class="agent-msg ${m.who === "you" ? "you" : "agent"}">${esc(m.text).replace(/\n/g, "<br>")}${extra}</div>`;
  }

  function proposalRow(p) {
    return `<div class="agent-row">
      <div class="agent-row-text">${esc(p.summary)}</div>
      <div class="agent-row-acts">
        <button class="primary agent-small" data-agent="approve" data-id="${esc(p.id)}">Approve</button>
        <button class="ghost agent-small" data-agent="reject" data-id="${esc(p.id)}">Reject</button>
      </div></div>`;
  }

  function goalBlock(g) {
    const steps = g.steps.map((s) => `<label class="agent-step${s.done ? " done" : ""}${g.next_step && g.next_step.id === s.id ? " next" : ""}">
        <input type="checkbox" data-agent="step" data-id="${esc(s.id)}" ${s.done ? "checked disabled" : ""}>
        <span>${esc(s.title)}</span></label>`).join("");
    const due = g.deadline ? ` · due ${esc(g.deadline)}` : "";
    const by = g.planned_by === "starter" ? " · starter steps" : "";
    return `<details class="agent-goal">
      <summary><span>${esc(g.title)}</span><span class="agent-meta">${g.done} of ${g.of} steps${due}${by}</span></summary>
      ${steps}
      <div class="agent-inline">
        <input class="field" data-agent-input="step" data-goal="${esc(g.id)}" placeholder="Add a step" maxlength="200">
        <button class="ghost agent-small" data-agent="add-step" data-goal="${esc(g.id)}">Add</button>
      </div>
    </details>`;
  }

  /* The morning check-in. Shown as what is true: whether this browser can receive push at
     all, whether a device is subscribed, and what the last send returned. */
  function pushSupported() {
    return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  }

  function pushBlock(push) {
    if (!pushSupported()) {
      return `<p class="hint agent-push">Morning check-in: this browser cannot receive notifications. On iPhone, add the app to your Home Screen first.</p>`;
    }
    const subs = (push && push.subscriptions) || [];
    const on = subs.length > 0;
    const last = subs.map((x) => x.last_result).filter(Boolean)[0] || "";
    return `<div class="agent-row agent-push">
      <div class="agent-row-text">Morning check-in · ${on ? `on, ${subs.length} device${subs.length === 1 ? "" : "s"}, ${String((push && push.checkin_hour) || 8).padStart(2, "0")}:00 your time${push && !push.checkins_running ? " (not scheduled on this server yet)" : ""}` : "off"}${last ? `<br><span class="agent-meta">last send: ${esc(last)}</span>` : ""}</div>
      <div class="agent-row-acts">${on
        ? `<button class="ghost agent-small" data-agent="push-test">Test</button><button class="ghost agent-small" data-agent="push-off">Turn off</button>`
        : `<button class="primary agent-small" data-agent="push-on">Turn on</button>`}</div>
    </div>`;
  }

  /* Your calendar both ways (modules/calendars/personal.py). Out: a subscribe link your
     phone's calendar app reads. In: your calendar's secret address, read as free/busy so
     "plan my day" stops planning over meetings. The secret address is never shown back. */
  function calendarBlock(cals) {
    const rows = cals.map((c) => `<div class="agent-row"><div class="agent-row-text">${esc(c.calendar)}<br><span class="agent-meta">${esc(c.last_status || "")}</span></div>
      <div class="agent-row-acts"><button class="ghost agent-small" data-agent="cal-remove" data-id="${esc(c.source_id)}">Remove</button></div></div>`).join("");
    return `<details class="agent-goal" id="agent-calendar">
      <summary><span>Calendar</span><span class="agent-meta">${cals.length ? `${cals.length} connected` : "not connected"}</span></summary>
      <div class="agent-row"><div class="agent-row-text">Put your LifeOS plans in your phone's calendar</div>
        <div class="agent-row-acts"><button class="ghost agent-small" data-agent="cal-link">Get link</button></div></div>
      <div id="agent-cal-link"></div>
      <p class="hint" style="margin-top:8px;">Show your busy times here, so plans avoid your meetings. Paste your calendar's secret iCal address (Google: Settings → your calendar → "Secret address in iCal format"). Only the times are kept, not titles.</p>
      <div class="agent-inline">
        <input class="field" id="agent-cal-url" placeholder="https://… or webcal://…" autocomplete="off">
        <button class="ghost agent-small" data-agent="cal-add">Connect</button>
      </div>
      ${rows}
    </details>`;
  }

  async function pushOn() {
    const allowed = await Notification.requestPermission();
    if (allowed !== "granted") throw new Error("Notifications were not allowed in this browser.");
    const reg = await navigator.serviceWorker.ready;
    const { public_key } = await api("/v1/push/key");
    const pad = "=".repeat((4 - (public_key.length % 4)) % 4);
    const raw = atob((public_key + pad).replace(/-/g, "+").replace(/_/g, "/"));
    const key = Uint8Array.from(raw, (c) => c.charCodeAt(0));
    const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    await api("/v1/push/subscribe", { subscription: sub.toJSON(), timezone });
  }

  async function pushOff() {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (sub) {
      await apiDelete("/v1/push/subscribe", { endpoint: sub.endpoint });
      await sub.unsubscribe();
    }
  }

  function inner() {
    const d = A.data || { checkin: null, goals: [], proposals: [], memory: [] };
    const needs = (d.checkin && d.checkin.needs_you || []).filter((i) => i.kind !== "approval");
    const log = A.log.slice(-8).map(bubble).join("") ||
      `<div class="agent-msg agent">Tell me a goal and I'll draft a plan. Say "remember …" and I'll keep it. Ask "what's next?" any time. I never act without your approval.</div>`;
    const assisted = state.health && state.health.claude;

    return `<h2>Your agent</h2>
      <p class="hint">${assisted ? "Plans and answers are drafted by a model over your own rows." :
        "Running without a model: goals, plans, memory and check-ins work; open questions need ANTHROPIC_API_KEY on the server."}</p>
      <div class="agent-log" id="agent-log">${log}</div>
      <div class="agent-inline">
        <input class="field" id="agent-input" data-agent-input="ask" placeholder="I want to… / plan Saturday in Lisbon / remember…" maxlength="2000" autocomplete="off">
        <button class="ghost agent-small" data-agent="mic" aria-label="Speak">🎙️</button>
        <button class="primary agent-small" data-agent="send">Send</button>
      </div>
      <div class="agent-chips">
        <button class="pill" data-agent="chip" data-text="What's next?">What's next?</button>
        <button class="pill" data-agent="chip" data-text="Plan today">Plan today</button>
        <button class="pill" data-agent="chip" data-text="I want to ">New goal</button>
        <button class="pill" data-agent="chip" data-text="Remember ">Remember…</button>
        <button class="pill" data-agent="chip" data-text="What do you know about me?">What you know</button>
      </div>
      ${d.proposals.length ? `<h3 class="agent-h">Waiting for your approval</h3>${d.proposals.map(proposalRow).join("")}` : ""}
      ${needs.length ? `<h3 class="agent-h">Needs you</h3>${needs.map((i) => `<div class="agent-row"><div class="agent-row-text">${esc(i.why)}</div></div>`).join("")}` : ""}
      ${d.goals.length ? `<h3 class="agent-h">Goals</h3>${d.goals.map(goalBlock).join("")}` : ""}
      ${pushBlock(d.push)}
      ${calendarBlock(d.calendars || [])}
      <details class="agent-goal">
        <summary><span>What I remember</span><span class="agent-meta">${d.memory.length}</span></summary>
        ${d.memory.length ? d.memory.map((f) => `<div class="agent-row"><div class="agent-row-text">${esc(f.text)}</div>
          <div class="agent-row-acts"><button class="ghost agent-small" data-agent="forget" data-id="${esc(f.id)}" aria-label="Forget">Forget</button></div></div>`).join("")
          : `<p class="hint">Nothing yet. Only what you tell me to remember is kept, and you can delete any of it here.</p>`}
      </details>`;
  }

  function cardHtml() {
    return `<div class="card" id="agent-card">${inner()}</div>`;
  }

  function redraw(card) {
    const open = [...card.querySelectorAll("details.agent-goal")].map((d) => d.open);
    card.innerHTML = inner();
    const linkBox = card.querySelector("#agent-cal-link");
    if (linkBox && A.calLink) {
      linkBox.innerHTML = `<div class="agent-row"><div class="agent-row-text" style="font-size:12px;">${esc(A.calLink.https)}<br><span class="agent-meta">${esc(A.calLink.warning)}</span></div></div>
        <div class="agent-inline"><a class="agent-open" href="${esc(A.calLink.webcal)}">Open in calendar</a>
        <button class="ghost agent-small" data-agent="cal-copy">Copy</button></div>`;
    }
    card.querySelectorAll("details.agent-goal").forEach((d, i) => { if (open[i]) d.open = true; });
    const log = card.querySelector("#agent-log");
    if (log) log.scrollTop = log.scrollHeight;
  }

  async function run(card, fn) {
    if (A.busy) return;
    A.busy = true;
    card.classList.add("agent-busy");
    try {
      await fn();
      await load();
    } catch (e) {
      toast("⚠ " + e.message);
    } finally {
      A.busy = false;
      card.classList.remove("agent-busy");
      redraw(card);
    }
  }

  function send(card, text) {
    text = String(text || "").trim();
    if (!text) return;
    A.log.push({ who: "you", text });
    saveLog();
    redraw(card);
    return run(card, async () => {
      const r = await api("/v1/agent/ask", { message: text });
      let reply = r.reply || "";
      if (r.intent !== "plan" && r.proposals && r.proposals.length) reply += `\n${r.proposals.length} action(s) waiting for your approval below.`;
      A.log.push({ who: "agent", text: reply });
      saveLog();
    });
  }

  function listen(card) {
    const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Speech) return toast("This browser has no speech input. Type instead.");
    try {
      const rec = new Speech();
      rec.lang = navigator.language || "en-US";
      rec.interimResults = false;
      rec.onresult = (evt) => send(card, evt.results[0][0].transcript);
      rec.onerror = () => toast("Didn't catch that. Try again or type.");
      rec.start();
      toast("Listening…");
    } catch (e) {
      toast("Speech input failed to start.");
    }
  }

  function attach(root) {
    const card = root.querySelector("#agent-card");
    if (!card || card.dataset.agentBound) return;
    card.dataset.agentBound = "1";
    const log = card.querySelector("#agent-log");
    if (log) log.scrollTop = log.scrollHeight;

    card.addEventListener("click", (evt) => {
      const el = evt.target.closest("[data-agent]");
      if (!el || !card.contains(el)) return;
      const what = el.dataset.agent;
      const id = el.dataset.id;
      if (what === "send") {
        const input = card.querySelector("#agent-input");
        const text = input.value;
        input.value = "";
        send(card, text);
      } else if (what === "chip") {
        const input = card.querySelector("#agent-input");
        const text = el.dataset.text;
        if (text.endsWith(" ")) { input.value = text; input.focus(); } else send(card, text);
      } else if (what === "mic") {
        listen(card);
      } else if (what === "approve") {
        run(card, async () => {
          const r = await api(`/v1/agent/proposals/${encodeURIComponent(id)}/approve`, {});
          const res = r.result || {};
          A.log.push({ who: "agent", text: "Done: " + (res.what || "approved"), open: res.open || "", link: res.url || "" });
          saveLog();
        });
      } else if (what === "reject") {
        run(card, () => api(`/v1/agent/proposals/${encodeURIComponent(id)}/reject`, {}));
      } else if (what === "step") {
        evt.preventDefault();
        run(card, async () => {
          const g = await api(`/v1/agent/steps/${encodeURIComponent(id)}/done`, {});
          if (g.status === "done") { A.log.push({ who: "agent", text: `Goal complete: ${g.title}` }); saveLog(); }
        });
      } else if (what === "add-step") {
        const input = card.querySelector(`[data-agent-input=step][data-goal="${CSS.escape(el.dataset.goal)}"]`);
        const title = input ? input.value.trim() : "";
        if (!title) return toast("Write the step first.");
        run(card, () => api(`/v1/agent/goals/${encodeURIComponent(el.dataset.goal)}/steps`, { title }));
      } else if (what === "cal-link") {
        run(card, async () => {
          const r = await api("/v1/calendar/link", {});
          const https = new URL(r.path, location.origin).href;
          A.calLink = { https, webcal: https.replace(/^https?:/, "webcal:"), warning: r.warning };
        });
      } else if (what === "cal-copy") {
        if (A.calLink && navigator.clipboard) navigator.clipboard.writeText(A.calLink.https).then(() => toast("Copied"), () => toast("Copy failed — select and copy it"));
      } else if (what === "cal-add") {
        const url = card.querySelector("#agent-cal-url").value.trim();
        if (!url) return toast("Paste the address first.");
        run(card, async () => {
          const r = await api("/v1/calendar/sources", { url });
          const synced = await api(`/v1/calendar/sources/${encodeURIComponent(r.source_id)}/sync`, {});
          A.log.push({ who: "agent", text: synced.status === "ok"
            ? `Connected. ${synced.busy_blocks} busy time(s) in the next month; I'll plan around them.`
            : "Saved, but the calendar could not be read yet. Check the address; it retries on every refresh." });
          saveLog();
        });
      } else if (what === "cal-remove") {
        run(card, () => apiDelete(`/v1/calendar/sources/${encodeURIComponent(id)}`));
      } else if (what === "push-on") {
        run(card, pushOn);
      } else if (what === "push-off") {
        run(card, pushOff);
      } else if (what === "push-test") {
        run(card, async () => {
          const r = await api("/v1/push/test", {});
          A.log.push({ who: "agent", text: r.push_delivered
            ? `Sent to ${r.delivered} of ${r.devices} device(s). It should appear in a moment.`
            : `Not delivered: ${r.why || (r.results && r.results[0] && r.results[0].why) || "unknown"}` });
          saveLog();
        });
      } else if (what === "forget") {
        run(card, () => apiDelete(`/v1/agent/memory/${encodeURIComponent(id)}`));
      }
    });

    card.addEventListener("keydown", (evt) => {
      if (evt.key !== "Enter" || evt.shiftKey) return;
      const input = evt.target.closest("[data-agent-input]");
      if (!input) return;
      evt.preventDefault();
      const btn = input.dataset.agentInput === "ask"
        ? card.querySelector("[data-agent=send]")
        : card.querySelector(`[data-agent=add-step][data-goal="${CSS.escape(input.dataset.goal)}"]`);
      if (btn) btn.click();
    });
  }

  window.LifeAgent = { load, cardHtml, attach, focus() {
    const input = document.querySelector("#agent-input");
    if (input) { input.scrollIntoView({ block: "center" }); input.focus(); }
  } };
})();
