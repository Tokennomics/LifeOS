/**
 * LifeOS PWA Visual Dashboard Extensions.
 *
 * Renders interactive UI cards for Habit Routines, Knowledge Vault,
 * Energy & Focus Balance, AI Assistant Chat, and Financial Goals.
 */

(function () {
    const API_BASE = '/v1';

    /* Every string below is interpolated into `innerHTML`. Without escaping, a routine
       named `<img src=x onerror=...>` executes — confirmed in Chromium, not inferred — and
       this page keeps the session bearer token in localStorage, so script execution here
       is account takeover. The three widgets read the account's own rows today, which makes
       it latent rather than live; it stops being latent the moment any of this text arrives
       from an ICS import, a seeded venue name, or another account. Matches `esc` in app.js. */
    function esc(value) {
        return String(value ?? "").replace(/[&<>"']/g, (c) => ({
            "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    }

    /* A number, or nothing. Interpolating an unchecked value into `style="width: …%"` is a
       CSS injection even when HTML-escaped, because the quotes are already there. */
    function num(value, { min = -Infinity, max = Infinity } = {}) {
        const n = Number(value);
        return Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : 0;
    }

    async function fetchJSON(endpoint, options = {}) {
        try {
            const token = localStorage.getItem("lifeos.token");
            const headers = Object.assign({}, options.headers || {});
            if (token) headers["Authorization"] = "Bearer " + token;
            const res = await fetch(`${API_BASE}${endpoint}`, { ...options, headers });
            if (!res.ok) return null;
            return await res.json();
        } catch (e) {
            console.error('API Error:', e);
            return null;
        }
    }

    // --- Habit Routines Widget ---
    async function renderRoutinesWidget(container) {
        const data = await fetchJSON('/routines/streaks');
        if (!data) return;

        let html = '<div class="card"><h3>🔥 Habit Routines</h3><ul class="routine-list">';
        data.forEach(r => {
            html += `
                <li class="routine-item" data-id="${esc(r.routine_id)}">
                    <div class="routine-info">
                        <strong>${esc(r.name)}</strong> — <span>${esc(r.trigger)}</span>
                        <span class="badge">Streak: ${num(r.streak, { min: 0 })} 🔥</span>
                    </div>
                    <button class="btn-complete" data-act="complete-routine" data-routine="${esc(r.routine_id)}">Done</button>
                </li>`;
        });
        html += '</ul></div>';
        container.innerHTML += html;
    }

    // --- Energy & Burnout Monitor Widget ---
    async function renderEnergyWidget(container) {
        const data = await fetchJSON('/horizon/energy-balance');
        if (!data) return;

        const riskClass = data.burnout_risk === 'high' ? 'risk-high' : (data.burnout_risk === 'moderate' ? 'risk-mod' : 'risk-low');
        const html = `
            <div class="card energy-card ${riskClass}">
                <h3>⚡ Energy & Focus Balance</h3>
                <div class="meter-group">
                    <p>Cognitive Load Index: <strong>${esc(data.cognitive_load_index)}</strong></p>
                    <p>Burnout Risk: <span class="risk-tag">${esc(String(data.burnout_risk ?? "").toUpperCase())}</span></p>
                </div>
                <p class="recommendation">💡 <em>${esc(data.recommendation)}</em></p>
            </div>`;
        container.innerHTML += html;
    }

    // --- Financial Goals Progress Widget ---
    async function renderFinanceWidget(container) {
        const data = await fetchJSON('/finance/summary');
        if (!data || !data.goals) return;

        let html = '<div class="card"><h3>💰 Financial Goals</h3>';
        data.goals.forEach(g => {
            html += `
                <div class="finance-goal">
                    <div class="goal-header">
                        <strong>${esc(g.title)}</strong>
                        <span>${esc(g.current_amount)} / ${esc(g.target_amount)} ${esc(g.currency)} (${num(g.completion_percentage, { min: 0, max: 100 })}%)</span>
                    </div>
                    <div class="progress-bar"><div class="fill" style="width: ${num(g.completion_percentage, { min: 0, max: 100 })}%"></div></div>
                </div>`;
        });
        html += '</div>';
        container.innerHTML += html;
    }

    // Public API
    window.LifeOSDashboard = {
        async init(containerId) {
            const container = document.getElementById(containerId);
            if (!container) return;

            /* One delegated listener, bound once, instead of an `onclick` attribute per row.
               The attribute version interpolated the routine id into HTML, so an id
               containing a quote broke out of it — and it was the last inline handler in the
               codebase, the other five having been removed because each one lied about what
               it did. `dataset` carries the id as data, where it cannot be parsed as code. */
            if (!container.dataset.wired) {
                container.addEventListener("click", (event) => {
                    const button = event.target.closest("[data-act=complete-routine]");
                    if (button && button.dataset.routine) {
                        window.LifeOSDashboard.completeRoutine(button.dataset.routine);
                    }
                });
                container.dataset.wired = "1";
            }

            container.innerHTML = '';
            await renderEnergyWidget(container);
            await renderRoutinesWidget(container);
            await renderFinanceWidget(container);
        },
        async completeRoutine(routineId) {
            await fetchJSON(`/routines/${routineId}/complete`, { method: 'POST' });
            window.LifeOSDashboard.init('dashboard-tab');
        }
    };
})();
