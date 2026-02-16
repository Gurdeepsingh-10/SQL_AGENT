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


// State
let currentUser = null;
let token = localStorage.getItem("sql_agent_token");
let currentConnectionId = null;

// DOM Elements
const authOverlay = document.getElementById("auth-overlay");
const loginForm = document.getElementById("login-form");
const registerForm = document.getElementById("register-form");
const showRegisterBtn = document.getElementById("show-register-btn");
const showLoginBtn = document.getElementById("show-login-btn");
const authError = document.getElementById("auth-error");

const dashboard = document.getElementById("dashboard");
const userDisplay = document.getElementById("user-display");
const logoutBtn = document.getElementById("logout-btn");

const connectionList = document.getElementById("connection-list");
const addConnectionBtn = document.getElementById("add-connection-btn");
const connectionModal = document.getElementById("connection-modal");
const connectionForm = document.getElementById("connection-form");
const closeConnModal = document.getElementById("close-conn-modal");
const currentConnectionBadge = document.getElementById("current-connection-badge");

const chatHistory = document.getElementById("chat-history");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");

// Initialization
// Navigation Functions
function navigateTo(targetId) {
    // Hide all sections
    document.querySelectorAll('.section').forEach(section => {
        section.classList.add('hidden');
        section.classList.remove('active');
    });

    // Show target section
    const targetSection = document.getElementById(`${targetId}-section`);
    if (targetSection) {
        targetSection.classList.remove('hidden');
        targetSection.classList.add('active');
    }

    // Update active nav link
    document.querySelectorAll('.nav-link').forEach(link => {
        link.classList.remove('active');
        if (link.dataset.target === targetId) {
            link.classList.add('active');
        }
    });

    // Special handling for app section (require auth)
    if (targetId === 'app' && !token) {
        showAuth();
    }
}

// Initialization
document.addEventListener("DOMContentLoaded", () => {
    // Initialize dark mode
    initDarkMode();
    const themeToggle = document.getElementById("theme-toggle");
    if (themeToggle) themeToggle.addEventListener("change", toggleDarkMode);

    // Setup Navigation
    document.querySelectorAll('.nav-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            navigateTo(link.dataset.target);
        });
    });

    // Setup Logout (Navbar)
    const logoutBtnNav = document.getElementById("logout-btn-nav");
    if (logoutBtnNav) {
        logoutBtnNav.addEventListener("click", () => {
            token = null;
            localStorage.removeItem("sql_agent_token");
            location.reload();
        });
    }

    // Clear chat history on page load
    chatHistory.innerHTML = "";

    // Add welcome message
    addMessage("agent", "System initialized. ready for input.");

    if (token) {
        // If logged in, show logout button in navbar
        const logoutNav = document.getElementById("logout-btn-nav");
        if (logoutNav) logoutNav.classList.remove("hidden");

        // Fetch connections for app
        fetchConnections();

        // Default to hero, user can navigate to app
        navigateTo('hero');
    } else {
        // Default to Hero
        navigateTo('hero');
    }
});

// --- Authentication ---

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
    const username = document.getElementById("username").value; // actually using email in backend? Let's check docs/readme. 
    // README says: "email": "user@example.com", "password": "..."
    // But input id is username. Let's assume user might type email.

    // API expects email (username field in OAuth2PasswordRequestForm usually)
    // Looking at standard FastAPI auth, usually it's form-data with 'username' and 'password'.
    // Let's try JSON first as per README curl example: POST /auth/login with JSON
    // Wait, README says: POST /auth/login with JSON { "email": ..., "password": ... }

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
            currentUser = { email }; // We don't get full user object back on login usually, but let's store what we have
            showDashboard();
            fetchConnections();
        } else {
            let errorMsg = "Login failed";
            if (data.detail) {
                if (typeof data.detail === 'string') {
                    errorMsg = data.detail;
                } else if (Array.isArray(data.detail)) {
                    errorMsg = data.detail.map(e => e.msg).join(", ");
                } else {
                    errorMsg = JSON.stringify(data.detail);
                }
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
                if (typeof data.detail === 'string') {
                    errorMsg = data.detail;
                } else if (Array.isArray(data.detail)) {
                    errorMsg = data.detail.map(e => e.msg).join(", ");
                } else {
                    errorMsg = JSON.stringify(data.detail);
                }
            }
            authError.textContent = errorMsg;
        }
    } catch (err) {
        authError.textContent = "Network error";
    }
});

logoutBtn.addEventListener("click", () => {
    token = null;
    localStorage.removeItem("sql_agent_token");
    location.reload();
});

function showAuth() {
    authOverlay.classList.remove("hidden");
    dashboard.classList.add("hidden");
}

function showDashboard() {
    authOverlay.classList.add("hidden");
    dashboard.classList.remove("hidden");
    userDisplay.textContent = "Authorized User"; // Could fetch /users/me if endpoint exists
}

// --- Connections ---

async function fetchConnections() {
    try {
        const response = await fetch(`${API_BASE}/connections/list`, {
            headers: { "Authorization": `Bearer ${token}` }
        });

        if (response.status === 401) {
            logoutBtn.click();
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

    // Filter out inactive connections (ones with errors)
    const activeConnections = connections.filter(conn => conn.is_active);

    if (activeConnections.length === 0) {
        connectionList.innerHTML = "<div class='connection-item'>No connections</div>";
        return;
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

        // Click on connection info to select
        div.querySelector(".conn-info").addEventListener("click", () => {
            selectConnection(conn);
        });

        // Click on delete button to remove
        div.querySelector(".delete-btn").addEventListener("click", async (e) => {
            e.stopPropagation();
            if (confirm(`Delete connection "${conn.connection_name}"?`)) {
                await deleteConnection(conn.id);
            }
        });

        if (currentConnectionId === conn.id) {
            div.classList.add("active");
        } else if (!currentConnectionId && conn.is_default) {
            selectConnection(conn);
        }

        connectionList.appendChild(div);
    });
}

async function deleteConnection(connectionId) {
    try {
        const response = await fetch(`${API_BASE}/connections/${connectionId}`, {
            method: "DELETE",
            headers: { "Authorization": `Bearer ${token}` }
        });

        if (response.ok) {
            // Refresh connection list
            fetchConnections();

            // Clear selection if deleted connection was selected
            if (currentConnectionId === connectionId) {
                currentConnectionId = null;
                currentConnectionBadge.textContent = "NO CONNECTION";
            }
        } else {
            alert("Failed to delete connection");
        }
    } catch (err) {
        console.error("Error deleting connection:", err);
        alert("Error deleting connection");
    }
}

function selectConnection(conn) {
    currentConnectionId = conn.id;
    currentConnectionBadge.textContent = conn.connection_name;

    // Update UI active state
    Array.from(connectionList.children).forEach(child => {
        child.classList.remove("active");
        if (child.textContent.includes(conn.connection_name)) {
            child.classList.add("active");
        }
    });

    addMessage("agent", `Switched to connection: ${conn.connection_name}`);
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
    const submitBtn = document.querySelector("#connection-form button[type='submit']");

    // Disable button to prevent double submit
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
                is_default: false
            })
        });

        const data = await response.json();

        if (response.ok) {
            connectionModal.classList.add("hidden");
            document.getElementById("connection-form").reset();
            fetchConnections();
            addMessage("agent", `Connection '${name}' added successfully.`);
        } else {
            alert(data.detail || "Failed to add connection");
        }
    } catch (err) {
        console.error(err);
        alert("Error adding connection");
    } finally {
        // Re-enable button
        submitBtn.disabled = false;
        submitBtn.textContent = "Save";
    }
});

// --- Chat ---

chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const query = chatInput.value.trim();
    if (!query) return;

    // Add user message
    addMessage("user", query);
    chatInput.value = "";

    if (!currentConnectionId) {
        addMessage("agent", "Error: No database connection selected.");
        return;
    }

    // Show loading state
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

        const data = await response.json();

        // Remove loading message
        const loadingMsg = document.querySelector(`[data-id="${loadingId}"]`);
        if (loadingMsg) loadingMsg.remove();

        if (data.success) {
            // Render table if results exist
            if (Array.isArray(data.results) && data.results.length > 0) {
                const tableHtml = createTableFromResults(data.results);
                addMessage("agent", data.message, tableHtml);
            } else {
                addMessage("agent", data.message);
            }
        } else {
            let errorMsg = data.message || "Unknown error";
            if (data.error) errorMsg += `\nDetails: ${data.error}`;
            addMessage("agent", errorMsg);
        }

    } catch (err) {
        const loadingMsg = document.querySelector(`[data-id="${loadingId}"]`);
        if (loadingMsg) loadingMsg.remove();
        addMessage("agent", "System Error: Failed to reach backend.");
        console.error(err);
    }
});

function addMessage(role, content, extraHtml = null) {
    const div = document.createElement("div");
    div.className = `message ${role}`;

    // Simple markdown parsing for code blocks
    let formattedContent = content
        .replace(/\n/g, "<br>")
        .replace(/```sql(.*?)```/gs, "<pre><code>$1</code></pre>")
        .replace(/```(.*?)```/gs, "<pre><code>$1</code></pre>");

    div.innerHTML = `<div class="message-content">${formattedContent}</div>`;

    // Append table if provided
    if (extraHtml) {
        const extraDiv = document.createElement("div");
        extraDiv.innerHTML = extraHtml;
        div.appendChild(extraDiv);
    }

    // Unique ID for removing if needed
    const id = Date.now();
    div.setAttribute("data-id", id);

    chatHistory.appendChild(div);
    chatHistory.scrollTop = chatHistory.scrollHeight;

    return id;
}

function createTableFromResults(results) {
    if (!results || results.length === 0) return "";

    // Get headers from first object keys
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
