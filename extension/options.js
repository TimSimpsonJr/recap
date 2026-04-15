const DEFAULT_PATTERNS = [
  { pattern: "meet.google.com/", platform: "google_meet" },
  { pattern: "teams.microsoft.com/", platform: "teams", requirePath: ["meetup-join", "pre-join"] },
  { pattern: "meeting.zoho.com/meeting/", platform: "zoho_meet" },
  { pattern: "meeting.zoho.eu/meeting/", platform: "zoho_meet" },
  { pattern: "meeting.zoho.in/meeting/", platform: "zoho_meet" },
  { pattern: "meeting.zoho.com.au/meeting/", platform: "zoho_meet" },
  { pattern: "meeting.tranzpay.io/", platform: "zoho_meet" },
];

const PLATFORMS = ["google_meet", "teams", "zoho_meet", "unknown"];

const DEFAULT_BASE_URL = "http://localhost:9847";
const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1", "::1", "[::1]"]);

const container = document.getElementById("patterns");
const addBtn = document.getElementById("add-btn");
const saveBtn = document.getElementById("save-btn");
const resetBtn = document.getElementById("reset-btn");
const savedMsg = document.getElementById("saved-msg");

const baseUrlInput = document.getElementById("base-url-input");
const baseUrlError = document.getElementById("base-url-error");
const saveUrlBtn = document.getElementById("save-url-btn");
const connectBtn = document.getElementById("connect-btn");
const disconnectBtn = document.getElementById("disconnect-btn");
const authStatus = document.getElementById("auth-status");

function createPatternRow(pattern, index) {
  const row = document.createElement("div");
  row.className = "pattern-row";
  row.dataset.index = index;

  const input = document.createElement("input");
  input.type = "text";
  input.value = pattern.pattern;
  input.placeholder = "e.g. meet.google.com/";
  row.appendChild(input);

  const select = document.createElement("select");
  for (const p of PLATFORMS) {
    const option = document.createElement("option");
    option.value = p;
    option.textContent = p;
    if (p === pattern.platform) option.selected = true;
    select.appendChild(option);
  }
  row.appendChild(select);

  const removeBtn = document.createElement("button");
  removeBtn.className = "remove-btn";
  removeBtn.textContent = "\u00d7";
  removeBtn.title = "Remove pattern";
  row.appendChild(removeBtn);

  return row;
}

function renderPatterns(patterns) {
  const rows = patterns.map((p, i) => createPatternRow(p, i));
  container.replaceChildren(...rows);
}

function collectPatterns() {
  const rows = container.querySelectorAll(".pattern-row");
  const patterns = [];
  for (const row of rows) {
    const input = row.querySelector("input");
    const select = row.querySelector("select");
    const value = input.value.trim();
    if (value) {
      patterns.push({ pattern: value, platform: select.value });
    }
  }
  return patterns;
}

async function loadPatterns() {
  const result = await chrome.storage.local.get("meetingPatterns");
  const patterns = result.meetingPatterns || DEFAULT_PATTERNS;
  renderPatterns(patterns);
}

function showSaved() {
  savedMsg.classList.add("visible");
  setTimeout(() => savedMsg.classList.remove("visible"), 2000);
}

saveBtn.addEventListener("click", async () => {
  const patterns = collectPatterns();
  await chrome.storage.local.set({ meetingPatterns: patterns });
  showSaved();
});

resetBtn.addEventListener("click", () => {
  renderPatterns(DEFAULT_PATTERNS);
});

addBtn.addEventListener("click", () => {
  const row = createPatternRow({ pattern: "", platform: "unknown" }, container.children.length);
  container.appendChild(row);
});

container.addEventListener("click", (e) => {
  if (e.target.classList.contains("remove-btn")) {
    e.target.closest(".pattern-row").remove();
  }
});

function normalizeBaseUrl(raw) {
  return raw.trim().replace(/\/+$/, "");
}

function validateLoopbackUrl(raw) {
  try {
    const url = new URL(raw);
    if (!LOOPBACK_HOSTS.has(url.hostname)) {
      return `host must be loopback; got ${url.hostname}`;
    }
    return null;
  } catch (e) {
    return `invalid URL: ${e.message}`;
  }
}

function setAuthStatus(text, variant) {
  authStatus.textContent = text;
  authStatus.dataset.variant = variant || "neutral";
}

function renderAuthState(auth) {
  if (auth && auth.token) {
    const when = new Date(auth.pairedAt).toLocaleString();
    setAuthStatus(`Connected (paired ${when}).`, "ok");
    connectBtn.hidden = true;
    disconnectBtn.hidden = false;
  } else {
    setAuthStatus("Not paired.", "neutral");
    connectBtn.hidden = false;
    disconnectBtn.hidden = true;
  }
}

async function loadAuth() {
  const result = await chrome.storage.local.get("recapAuth");
  const auth = result.recapAuth || null;
  baseUrlInput.value = (auth && auth.baseUrl) || DEFAULT_BASE_URL;
  renderAuthState(auth);
}

async function saveBaseUrl() {
  const raw = baseUrlInput.value;
  const err = validateLoopbackUrl(raw);
  baseUrlError.textContent = err || "";
  baseUrlError.hidden = !err;
  if (err) return;
  const normalized = normalizeBaseUrl(raw);
  baseUrlInput.value = normalized;

  const existing = (await chrome.storage.local.get("recapAuth")).recapAuth || {};
  if (existing.baseUrl !== normalized) {
    await chrome.storage.local.set({ recapAuth: { baseUrl: normalized } });
  }
  renderAuthState({ baseUrl: normalized });
}

async function connect() {
  const existing = (await chrome.storage.local.get("recapAuth")).recapAuth || {};
  const baseUrl = existing.baseUrl || DEFAULT_BASE_URL;
  setAuthStatus("Pairing\u2026", "neutral");

  let resp;
  try {
    resp = await fetch(`${baseUrl}/bootstrap/token`, {
      signal: AbortSignal.timeout(1000),
    });
  } catch (e) {
    setAuthStatus(`Daemon unreachable: ${e.message}`, "error");
    return;
  }

  if (resp.status === 404) {
    setAuthStatus(
      "Pairing window not open. Right-click the Recap tray icon \u2192 "
      + "\u201CPair browser extension\u2026\u201D, then click Connect.",
      "warning",
    );
    return;
  }
  if (resp.status === 403) {
    setAuthStatus("Pairing rejected (non-loopback).", "error");
    return;
  }
  if (!resp.ok) {
    setAuthStatus(`Pairing failed: HTTP ${resp.status}`, "error");
    return;
  }

  const body = await resp.json();
  if (!body.token) {
    setAuthStatus("Pairing response missing token.", "error");
    return;
  }
  const auth = { token: body.token, baseUrl, pairedAt: Date.now() };
  await chrome.storage.local.set({ recapAuth: auth });
  renderAuthState(auth);
}

async function disconnect() {
  await chrome.storage.local.remove("recapAuth");
  renderAuthState(null);
}

saveUrlBtn.addEventListener("click", saveBaseUrl);
connectBtn.addEventListener("click", connect);
disconnectBtn.addEventListener("click", disconnect);

chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "local" || !changes.recapAuth) return;
  const newAuth = changes.recapAuth.newValue || null;
  if (newAuth) baseUrlInput.value = newAuth.baseUrl || DEFAULT_BASE_URL;
  renderAuthState(newAuth);
});

loadAuth();
loadPatterns();
