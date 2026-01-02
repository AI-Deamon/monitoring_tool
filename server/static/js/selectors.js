/**
 * Dashboard Selectors Logic
 * Handles global Agent and Date selection.
 */

async function loadSelectors() {
    const agentSelect = document.getElementById('global-agent-select');
    const dateSelect = document.getElementById('global-date-select');

    if (!agentSelect || !dateSelect) return;

    // 1. Set Date from URL or Default (Today)
    const urlParams = new URLSearchParams(window.location.search);
    const currentDateParam = urlParams.get('date');

    if (currentDateParam) {
        dateSelect.value = currentDateParam;
    } else {
        dateSelect.valueAsDate = new Date();
    }

    // 2. Fetch and Populate Agents
    try {
        // Use the API that supports date filtering, though mainly we just need the list here
        const data = await fetchJSON('/dashboard/api/agents');

        // Clear "Loading..." option
        // Keep the first "Overview" option
        while (agentSelect.options.length > 1) {
            agentSelect.remove(1);
        }

        if (data && data.data) {
            data.data.forEach(agent => {
                const option = document.createElement('option');
                option.value = agent.agent_id;
                option.textContent = `${agent.hostname} (${agent.status})`;
                if (agent.status === 'offline') {
                    option.textContent += ' 🔴';
                } else {
                    option.textContent += ' 🟢';
                }
                agentSelect.appendChild(option);
            });
        }

        // 3. Set Selected Agent based on URL
        // Check if we are in /agent/<id> view
        const path = window.location.pathname;
        if (path.includes('/dashboard/agent/')) {
            // Extract Agent ID from path: /dashboard/agent/UUID-Here
            // or /dashboard/agent/UUID-Here/details etc.
            const parts = path.split('/');
            const agentIndex = parts.indexOf('agent');
            if (agentIndex !== -1 && parts[agentIndex + 1]) {
                const currentAgentId = parts[agentIndex + 1];
                agentSelect.value = currentAgentId;
            }
        } else {
            agentSelect.value = ""; // Overview
        }

    } catch (e) {
        console.error("Error loading agents for selector:", e);
    }

    // =========================================================
    // EVENT LISTENERS
    // =========================================================

    // Handle Date Change
    dateSelect.addEventListener('change', (e) => {
        const newDate = e.target.value;
        const currentUrl = new URL(window.location.href);
        if (newDate) {
            currentUrl.searchParams.set('date', newDate);
        } else {
            currentUrl.searchParams.delete('date');
        }
        window.location.href = currentUrl.toString();
    });

    // Handle Agent Change
    agentSelect.addEventListener('change', (e) => {
        const agentId = e.target.value;
        const currentUrl = new URL(window.location.href);
        const dateParam = currentUrl.searchParams.get('date');

        let newPath;
        if (agentId) {
            // Go to specific agent
            newPath = `/dashboard/agent/${agentId}`;
        } else {
            // Go to Overview
            newPath = `/dashboard/`;
        }

        // Construct new URL preserving Date param
        const newUrl = new URL(newPath, window.location.origin);
        if (dateParam) {
            newUrl.searchParams.set('date', dateParam);
        }

        window.location.href = newUrl.toString();
    });
}

// Initialize on load
document.addEventListener('DOMContentLoaded', loadSelectors);
