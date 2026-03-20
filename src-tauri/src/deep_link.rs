use serde::Serialize;
use tauri::Emitter;
use tauri_plugin_deep_link::DeepLinkExt;

/// Payload emitted to the frontend when an OAuth callback deep link arrives.
#[derive(Debug, Clone, Serialize)]
pub struct OAuthCallbackPayload {
    pub provider: String,
    pub code: String,
    pub state: String,
}

/// Register deep link handler and process any URLs the app was opened with.
pub fn setup_deep_links(app: &tauri::AppHandle) -> tauri::Result<()> {
    // Register the recap:// protocol at runtime (needed for dev on Windows)
    #[cfg(desktop)]
    app.deep_link()
        .register("recap")
        .map_err(|e| tauri::Error::Anyhow(e.into()))?;

    // Handle deep links received while app is running
    let handle = app.clone();
    app.deep_link().on_open_url(move |event| {
        for url in event.urls() {
            handle_deep_link_url(&handle, url.as_str());
        }
    });

    // Check if app was launched via deep link
    if let Ok(Some(urls)) = app.deep_link().get_current() {
        for url in urls {
            handle_deep_link_url(app, url.as_str());
        }
    }

    Ok(())
}

fn handle_deep_link_url(app: &tauri::AppHandle, url: &str) {
    // Parse recap://oauth/{provider}/callback?code=...
    if let Ok(parsed) = url::Url::parse(url) {
        match parsed.host_str() {
            Some("oauth") => {
                let path_segments: Vec<&str> = parsed
                    .path_segments()
                    .map(|s| s.collect())
                    .unwrap_or_default();
                if path_segments.len() >= 2 && path_segments[1] == "callback" {
                    let provider = path_segments[0].to_string();
                    let code = parsed
                        .query_pairs()
                        .find(|(key, _)| key == "code")
                        .map(|(_, value)| value.to_string());
                    let state = parsed
                        .query_pairs()
                        .find(|(key, _)| key == "state")
                        .map(|(_, value)| value.to_string())
                        .unwrap_or_default();
                    if let Some(code) = code {
                        log::info!("OAuth callback for {}: code received", provider);
                        let payload = OAuthCallbackPayload {
                            provider,
                            code,
                            state,
                        };
                        if let Err(e) = app.emit("oauth-callback", &payload) {
                            log::error!("Failed to emit oauth-callback event: {}", e);
                        }
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
