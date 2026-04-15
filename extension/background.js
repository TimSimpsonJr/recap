const DEFAULT_BASE_URL = "http://localhost:9847";

const DEFAULT_MEETING_PATTERNS = [
  { pattern: "meet.google.com/", platform: "google_meet", excludeExact: "meet.google.com/" },
  { pattern: "teams.microsoft.com/", platform: "teams", requirePath: ["meetup-join", "pre-join"] },
  { pattern: "meeting.zoho.com/meeting/", platform: "zoho_meet" },
  { pattern: "meeting.zoho.eu/meeting/", platform: "zoho_meet" },
  { pattern: "meeting.zoho.in/meeting/", platform: "zoho_meet" },
  { pattern: "meeting.zoho.com.au/meeting/", platform: "zoho_meet" },
  { pattern: "meeting.tranzpay.io/", platform: "zoho_meet" },
];

let cachedAuth = null;
let daemonReachable = false;
let activeMeetingTabs = new Map();

const authReady = (async () => {
  const result = await chrome.storage.local.get("recapAuth");
  cachedAuth = result.recapAuth || null;
})();

chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "local" || !changes.recapAuth) return;
  cachedAuth = changes.recapAuth.newValue || null;
  void findRecapDaemon();
});

function currentBaseUrl() {
  return (cachedAuth && cachedAuth.baseUrl) || DEFAULT_BASE_URL;
}

function setBadge(state) {
  if (state === "connected") {
    chrome.action.setBadgeBackgroundColor({ color: "#4baa55" });
    chrome.action.setBadgeText({ text: "ON" });
    chrome.action.setTitle({ title: "Recap - Connected" });
  } else if (state === "auth") {
    chrome.action.setBadgeBackgroundColor({ color: "#d9534f" });
    chrome.action.setBadgeText({ text: "AUTH" });
    chrome.action.setTitle({ title: "Recap - Not paired. Open options to connect." });
  } else {
    chrome.action.setBadgeBackgroundColor({ color: "#7a8493" });
    chrome.action.setBadgeText({ text: "" });
    chrome.action.setTitle({ title: "Recap - Not connected" });
  }
}

async function findRecapDaemon() {
  await authReady;
  const baseUrl = currentBaseUrl();
  try {
    const resp = await fetch(`${baseUrl}/health`, { signal: AbortSignal.timeout(1000) });
    if (resp.ok) {
      daemonReachable = true;
      setBadge(cachedAuth && cachedAuth.token ? "connected" : "auth");
      return true;
    }
  } catch (_) {}
  daemonReachable = false;
  setBadge("offline");
  return false;
}

async function getMeetingPatterns() {
  const result = await chrome.storage.local.get("meetingPatterns");
  return result.meetingPatterns || DEFAULT_MEETING_PATTERNS;
}

function matchesMeetingUrl(url, patterns) {
  try {
    const parsed = new URL(url);
    const fullUrl = parsed.hostname + parsed.pathname;
    for (const rule of patterns) {
      if (!fullUrl.includes(rule.pattern)) continue;
      if (rule.excludeExact && fullUrl === rule.excludeExact) continue;
      if (rule.requirePath && !rule.requirePath.some((p) => parsed.pathname.includes(p))) continue;
      return rule.platform;
    }
  } catch (_) {}
  return null;
}

async function notifyRecap(endpoint, data) {
  await authReady;
  if (!cachedAuth || !cachedAuth.token) {
    console.warn("Recap: not paired; skipping", endpoint);
    setBadge("auth");
    return;
  }
  if (!daemonReachable) await findRecapDaemon();
  if (!daemonReachable) return;

  const url = `${currentBaseUrl()}${endpoint}`;
  try {
    const resp = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${cachedAuth.token}`,
      },
      body: JSON.stringify(data),
    });
    if (resp.status === 401) {
      console.warn("Recap: 401; clearing stored token");
      await chrome.storage.local.remove("recapAuth");
      setBadge("auth");
      return;
    }
    if (!resp.ok) {
      console.warn(`Recap: ${endpoint} returned ${resp.status}`);
    }
  } catch (e) {
    console.warn("Recap:", endpoint, "failed:", e.message);
    daemonReachable = false;
    setBadge("offline");
  }
}

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (changeInfo.status !== "complete" || !tab.url) return;
  const patterns = await getMeetingPatterns();
  const platform = matchesMeetingUrl(tab.url, patterns);
  if (platform && !activeMeetingTabs.has(tabId)) {
    activeMeetingTabs.set(tabId, { url: tab.url, title: tab.title, platform });
    await notifyRecap("/api/meeting-detected", {
      url: tab.url, title: tab.title || "Meeting", platform, tabId,
    });
  } else if (!platform && activeMeetingTabs.has(tabId)) {
    activeMeetingTabs.delete(tabId);
    await notifyRecap("/api/meeting-ended", { tabId });
  }
});

chrome.tabs.onRemoved.addListener(async (tabId) => {
  if (activeMeetingTabs.has(tabId)) {
    activeMeetingTabs.delete(tabId);
    await notifyRecap("/api/meeting-ended", { tabId });
  }
});

chrome.alarms.create("recap-health-check", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "recap-health-check") void findRecapDaemon();
});

void findRecapDaemon();
