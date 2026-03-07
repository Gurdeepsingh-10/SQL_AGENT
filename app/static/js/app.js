// API Base URL
const API_BASE = "";

// Dark Mode Functions
function initDarkMode() {
    const savedTheme = localStorage.getItem("theme") || "light";
    document.documentElement.setAttribute("data-theme", savedTheme);
    updateThemeIcon(savedTheme);
}

function toggleDarkMode() {
    const currentTheme = document.documentElement.getAttribute("data-theme");
    const newTheme = currentTheme === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", newTheme);
    localStorage.setItem("theme", newTheme);
    updateThemeIcon(newTheme);
}

function updateThemeIcon(theme) {
    const icon = document.querySelector(".theme-icon");
    if (icon) {
        icon.textContent = theme === "dark" ? "🌙" : "☀️";
    }
}

// ============================================================
// HERO TERMINAL DEMO — Typing Animation
// ============================================================
function initHeroDemo() {
    const queryEl = document.getElementById('demo-query');
    const cursorEl = document.getElementById('demo-cursor');
    const responseEl = document.getElementById('demo-response');
    const sqlEl = document.getElementById('demo-sql');

    if (!queryEl) return;

    const demos = [
        {
            query: 'show top 5 products by revenue this month',
            sql: `SELECT product,\n  SUM(revenue) AS revenue,\n  COUNT(*) AS units\nFROM sales\nWHERE date >= DATE_TRUNC('month', NOW())\nGROUP BY product\nORDER BY revenue DESC\nLIMIT 5;`
        },
        {
            query: 'how many users signed up last week?',
            sql: `SELECT COUNT(*) AS new_users\nFROM users\nWHERE created_at >=\n  NOW() - INTERVAL '7 days';`
        },
        {
            query: 'list all orders that are still pending',
            sql: `SELECT id, customer,\n  amount, created_at\nFROM orders\nWHERE status = 'pending'\nORDER BY created_at ASC;`
        }
    ];

    let demoIndex = 0;
    let demoTimeout = null;

    function typeText(el, text, speed, callback) {
        let i = 0;
        el.textContent = '';
        const iv = setInterval(() => {
            el.textContent += text[i];
            i++;
            if (i >= text.length) {
                clearInterval(iv);
                if (callback) callback();
            }
        }, speed);
    }

    function runDemo() {
        const demo = demos[demoIndex % demos.length];
        demoIndex++;

        // Reset
        responseEl.classList.add('hidden');
        queryEl.textContent = '';
        sqlEl.textContent = '';
        cursorEl.style.display = 'inline';

        // 1. Type the query
        demoTimeout = setTimeout(() => {
            typeText(queryEl, demo.query, 42, () => {
                // 2. Brief pause then reveal response
                demoTimeout = setTimeout(() => {
                    cursorEl.style.display = 'none';
                    sqlEl.textContent = demo.sql;
                    responseEl.classList.remove('hidden');

                    // 3. Hold, then loop to next demo
                    demoTimeout = setTimeout(runDemo, 5800);
                }, 650);
            });
        }, 350);
    }

    // Start after page settles
    demoTimeout = setTimeout(runDemo, 900);
}

// ============================================================
// State
// ============================================================
let currentUser = null;
let token = localStorage.getItem("sql_agent_token");
// Restore the last-used connection ID from localStorage so it survives page refreshes
let currentConnectionId = (() => {
    const saved = localStorage.getItem("sql_agent_connection_id");
    return saved ? parseInt(saved, 10) : null;
})();

// DOM Elements
const authOverlay = document.getElementById("auth-overlay");
const loginForm = document.getElementById("login-form");
const registerForm = document.getElementById("register-form");
const showRegisterBtn = document.getElementById("show-register-btn");
const showLoginBtn = document.getElementById("show-login-btn");
const authError = document.getElementById("auth-error");
const dashboard = document.getElementById("dashboard");
const connectionList = document.getElementById("connection-list");
const addConnectionBtn = document.getElementById("add-connection-btn");
const connectionModal = document.getElementById("connection-modal");
const connectionForm = document.getElementById("connection-form");
const closeConnModal = document.getElementById("close-conn-modal");
const currentConnectionBadge = document.getElementById("current-connection-badge");
const chatHistory = document.getElementById("chat-history");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");

// ============================================================
// Navigation
// ============================================================
function navigateTo(targetId) {
    document.querySelectorAll('.section').forEach(section => {
        section.classList.add('hidden');
        section.classList.remove('active');
    });

    const targetSection = document.getElementById(`${targetId}-section`);
    if (targetSection) {
        targetSection.classList.remove('hidden');
        targetSection.classList.add('active');
    }

    document.querySelectorAll('.nav-link').forEach(link => {
        link.classList.remove('active');
        if (link.dataset.target === targetId) {
            link.classList.add('active');
        }
    });

    if ((targetId === 'app' || targetId === 'dashboard') && !token) {
        showAuth();
        return; // Stop navigation if unauthenticated
    }

    if (targetId === 'dashboard' && token && currentConnectionId) {
        loadDashboardData(currentConnectionId);
        startDashboardAutoRefresh(currentConnectionId);
    }
    // Stop auto-refresh when navigating away
    if (targetId !== 'dashboard' && _dashboardRefreshTimer) {
        clearInterval(_dashboardRefreshTimer);
        _dashboardRefreshTimer = null;
    }
}

// ============================================================
// Initialization
// ============================================================
document.addEventListener("DOMContentLoaded", () => {
    // Dark mode
    initDarkMode();
    const themeToggle = document.getElementById("theme-toggle");
    if (themeToggle) themeToggle.addEventListener("change", toggleDarkMode);

    // Navigation
    document.querySelectorAll('.nav-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            navigateTo(link.dataset.target);
        });
    });

    // Dashboard Telemetry Toggle
    const telemetryToggle = document.getElementById("telemetry-toggle");
    const labelDb = document.getElementById("label-db-telemetry");
    const labelAgent = document.getElementById("label-agent-telemetry");
    const viewDb = document.getElementById("db-telemetry-view");
    const viewAgent = document.getElementById("agent-telemetry-view");

    if (telemetryToggle) {
        telemetryToggle.addEventListener("change", (e) => {
            if (e.target.checked) {
                // Show Agent Telemetry
                labelDb.classList.remove("active");
                labelAgent.classList.add("active");
                viewDb.classList.remove("active");
                viewDb.classList.add("hidden");
                viewAgent.classList.remove("hidden");
                viewAgent.classList.add("active");
            } else {
                // Show DB Telemetry
                labelAgent.classList.remove("active");
                labelDb.classList.add("active");
                viewAgent.classList.remove("active");
                viewAgent.classList.add("hidden");
                viewDb.classList.remove("hidden");
                viewDb.classList.add("active");
            }
            // Re-render charts into now-visible canvases (Chart.js needs visible DOM)
            if (currentConnectionId) {
                setTimeout(() => loadDashboardData(currentConnectionId), 80);
            }
        });
    }

    // Refresh button on dashboard
    const dashRefreshBtn = document.getElementById("dashboard-refresh-btn");
    if (dashRefreshBtn) {
        dashRefreshBtn.addEventListener("click", () => {
            if (currentConnectionId) loadDashboardData(currentConnectionId);
        });
    }

    // Navbar logout
    const logoutBtnNav = document.getElementById("logout-btn-nav");
    if (logoutBtnNav) {
        logoutBtnNav.addEventListener("click", () => {
            token = null;
            localStorage.removeItem("sql_agent_token");
            // NOTE: We intentionally keep sql_agent_connection_id in localStorage
            // so it auto-restores when the user logs back in.
            location.reload();
        });
    }

    // Chat
    chatHistory.innerHTML = "";
    addMessage("agent", "System initialized. ready for input.");

    if (token) {
        const logoutNav = document.getElementById("logout-btn-nav");
        if (logoutNav) logoutNav.classList.remove("hidden");
        // Show a loading indicator in the badge while connections are being fetched
        if (currentConnectionBadge && currentConnectionId) {
            currentConnectionBadge.textContent = "LOADING...";
        }
        // Fetch connections from the backend — this will auto-restore the saved selection
        fetchConnections();
        navigateTo('hero');
    } else {
        navigateTo('hero');
    }

    // Start hero terminal demo
    initHeroDemo();
});

// ============================================================
// Authentication
// ============================================================
showRegisterBtn.addEventListener("click", () => {
    loginForm.classList.add("hidden");
    registerForm.classList.remove("hidden");
    authError.textContent = "";
});

showLoginBtn.addEventListener("click", () => {
    registerForm.classList.add("hidden");
    loginForm.classList.remove("hidden");
    authError.textContent = "";
});

loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = document.getElementById("username").value;
    const password = document.getElementById("password").value;

    try {
        const response = await fetch(`${API_BASE}/auth/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, password })
        });

        const data = await response.json();

        if (response.ok) {
            token = data.access_token;
            localStorage.setItem("sql_agent_token", token);
            currentUser = { email };
            showDashboard();
            fetchConnections();
        } else {
            let errorMsg = "Login failed";
            if (data.detail) {
                errorMsg = typeof data.detail === 'string'
                    ? data.detail
                    : Array.isArray(data.detail)
                        ? data.detail.map(e => e.msg).join(", ")
                        : JSON.stringify(data.detail);
            }
            authError.textContent = errorMsg;
        }
    } catch (err) {
        authError.textContent = "Network error";
    }
});

registerForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = document.getElementById("reg-email").value;
    const username = document.getElementById("reg-username").value;
    const password = document.getElementById("reg-password").value;

    try {
        const response = await fetch(`${API_BASE}/auth/register`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, username, password })
        });

        const data = await response.json();

        if (response.ok) {
            alert("Registration successful! Please login.");
            registerForm.classList.add("hidden");
            loginForm.classList.remove("hidden");
        } else {
            let errorMsg = "Registration failed";
            if (data.detail) {
                errorMsg = typeof data.detail === 'string'
                    ? data.detail
                    : Array.isArray(data.detail)
                        ? data.detail.map(e => e.msg).join(", ")
                        : JSON.stringify(data.detail);
            }
            authError.textContent = errorMsg;
        }
    } catch (err) {
        authError.textContent = "Network error";
    }
});

function showAuth() {
    authOverlay.classList.remove("hidden");
}

function showDashboard() {
    authOverlay.classList.add("hidden");
    navigateTo('app');
    const logoutNav = document.getElementById("logout-btn-nav");
    if (logoutNav) logoutNav.classList.remove("hidden");
}

// ============================================================
// Connections
// ============================================================
async function fetchConnections() {
    try {
        const response = await fetch(`${API_BASE}/connections/list`, {
            headers: { "Authorization": `Bearer ${token}` }
        });

        if (response.status === 401) {
            token = null;
            localStorage.removeItem("sql_agent_token");
            location.reload();
            return;
        }

        const connections = await response.json();
        renderConnections(connections);
    } catch (err) {
        console.error("Failed to fetch connections", err);
    }
}

function renderConnections(connections) {
    connectionList.innerHTML = "";

    const activeConnections = connections.filter(conn => conn.is_active);

    if (activeConnections.length === 0) {
        connectionList.innerHTML = "<div class='connection-item'>No connections</div>";
        // Clear stale saved connection if it no longer exists
        localStorage.removeItem("sql_agent_connection_id");
        currentConnectionId = null;
        if (currentConnectionBadge) currentConnectionBadge.textContent = "NO CONNECTION";
        return;
    }

    // Determine which connection to auto-select:
    // Priority 1: the saved connection ID from localStorage (survives refresh)
    // Priority 2: the connection marked as default
    // Priority 3: the first active connection
    let connectionToSelect = null;

    if (currentConnectionId) {
        // Verify the saved connection still exists and is active
        connectionToSelect = activeConnections.find(c => c.id === currentConnectionId) || null;
    }
    if (!connectionToSelect) {
        connectionToSelect = activeConnections.find(c => c.is_default) || activeConnections[0];
    }

    activeConnections.forEach(conn => {
        const div = document.createElement("div");
        div.className = "connection-item";
        div.innerHTML = `
            <div style="flex: 1; cursor: pointer;" class="conn-info">
                <span>${conn.connection_name}</span>
            </div>
            <button class="delete-btn" data-id="${conn.id}" title="Delete connection">×</button>
        `;

        div.querySelector(".conn-info").addEventListener("click", () => {
            selectConnection(conn);
        });

        div.querySelector(".delete-btn").addEventListener("click", async (e) => {
            e.stopPropagation();
            if (confirm(`Delete connection "${conn.connection_name}"?`)) {
                await deleteConnection(conn.id);
            }
        });

        connectionList.appendChild(div);
    });

    // Auto-select silently (no chat message) — this is a restore, not a user action
    if (connectionToSelect) {
        selectConnection(connectionToSelect, true);
        // Mark the active item in the list
        Array.from(connectionList.children).forEach(child => {
            const nameEl = child.querySelector && child.querySelector(".conn-info span");
            if (nameEl && nameEl.textContent === connectionToSelect.connection_name) {
                child.classList.add("active");
            }
        });
    }
}

async function deleteConnection(connectionId) {
    try {
        const response = await fetch(`${API_BASE}/connections/${connectionId}`, {
            method: "DELETE",
            headers: { "Authorization": `Bearer ${token}` }
        });

        if (response.ok) {
            if (currentConnectionId === connectionId) {
                currentConnectionId = null;
                // Clear the persisted selection since this connection is gone
                localStorage.removeItem("sql_agent_connection_id");
                if (currentConnectionBadge) currentConnectionBadge.textContent = "NO CONNECTION";
            }
            fetchConnections();
        } else {
            alert("Failed to delete connection");
        }
    } catch (err) {
        console.error("Error deleting connection:", err);
        alert("Error deleting connection");
    }
}

function selectConnection(conn, silent = false) {
    currentConnectionId = conn.id;
    // Persist the selected connection ID so it survives page refreshes
    localStorage.setItem("sql_agent_connection_id", conn.id);

    if (currentConnectionBadge) {
        currentConnectionBadge.textContent = conn.connection_name;
    }

    Array.from(connectionList.children).forEach(child => {
        child.classList.remove("active");
        if (child.querySelector && child.querySelector(".conn-info")) {
            const nameEl = child.querySelector(".conn-info span");
            if (nameEl && nameEl.textContent === conn.connection_name) {
                child.classList.add("active");
            }
        }
    });

    // Only show the "switched" message when the user explicitly clicks,
    // not when auto-restoring on page load
    if (!silent) {
        addMessage("agent", `Switched to connection: ${conn.connection_name}`);
    }
}

addConnectionBtn.addEventListener("click", () => {
    connectionModal.classList.remove("hidden");
});

closeConnModal.addEventListener("click", () => {
    connectionModal.classList.add("hidden");
});

connectionForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = document.getElementById("conn-name").value;
    const url = document.getElementById("conn-url").value;
    const setDefault = document.getElementById("conn-default")?.checked ?? true;
    const submitBtn = document.querySelector("#connection-form button[type='submit']");

    submitBtn.disabled = true;
    submitBtn.textContent = "Saving...";

    try {
        const response = await fetch(`${API_BASE}/connections/add`, {
            method: "POST",
            headers: {
                "Authorization": `Bearer ${token}`,
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                connection_name: name,
                connection_url: url,
                is_default: setDefault
            })
        });

        const data = await response.json();

        if (response.ok) {
            connectionModal.classList.add("hidden");
            document.getElementById("connection-form").reset();
            // Persist this connection so it auto-selects on next login
            localStorage.setItem("sql_agent_connection_id", data.id);
            currentConnectionId = data.id;
            await fetchConnections();
            addMessage("agent", `✅ Connection '${name}' saved. It will auto-connect on your next login.`);
        } else {
            alert(data.detail || "Failed to add connection");
        }
    } catch (err) {
        console.error(err);
        alert("Error adding connection");
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = "Save";
    }
});

// ============================================================
// Chat
// ============================================================
// ── Pending confirmation state ───────────────────────────────────────────────
let _pendingConfirmQuery = null;
let _pendingConfirmSQL = null;

// ── Send a query (core function — reused by chat + confirmation modal) ────────
async function _sendQuery(queryText, confirmed = false) {
    if (!currentConnectionId) {
        addMessage("agent", "Error: No database connection selected.");
        return;
    }

    const loadingId = addMessage("agent", "Processing... <span class='blink'>_</span>");

    try {
        const response = await fetch(`${API_BASE}/agent/query`, {
            method: "POST",
            headers: {
                "Authorization": `Bearer ${token}`,
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                query: queryText,
                connection_id: currentConnectionId,
                confirmed: confirmed,
            })
        });

        const data = await response.json().catch(() => ({}));
        const loadingMsg = document.querySelector(`[data-id="${loadingId}"]`);
        if (loadingMsg) loadingMsg.remove();

        if (response.status === 401) {
            addMessage("agent", "⚠️ Your session has expired. Please log in again.");
            token = null; localStorage.removeItem("sql_agent_token");
            setTimeout(() => location.reload(), 1500); return;
        }
        if (response.status === 403) { addMessage("agent", "⛔ Access denied."); return; }
        if (response.status >= 500) { addMessage("agent", "🔴 Server error. Please try again."); return; }

        // ── Confirmation required ───────────────────────────────────────────────
        if (data.requires_confirmation && data.pending_sql) {
            _pendingConfirmQuery = queryText;
            _pendingConfirmSQL = data.pending_sql;
            // Show modal
            document.getElementById('confirm-sql').textContent = data.pending_sql;
            document.getElementById('confirm-message').textContent =
                data.message || 'This query will modify your database.';
            const badge = document.getElementById('confirm-risk-badge');
            if (badge) {
                const isDanger = data.message && data.message.includes('permanently');
                badge.textContent = isDanger ? 'DANGER' : 'CONFIRM';
                badge.style.background = isDanger ? '#ef444422' : '#f59e0b22';
                badge.style.color = isDanger ? '#ef4444' : '#f59e0b';
            }
            document.getElementById('confirm-modal').classList.remove('hidden');
            return;
        }

        if (data.success) {
            if (Array.isArray(data.results) && data.results.length > 0) {
                let extraHtml = createTableFromResults(data.results);
                if (data.chart_config) {
                    const canvasId = `chart-${Date.now()}`;
                    extraHtml = `<div class="chart-container" style="position:relative;height:35vh;width:100%;margin-bottom:20px;background:var(--panel-bg);padding:10px;border-radius:8px;"><canvas id="${canvasId}"></canvas></div>` + extraHtml;
                    addMessage("agent", data.message, extraHtml);
                    setTimeout(() => {
                        const ctx2 = document.getElementById(canvasId);
                        if (ctx2) {
                            try {
                                let cfg = data.chart_config;
                                if (!cfg.data) cfg.data = { labels: [], datasets: [{ data: [] }] };
                                const keys = Object.keys(data.results[0]);
                                if (keys.length >= 2 && (!cfg.data.labels || !cfg.data.labels.length)) {
                                    cfg.data.labels = data.results.map(r => String(r[keys[0]]));
                                    if (cfg.data.datasets?.length) {
                                        cfg.data.datasets[0].data = data.results.map(r => Number(r[keys[1]]));
                                        cfg.data.datasets[0].backgroundColor = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4'].map(c => c + 'aa');
                                    }
                                }
                                if (!cfg.options) cfg.options = {};
                                cfg.options.responsive = true; cfg.options.maintainAspectRatio = false;
                                new Chart(ctx2, cfg);
                            } catch (ce) { console.error('Chart error:', ce); }
                        }
                    }, 50);
                } else {
                    addMessage("agent", data.message, extraHtml);
                }
            } else {
                addMessage("agent", data.message);
            }
            // ── Active dashboard refresh ───────────────────────────────────────────
            // Fire in background so the dashboard stays live after every query
            if (currentConnectionId) {
                setTimeout(() => loadDashboardData(currentConnectionId), 600);
            }
        } else {
            let errorMsg = data.message || "The query could not be completed.";
            if (data.error && data.error !== data.message) errorMsg += `\nDetails: ${data.error}`;
            addMessage("agent", errorMsg);
        }

    } catch (err) {
        const loadingMsg2 = document.querySelector(`[data-id="${loadingId}"]`);
        if (loadingMsg2) loadingMsg2.remove();
        addMessage("agent", "🔴 System Error: Failed to reach backend.");
        console.error(err);
    }
}

// ── Confirmation modal buttons ────────────────────────────────────────────────
document.getElementById('confirm-approve-btn')?.addEventListener('click', async () => {
    document.getElementById('confirm-modal').classList.add('hidden');
    if (_pendingConfirmQuery) {
        addMessage("user", "✓ Approved — executing query");
        await _sendQuery(_pendingConfirmQuery, true);
        _pendingConfirmQuery = null; _pendingConfirmSQL = null;
    }
});
document.getElementById('confirm-cancel-btn')?.addEventListener('click', () => {
    document.getElementById('confirm-modal').classList.add('hidden');
    addMessage("agent", "❌ Execution cancelled. No changes were made.");
    _pendingConfirmQuery = null; _pendingConfirmSQL = null;
});

// ── Chat form submit ──────────────────────────────────────────────────────────
chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const query = chatInput.value.trim();
    if (!query) return;
    addMessage("user", query);
    chatInput.value = "";
    await _sendQuery(query);
});




function addMessage(role, content, extraHtml = null) {
    const div = document.createElement("div");
    div.className = `message ${role}`;

    let formattedContent = content
        .replace(/```sql([\s\S]*?)```/g, "<pre><code>$1</code></pre>")
        .replace(/```([\s\S]*?)```/g, "<pre><code>$1</code></pre>")
        .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
        .replace(/`([^`]+)`/g, "<code style='background:var(--input-bg);padding:1px 4px;border-radius:3px'>$1</code>")
        .replace(/\n/g, "<br>");

    div.innerHTML = `<div class="message-content">${formattedContent}</div>`;

    if (extraHtml) {
        const extraDiv = document.createElement("div");
        extraDiv.innerHTML = extraHtml;
        div.appendChild(extraDiv);
    }

    const id = Date.now();
    div.setAttribute("data-id", id);

    chatHistory.appendChild(div);
    chatHistory.scrollTop = chatHistory.scrollHeight;

    return id;
}

function createTableFromResults(results) {
    if (!results || results.length === 0) return "";

    const headers = Object.keys(results[0]);

    let html = `<div class="table-container"><table><thead><tr>`;
    headers.forEach(h => html += `<th>${h}</th>`);
    html += `</tr></thead><tbody>`;

    results.forEach(row => {
        html += `<tr>`;
        headers.forEach(h => html += `<td>${row[h] !== null ? row[h] : 'NULL'}</td>`);
        html += `</tr>`;
    });

    html += `</tbody></table></div>`;
    return html;
}

// ============================================================
// Dashboard Telemetry — Real-time Auto-Rendering Engine
// ============================================================

// Track all chart instances — destroy & recreate on every reload
const _charts = {};
let _dashboardRefreshTimer = null;

/**
 * Stable deterministic color from a string (table name).
 * Same string ALWAYS produces the same colour — no more legend shuffling.
 */
function tableColor(str) {
    const palette = [
        '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
        '#06b6d4', '#f97316', '#84cc16', '#ec4899', '#6366f1',
        '#14b8a6', '#a78bfa', '#fb923c', '#4ade80', '#f43f5e',
    ];
    let hash = 0;
    for (let i = 0; i < str.length; i++) hash = (hash * 31 + str.charCodeAt(i)) | 0;
    return palette[Math.abs(hash) % palette.length];
}

const SUCCESS_COLORS = { ok: '#10b981cc', fail: '#ef4444cc' };

// Shared Chart.js option presets
const _gridOpts = (axis) => axis === 'y'
    ? { beginAtZero: true, grid: { color: 'rgba(128,128,128,0.1)' }, ticks: { color: '#9ca3af' } }
    : { grid: { display: false }, ticks: { color: '#9ca3af' } };

const _baseOpts = (extra = {}) => ({
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 500 },
    plugins: { legend: { display: false } },
    ...extra
});

function _mkChart(id, cfg) {
    const el = document.getElementById(id);
    if (!el) return;
    if (_charts[id]) { _charts[id].destroy(); }
    _charts[id] = new Chart(el, cfg);
}

function _destroyAllCharts() {
    Object.values(_charts).forEach(c => { try { c.destroy(); } catch (e) { } });
    Object.keys(_charts).forEach(k => delete _charts[k]);
}

function _setKpi(id, value, extraStyle = '') {
    const el = document.getElementById(id);
    if (!el) return;
    const v = el.querySelector('.kpi-value') || el;
    v.innerHTML = value;
    if (extraStyle) v.style.cssText += extraStyle;
}

function _spinner(ids) {
    ids.forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        const v = el.querySelector('.kpi-value') || el;
        v.innerHTML = "<span class='blink'>…</span>";
    });
}

// ── Main loader ──────────────────────────────────────────────────────────────
async function loadDashboardData(connectionId) {
    if (!connectionId) return;

    // Spinner all KPIs
    _spinner([
        'kpi-tables', 'kpi-rows', 'kpi-size', 'kpi-cols', 'kpi-health',
        'kpi-latency', 'kpi-peak-latency', 'kpi-total-queries',
        'kpi-success-rate', 'kpi-tokens', 'kpi-cost', 'kpi-avg-tokens', 'kpi-langsmith-status',
    ]);
    // Also pulse the intel strip values
    ['intel-no-pk', 'intel-conns', 'intel-dialect'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.innerHTML = "<span class='blink'>…</span>";
    });

    await Promise.all([
        _loadDbTelemetry(connectionId),
        _loadAgentTelemetry(connectionId),
    ]);

    const badge = document.getElementById("dashboard-last-refresh");
    if (badge) badge.textContent = `Updated ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}`;
}

// ── DB Telemetry ─────────────────────────────────────────────────────────────
async function _loadDbTelemetry(connectionId) {
    try {
        const res = await fetch(`${API_BASE}/dashboard/${connectionId}/db-telemetry`, {
            headers: { "Authorization": `Bearer ${token}` }
        });
        if (!res.ok) return;
        const d = await res.json();
        if (!d.success) return;

        const m = d.metrics;

        // ── Core 5 KPI cards ────────────────────────────────────────────────
        _setKpi('kpi-tables', m.total_tables ?? '--');
        _setKpi('kpi-rows', m.total_rows != null ? Number(m.total_rows).toLocaleString() : '--');
        _setKpi('kpi-size', m.db_size ?? '--');
        _setKpi('kpi-cols', m.total_columns ?? '--');
        const healthEl = document.getElementById('kpi-health')?.querySelector('.kpi-value');
        if (healthEl) {
            healthEl.textContent = m.status ?? 'Unknown';
            healthEl.style.color = m.status === 'Healthy' ? '#22c55e' : '#ef4444';
        }

        // ── DB Intel strip (horizontal info bar) ────────────────────────────
        const setIntel = (id, val) => {
            const el = document.getElementById(id);
            if (el) el.textContent = val ?? '--';
        };
        setIntel('intel-no-pk', `${m.tables_no_pk ?? '--'} of ${m.total_tables ?? '--'} tables`);
        setIntel('intel-conns', `${m.active_connections ?? '--'} / ${m.pool_size ?? '--'} pool`);
        // Show first 40 chars of dialect version (can be long pg version string)
        const dialectFull = m.dialect_version ?? '--';
        setIntel('intel-dialect', dialectFull.length > 42 ? dialectFull.substring(0, 40) + '…' : dialectFull);

        // ── Chart data setup ─────────────────────────────────────────────────
        const schemaDetails = d.schema_details || {};
        const tableNames = Object.keys(schemaDetails);
        const rowCounts = tableNames.map(t => schemaDetails[t].row_count ?? 0);
        const colCounts = tableNames.map(t => schemaDetails[t].col_count ?? 0);
        const colors = tableNames.map(t => tableColor(t)); // stable per name

        // ① Horizontal Bar — Data Volume ──────────────────────────────────
        _mkChart('chart-rows-bar', {
            type: 'bar',
            data: {
                labels: tableNames,
                datasets: [{
                    label: 'Rows', data: rowCounts,
                    backgroundColor: colors.map(c => c + 'cc'),
                    borderColor: colors, borderWidth: 2, borderRadius: 6,
                }]
            },
            options: {
                ..._baseOpts(),
                indexAxis: 'y',   // ← horizontal
                plugins: {
                    legend: { display: false },
                    tooltip: { callbacks: { label: ctx => ` ${ctx.parsed.x.toLocaleString()} rows` } }
                },
                scales: {
                    x: { ..._gridOpts('y'), beginAtZero: true },
                    y: { grid: { display: false }, ticks: { color: '#9ca3af', font: { size: 11 } } }
                }
            }
        });

        // ② Doughnut — Table Share ──────────────────────────────────────────
        const totalRows = rowCounts.reduce((a, b) => a + b, 0);
        if (totalRows > 0) {
            _mkChart('chart-rows-doughnut', {
                type: 'doughnut',
                data: {
                    labels: tableNames,
                    datasets: [{
                        data: rowCounts,
                        backgroundColor: colors.map(c => c + 'cc'),
                        borderColor: colors, borderWidth: 2, hoverOffset: 10
                    }]
                },
                options: {
                    ..._baseOpts({ cutout: '65%' }),
                    plugins: {
                        legend: { display: true, position: 'bottom', labels: { color: '#9ca3af', padding: 10, boxWidth: 12 } },
                        tooltip: {
                            callbacks: {
                                label: ctx => {
                                    const pct = ((ctx.parsed / totalRows) * 100).toFixed(1);
                                    return ` ${ctx.label}: ${ctx.parsed.toLocaleString()} (${pct}%)`;
                                }
                            }
                        }
                    }
                }
            });
        }

        // ③ Polar Area — Schema Complexity (unique / cool chart) ───────────
        if (tableNames.length > 0) {
            _mkChart('chart-columns-bar', {
                type: 'polarArea',
                data: {
                    labels: tableNames,
                    datasets: [{
                        data: colCounts,
                        backgroundColor: colors.map(c => c + 'aa'),
                        borderColor: colors, borderWidth: 2,
                    }]
                },
                options: {
                    ..._baseOpts(),
                    plugins: {
                        legend: { display: true, position: 'bottom', labels: { color: '#9ca3af', boxWidth: 12, padding: 8 } },
                        tooltip: { callbacks: { label: ctx => ` ${ctx.label}: ${ctx.parsed.r} columns` } }
                    },
                    scales: {
                        r: {
                            ticks: { display: false },
                            grid: { color: 'rgba(128,128,128,0.15)' },
                            pointLabels: { display: false },
                        }
                    }
                }
            });
        }

        // ④ Doughnut — PK Coverage ──────────────────────────────────────────
        const hasPk = tableNames.filter(t => schemaDetails[t].has_pk).length;
        const noPk = tableNames.length - hasPk;
        _mkChart('chart-pk-coverage', {
            type: 'doughnut',
            data: {
                labels: ['Has PK', 'No PK'],
                datasets: [{
                    data: [hasPk, noPk],
                    backgroundColor: ['#10b981cc', '#ef4444cc'],
                    borderColor: ['#10b981', '#ef4444'], borderWidth: 2, hoverOffset: 8
                }]
            },
            options: {
                ..._baseOpts({ cutout: '60%' }),
                plugins: {
                    legend: { display: true, position: 'bottom', labels: { color: '#9ca3af', boxWidth: 12, padding: 10 } },
                    tooltip: { callbacks: { label: ctx => ` ${ctx.label}: ${ctx.parsed} tables` } }
                }
            }
        });

        // ── Schema detail table ──────────────────────────────────────────────
        const schemaContainer = document.getElementById("db-schema-chart-container");
        if (schemaContainer) {
            const totalR = rowCounts.reduce((a, b) => a + b, 0);
            let html = `<table class="schema-detail-table"><thead><tr>
                <th>Table</th><th>Rows</th><th>Share</th><th>Columns</th><th>PK</th>
            </tr></thead><tbody>`;
            tableNames.forEach((name, i) => {
                const info = schemaDetails[name];
                const pct = totalR > 0 ? ((info.row_count / totalR) * 100).toFixed(1) : '0.0';
                const col = colors[i];
                const pkBadge = info.has_pk
                    ? `<span style="color:#10b981;font-size:0.75rem">✓ PK</span>`
                    : `<span style="color:#f59e0b;font-size:0.75rem">⚠ None</span>`;
                const bar = `<div style="height:6px;width:100%;background:var(--border-color);border-radius:3px;overflow:hidden">
                              <div style="height:100%;width:${pct}%;background:${col};border-radius:3px"></div></div>`;
                html += `<tr>
                    <td><strong>${name}</strong></td>
                    <td style="font-variant-numeric:tabular-nums">${info.row_count.toLocaleString()}</td>
                    <td style="min-width:80px">${bar}<span style="font-size:0.72rem;opacity:0.6">${pct}%</span></td>
                    <td>${info.col_count}</td>
                    <td>${pkBadge}</td>
                </tr>`;
            });
            html += "</tbody></table>";
            schemaContainer.innerHTML = html;
        }

    } catch (e) {
        console.error("DB telemetry error:", e);
    }
}


// ── Agent Telemetry ───────────────────────────────────────────────────────────
async function _loadAgentTelemetry(connectionId) {
    try {
        const res = await fetch(`${API_BASE}/dashboard/${connectionId}/agent-telemetry`, {
            headers: { "Authorization": `Bearer ${token}` }
        });
        if (!res.ok) return;
        const d = await res.json();
        if (!d.success) return;

        const m = d.metrics;

        // KPIs (core + new)
        _setKpi('kpi-latency', m.avg_latency);
        _setKpi('kpi-peak-latency', m.peak_latency ?? '--');
        _setKpi('kpi-total-queries', m.total_queries);
        _setKpi('kpi-success-rate', m.success_rate);
        _setKpi('kpi-tokens', `<span style="font-size:0.9rem">${m.token_display ?? '--'}</span>`);
        _setKpi('kpi-cost', m.est_cost_usd ?? '--');
        _setKpi('kpi-avg-tokens', m.avg_tokens_per_query ?? '--');

        // LangSmith status badge
        const ls = m.langsmith || {};
        const lsStatusEl = document.querySelector('#kpi-langsmith-status .kpi-value') ||
            document.getElementById('kpi-langsmith-status');
        if (lsStatusEl) {
            lsStatusEl.textContent = ls.configured ? (ls.total_tokens != null ? '● Live' : '⚠ Error') : '○ Off';
            lsStatusEl.style.color = ls.configured && ls.total_tokens != null ? '#22c55e'
                : ls.configured ? '#f59e0b' : '#9ca3af';
        }

        // Intent colors also use stable hash
        _mkChart('chart-success-fail', {
            type: 'doughnut',
            data: {
                labels: ['Success', 'Failed'],
                datasets: [{
                    data: [m.successful ?? 0, m.failed ?? 0],
                    backgroundColor: [SUCCESS_COLORS.ok, SUCCESS_COLORS.fail],
                    borderColor: ['#10b981', '#ef4444'], borderWidth: 2, hoverOffset: 8
                }]
            },
            options: {
                ..._baseOpts({ cutout: '60%' }),
                plugins: {
                    legend: { display: true, position: 'bottom', labels: { color: '#9ca3af', boxWidth: 12, padding: 10 } },
                    tooltip: { callbacks: { label: ctx => ` ${ctx.label}: ${ctx.parsed}` } }
                }
            }
        });

        // ⑥  Pie — intent distribution (stable colors by intent name)
        const intents = d.intent_distribution || {};
        const intentNames = Object.keys(intents);
        const intentValues = Object.values(intents);
        const intentColors = intentNames.map(n => tableColor(n));  // stable per intent name
        if (intentNames.length > 0) {
            _mkChart('chart-intent-pie', {
                type: 'pie',
                data: {
                    labels: intentNames,
                    datasets: [{
                        data: intentValues,
                        backgroundColor: intentColors.map(c => c + 'bb'),
                        borderColor: intentColors, borderWidth: 2, hoverOffset: 8
                    }]
                },
                options: {
                    ..._baseOpts(),
                    plugins: {
                        legend: { display: true, position: 'bottom', labels: { color: '#9ca3af', boxWidth: 12, padding: 8 } },
                        tooltip: { callbacks: { label: ctx => ` ${ctx.label}: ${ctx.parsed} queries` } }
                    }
                }
            });
        }

        // ⑥ Line — latency trend
        const trend = d.latency_trend || [];
        if (trend.length > 0) {
            _mkChart('chart-latency-trend', {
                type: 'line',
                data: {
                    labels: trend.map(t => t.label),
                    datasets: [{
                        label: 'Latency (s)',
                        data: trend.map(t => t.latency),
                        borderColor: '#3b82f6',
                        backgroundColor: 'rgba(59,130,246,0.1)',
                        borderWidth: 2.5,
                        pointBackgroundColor: '#3b82f6',
                        pointRadius: 5,
                        pointHoverRadius: 7,
                        tension: 0.4,
                        fill: true,
                    }]
                },
                options: {
                    ..._baseOpts(),
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                title: (items) => {
                                    const t = trend[items[0].dataIndex];
                                    return t ? new Date(t.timestamp).toLocaleTimeString() : '';
                                },
                                label: ctx => ` ${ctx.parsed.y}s`
                            }
                        }
                    },
                    scales: {
                        y: { ..._gridOpts('y'), title: { display: true, text: 'seconds', color: '#9ca3af', font: { size: 11 } } },
                        x: _gridOpts('x')
                    }
                }
            });
        }

        renderQueryHistory(d.history);

    } catch (e) {
        console.error("Agent telemetry error:", e);
    }
}

// ── Auto-refresh (ONLY while dashboard tab is visible) ───────────────────────
function startDashboardAutoRefresh(connectionId) {
    if (_dashboardRefreshTimer) clearInterval(_dashboardRefreshTimer);
    _dashboardRefreshTimer = setInterval(() => {
        if (currentConnectionId) loadDashboardData(currentConnectionId);
    }, 30000);
}

// ── Query history table ───────────────────────────────────────────────────────
function formatDate(isoStr) {
    if (!isoStr) return "--";
    const d = new Date(isoStr);
    return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function renderQueryHistory(historyList) {
    const tbody = document.querySelector("#query-history-table tbody");
    if (!tbody) return;
    tbody.innerHTML = "";

    if (!historyList || historyList.length === 0) {
        tbody.innerHTML = "<tr><td colspan='5' style='text-align:center;padding:24px;opacity:0.45'>No queries recorded yet</td></tr>";
        return;
    }

    historyList.forEach(q => {
        const tr = document.createElement("tr");
        const isOk = q.status === "Success";
        const badge = isOk
            ? `<span class="status-badge status-ok">✓ Success</span>`
            : `<span class="status-badge status-fail">✗ Failed</span>`;
        const shortPrompt = q.prompt.length > 60 ? q.prompt.substring(0, 60) + '…' : q.prompt;
        tr.innerHTML = `
            <td style="white-space:nowrap">${formatDate(q.timestamp)}</td>
            <td title="${q.prompt.replace(/"/g, '&quot;')}">${shortPrompt}</td>
            <td><code style="font-size:0.78rem;opacity:0.8">${q.intent}</code></td>
            <td>${q.latency}s</td>
            <td>${badge}</td>
        `;
        tbody.appendChild(tr);
    });
}