const API = "/api/v1";
let key = localStorage.getItem("zyrox_dash_key") || "";
let currentGuildId = null;

const $ = (id) => document.getElementById(id);

function authHeaders() {
  return { "Content-Type": "application/json", "Authorization": `Bearer ${key}` };
}

async function api(path, options = {}) {
  const res = await fetch(API + path, {
    ...options,
    headers: { ...authHeaders(), ...(options.headers || {}) },
  });
  if (res.status === 401) {
    logout();
    throw new Error("Unauthorized");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch (_) {}
    throw new Error(`${res.status}: ${detail}`);
  }
  const ct = res.headers.get("content-type") || "";
  return ct.includes("application/json") ? res.json() : res.text();
}

function toast(msg, isError = false) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast" + (isError ? " error" : "");
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.add("hidden"), 3000);
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/* ---------- Auth ---------- */
function login() {
  const val = $("api-key-input").value.trim();
  if (!val) { $("login-error").textContent = "Please enter your API key."; $("login-error").classList.remove("hidden"); return; }
  key = val;
  localStorage.setItem("zyrox_dash_key", key);
  api("/bot/info")
    .then((info) => {
      $("bot-name").textContent = info.name || "ZyroX";
      $("login-error").classList.add("hidden");
      showApp();
    })
    .catch((e) => {
      localStorage.removeItem("zyrox_dash_key");
      key = "";
      $("login-error").textContent = "Invalid API key: " + e.message;
      $("login-error").classList.remove("hidden");
    });
}

function logout() {
  localStorage.removeItem("zyrox_dash_key");
  key = "";
  $("app").classList.add("hidden");
  $("login").classList.remove("hidden");
}

function showApp() {
  $("login").classList.add("hidden");
  $("app").classList.remove("hidden");
  navigate("overview");
}

/* ---------- Navigation ---------- */
const views = ["overview", "servers", "admin", "logs", "guild"];

function navigate(view) {
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  views.forEach((v) => $("view-" + v).classList.toggle("active", v === view));
  if (view === "overview") loadOverview();
  if (view === "servers") loadServers();
  if (view === "admin") loadAdmin();
  if (view === "logs") loadLogs();
  if (view === "guild" && currentGuildId) loadGuild(currentGuildId);
}

document.querySelectorAll(".nav-item").forEach((b) =>
  b.addEventListener("click", () => navigate(b.dataset.view))
);
$("logout-btn").addEventListener("click", logout);
$("login-btn").addEventListener("click", login);
$("api-key-input").addEventListener("keydown", (e) => { if (e.key === "Enter") login(); });

/* ---------- Overview ---------- */
async function loadOverview() {
  try {
    const [info, stats, status] = await Promise.all([
      api("/bot/info"),
      api("/admin/stats"),
      api("/bot/status"),
    ]);
    $("stat-servers").textContent = formatNum(info.guilds ?? stats.active_servers ?? 0);
    $("stat-users").textContent = formatNum(info.users ?? stats.total_users ?? 0);
    $("stat-ping").textContent = info.latency ?? "—";
    $("stat-commands").textContent = formatNum(info.commands ?? 0);
    $("stat-db").textContent = stats.db_size ?? "—";
    $("stat-uptime").textContent = status.uptime ? formatUptime(status.uptime) : "—";

    const nodes = (stats.nodes || []).map((n) => `
      <div class="node">
        <span class="node-name">${esc(n.icon)} ${esc(n.name)}</span>
        <span class="node-load">${esc(n.load)}</span>
        <span class="node-status ${esc(n.status)}">${esc(n.status)}</span>
      </div>`).join("");
    $("nodes").innerHTML = nodes || "<p class='muted'>No data.</p>";
  } catch (e) {
    toast(e.message, true);
  }
}

function formatNum(n) {
  const x = parseInt(n, 10);
  if (isNaN(x)) return "—";
  if (x >= 1e6) return (x / 1e6).toFixed(1) + "M";
  if (x >= 1e3) return (x / 1e3).toFixed(1) + "k";
  return String(x);
}

function formatUptime(seconds) {
  const s = parseInt(seconds, 10);
  if (isNaN(s)) return "—";
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

/* ---------- Servers ---------- */
async function loadServers() {
  try {
    const guilds = await api("/guilds/");
    $("guild-list").innerHTML = guilds.map((g) => `
      <div class="guild-item" onclick="openGuild('${g.id}')">
        ${g.icon_url
          ? `<img src="${esc(g.icon_url)}" alt="">`
          : `<div class="guild-icon-placeholder">${esc((g.name || "?").charAt(0).toUpperCase())}</div>`}
        <div>
          <div class="guild-name">${esc(g.name)}</div>
          <div class="guild-meta">${formatNum(g.member_count)} members · ID: ${esc(g.id)}</div>
        </div>
      </div>`).join("") || "<p>Bot is not in any servers.</p>";
  } catch (e) { toast(e.message, true); }
}

function openGuild(id) {
  currentGuildId = id;
  navigate("guild");
}

/* ---------- Guild Detail ---------- */
async function loadGuild(id) {
  try {
    const [g, prefix, welcome, automod, leveling, logging, verification, antinuke] = await Promise.all([
      api(`/guilds/${id}`),
      api(`/guilds/${id}/prefix`),
      api(`/guilds/${id}/welcome`),
      api(`/guilds/${id}/automod`),
      api(`/guilds/${id}/leveling`),
      api(`/guilds/${id}/logging`),
      api(`/guilds/${id}/verification`),
      api(`/guilds/${id}/antinuke`),
    ]);

    const icon = g.icon
      ? `https://cdn.discordapp.com/icons/${g.id}/${g.icon}.png?size=128`
      : null;

    $("guild-detail").innerHTML = `
      <div class="detail-header">
        ${icon ? `<img src="${esc(icon)}" alt="">` : `<div class="guild-icon-placeholder" style="width:60px;height:60px;font-size:24px">${esc(g.name.charAt(0).toUpperCase())}</div>`}
        <div>
          <h3>${esc(g.name)}</h3>
          <p class="muted" style="color:var(--muted)">${formatNum(g.member_count)} members · ${g.channel_count} channels · ${g.role_count} roles</p>
        </div>
      </div>
      <div class="settings">
        ${prefixCard(prefix)}
        ${welcomeCard(welcome)}
        ${automodCard(automod)}
        ${levelingCard(leveling)}
        ${loggingCard(logging)}
        ${verificationCard(verification)}
        ${antinukeCard(antinuke)}
      </div>`;
  } catch (e) { toast(e.message, true); }
}

$("back-to-servers").addEventListener("click", () => { currentGuildId = null; navigate("servers"); });

function prefixCard(p) {
  return `
    <div class="settings-card">
      <h4>Command Prefix</h4>
      <div class="field"><input type="text" id="field-prefix" value="${esc(p.prefix)}"></div>
      <button class="btn save-btn" onclick="savePrefix()">Save Prefix</button>
    </div>`;
}

async function savePrefix() {
  const v = $("field-prefix").value.trim();
  if (!v) return toast("Prefix cannot be empty.", true);
  try {
    await api(`/guilds/${currentGuildId}/prefix`, {
      method: "POST",
      body: JSON.stringify({ prefix: v }),
    });
    toast("Prefix updated.");
  } catch (e) { toast(e.message, true); }
}

function welcomeCard(w) {
  return `
    <div class="settings-card">
      <h4>Welcome</h4>
      <div class="field"><label>Welcome message</label>
        <input type="text" id="field-welcome-msg" value="${esc(w.welcome_message || "")}"></div>
      <div class="field"><label>Channel ID</label>
        <input type="text" id="field-welcome-channel" value="${esc(w.channel_id || "")}"></div>
      <button class="btn save-btn" onclick="saveWelcome()">Save Welcome</button>
    </div>`;
}

async function saveWelcome() {
  try {
    await api(`/guilds/${currentGuildId}/welcome`, {
      method: "PATCH",
      body: JSON.stringify({
        welcome_message: $("field-welcome-msg").value,
        channel_id: $("field-welcome-channel").value || null,
      }),
    });
    toast("Welcome updated.");
  } catch (e) { toast(e.message, true); }
}

function automodCard(a) {
  return `
    <div class="settings-card">
      <h4>AutoMod</h4>
      <div class="row">
        <span>Enabled</span>
        <label class="switch">
          <input type="checkbox" id="field-automod" ${a.enabled ? "checked" : ""}>
          <span class="slider"></span>
        </label>
      </div>
      <div class="field"><label>Logging channel ID</label>
        <input type="text" id="field-automod-log" value="${esc(a.logging_channel || "")}"></div>
      <button class="btn save-btn" onclick="saveAutomod()">Save AutoMod</button>
    </div>`;
}

async function saveAutomod() {
  try {
    await api(`/guilds/${currentGuildId}/automod`, {
      method: "PATCH",
      body: JSON.stringify({
        enabled: $("field-automod").checked,
        logging_channel: $("field-automod-log").value ? parseInt($("field-automod-log").value, 10) : null,
      }),
    });
    toast("AutoMod updated.");
  } catch (e) { toast(e.message, true); }
}

function levelingCard(l) {
  return `
    <div class="settings-card">
      <h4>Leveling</h4>
      <div class="row">
        <span>Enabled</span>
        <label class="switch">
          <input type="checkbox" id="field-leveling" ${l.enabled ? "checked" : ""}>
          <span class="slider"></span>
        </label>
      </div>
      <div class="field"><label>XP per message</label>
        <input type="number" id="field-leveling-xp" value="${esc(l.xp_per_message)}"></div>
      <div class="field"><label>Cooldown (seconds)</label>
        <input type="number" id="field-leveling-cd" value="${esc(l.cooldown)}"></div>
      <button class="btn save-btn" onclick="saveLeveling()">Save Leveling</button>
    </div>`;
}

async function saveLeveling() {
  try {
    await api(`/guilds/${currentGuildId}/leveling`, {
      method: "PATCH",
      body: JSON.stringify({
        enabled: $("field-leveling").checked,
        xp_per_message: parseInt($("field-leveling-xp").value, 10) || 0,
        cooldown: parseInt($("field-leveling-cd").value, 10) || 0,
      }),
    });
    toast("Leveling updated.");
  } catch (e) { toast(e.message, true); }
}

function loggingCard(l) {
  const channels = Object.entries(l.log_channels || {})
    .map(([k, v]) => `<div class="field"><label>${esc(k)}</label>
      <input type="text" value="${esc(v)}" data-log-channel="${esc(k)}"></div>`).join("");
  return `
    <div class="settings-card">
      <h4>Logging Channels</h4>
      ${channels || "<p style='color:var(--muted)'>No log channels configured.</p>"}
      <button class="btn save-btn" onclick="saveLogging()">Save Logging</button>
    </div>`;
}

async function saveLogging() {
  const logChannels = {};
  document.querySelectorAll("[data-log-channel]").forEach((el) => {
    const v = el.value.trim();
    if (v) logChannels[el.dataset.logChannel] = parseInt(v, 10);
  });
  try {
    await api(`/guilds/${currentGuildId}/logging`, {
      method: "PATCH",
      body: JSON.stringify({ log_channels: logChannels }),
    });
    toast("Logging updated.");
  } catch (e) { toast(e.message, true); }
}

function verificationCard(v) {
  return `
    <div class="settings-card">
      <h4>Verification</h4>
      <div class="field"><label>Verification channel ID</label>
        <input type="text" id="field-verif-channel" value="${esc(v.verification_channel_id || "")}"></div>
      <div class="field"><label>Verified role ID</label>
        <input type="text" id="field-verif-role" value="${esc(v.verified_role_id || "")}"></div>
      <button class="btn save-btn" onclick="saveVerification()">Save Verification</button>
    </div>`;
}

async function saveVerification() {
  try {
    await api(`/guilds/${currentGuildId}/verification`, {
      method: "PATCH",
      body: JSON.stringify({
        verification_channel_id: $("field-verif-channel").value || null,
        verified_role_id: $("field-verif-role").value || null,
      }),
    });
    toast("Verification updated.");
  } catch (e) { toast(e.message, true); }
}

function antinukeCard(a) {
  return `
    <div class="settings-card">
      <h4>Anti-Nuke</h4>
      <div class="row">
        <span>Enabled</span>
        <label class="switch">
          <input type="checkbox" id="field-antinuke" ${a.status ? "checked" : ""}>
          <span class="slider"></span>
        </label>
      </div>
      <button class="btn save-btn" onclick="saveAntinuke()">Save Anti-Nuke</button>
    </div>`;
}

async function saveAntinuke() {
  try {
    await api(`/guilds/${currentGuildId}/antinuke`, {
      method: "PATCH",
      body: JSON.stringify({ status: $("field-antinuke").checked }),
    });
    toast("Anti-Nuke updated.");
  } catch (e) { toast(e.message, true); }
}

/* ---------- Admin ---------- */
async function loadAdmin() {
  try {
    const c = await api("/admin/config");
    $("maintenance-toggle").checked = !!c.maintenance_mode;
  } catch (e) { toast(e.message, true); }
}

$("maintenance-toggle").addEventListener("change", async (e) => {
  try {
    await api("/admin/config", {
      method: "PATCH",
      body: JSON.stringify({ maintenance_mode: e.target.checked }),
    });
    toast(e.target.checked ? "Maintenance mode ON." : "Maintenance mode OFF.");
  } catch (err) {
    e.target.checked = !e.target.checked;
    toast(err.message, true);
  }
});

$("global-notification-btn").addEventListener("click", async () => {
  const msg = $("global-notification-input").value.trim();
  if (!msg) return toast("Enter a message first.", true);
  try {
    await api("/admin/config", {
      method: "PATCH",
      body: JSON.stringify({ global_notification: msg }),
    });
    $("global-notification-input").value = "";
    toast("Global notification sent.");
  } catch (e) { toast(e.message, true); }
});

/* ---------- Logs ---------- */
async function loadLogs() {
  try {
    const logs = await api("/admin/logs");
    const rows = (logs || []).map((l) => `
      <tr>
        <td>${esc(l.timestamp)}</td>
        <td><span class="code-badge">${esc(l.method)}</span></td>
        <td><span class="code-badge">${esc(l.path)}</span></td>
        <td class="${l.status_code < 400 ? "status-2xx" : "status-4xx"}">${esc(l.status_code)}</td>
        <td>${esc(l.duration_ms)} ms</td>
      </tr>`).join("");
    $("log-body").innerHTML = rows || "<tr><td colspan='5'>No requests yet.</td></tr>";
  } catch (e) { toast(e.message, true); }
}

$("refresh-logs").addEventListener("click", loadLogs);

/* ---------- Init ---------- */
if (key) {
  api("/bot/info")
    .then((info) => { $("bot-name").textContent = info.name || "ZyroX"; showApp(); })
    .catch(() => logout());
} else {
  $("login").classList.remove("hidden");
}

setInterval(() => {
  if (!$("view-overview").classList.contains("active")) return;
  loadOverview();
}, 30000);
