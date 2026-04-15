# Phase 4 manual acceptance checklist

Automated tests (`uv run pytest -q` and `cd obsidian-recap && npm run build`)
cover the Python + TypeScript contracts but can't exercise the Chrome MV3
runtime, Obsidian UI polish, or real end-user flows. Walk through this list
against a live daemon + paired extension + plugin before declaring Phase 4
shipped.

## Preflight

- [ ] `uv run pytest -q` → all pass (expect 552 passed, 3 skipped).
- [ ] `cd obsidian-recap && npm run build` → zero tsc errors.
- [ ] `grep -rn "catch *{}\|catch *(e) *{}\|catch *(e) *{ *console\." obsidian-recap/src --include="*.ts"` → 0 hits.
- [ ] `grep -n "'/meeting-detected'\|'/meeting-ended'" recap/daemon/server.py` → only the `/api/meeting-*` variants remain.
- [ ] Daemon starts cleanly: `uv run python -m recap.daemon --config <path>`.

## Extension (Chrome/Edge MV3)

- [ ] Load the unpacked extension from `extension/` in `chrome://extensions` (developer mode, "Load unpacked").
- [ ] Open the extension options page: "Daemon connection" section appears above the "Meeting URL Patterns" section.
- [ ] Enter a non-loopback URL (`http://example.com`) → click **Save URL** → red inline error, nothing saved.
- [ ] Enter `http://localhost:9847/` → **Save URL** → trailing slash stripped, no error, status still shows "Not paired" if no token.
- [ ] Click **Connect** without first using the tray menu → yellow message: "Pairing window not open. Right-click the Recap tray icon → 'Pair browser extension…', then click Connect."
- [ ] Right-click the Recap tray icon → "Pair browser extension…" → click **Connect** in the options page → status flips to "Connected (paired …)".
- [ ] Badge in the Chrome toolbar: green "ON" when paired + daemon reachable.
- [ ] Open a meeting URL (e.g. `https://meet.google.com/abc-defg-hij`) → `POST /api/meeting-detected` sent with Bearer header (verify in daemon logs). Close the tab → `/api/meeting-ended`.
- [ ] Click **Disconnect** → badge flips to grey "AUTH"; future meeting POSTs are skipped with a console warning (no 401 churn).
- [ ] Edit Daemon URL from `http://localhost:9847` to `http://127.0.0.1:9847` → **Save URL** → status flips back to "Not paired" (token cleared because baseUrl changed). Re-pair from tray.
- [ ] Manually delete the auth token from the daemon's `_Recap/.recap/auth-token` file, restart the daemon → next meeting POST returns 401 → extension badge flips to "AUTH", stored token cleared.

## Plugin — notification history

- [ ] Open Obsidian with the plugin active and the daemon running.
- [ ] Run the "Recap: View notification history" command → modal opens, backfill loads the most recent 100 journal entries.
- [ ] Trigger a pipeline event (start/stop a recording) → a new notification appears in the modal within a second via WebSocket.
- [ ] Restart the daemon while the modal is open → plugin reconnects; subsequent events resume streaming; no duplicate entries.

## Plugin — settings UI

- [ ] Open Settings → Recap. All five config-backed sections populate from `/api/config`.
- [ ] **Organizations:** add an org, set it default (other orgs' default toggles clear), click **Save orgs** → Notice "Orgs saved. Restart the daemon…". Open `config.yaml` → new org present as a dict-keyed entry; top-of-file comments still present.
- [ ] **Meeting detection:** flip `teams` to `prompt` behavior, toggle `zoom` off → **Save detection** → YAML shows `behavior: prompt` and `enabled: false` on the expected rules; other rules untouched.
- [ ] **Calendar sync:** toggle `google` off → **Save calendar** → YAML has `google.enabled: false`. Restart the daemon, confirm `/api/status` no longer shows google in `last_calendar_sync` progression (the scheduler skips it).
- [ ] **Known contacts:** add a contact with name `Jane Smith`, display name `Jane S.`, alias `Jane`, email `jane@example.com` → **Save contacts** → YAML entry carries all four fields. Reopen Settings → all four fields survive round-trip.
- [ ] **Daemon lifecycle:** section shows "State: <state>, uptime: <N>s". Click **How to restart** → Notice instructs tray → Quit → relaunch.

## Plugin — speaker correction modal

- [ ] Open a meeting note with `SPEAKER_XX` labels → run "Recap: Fix unidentified speakers".
- [ ] Each speaker row renders `<audio controls>`; clicking play streams ~5s of that speaker's first utterance.
- [ ] Name input autocomplete lists both `contact.name` and `contact.display_name` from the daemon config (plus vault People notes).
- [ ] For a recording where the `.flac` has been archived to `.m4a` (and source deleted), playback still works — the endpoint falls back to the archived file.
- [ ] If the transcript is missing, the row shows "(clip unavailable: …)" instead of a broken player; the rest of the modal still works.

## Plugin — MeetingListView narrowing

- [ ] On a large vault (>1000 markdown files), open the Recap meeting list → notes outside the configured org subfolders are not scanned (verify via console timing if needed).
- [ ] Disconnect the daemon → the view falls back to a whole-vault scan and shows a Notice "Recap: could not load org config — scanning whole vault."

## Plugin — silent-catch sanity

- [ ] Force-disconnect daemon (stop the process) while a refresh is in flight → Notice surfaces with the error message, not a silent no-op.
- [ ] Re-run the Preflight silent-catch grep → still 0 hits.

## Regression guards

- [ ] `uv run pytest tests/test_phase4_integration.py -q` passes.
- [ ] `uv run pytest tests/test_clip_endpoint.py -q` passes (integration test exercises real ffmpeg if installed, skips otherwise).
- [ ] `uv run pytest tests/test_api_config.py tests/test_api_events.py -q` passes.
