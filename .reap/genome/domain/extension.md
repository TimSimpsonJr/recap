# Domain: Browser Extension

## Responsibility

Chrome/Edge MV3 extension that detects meeting URLs in the user's browser tabs and signals the daemon. Pure signaling; no recording, no transcription, no vault access.

## Key Entities

- **`manifest.json`** — MV3 manifest; declares content scripts, background service worker, host permissions for configured meeting URL patterns.
- **`background.js`** — service worker; watches tab URLs against configured patterns; POSTs `/api/meeting-detected` (and related `/api/meeting-*` endpoints) with `Authorization: Bearer <token>`. Uses an `authReady` promise to close the MV3 wake-up race (service worker restart vs. token load from `chrome.storage.local`). Manages the toolbar badge states: connected (green ON) / AUTH (needs pairing) / offline.
- **`options.html` + `options.js`** — pairing UI. Validates that the daemon URL is loopback (`127.0.0.1` / `localhost`), calls `/bootstrap/token`, stores `{token, baseUrl, pairedAt}` in `chrome.storage.local.recapAuth`, lets the user configure meeting URL patterns.

## Boundaries

- Does NOT record audio, capture screen, or read vault files.
- Does NOT persist anything beyond the pairing token and URL patterns.
- Talks only to the paired daemon URL; a 401 clears the token and flips the badge to AUTH.
- No build step — pure JavaScript; loaded unpacked during development, packaged as a `.zip` for distribution.
- MV3 constraints: no `setInterval` (use `chrome.alarms`); service worker can die after 30s idle, so every handler must tolerate cold start.
