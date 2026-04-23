// content.js - scrapes participant rosters on request from background.
// Runs only on domains declared in manifest content_scripts.matches
// (Meet, Zoho regional variants, tranzpay).
//
// LIMITATION: Teams-via-browser (teams.microsoft.com) is a known v1 gap
// and is deliberately absent from content_scripts.matches.

function platformForHost(hostname) {
  if (hostname === "meet.google.com") return "google_meet";
  if (hostname.startsWith("meeting.zoho.") || hostname === "meeting.tranzpay.io") return "zoho_meet";
  return null;
}

function scrapeMeet() {
  // Meet's roster lives in the People side panel. Fallback selector
  // ladder - first non-empty result wins. Selectors drift; re-tune
  // from docs/handoffs/29-fixtures/ when they break.
  const selectors = [
    '[role="list"][aria-label*="participant" i] [role="listitem"] [data-self-name]',
    '[role="list"][aria-label*="participant" i] [role="listitem"] span',
    '[data-participant-id]',
    'div[jsname][data-participant-id] span',
  ];
  for (const sel of selectors) {
    const nodes = document.querySelectorAll(sel);
    if (nodes.length === 0) continue;
    const names = Array.from(nodes, n =>
      (n.getAttribute("data-self-name") || n.textContent || "").trim()
    ).filter(Boolean);
    if (names.length) return names;
  }
  return [];
}

function scrapeZoho() {
  // Zoho Meeting participant panel. Selectors TBD from fixture HTML.
  const selectors = [
    '[data-testid="participant-name"]',
    '.participant-list .participant-name',
    '.zm-participants-item__name',
  ];
  for (const sel of selectors) {
    const nodes = document.querySelectorAll(sel);
    if (nodes.length === 0) continue;
    const names = Array.from(nodes, n => (n.textContent || "").trim()).filter(Boolean);
    if (names.length) return names;
  }
  return [];
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.type === "recap:get-roster") {
    const platform = platformForHost(window.location.hostname);
    let participants = [];
    try {
      if (platform === "google_meet") participants = scrapeMeet();
      else if (platform === "zoho_meet") participants = scrapeZoho();
    } catch (e) {
      console.warn("Recap content-script scrape failed:", e.message);
    }
    sendResponse({ platform, participants });
    return true;  // keep channel open for async sendResponse
  }
});
