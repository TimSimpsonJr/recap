# Tauri App Shell Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Tauri v2 desktop app shell with system tray, deep links, OAuth for five platforms, Stronghold credential storage, settings UI in Svelte, and a PyInstaller sidecar wrapper for the Python pipeline.

**Architecture:** Monorepo expansion — Tauri v2 scaffolded into the existing `recap` repo. Svelte + Vite + Tailwind frontend. Rust backend handles system tray, deep links, OAuth token exchange, and sidecar management. Stronghold for encrypted credential storage, tauri-plugin-store for non-secret settings. Python pipeline bundled as a PyInstaller sidecar binary.

**Tech Stack:** Tauri v2, Rust, Svelte 5, TypeScript, Vite, Tailwind CSS, tauri-plugin-stronghold, tauri-plugin-store, tauri-plugin-deep-link, tauri-plugin-autostart, tauri-plugin-shell, PyInstaller

**Design doc:** `docs/plans/2026-03-17-tauri-app-shell-design.md`

**Docs to reference during implementation:**
- Tauri v2 docs: https://v2.tauri.app/
- Tauri v2 system tray: https://v2.tauri.app/learn/system-tray/
- Tauri v2 deep link plugin: https://v2.tauri.app/plugin/deep-linking/
- Tauri v2 sidecar: https://v2.tauri.app/develop/sidecar/
- Tauri v2 stronghold plugin: https://v2.tauri.app/plugin/stronghold/
- Tauri v2 store plugin: https://v2.tauri.app/plugin/store/
- Tauri v2 autostart plugin: https://v2.tauri.app/plugin/autostart/
- Tauri v2 global shortcut plugin: https://v2.tauri.app/plugin/global-shortcut/
- Tauri v2 shell plugin: https://v2.tauri.app/plugin/shell/
- PyInstaller docs: https://pyinstaller.org/en/stable/

---

### Task 1: Tauri + Svelte Project Scaffolding

**Files:**
- Create: `package.json`, `vite.config.ts`, `svelte.config.js`, `tsconfig.json`
- Create: `src/main.ts`, `src/App.svelte`, `src/app.css`
- Create: `src-tauri/Cargo.toml`, `src-tauri/tauri.conf.json`, `src-tauri/src/main.rs`, `src-tauri/src/lib.rs`
- Create: `src-tauri/capabilities/default.json`, `src-tauri/icons/`
- Modify: `.gitignore`

**Step 1: Scaffold Tauri + Svelte project into the existing repo**

Run from the repo root:
```bash
npm create tauri-app@latest . -- --template svelte-ts
```

If the scaffolder refuses to write into a non-empty directory, create in a temp directory and copy:
```bash
npm create tauri-app@latest recap-tauri -- --template svelte-ts
# Then copy src/, src-tauri/, package.json, vite.config.ts, svelte.config.js, tsconfig.json into the existing repo
# Remove the temp directory
```

When prompted for identifier, use `com.recap.app`.

**Step 2: Install Tailwind CSS**

```bash
npm install -D tailwindcss @tailwindcss/vite
```

Add Tailwind to `vite.config.ts`:
```typescript
import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [svelte(), tailwindcss()],
});
```

Add to the top of `src/app.css`:
```css
@import "tailwindcss";
```

**Step 3: Install Tauri plugins (npm side)**

```bash
npm install @tauri-apps/plugin-stronghold @tauri-apps/plugin-store @tauri-apps/plugin-deep-link @tauri-apps/plugin-autostart @tauri-apps/plugin-shell
```

**Step 4: Add Tauri plugin dependencies to `src-tauri/Cargo.toml`**

Add to `[dependencies]`:
```toml
tauri-plugin-stronghold = "2"
tauri-plugin-store = "2"
tauri-plugin-deep-link = "2"
tauri-plugin-autostart = "2"
tauri-plugin-shell = "2"
serde = { version = "1", features = ["derive"] }
serde_json = "1"
tokio = { version = "1", features = ["full"] }
reqwest = { version = "0.12", features = ["json"] }
```

`reqwest` is for OAuth token exchange HTTP calls. `tokio` for async runtime. `serde`/`serde_json` for JSON serialization.

**Step 5: Configure deep link protocol in `src-tauri/tauri.conf.json`**

Add to the top-level config:
```json
{
  "plugins": {
    "deep-link": {
      "desktop": {
        "schemes": ["recap"]
      }
    }
  }
}
```

**Step 6: Configure capabilities in `src-tauri/capabilities/default.json`**

Ensure the capabilities file includes permissions for all plugins:
```json
{
  "identifier": "default",
  "description": "Default capabilities for the main window",
  "windows": ["main"],
  "permissions": [
    "core:default",
    "stronghold:default",
    "store:default",
    "deep-link:default",
    "autostart:default",
    "shell:default"
  ]
}
```

**Step 7: Update `.gitignore`**

Add these entries:
```
# Tauri
src-tauri/target/
src-tauri/binaries/

# Node
node_modules/
dist/
```

**Step 8: Verify the scaffold builds and runs**

```bash
npm install
npm run tauri dev
```

Expected: A Tauri window opens showing the default Svelte template. Close it.

**Step 9: Commit**

```bash
git add -A
git commit -m "feat: scaffold Tauri v2 + Svelte + Tailwind project"
```

---

### Task 2: System Tray

**Files:**
- Create: `src-tauri/src/tray.rs`
- Modify: `src-tauri/src/lib.rs`
- Modify: `src-tauri/tauri.conf.json`

**Step 1: Create the tray module**

Create `src-tauri/src/tray.rs`:

```rust
use tauri::{
    menu::{Menu, MenuItem, PredefinedMenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, Runtime,
};

pub fn create_tray<R: Runtime>(app: &tauri::AppHandle<R>) -> tauri::Result<()> {
    let start_recording = MenuItem::with_id(app, "start_recording", "Start Recording", false, None::<&str>)?;
    let stop_recording = MenuItem::with_id(app, "stop_recording", "Stop Recording", false, None::<&str>)?;
    let separator1 = PredefinedMenuItem::separator(app)?;
    let open_dashboard = MenuItem::with_id(app, "open_dashboard", "Open Dashboard", true, None::<&str>)?;
    let settings = MenuItem::with_id(app, "settings", "Settings", true, None::<&str>)?;
    let separator2 = PredefinedMenuItem::separator(app)?;
    let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;

    let menu = Menu::with_items(
        app,
        &[
            &start_recording,
            &stop_recording,
            &separator1,
            &open_dashboard,
            &settings,
            &separator2,
            &quit,
        ],
    )?;

    TrayIconBuilder::new()
        .menu(&menu)
        .menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "open_dashboard" => {
                show_main_window(app);
            }
            "settings" => {
                show_main_window(app);
                // TODO: emit event to navigate to settings route
            }
            "quit" => {
                app.exit(0);
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                let app = tray.app_handle();
                show_main_window(app);
            }
        })
        .build(app)?;

    Ok(())
}

fn show_main_window<R: Runtime>(app: &tauri::AppHandle<R>) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}
```

**Step 2: Wire tray into the app setup**

Modify `src-tauri/src/lib.rs` to register plugins and create the tray:

```rust
mod tray;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_store::Builder::default().build())
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            None,
        ))
        .setup(|app| {
            // Stronghold with Argon2 password hashing
            let salt_path = app
                .path()
                .app_local_data_dir()
                .expect("could not resolve app local data path")
                .join("salt.txt");
            app.handle().plugin(
                tauri_plugin_stronghold::Builder::with_argon2(&salt_path).build(),
            )?;

            // Deep link plugin
            app.handle().plugin(tauri_plugin_deep_link::init())?;

            // System tray
            tray::create_tray(app.handle())?;

            // Start minimized to tray — hide the main window
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.hide();
            }

            Ok(())
        })
        .on_window_event(|window, event| {
            // Closing the window hides it instead of quitting
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                let _ = window.hide();
                api.prevent_close();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
```

**Step 3: Configure the main window to be hidden on startup**

In `src-tauri/tauri.conf.json`, set the main window to be hidden initially:
```json
{
  "app": {
    "windows": [
      {
        "label": "main",
        "title": "Recap",
        "width": 900,
        "height": 700,
        "visible": false
      }
    ]
  }
}
```

**Step 4: Verify tray works**

```bash
npm run tauri dev
```

Expected: No window appears. A tray icon shows in the system tray. Right-click shows the menu. "Open Dashboard" shows the window. Closing the window hides it. "Quit" exits the app.

**Step 5: Commit**

```bash
git add src-tauri/src/tray.rs src-tauri/src/lib.rs src-tauri/tauri.conf.json
git commit -m "feat: add system tray with menu and hide-on-close behavior"
```

---

### Task 3: Deep Link Handler

**Files:**
- Create: `src-tauri/src/deep_link.rs`
- Modify: `src-tauri/src/lib.rs`

**Step 1: Create the deep link handler module**

Create `src-tauri/src/deep_link.rs`:

```rust
use tauri::Manager;
use tauri_plugin_deep_link::DeepLinkExt;

/// Register deep link handler and process any URLs the app was opened with.
pub fn setup_deep_links(app: &tauri::AppHandle) -> tauri::Result<()> {
    // Register the recap:// protocol at runtime (needed for dev on Windows)
    #[cfg(desktop)]
    app.deep_link().register("recap")?;

    // Handle deep links received while app is running
    app.deep_link().on_open_url(|event| {
        for url in event.urls() {
            handle_deep_link_url(url.as_str());
        }
    });

    // Check if app was launched via deep link
    if let Ok(Some(urls)) = app.deep_link().get_current() {
        for url in urls {
            handle_deep_link_url(url.as_str());
        }
    }

    Ok(())
}

fn handle_deep_link_url(url: &str) {
    // Parse recap://oauth/{provider}/callback?code=...
    if let Ok(parsed) = url::Url::parse(url) {
        match parsed.host_str() {
            Some("oauth") => {
                let path_segments: Vec<&str> = parsed.path_segments()
                    .map(|s| s.collect())
                    .unwrap_or_default();
                if path_segments.len() >= 2 && path_segments[1] == "callback" {
                    let provider = path_segments[0];
                    let code = parsed.query_pairs()
                        .find(|(key, _)| key == "code")
                        .map(|(_, value)| value.to_string());
                    if let Some(code) = code {
                        log::info!("OAuth callback for {}: code received", provider);
                        // TODO: pass to oauth module for token exchange
                    }
                }
            }
            Some("meeting") => {
                // Future: recap://meeting/start?url=...
                log::info!("Meeting deep link: {}", url);
            }
            _ => {
                log::warn!("Unknown deep link: {}", url);
            }
        }
    }
}
```

**Step 2: Add `url` crate to `src-tauri/Cargo.toml`**

```toml
url = "2"
log = "0.4"
```

**Step 3: Wire deep links into app setup**

In `src-tauri/src/lib.rs`, add after the tray setup in the `setup` closure:

```rust
mod deep_link;

// Inside setup closure, after tray::create_tray:
deep_link::setup_deep_links(app.handle())?;
```

**Step 4: Verify deep link registration**

```bash
npm run tauri dev
```

Then in a browser or Run dialog, navigate to `recap://oauth/zoom/callback?code=test123`. The app should receive the URL (check terminal output for the log message).

**Step 5: Commit**

```bash
git add src-tauri/src/deep_link.rs src-tauri/src/lib.rs src-tauri/Cargo.toml
git commit -m "feat: add deep link handler for recap:// protocol"
```

---

### Task 4: Stronghold Credential Storage Module

**Files:**
- Create: `src-tauri/src/credentials.rs`
- Modify: `src-tauri/src/lib.rs`

**Step 1: Create the credentials module**

This module wraps Stronghold operations behind Tauri IPC commands so the Svelte frontend can store and retrieve credentials.

Create `src-tauri/src/credentials.rs`:

```rust
use serde::{Deserialize, Serialize};
use tauri::Manager;

/// Provider identifiers for credential storage.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Provider {
    Zoom,
    Google,
    Microsoft,
    Zoho,
    Todoist,
}

impl Provider {
    pub fn as_str(&self) -> &str {
        match self {
            Provider::Zoom => "zoom",
            Provider::Google => "google",
            Provider::Microsoft => "microsoft",
            Provider::Zoho => "zoho",
            Provider::Todoist => "todoist",
        }
    }
}

/// What we store per provider in Stronghold.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProviderCredentials {
    pub client_id: Option<String>,
    pub client_secret: Option<String>,
    pub access_token: Option<String>,
    pub refresh_token: Option<String>,
}

/// Tauri command: store a credential key-value pair.
/// Key format: "{provider}.{field}" e.g. "zoom.client_id"
#[tauri::command]
pub async fn store_credential(
    app: tauri::AppHandle,
    key: String,
    value: String,
) -> Result<(), String> {
    // Stronghold operations are done from the frontend JS API
    // This command is a pass-through placeholder for any Rust-side credential needs
    // The frontend calls Stronghold directly via @tauri-apps/plugin-stronghold
    Ok(())
}

/// Tauri command: get all credentials for a provider (without secrets, for display).
#[tauri::command]
pub async fn get_provider_status(
    app: tauri::AppHandle,
    provider: String,
) -> Result<ProviderStatus, String> {
    // Return connection status — actual token reads happen in the frontend via Stronghold JS API
    Ok(ProviderStatus {
        provider,
        connected: false,
        display_name: None,
        needs_reconnect: false,
    })
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProviderStatus {
    pub provider: String,
    pub connected: bool,
    pub display_name: Option<String>,
    pub needs_reconnect: bool,
}
```

Note: In Tauri v2, Stronghold is primarily accessed from the JavaScript frontend via `@tauri-apps/plugin-stronghold`. The Rust side initializes the plugin (already done in Task 2). Credential CRUD happens in the Svelte stores (Task 9). This Rust module provides supplementary IPC commands for any backend-driven credential operations (like OAuth token exchange in Task 5).

**Step 2: Register commands in `src-tauri/src/lib.rs`**

Add to the builder chain:
```rust
mod credentials;

// In the builder, before .run():
.invoke_handler(tauri::generate_handler![
    credentials::store_credential,
    credentials::get_provider_status,
])
```

**Step 3: Commit**

```bash
git add src-tauri/src/credentials.rs src-tauri/src/lib.rs
git commit -m "feat: add credential storage module with Tauri IPC commands"
```

---

### Task 5: OAuth Infrastructure

**Files:**
- Create: `src-tauri/src/oauth.rs`
- Modify: `src-tauri/src/lib.rs`
- Modify: `src-tauri/src/deep_link.rs`

**Step 1: Create the OAuth module**

This module handles: (1) building authorization URLs, (2) exchanging auth codes for tokens, (3) running a localhost HTTP server for Google/Microsoft redirects, and (4) refreshing expired tokens.

Create `src-tauri/src/oauth.rs`:

```rust
use reqwest::Client;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::Mutex;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OAuthConfig {
    pub provider: String,
    pub client_id: String,
    pub client_secret: String,
    pub auth_url: String,
    pub token_url: String,
    pub scopes: Vec<String>,
    pub redirect_method: RedirectMethod,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RedirectMethod {
    DeepLink,
    Localhost,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TokenResponse {
    pub access_token: String,
    pub refresh_token: Option<String>,
    pub expires_in: Option<u64>,
    pub token_type: Option<String>,
}

/// Provider-specific OAuth configuration.
pub fn get_provider_config(provider: &str, client_id: &str, client_secret: &str, redirect_uri: &str) -> OAuthConfig {
    match provider {
        "zoom" => OAuthConfig {
            provider: "zoom".into(),
            client_id: client_id.into(),
            client_secret: client_secret.into(),
            auth_url: "https://zoom.us/oauth/authorize".into(),
            token_url: "https://zoom.us/oauth/token".into(),
            scopes: vec!["meeting:read".into(), "recording:read".into(), "user:read".into()],
            redirect_method: RedirectMethod::DeepLink,
        },
        "google" => OAuthConfig {
            provider: "google".into(),
            client_id: client_id.into(),
            client_secret: client_secret.into(),
            auth_url: "https://accounts.google.com/o/oauth2/v2/auth".into(),
            token_url: "https://oauth2.googleapis.com/token".into(),
            scopes: vec!["https://www.googleapis.com/auth/calendar.readonly".into()],
            redirect_method: RedirectMethod::Localhost,
        },
        "microsoft" => OAuthConfig {
            provider: "microsoft".into(),
            client_id: client_id.into(),
            client_secret: client_secret.into(),
            auth_url: "https://login.microsoftonline.com/common/oauth2/v2.0/authorize".into(),
            token_url: "https://login.microsoftonline.com/common/oauth2/v2.0/token".into(),
            scopes: vec!["OnlineMeetings.Read".into(), "User.Read".into()],
            redirect_method: RedirectMethod::Localhost,
        },
        "zoho" => OAuthConfig {
            provider: "zoho".into(),
            client_id: client_id.into(),
            client_secret: client_secret.into(),
            auth_url: "https://accounts.zoho.com/oauth/v2/auth".into(),
            token_url: "https://accounts.zoho.com/oauth/v2/token".into(),
            scopes: vec!["ZohoMeeting.manageOrg.READ".into(), "ZohoCalendar.calendar.READ".into()],
            redirect_method: RedirectMethod::DeepLink,
        },
        "todoist" => OAuthConfig {
            provider: "todoist".into(),
            client_id: client_id.into(),
            client_secret: client_secret.into(),
            auth_url: "https://todoist.com/oauth/authorize".into(),
            token_url: "https://todoist.com/oauth/access_token".into(),
            scopes: vec!["data:read_write".into()],
            redirect_method: RedirectMethod::DeepLink,
        },
        _ => panic!("Unknown provider: {}", provider),
    }
}

/// Build the authorization URL the user's browser should open.
pub fn build_auth_url(config: &OAuthConfig, redirect_uri: &str, state: &str) -> String {
    let scopes = config.scopes.join(" ");
    format!(
        "{}?client_id={}&redirect_uri={}&response_type=code&scope={}&state={}",
        config.auth_url,
        urlencoding::encode(&config.client_id),
        urlencoding::encode(redirect_uri),
        urlencoding::encode(&scopes),
        urlencoding::encode(state),
    )
}

/// Exchange an authorization code for tokens.
pub async fn exchange_code(
    config: &OAuthConfig,
    code: &str,
    redirect_uri: &str,
) -> Result<TokenResponse, String> {
    let client = Client::new();
    let mut params = HashMap::new();
    params.insert("grant_type", "authorization_code");
    params.insert("code", code);
    params.insert("redirect_uri", redirect_uri);
    params.insert("client_id", &config.client_id);
    params.insert("client_secret", &config.client_secret);

    let resp = client
        .post(&config.token_url)
        .form(&params)
        .send()
        .await
        .map_err(|e| format!("Token exchange request failed: {}", e))?;

    if !resp.status().is_success() {
        let body = resp.text().await.unwrap_or_default();
        return Err(format!("Token exchange failed: {}", body));
    }

    resp.json::<TokenResponse>()
        .await
        .map_err(|e| format!("Failed to parse token response: {}", e))
}

/// Refresh an expired access token.
pub async fn refresh_token(
    config: &OAuthConfig,
    refresh_token: &str,
) -> Result<TokenResponse, String> {
    let client = Client::new();
    let mut params = HashMap::new();
    params.insert("grant_type", "refresh_token");
    params.insert("refresh_token", refresh_token);
    params.insert("client_id", &config.client_id);
    params.insert("client_secret", &config.client_secret);

    let resp = client
        .post(&config.token_url)
        .form(&params)
        .send()
        .await
        .map_err(|e| format!("Token refresh request failed: {}", e))?;

    if !resp.status().is_success() {
        let body = resp.text().await.unwrap_or_default();
        return Err(format!("Token refresh failed: {}", body));
    }

    resp.json::<TokenResponse>()
        .await
        .map_err(|e| format!("Failed to parse refresh response: {}", e))
}
```

**Step 2: Add `urlencoding` crate to `src-tauri/Cargo.toml`**

```toml
urlencoding = "2"
```

**Step 3: Create the localhost OAuth callback server**

Add to `src-tauri/src/oauth.rs`:

```rust
use std::net::TcpListener;
use std::io::{Read, Write};

/// Start a temporary localhost HTTP server for OAuth callback.
/// Returns (port, receiver) — receiver yields the auth code when the callback arrives.
pub fn start_localhost_server() -> Result<(u16, tokio::sync::oneshot::Receiver<String>), String> {
    let listener = TcpListener::bind("127.0.0.1:0")
        .map_err(|e| format!("Failed to bind localhost server: {}", e))?;
    let port = listener.local_addr()
        .map_err(|e| format!("Failed to get local address: {}", e))?
        .port();

    let (tx, rx) = tokio::sync::oneshot::channel::<String>();

    std::thread::spawn(move || {
        if let Ok((mut stream, _)) = listener.accept() {
            let mut buf = [0u8; 4096];
            if let Ok(n) = stream.read(&mut buf) {
                let request = String::from_utf8_lossy(&buf[..n]);
                // Parse GET /?code=...&state=... HTTP/1.1
                if let Some(query_start) = request.find('?') {
                    if let Some(query_end) = request[query_start..].find(' ') {
                        let query = &request[query_start + 1..query_start + query_end];
                        for param in query.split('&') {
                            if let Some(code) = param.strip_prefix("code=") {
                                let _ = tx.send(code.to_string());
                                break;
                            }
                        }
                    }
                }

                let response = "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n<html><body><h1>Authorization successful!</h1><p>You can close this tab and return to Recap.</p></body></html>";
                let _ = stream.write_all(response.as_bytes());
            }
        }
    });

    Ok((port, rx))
}
```

**Step 4: Add Tauri IPC commands for OAuth**

Add to `src-tauri/src/oauth.rs`:

```rust
/// Tauri command: start OAuth flow for a provider.
/// Opens the browser to the auth URL. For localhost providers, starts the callback server.
#[tauri::command]
pub async fn start_oauth(
    app: tauri::AppHandle,
    provider: String,
    client_id: String,
    client_secret: String,
    zoho_region: Option<String>,
) -> Result<(), String> {
    let redirect_uri = match get_provider_config(&provider, &client_id, &client_secret, "").redirect_method {
        RedirectMethod::DeepLink => {
            format!("recap://oauth/{}/callback", provider)
        }
        RedirectMethod::Localhost => {
            let (port, rx) = start_localhost_server()?;
            let redirect = format!("http://localhost:{}", port);

            // Spawn a task to wait for the callback and exchange the code
            let config = get_provider_config(&provider, &client_id, &client_secret, &redirect);
            let redirect_clone = redirect.clone();
            tauri::async_runtime::spawn(async move {
                if let Ok(code) = rx.await {
                    match exchange_code(&config, &code, &redirect_clone).await {
                        Ok(tokens) => {
                            log::info!("OAuth tokens received for {}", provider);
                            // TODO: emit event to frontend with tokens for Stronghold storage
                        }
                        Err(e) => {
                            log::error!("Token exchange failed for {}: {}", provider, e);
                        }
                    }
                }
            });

            redirect
        }
    };

    let state = uuid::Uuid::new_v4().to_string();
    let config = get_provider_config(&provider, &client_id, &client_secret, &redirect_uri);
    let auth_url = build_auth_url(&config, &redirect_uri, &state);

    // Open browser
    open::that(&auth_url).map_err(|e| format!("Failed to open browser: {}", e))?;

    Ok(())
}

/// Tauri command: exchange an auth code for tokens (called from deep link handler).
#[tauri::command]
pub async fn exchange_oauth_code(
    provider: String,
    code: String,
    client_id: String,
    client_secret: String,
) -> Result<TokenResponse, String> {
    let redirect_uri = format!("recap://oauth/{}/callback", provider);
    let config = get_provider_config(&provider, &client_id, &client_secret, &redirect_uri);
    exchange_code(&config, &code, &redirect_uri).await
}
```

**Step 5: Add `uuid` and `open` crates to `src-tauri/Cargo.toml`**

```toml
uuid = { version = "1", features = ["v4"] }
open = "5"
```

**Step 6: Register OAuth commands in `src-tauri/src/lib.rs`**

```rust
mod oauth;

// Add to invoke_handler:
.invoke_handler(tauri::generate_handler![
    credentials::store_credential,
    credentials::get_provider_status,
    oauth::start_oauth,
    oauth::exchange_oauth_code,
])
```

**Step 7: Wire deep link handler to OAuth token exchange**

Update `src-tauri/src/deep_link.rs` to emit an event to the frontend when an OAuth callback is received, so the Svelte code can handle token storage:

```rust
use tauri::Emitter;

fn handle_deep_link_url(app: &tauri::AppHandle, url: &str) {
    if let Ok(parsed) = url::Url::parse(url) {
        let path_segments: Vec<&str> = parsed.path_segments()
            .map(|s| s.collect())
            .unwrap_or_default();

        // recap://oauth/{provider}/callback?code=...
        if parsed.scheme() == "recap" {
            if let Some(host) = parsed.host_str() {
                if host == "oauth" && path_segments.len() >= 2 && path_segments[1] == "callback" {
                    let provider = path_segments[0].to_string();
                    let code = parsed.query_pairs()
                        .find(|(key, _)| key == "code")
                        .map(|(_, value)| value.to_string());

                    if let Some(code) = code {
                        let _ = app.emit("oauth-callback", serde_json::json!({
                            "provider": provider,
                            "code": code,
                        }));
                    }
                }
            }
        }
    }
}
```

Update `setup_deep_links` to pass the app handle to the handler. The `on_open_url` closure needs access to the app handle — check the Tauri v2 deep link plugin docs for the exact closure signature and adjust accordingly.

**Step 8: Verify OAuth flow starts**

```bash
npm run tauri dev
```

Open browser console in the Tauri webview (right-click → Inspect). Call `invoke('start_oauth', { provider: 'zoom', clientId: 'test', clientSecret: 'test' })`. Expected: Browser opens to Zoom's OAuth page (will show an error since credentials are fake, but the flow starts).

**Step 9: Commit**

```bash
git add src-tauri/src/oauth.rs src-tauri/src/deep_link.rs src-tauri/src/lib.rs src-tauri/Cargo.toml
git commit -m "feat: add OAuth infrastructure with token exchange and localhost server"
```

---

### Task 6: Sidecar Build Script and Rust Wrapper

**Files:**
- Create: `scripts/build-sidecar.py`
- Create: `run_pipeline.py` (PyInstaller entry point stub)
- Create: `src-tauri/src/sidecar.rs`
- Modify: `src-tauri/src/lib.rs`
- Modify: `src-tauri/tauri.conf.json`

**Step 1: Create PyInstaller entry point**

Create `run_pipeline.py` at repo root:

```python
"""PyInstaller entry point for the recap pipeline sidecar."""
from recap.cli import main

if __name__ == "__main__":
    main()
```

**Step 2: Create the sidecar build script**

Create `scripts/build-sidecar.py`:

```python
"""Build the recap pipeline as a PyInstaller sidecar binary for Tauri."""
import subprocess
import shutil
import platform
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
BINARIES_DIR = REPO_ROOT / "src-tauri" / "binaries"


def get_target_triple() -> str:
    """Get the Rust target triple for the current platform."""
    result = subprocess.run(
        ["rustc", "--print", "host-tuple"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def build_sidecar() -> None:
    target_triple = get_target_triple()
    sidecar_name = f"recap-pipeline-{target_triple}"

    if platform.system() == "Windows":
        sidecar_name += ".exe"

    print(f"Building sidecar: {sidecar_name}")

    # Run PyInstaller
    subprocess.run(
        [
            "pyinstaller",
            "--onefile",
            "--name", sidecar_name.replace(".exe", "") if platform.system() == "Windows" else sidecar_name,
            str(REPO_ROOT / "run_pipeline.py"),
        ],
        cwd=str(REPO_ROOT),
        check=True,
    )

    # Copy to src-tauri/binaries/
    BINARIES_DIR.mkdir(parents=True, exist_ok=True)
    dist_path = REPO_ROOT / "dist" / sidecar_name
    dest_path = BINARIES_DIR / sidecar_name
    shutil.copy2(str(dist_path), str(dest_path))
    print(f"Sidecar copied to: {dest_path}")


if __name__ == "__main__":
    build_sidecar()
```

**Step 3: Declare sidecar in `src-tauri/tauri.conf.json`**

Add to the `bundle` section:
```json
{
  "bundle": {
    "externalBin": [
      "binaries/recap-pipeline"
    ]
  }
}
```

**Step 4: Create the sidecar Rust wrapper**

Create `src-tauri/src/sidecar.rs`:

```rust
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::CommandEvent;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SidecarResult {
    pub success: bool,
    pub stdout: String,
    pub stderr: String,
}

/// Tauri command: run the recap pipeline sidecar.
/// Phase 3 scope: infrastructure only. Actual triggering happens in Phase 4.
#[tauri::command]
pub async fn run_pipeline(
    app: tauri::AppHandle,
    config_path: String,
    recording_path: String,
) -> Result<SidecarResult, String> {
    let sidecar = app
        .shell()
        .sidecar("recap-pipeline")
        .map_err(|e| format!("Failed to create sidecar command: {}", e))?
        .args(["process", "--config", &config_path, &recording_path]);

    let output = sidecar
        .output()
        .await
        .map_err(|e| format!("Sidecar execution failed: {}", e))?;

    Ok(SidecarResult {
        success: output.status.success(),
        stdout: String::from_utf8_lossy(&output.stdout).to_string(),
        stderr: String::from_utf8_lossy(&output.stderr).to_string(),
    })
}

/// Tauri command: check if the sidecar binary exists.
#[tauri::command]
pub async fn check_sidecar_status(app: tauri::AppHandle) -> Result<bool, String> {
    // Try to create the sidecar command — if it fails, the binary isn't found
    match app.shell().sidecar("recap-pipeline") {
        Ok(_) => Ok(true),
        Err(_) => Ok(false),
    }
}
```

**Step 5: Register sidecar commands in `src-tauri/src/lib.rs`**

```rust
mod sidecar;

// Add to invoke_handler:
.invoke_handler(tauri::generate_handler![
    credentials::store_credential,
    credentials::get_provider_status,
    oauth::start_oauth,
    oauth::exchange_oauth_code,
    sidecar::run_pipeline,
    sidecar::check_sidecar_status,
])
```

**Step 6: Build the sidecar and test**

```bash
pip install pyinstaller
python scripts/build-sidecar.py
```

Expected: `src-tauri/binaries/recap-pipeline-x86_64-pc-windows-msvc.exe` is created.

**Step 7: Commit**

```bash
git add scripts/build-sidecar.py run_pipeline.py src-tauri/src/sidecar.rs src-tauri/src/lib.rs src-tauri/tauri.conf.json
git commit -m "feat: add sidecar build script and Rust wrapper for Python pipeline"
```

---

### Task 7: Svelte Stores and Tauri IPC Wrappers

**Files:**
- Create: `src/lib/tauri.ts`
- Create: `src/lib/stores/credentials.ts`
- Create: `src/lib/stores/settings.ts`

**Step 1: Create typed Tauri IPC wrappers**

Create `src/lib/tauri.ts`:

```typescript
import { invoke } from "@tauri-apps/api/core";

// OAuth
export async function startOAuth(
  provider: string,
  clientId: string,
  clientSecret: string,
  zohoRegion?: string
): Promise<void> {
  return invoke("start_oauth", {
    provider,
    clientId,
    clientSecret,
    zohoRegion,
  });
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string | null;
  expires_in: number | null;
  token_type: string | null;
}

export async function exchangeOAuthCode(
  provider: string,
  code: string,
  clientId: string,
  clientSecret: string
): Promise<TokenResponse> {
  return invoke("exchange_oauth_code", {
    provider,
    code,
    clientId,
    clientSecret,
  });
}

// Sidecar
export interface SidecarResult {
  success: boolean;
  stdout: string;
  stderr: string;
}

export async function runPipeline(
  configPath: string,
  recordingPath: string
): Promise<SidecarResult> {
  return invoke("run_pipeline", { configPath, recordingPath });
}

export async function checkSidecarStatus(): Promise<boolean> {
  return invoke("check_sidecar_status");
}
```

**Step 2: Create the credentials store**

This store wraps Stronghold operations for credential CRUD.

Create `src/lib/stores/credentials.ts`:

```typescript
import { writable, derived } from "svelte/store";
import { Client, Stronghold } from "@tauri-apps/plugin-stronghold";
import { appDataDir } from "@tauri-apps/api/path";

const VAULT_PASSWORD = "recap-vault-password"; // Stronghold handles encryption via Argon2
const CLIENT_NAME = "recap";

export type ProviderName = "zoom" | "google" | "microsoft" | "zoho" | "todoist";
export type ConnectionStatus = "disconnected" | "connected" | "reconnect_required";

export interface ProviderState {
  clientId: string;
  clientSecret: string;
  accessToken: string | null;
  refreshToken: string | null;
  displayName: string | null;
  status: ConnectionStatus;
}

type CredentialsState = Record<ProviderName, ProviderState>;

const defaultProviderState: ProviderState = {
  clientId: "",
  clientSecret: "",
  accessToken: null,
  refreshToken: null,
  displayName: null,
  status: "disconnected",
};

const initialState: CredentialsState = {
  zoom: { ...defaultProviderState },
  google: { ...defaultProviderState },
  microsoft: { ...defaultProviderState },
  zoho: { ...defaultProviderState },
  todoist: { ...defaultProviderState },
};

export const credentials = writable<CredentialsState>(initialState);

let stronghold: Stronghold | null = null;
let store: any = null;

async function getStore() {
  if (store) return store;
  const dir = await appDataDir();
  stronghold = await Stronghold.load(`${dir}/vault.hold`, VAULT_PASSWORD);
  let client: Client;
  try {
    client = await stronghold.loadClient(CLIENT_NAME);
  } catch {
    client = await stronghold.createClient(CLIENT_NAME);
  }
  store = client.getStore();
  return store;
}

async function storeValue(key: string, value: string): Promise<void> {
  const s = await getStore();
  const data = Array.from(new TextEncoder().encode(value));
  await s.insert(key, data);
  await stronghold!.save();
}

async function getValue(key: string): Promise<string | null> {
  const s = await getStore();
  try {
    const data = await s.get(key);
    if (!data || data.length === 0) return null;
    return new TextDecoder().decode(new Uint8Array(data));
  } catch {
    return null;
  }
}

async function removeValue(key: string): Promise<void> {
  const s = await getStore();
  try {
    await s.remove(key);
    await stronghold!.save();
  } catch {
    // Key might not exist
  }
}

/// Load all provider credentials from Stronghold into the store.
export async function loadCredentials(): Promise<void> {
  const providers: ProviderName[] = ["zoom", "google", "microsoft", "zoho", "todoist"];
  const state = { ...initialState };

  for (const provider of providers) {
    const clientId = await getValue(`${provider}.client_id`);
    const clientSecret = await getValue(`${provider}.client_secret`);
    const accessToken = await getValue(`${provider}.access_token`);
    const refreshToken = await getValue(`${provider}.refresh_token`);
    const displayName = await getValue(`${provider}.display_name`);

    state[provider] = {
      clientId: clientId ?? "",
      clientSecret: clientSecret ?? "",
      accessToken,
      refreshToken,
      displayName,
      status: accessToken ? "connected" : "disconnected",
    };
  }

  credentials.set(state);
}

/// Save client credentials for a provider.
export async function saveClientCredentials(
  provider: ProviderName,
  clientId: string,
  clientSecret: string
): Promise<void> {
  await storeValue(`${provider}.client_id`, clientId);
  await storeValue(`${provider}.client_secret`, clientSecret);
  credentials.update((state) => ({
    ...state,
    [provider]: { ...state[provider], clientId, clientSecret },
  }));
}

/// Save OAuth tokens after successful authorization.
export async function saveTokens(
  provider: ProviderName,
  accessToken: string,
  refreshToken: string | null,
  displayName: string | null
): Promise<void> {
  await storeValue(`${provider}.access_token`, accessToken);
  if (refreshToken) {
    await storeValue(`${provider}.refresh_token`, refreshToken);
  }
  if (displayName) {
    await storeValue(`${provider}.display_name`, displayName);
  }
  credentials.update((state) => ({
    ...state,
    [provider]: {
      ...state[provider],
      accessToken,
      refreshToken,
      displayName,
      status: "connected",
    },
  }));
}

/// Disconnect a provider — remove tokens but keep client credentials.
export async function disconnect(provider: ProviderName): Promise<void> {
  await removeValue(`${provider}.access_token`);
  await removeValue(`${provider}.refresh_token`);
  await removeValue(`${provider}.display_name`);
  credentials.update((state) => ({
    ...state,
    [provider]: {
      ...state[provider],
      accessToken: null,
      refreshToken: null,
      displayName: null,
      status: "disconnected",
    },
  }));
}
```

**Step 3: Create the settings store**

Create `src/lib/stores/settings.ts`:

```typescript
import { writable } from "svelte/store";
import { Store } from "@tauri-apps/plugin-store";

export interface AppSettings {
  // Vault
  vaultPath: string;
  meetingsFolder: string;
  peopleFolder: string;
  companiesFolder: string;
  // Recording
  recordingsFolder: string;
  // WhisperX
  whisperxModel: string;
  whisperxDevice: string;
  whisperxComputeType: string;
  whisperxLanguage: string;
  // Todoist
  todoistProject: string;
  todoistLabels: string;
  // Zoho
  zohoRegion: string;
  // General
  showNotificationOnComplete: boolean;
}

const defaults: AppSettings = {
  vaultPath: "",
  meetingsFolder: "Work/Meetings",
  peopleFolder: "Work/People",
  companiesFolder: "Work/Companies",
  recordingsFolder: "",
  whisperxModel: "large-v3",
  whisperxDevice: "cuda",
  whisperxComputeType: "float16",
  whisperxLanguage: "en",
  todoistProject: "",
  todoistLabels: "",
  zohoRegion: "com",
  showNotificationOnComplete: true,
};

export const settings = writable<AppSettings>({ ...defaults });

let tauriStore: Store | null = null;

async function getStore(): Promise<Store> {
  if (!tauriStore) {
    tauriStore = await Store.load("settings.json");
  }
  return tauriStore;
}

/// Load settings from tauri-plugin-store, falling back to defaults.
export async function loadSettings(): Promise<void> {
  const store = await getStore();
  const loaded: Partial<AppSettings> = {};

  for (const [key, defaultValue] of Object.entries(defaults)) {
    const value = await store.get(key);
    if (value !== null && value !== undefined) {
      (loaded as any)[key] = value;
    } else {
      (loaded as any)[key] = defaultValue;
    }
  }

  settings.set(loaded as AppSettings);
}

/// Save a single setting.
export async function saveSetting<K extends keyof AppSettings>(
  key: K,
  value: AppSettings[K]
): Promise<void> {
  const store = await getStore();
  await store.set(key, value);
  await store.save();
  settings.update((s) => ({ ...s, [key]: value }));
}

/// Save all settings at once.
export async function saveAllSettings(values: AppSettings): Promise<void> {
  const store = await getStore();
  for (const [key, value] of Object.entries(values)) {
    await store.set(key, value);
  }
  await store.save();
  settings.set(values);
}
```

**Step 4: Commit**

```bash
git add src/lib/tauri.ts src/lib/stores/credentials.ts src/lib/stores/settings.ts
git commit -m "feat: add Svelte stores for credentials and settings with Tauri IPC wrappers"
```

---

### Task 8: Settings Page — Layout and Routing

**Files:**
- Modify: `src/App.svelte`
- Create: `src/routes/Settings.svelte`
- Create: `src/routes/Dashboard.svelte`
- Modify: `src/app.css`

**Step 1: Set up simple hash-based routing in App.svelte**

Replace `src/App.svelte`:

```svelte
<script lang="ts">
  import { onMount } from "svelte";
  import Settings from "./routes/Settings.svelte";
  import Dashboard from "./routes/Dashboard.svelte";
  import { loadCredentials } from "./lib/stores/credentials";
  import { loadSettings } from "./lib/stores/settings";

  let currentRoute = $state("dashboard");

  onMount(async () => {
    await loadCredentials();
    await loadSettings();

    // Simple hash routing
    const updateRoute = () => {
      const hash = window.location.hash.slice(1) || "dashboard";
      currentRoute = hash;
    };
    window.addEventListener("hashchange", updateRoute);
    updateRoute();
  });
</script>

<main class="min-h-screen bg-gray-50">
  {#if currentRoute === "settings"}
    <Settings />
  {:else}
    <Dashboard />
  {/if}
</main>
```

**Step 2: Create Dashboard placeholder**

Create `src/routes/Dashboard.svelte`:

```svelte
<script lang="ts">
</script>

<div class="max-w-4xl mx-auto p-8">
  <h1 class="text-2xl font-bold text-gray-900 mb-4">Recap</h1>
  <p class="text-gray-600 mb-6">Dashboard coming in Phase 5.</p>
  <a href="#settings" class="text-blue-600 hover:underline">Open Settings</a>
</div>
```

**Step 3: Create Settings page shell**

Create `src/routes/Settings.svelte`:

```svelte
<script lang="ts">
</script>

<div class="max-w-3xl mx-auto p-8">
  <div class="flex items-center justify-between mb-8">
    <h1 class="text-2xl font-bold text-gray-900">Settings</h1>
    <a href="#dashboard" class="text-blue-600 hover:underline text-sm">Back to Dashboard</a>
  </div>

  <div class="space-y-8">
    <section>
      <h2 class="text-lg font-semibold text-gray-800 mb-4">Platform Connections</h2>
      <p class="text-gray-500">Coming in next task.</p>
    </section>

    <section>
      <h2 class="text-lg font-semibold text-gray-800 mb-4">Vault Settings</h2>
      <p class="text-gray-500">Coming in next task.</p>
    </section>

    <section>
      <h2 class="text-lg font-semibold text-gray-800 mb-4">About</h2>
      <p class="text-gray-500">Coming in next task.</p>
    </section>
  </div>
</div>
```

**Step 4: Clean up default styles**

Replace `src/app.css`:

```css
@import "tailwindcss";
```

**Step 5: Verify routing works**

```bash
npm run tauri dev
```

Open the dashboard via tray. Click "Open Settings" link. Verify hash routing works between `#dashboard` and `#settings`.

**Step 6: Commit**

```bash
git add src/App.svelte src/routes/Settings.svelte src/routes/Dashboard.svelte src/app.css
git commit -m "feat: add settings page shell with hash-based routing"
```

---

### Task 9: Settings Page — Platform Connection Cards

**Files:**
- Create: `src/lib/components/ProviderCard.svelte`
- Modify: `src/routes/Settings.svelte`

**Step 1: Create the reusable ProviderCard component**

Create `src/lib/components/ProviderCard.svelte`:

```svelte
<script lang="ts">
  import { type ProviderName, type ProviderState, saveClientCredentials, disconnect } from "../stores/credentials";
  import { startOAuth } from "../tauri";
  import { settings } from "../stores/settings";

  interface Props {
    provider: ProviderName;
    label: string;
    state: ProviderState;
    showRegion?: boolean;
  }

  let { provider, label, state, showRegion = false }: Props = $props();

  let clientId = $state(state.clientId);
  let clientSecret = $state(state.clientSecret);
  let saving = $state(false);
  let connecting = $state(false);

  // Sync from parent state changes
  $effect(() => {
    clientId = state.clientId;
    clientSecret = state.clientSecret;
  });

  let hasCredentials = $derived(clientId.trim() !== "" && clientSecret.trim() !== "");

  async function saveCredentials() {
    saving = true;
    try {
      await saveClientCredentials(provider, clientId, clientSecret);
    } finally {
      saving = false;
    }
  }

  async function connect() {
    connecting = true;
    try {
      await saveClientCredentials(provider, clientId, clientSecret);
      let zohoRegion: string | undefined;
      if (provider === "zoho") {
        const s = $settings;
        zohoRegion = s.zohoRegion;
      }
      await startOAuth(provider, clientId, clientSecret, zohoRegion);
    } finally {
      connecting = false;
    }
  }

  async function handleDisconnect() {
    await disconnect(provider);
  }
</script>

<div class="border border-gray-200 rounded-lg p-4 bg-white">
  <h3 class="font-medium text-gray-900 mb-3">{label}</h3>

  <div class="space-y-3">
    <div>
      <label class="block text-sm text-gray-600 mb-1">Client ID</label>
      <input
        type="text"
        bind:value={clientId}
        onblur={saveCredentials}
        class="w-full border border-gray-300 rounded px-3 py-1.5 text-sm"
        placeholder="Enter client ID"
      />
    </div>

    <div>
      <label class="block text-sm text-gray-600 mb-1">Client Secret</label>
      <input
        type="password"
        bind:value={clientSecret}
        onblur={saveCredentials}
        class="w-full border border-gray-300 rounded px-3 py-1.5 text-sm"
        placeholder="Enter client secret"
      />
    </div>

    {#if showRegion}
      <div>
        <label class="block text-sm text-gray-600 mb-1">Region</label>
        <select class="w-full border border-gray-300 rounded px-3 py-1.5 text-sm">
          <option value="com">.com (US)</option>
          <option value="eu">.eu (Europe)</option>
          <option value="in">.in (India)</option>
          <option value="com.au">.com.au (Australia)</option>
        </select>
      </div>
    {/if}

    <div class="flex items-center justify-between pt-2">
      <div class="text-sm">
        {#if state.status === "connected"}
          <span class="text-green-600">● Connected{state.displayName ? ` as ${state.displayName}` : ""}</span>
        {:else if state.status === "reconnect_required"}
          <span class="text-amber-600">● Reconnect required</span>
        {:else}
          <span class="text-gray-400">● Disconnected</span>
        {/if}
      </div>

      <div>
        {#if state.status === "connected"}
          <button onclick={handleDisconnect} class="text-sm text-red-600 hover:underline">
            Disconnect
          </button>
        {:else}
          <button
            onclick={connect}
            disabled={!hasCredentials || connecting}
            class="text-sm bg-blue-600 text-white px-3 py-1 rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {connecting ? "Connecting..." : "Connect"}
          </button>
        {/if}
      </div>
    </div>

    {#if provider === "microsoft" && state.status === "connected"}
      <p class="text-xs text-amber-600 mt-1">
        Note: Personal accounts have limited recording API access. Recording will require manual start.
      </p>
    {/if}
  </div>
</div>
```

**Step 2: Wire ProviderCards into Settings page**

Update the Platform Connections section in `src/routes/Settings.svelte`:

```svelte
<script lang="ts">
  import ProviderCard from "../lib/components/ProviderCard.svelte";
  import { credentials } from "../lib/stores/credentials";
</script>

<!-- In the Platform Connections section: -->
<section>
  <h2 class="text-lg font-semibold text-gray-800 mb-4">Platform Connections</h2>
  <div class="space-y-4">
    <ProviderCard provider="zoom" label="Zoom" state={$credentials.zoom} />
    <ProviderCard provider="google" label="Google" state={$credentials.google} />
    <ProviderCard provider="microsoft" label="Microsoft Teams" state={$credentials.microsoft} />
    <ProviderCard provider="zoho" label="Zoho" state={$credentials.zoho} showRegion={true} />
    <ProviderCard provider="todoist" label="Todoist" state={$credentials.todoist} />
  </div>
</section>
```

**Step 3: Listen for OAuth callback events from deep links**

Add to `src/App.svelte` in the `onMount`:

```typescript
import { listen } from "@tauri-apps/api/event";
import { exchangeOAuthCode } from "./lib/tauri";
import { credentials, saveTokens } from "./lib/stores/credentials";
import type { ProviderName } from "./lib/stores/credentials";

// Inside onMount:
await listen("oauth-callback", async (event: any) => {
  const { provider, code } = event.payload;
  const creds = $credentials;
  const providerState = creds[provider as ProviderName];

  if (providerState?.clientId && providerState?.clientSecret) {
    try {
      const tokens = await exchangeOAuthCode(
        provider,
        code,
        providerState.clientId,
        providerState.clientSecret
      );
      await saveTokens(
        provider as ProviderName,
        tokens.access_token,
        tokens.refresh_token,
        null // displayName fetched separately per provider
      );
    } catch (err) {
      console.error(`OAuth token exchange failed for ${provider}:`, err);
    }
  }
});
```

**Step 4: Verify provider cards render**

```bash
npm run tauri dev
```

Navigate to settings. Verify all five provider cards render with credential inputs and Connect buttons.

**Step 5: Commit**

```bash
git add src/lib/components/ProviderCard.svelte src/routes/Settings.svelte src/App.svelte
git commit -m "feat: add platform connection cards with OAuth flow integration"
```

---

### Task 10: Settings Page — Vault, Recording, WhisperX, Todoist, General Sections

**Files:**
- Create: `src/lib/components/SettingsSection.svelte`
- Create: `src/lib/components/VaultSettings.svelte`
- Create: `src/lib/components/RecordingSettings.svelte`
- Create: `src/lib/components/WhisperXSettings.svelte`
- Create: `src/lib/components/TodoistSettings.svelte`
- Create: `src/lib/components/GeneralSettings.svelte`
- Modify: `src/routes/Settings.svelte`

**Step 1: Create a reusable section wrapper**

Create `src/lib/components/SettingsSection.svelte`:

```svelte
<script lang="ts">
  import type { Snippet } from "svelte";

  interface Props {
    title: string;
    children: Snippet;
  }

  let { title, children }: Props = $props();
</script>

<section>
  <h2 class="text-lg font-semibold text-gray-800 mb-4">{title}</h2>
  <div class="border border-gray-200 rounded-lg p-4 bg-white space-y-4">
    {@render children()}
  </div>
</section>
```

**Step 2: Create VaultSettings component**

Create `src/lib/components/VaultSettings.svelte`:

```svelte
<script lang="ts">
  import { settings, saveSetting } from "../stores/settings";
  import { open } from "@tauri-apps/plugin-dialog";

  async function browseVaultPath() {
    const selected = await open({ directory: true, multiple: false });
    if (selected) {
      await saveSetting("vaultPath", selected as string);
    }
  }
</script>

<div class="space-y-3">
  <div>
    <label class="block text-sm text-gray-600 mb-1">Vault Path</label>
    <div class="flex gap-2">
      <input
        type="text"
        value={$settings.vaultPath}
        onblur={(e) => saveSetting("vaultPath", e.currentTarget.value)}
        class="flex-1 border border-gray-300 rounded px-3 py-1.5 text-sm"
        placeholder="Path to Obsidian vault"
      />
      <button onclick={browseVaultPath} class="text-sm bg-gray-100 px-3 py-1.5 rounded border border-gray-300 hover:bg-gray-200">
        Browse
      </button>
    </div>
  </div>

  <div class="grid grid-cols-3 gap-3">
    <div>
      <label class="block text-sm text-gray-600 mb-1">Meetings Folder</label>
      <input
        type="text"
        value={$settings.meetingsFolder}
        onblur={(e) => saveSetting("meetingsFolder", e.currentTarget.value)}
        class="w-full border border-gray-300 rounded px-3 py-1.5 text-sm"
      />
    </div>
    <div>
      <label class="block text-sm text-gray-600 mb-1">People Folder</label>
      <input
        type="text"
        value={$settings.peopleFolder}
        onblur={(e) => saveSetting("peopleFolder", e.currentTarget.value)}
        class="w-full border border-gray-300 rounded px-3 py-1.5 text-sm"
      />
    </div>
    <div>
      <label class="block text-sm text-gray-600 mb-1">Companies Folder</label>
      <input
        type="text"
        value={$settings.companiesFolder}
        onblur={(e) => saveSetting("companiesFolder", e.currentTarget.value)}
        class="w-full border border-gray-300 rounded px-3 py-1.5 text-sm"
      />
    </div>
  </div>
</div>
```

Note: The `open` function requires `@tauri-apps/plugin-dialog`. Install it:
```bash
npm install @tauri-apps/plugin-dialog
```
And add the Cargo dependency `tauri-plugin-dialog = "2"` plus capability `"dialog:default"`.

**Step 3: Create RecordingSettings component**

Create `src/lib/components/RecordingSettings.svelte`:

```svelte
<script lang="ts">
  import { settings, saveSetting } from "../stores/settings";
  import { open } from "@tauri-apps/plugin-dialog";

  async function browseRecordingsFolder() {
    const selected = await open({ directory: true, multiple: false });
    if (selected) {
      await saveSetting("recordingsFolder", selected as string);
    }
  }
</script>

<div>
  <label class="block text-sm text-gray-600 mb-1">Recordings Folder</label>
  <div class="flex gap-2">
    <input
      type="text"
      value={$settings.recordingsFolder}
      onblur={(e) => saveSetting("recordingsFolder", e.currentTarget.value)}
      class="flex-1 border border-gray-300 rounded px-3 py-1.5 text-sm"
      placeholder="Path to store recordings"
    />
    <button onclick={browseRecordingsFolder} class="text-sm bg-gray-100 px-3 py-1.5 rounded border border-gray-300 hover:bg-gray-200">
      Browse
    </button>
  </div>
</div>
```

**Step 4: Create WhisperXSettings component**

Create `src/lib/components/WhisperXSettings.svelte`:

```svelte
<script lang="ts">
  import { settings, saveSetting } from "../stores/settings";
</script>

<div class="grid grid-cols-2 gap-3">
  <div>
    <label class="block text-sm text-gray-600 mb-1">Model</label>
    <select
      value={$settings.whisperxModel}
      onchange={(e) => saveSetting("whisperxModel", e.currentTarget.value)}
      class="w-full border border-gray-300 rounded px-3 py-1.5 text-sm"
    >
      <option value="large-v3">large-v3</option>
      <option value="medium">medium</option>
      <option value="small">small</option>
      <option value="base">base</option>
      <option value="tiny">tiny</option>
    </select>
  </div>

  <div>
    <label class="block text-sm text-gray-600 mb-1">Device</label>
    <select
      value={$settings.whisperxDevice}
      onchange={(e) => saveSetting("whisperxDevice", e.currentTarget.value)}
      class="w-full border border-gray-300 rounded px-3 py-1.5 text-sm"
    >
      <option value="cuda">CUDA (GPU)</option>
      <option value="cpu">CPU</option>
    </select>
  </div>

  <div>
    <label class="block text-sm text-gray-600 mb-1">Compute Type</label>
    <select
      value={$settings.whisperxComputeType}
      onchange={(e) => saveSetting("whisperxComputeType", e.currentTarget.value)}
      class="w-full border border-gray-300 rounded px-3 py-1.5 text-sm"
    >
      <option value="float16">float16</option>
      <option value="int8">int8</option>
      <option value="float32">float32</option>
    </select>
  </div>

  <div>
    <label class="block text-sm text-gray-600 mb-1">Language</label>
    <input
      type="text"
      value={$settings.whisperxLanguage}
      onblur={(e) => saveSetting("whisperxLanguage", e.currentTarget.value)}
      class="w-full border border-gray-300 rounded px-3 py-1.5 text-sm"
      placeholder="en"
    />
  </div>
</div>
```

**Step 5: Create TodoistSettings component**

Create `src/lib/components/TodoistSettings.svelte`:

```svelte
<script lang="ts">
  import { settings, saveSetting } from "../stores/settings";
</script>

<div class="space-y-3">
  <div>
    <label class="block text-sm text-gray-600 mb-1">Project</label>
    <input
      type="text"
      value={$settings.todoistProject}
      onblur={(e) => saveSetting("todoistProject", e.currentTarget.value)}
      class="w-full border border-gray-300 rounded px-3 py-1.5 text-sm"
      placeholder="Project name for meeting tasks"
    />
  </div>

  <div>
    <label class="block text-sm text-gray-600 mb-1">Default Labels</label>
    <input
      type="text"
      value={$settings.todoistLabels}
      onblur={(e) => saveSetting("todoistLabels", e.currentTarget.value)}
      class="w-full border border-gray-300 rounded px-3 py-1.5 text-sm"
      placeholder="Comma-separated labels"
    />
  </div>
</div>
```

**Step 6: Create GeneralSettings component**

Create `src/lib/components/GeneralSettings.svelte`:

```svelte
<script lang="ts">
  import { settings, saveSetting } from "../stores/settings";
</script>

<div class="space-y-3">
  <label class="flex items-center gap-2 text-sm text-gray-600">
    <input type="checkbox" disabled class="rounded" />
    Start on login
    <span class="text-xs text-gray-400">(enabled in final release)</span>
  </label>

  <label class="flex items-center gap-2 text-sm text-gray-600">
    <input
      type="checkbox"
      checked={$settings.showNotificationOnComplete}
      onchange={(e) => saveSetting("showNotificationOnComplete", e.currentTarget.checked)}
      class="rounded"
    />
    Show notification when processing complete
  </label>
</div>
```

**Step 7: Wire all sections into Settings.svelte**

Update `src/routes/Settings.svelte`:

```svelte
<script lang="ts">
  import ProviderCard from "../lib/components/ProviderCard.svelte";
  import SettingsSection from "../lib/components/SettingsSection.svelte";
  import VaultSettings from "../lib/components/VaultSettings.svelte";
  import RecordingSettings from "../lib/components/RecordingSettings.svelte";
  import WhisperXSettings from "../lib/components/WhisperXSettings.svelte";
  import TodoistSettings from "../lib/components/TodoistSettings.svelte";
  import GeneralSettings from "../lib/components/GeneralSettings.svelte";
  import { credentials } from "../lib/stores/credentials";
</script>

<div class="max-w-3xl mx-auto p-8">
  <div class="flex items-center justify-between mb-8">
    <h1 class="text-2xl font-bold text-gray-900">Settings</h1>
    <a href="#dashboard" class="text-blue-600 hover:underline text-sm">Back to Dashboard</a>
  </div>

  <div class="space-y-8">
    <section>
      <h2 class="text-lg font-semibold text-gray-800 mb-4">Platform Connections</h2>
      <div class="space-y-4">
        <ProviderCard provider="zoom" label="Zoom" state={$credentials.zoom} />
        <ProviderCard provider="google" label="Google" state={$credentials.google} />
        <ProviderCard provider="microsoft" label="Microsoft Teams" state={$credentials.microsoft} />
        <ProviderCard provider="zoho" label="Zoho" state={$credentials.zoho} showRegion={true} />
        <ProviderCard provider="todoist" label="Todoist" state={$credentials.todoist} />
      </div>
    </section>

    <SettingsSection title="Vault">
      <VaultSettings />
    </SettingsSection>

    <SettingsSection title="Recording">
      <RecordingSettings />
    </SettingsSection>

    <SettingsSection title="WhisperX">
      <WhisperXSettings />
    </SettingsSection>

    <SettingsSection title="Todoist">
      <TodoistSettings />
    </SettingsSection>

    <SettingsSection title="General">
      <GeneralSettings />
    </SettingsSection>
  </div>
</div>
```

**Step 8: Verify the full settings page**

```bash
npm run tauri dev
```

Navigate to settings. Verify all sections render: platform cards, vault settings with browse buttons, recording settings, WhisperX dropdowns, Todoist inputs, general checkboxes.

**Step 9: Commit**

```bash
git add src/lib/components/ src/routes/Settings.svelte
git commit -m "feat: add vault, recording, WhisperX, Todoist, and general settings sections"
```

---

### Task 11: Settings Page — About / Diagnostics

**Files:**
- Create: `src/lib/components/AboutSection.svelte`
- Modify: `src/routes/Settings.svelte`

**Step 1: Create the About component**

Create `src/lib/components/AboutSection.svelte`:

```svelte
<script lang="ts">
  import { onMount } from "svelte";
  import { checkSidecarStatus } from "../tauri";
  import { getVersion } from "@tauri-apps/api/app";

  let version = $state("...");
  let sidecarFound = $state<boolean | null>(null);

  onMount(async () => {
    version = await getVersion();
    sidecarFound = await checkSidecarStatus();
  });
</script>

<div class="space-y-2 text-sm">
  <div class="flex justify-between">
    <span class="text-gray-600">Version</span>
    <span class="text-gray-900">{version}</span>
  </div>

  <div class="flex justify-between">
    <span class="text-gray-600">Pipeline Sidecar</span>
    <span class={sidecarFound ? "text-green-600" : "text-red-600"}>
      {sidecarFound === null ? "Checking..." : sidecarFound ? "Found" : "Not found"}
    </span>
  </div>
</div>
```

Note: GPU detection and log viewer can be added later by invoking the sidecar with a `--check-gpu` flag or reading log files. Keep this minimal for Phase 3.

**Step 2: Add About section to Settings.svelte**

Add after the General section:

```svelte
<SettingsSection title="About">
  <AboutSection />
</SettingsSection>
```

Import `AboutSection` at the top.

**Step 3: Commit**

```bash
git add src/lib/components/AboutSection.svelte src/routes/Settings.svelte
git commit -m "feat: add about/diagnostics section to settings page"
```

---

### Task 12: Autostart Plugin (Disabled)

**Files:**
- Modify: `src-tauri/src/lib.rs`

The autostart plugin was already registered in Task 2. This task verifies it's configured but disabled by default.

**Step 1: Verify autostart is registered but not enabled**

In `src-tauri/src/lib.rs`, the autostart plugin is already initialized:

```rust
.plugin(tauri_plugin_autostart::init(
    tauri_plugin_autostart::MacosLauncher::LaunchAgent,
    None,
))
```

This registers the plugin but does NOT enable autostart. Autostart is enabled programmatically via the JS API (`enable()` / `disable()`). Since the General settings checkbox is disabled, autostart stays off.

**Step 2: Verify no autostart on app launch**

```bash
npm run tauri dev
```

Check Windows Task Manager → Startup tab. Recap should NOT appear.

**Step 3: No commit needed — already configured.**

---

### Task 13: Final Integration Test and Cleanup

**Files:**
- Modify: `.gitignore`
- Modify: `MANIFEST.md`

**Step 1: Full build test**

```bash
npm run tauri dev
```

Verify end-to-end:
1. App starts minimized to tray ✓
2. Right-click tray → menu appears ✓
3. Open Dashboard → window shows ✓
4. Close window → hides to tray ✓
5. Settings → all sections render ✓
6. Enter fake client credentials → Connect button enables ✓
7. Click Connect → browser opens to OAuth URL ✓
8. Quit via tray → app exits ✓

**Step 2: Update `.gitignore`**

Ensure these entries exist:
```
# Tauri build artifacts
src-tauri/target/
src-tauri/binaries/

# Node
node_modules/
dist/

# PyInstaller
build/
*.spec
```

**Step 3: Regenerate MANIFEST.md**

Update `MANIFEST.md` to reflect the new Tauri + Svelte structure alongside the existing Python pipeline.

**Step 4: Commit**

```bash
git add .gitignore MANIFEST.md
git commit -m "docs: update MANIFEST.md and .gitignore for Tauri app shell"
```

---

### Summary of Tasks

| Task | Description | Key Files |
|------|-------------|-----------|
| 1 | Scaffold Tauri + Svelte + Tailwind | `package.json`, `src-tauri/`, `src/` |
| 2 | System tray with menu | `src-tauri/src/tray.rs` |
| 3 | Deep link handler | `src-tauri/src/deep_link.rs` |
| 4 | Stronghold credential storage | `src-tauri/src/credentials.rs` |
| 5 | OAuth infrastructure | `src-tauri/src/oauth.rs` |
| 6 | Sidecar build + Rust wrapper | `scripts/build-sidecar.py`, `src-tauri/src/sidecar.rs` |
| 7 | Svelte stores + IPC wrappers | `src/lib/stores/`, `src/lib/tauri.ts` |
| 8 | Settings page layout + routing | `src/App.svelte`, `src/routes/` |
| 9 | Platform connection cards | `src/lib/components/ProviderCard.svelte` |
| 10 | Vault/Recording/WhisperX/Todoist/General settings | `src/lib/components/*.svelte` |
| 11 | About/diagnostics | `src/lib/components/AboutSection.svelte` |
| 12 | Autostart (verify disabled) | `src-tauri/src/lib.rs` |
| 13 | Integration test + cleanup | `.gitignore`, `MANIFEST.md` |
