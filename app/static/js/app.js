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

    if (targetId === 'app' && !token) {
        showAuth();
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
chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const query = chatInput.value.trim();
    if (!query) return;

    addMessage("user", query);
    chatInput.value = "";

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
                query: query,
                connection_id: currentConnectionId
            })
        });

        const data = await response.json().catch(() => ({}));

        const loadingMsg = document.querySelector(`[data-id="${loadingId}"]`);
        if (loadingMsg) loadingMsg.remove();

        // Handle HTTP-level errors first (before reading data.success)
        if (response.status === 401) {
            addMessage("agent", "⚠️ Your session has expired. Please log in again.");
            token = null;
            localStorage.removeItem("sql_agent_token");
            setTimeout(() => location.reload(), 1500);
            return;
        }
        if (response.status === 403) {
            addMessage("agent", "⛔ Access denied. You do not have permission to perform this action.");
            return;
        }
        if (response.status >= 500) {
            addMessage("agent", "🔴 The server encountered an internal error. Please try again in a moment.");
            return;
        }

        if (data.success) {
            if (Array.isArray(data.results) && data.results.length > 0) {
                const tableHtml = createTableFromResults(data.results);
                addMessage("agent", data.message, tableHtml);
            } else {
                addMessage("agent", data.message);
            }
        } else {
            let errorMsg = data.message || "The query could not be completed.";
            if (data.error && data.error !== data.message) errorMsg += `\nDetails: ${data.error}`;
            addMessage("agent", errorMsg);
        }

    } catch (err) {
        const loadingMsg = document.querySelector(`[data-id="${loadingId}"]`);
        if (loadingMsg) loadingMsg.remove();
        addMessage("agent", "🔴 System Error: Failed to reach backend.");
        console.error(err);
    }
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