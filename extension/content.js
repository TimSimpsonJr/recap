const RECAP_PORT_START = 17839;
const RECAP_PORT_END = 17845;
const INITIAL_CHECK_DELAY_MS = 3000;

const PLATFORM_SELECTORS = {
  google_meet: [
    '[data-self-name="You are presenting"]',
    '[aria-label*="presenting"]',
    '[data-is-presenting="true"]',
  ],
  teams: [
    '[data-tid="sharing-indicator"]',
    ".ts-sharing-screen-banner",
    '[aria-label*="sharing"]',
  ],
  zoho_meet: [
    ".screen-share-indicator",
    '[class*="sharing-banner"]',
    '[class*="screen-share-active"]',
  ],
};

let recapPort = null;
let isSharing = false;

function detectPlatform() {
  const host = window.location.hostname;
  if (host === "meet.google.com") return "google_meet";
  if (host.includes("teams.microsoft.com")) return "teams";
  if (host.includes("meeting.zoho") || host.includes("meeting.tranzpay.io"))
    return "zoho_meet";
  return null;
}

async function findRecapPort() {
  for (let port = RECAP_PORT_START; port <= RECAP_PORT_END; port++) {
    try {
      const resp = await fetch(`http://localhost:${port}/health`, {
        signal: AbortSignal.timeout(1000),
      });
      if (resp.ok) {
        recapPort = port;
        return port;
      }
    } catch (_) {}
  }
  recapPort = null;
  return null;
}

async function notifyRecap(endpoint) {
  if (!recapPort) await findRecapPort();
  if (!recapPort) return;
  try {
    await fetch(`http://localhost:${recapPort}${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tabId: null }),
    });
  } catch (_) {
    recapPort = null;
  }
}

function checkSharingState(platform) {
  const selectors = PLATFORM_SELECTORS[platform];
  if (!selectors) return false;
  return selectors.some((sel) => document.querySelector(sel) !== null);
}

function handleSharingChange(platform) {
  const nowSharing = checkSharingState(platform);
  if (nowSharing === isSharing) return;
  isSharing = nowSharing;
  if (isSharing) {
    notifyRecap("/sharing-started");
  } else {
    notifyRecap("/sharing-stopped");
  }
}

function init() {
  const platform = detectPlatform();
  if (!platform) return;

  // Initial check after page has had time to render
  setTimeout(() => handleSharingChange(platform), INITIAL_CHECK_DELAY_MS);

  // Watch for DOM changes that indicate sharing state transitions
  const observer = new MutationObserver(() => handleSharingChange(platform));
  observer.observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: [
      "class",
      "aria-label",
      "data-self-name",
      "data-is-presenting",
    ],
  });
}

init();
