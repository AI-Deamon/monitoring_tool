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
            const parts = path.split('/');
            const agentIndex = parts.indexOf('agent');
            if (agentIndex !== -1 && parts[agentIndex + 1]) {
                const currentAgentId = parts[agentIndex + 1];
                // Set the dropdown to show the current agent
                agentSelect.value = currentAgentId;
                console.log('Selected agent:', currentAgentId);
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
        const newDate = safeDateParam(e.target.value);
        const url = new URL(window.location.pathname, window.location.origin);
        if (newDate) url.searchParams.set('date', newDate);
        window.location.assign(url.pathname + url.search);  // same-origin, path+query only
    });

    // Handle Agent Change
    agentSelect.addEventListener('change', (e) => {
        const agentId = safeAgentId(e.target.value);
        const dateParam = safeDateParam(new URLSearchParams(window.location.search).get('date'));

        let newPath;
        if (agentId) {
            // Go to specific agent
            newPath = `/dashboard/agent/${agentId}`;
        } else {
            // Go to Overview
            newPath = `/dashboard/`;
        }

        // Construct new URL preserving Date param
        const url = new URL(newPath, window.location.origin);
        if (dateParam) {
            url.searchParams.set('date', dateParam);
        }

        window.location.assign(url.pathname + url.search);  // same-origin, path+query only
    });
}

// Initialize on load
document.addEventListener('DOMContentLoaded', loadSelectors);
