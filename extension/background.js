const RECAP_PORT_START = 17839;
const RECAP_PORT_END = 17845;
const HEALTH_CHECK_INTERVAL_MS = 30000;

const DEFAULT_MEETING_PATTERNS = [
  { pattern: "meet.google.com/", platform: "google_meet", excludeExact: "meet.google.com/" },
  { pattern: "teams.microsoft.com/", platform: "teams", requirePath: ["meetup-join", "pre-join"] },
  { pattern: "meeting.zoho.com/meeting/", platform: "zoho_meet" },
  { pattern: "meeting.zoho.eu/meeting/", platform: "zoho_meet" },
  { pattern: "meeting.zoho.in/meeting/", platform: "zoho_meet" },
  { pattern: "meeting.zoho.com.au/meeting/", platform: "zoho_meet" },
  { pattern: "meeting.tranzpay.io/", platform: "zoho_meet" },
];

let recapPort = null;
let activeMeetingTabs = new Map();

async function findRecapPort() {
  for (let port = RECAP_PORT_START; port <= RECAP_PORT_END; port++) {
    try {
      const resp = await fetch(`http://localhost:${port}/health`, {
        signal: AbortSignal.timeout(1000),
      });
      if (resp.ok) {
        recapPort = port;
        chrome.action.setBadgeBackgroundColor({ color: "#4baa55" });
        chrome.action.setBadgeText({ text: "ON" });
        chrome.action.setTitle({ title: "Recap — Connected" });
        return port;
      }
    } catch (_) {}
  }
  recapPort = null;
  chrome.action.setBadgeBackgroundColor({ color: "#7a8493" });
  chrome.action.setBadgeText({ text: "" });
  chrome.action.setTitle({ title: "Recap — Not connected" });
  return null;
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
  if (!recapPort) await findRecapPort();
  if (!recapPort) return;
  try {
    await fetch(`http://localhost:${recapPort}${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
  } catch (_) {
    recapPort = null;
  }
}

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (changeInfo.status !== "complete" || !tab.url) return;
  const patterns = await getMeetingPatterns();
  const platform = matchesMeetingUrl(tab.url, patterns);
  if (platform && !activeMeetingTabs.has(tabId)) {
    activeMeetingTabs.set(tabId, { url: tab.url, title: tab.title, platform });
    await notifyRecap("/meeting-detected", {
      url: tab.url,
      title: tab.title || "Meeting",
      platform,
      tabId,
    });
  } else if (!platform && activeMeetingTabs.has(tabId)) {
    activeMeetingTabs.delete(tabId);
    await notifyRecap("/meeting-ended", { tabId });
  }
});

chrome.tabs.onRemoved.addListener(async (tabId) => {
  if (activeMeetingTabs.has(tabId)) {
    activeMeetingTabs.delete(tabId);
    await notifyRecap("/meeting-ended", { tabId });
  }
});

// Use chrome.alarms instead of setInterval — MV3 service workers get terminated
// after 30s of inactivity, so setInterval doesn't survive.
chrome.alarms.create("recap-health-check", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "recap-health-check") {
    findRecapPort();
  }
});

// Initial check on service worker startup
findRecapPort();
