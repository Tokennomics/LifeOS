/**
 * LifeOS PWA Visual Dashboard Extensions.
 *
 * Renders interactive UI cards for Habit Routines, Knowledge Vault,
 * Energy & Focus Balance, AI Assistant Chat, and Financial Goals.
 */

(function () {
    const API_BASE = '/v1';

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
                <li class="routine-item" data-id="${r.routine_id}">
                    <div class="routine-info">
                        <strong>${r.name}</strong> — <span>${r.trigger}</span>
                        <span class="badge">Streak: ${r.streak} 🔥</span>
                    </div>
                    <button class="btn-complete" onclick="LifeOSDashboard.completeRoutine('${r.routine_id}')">Done</button>
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
                    <p>Cognitive Load Index: <strong>${data.cognitive_load_index}</strong></p>
                    <p>Burnout Risk: <span class="risk-tag">${data.burnout_risk.toUpperCase()}</span></p>
                </div>
                <p class="recommendation">💡 <em>${data.recommendation}</em></p>
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
                        <strong>${g.title}</strong>
                        <span>${g.current_amount} / ${g.target_amount} ${g.currency} (${g.completion_percentage}%)</span>
                    </div>
                    <div class="progress-bar"><div class="fill" style="width: ${g.completion_percentage}%"></div></div>
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
