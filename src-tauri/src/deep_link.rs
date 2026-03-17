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
                let path_segments: Vec<&str> = parsed
                    .path_segments()
                    .map(|s| s.collect())
                    .unwrap_or_default();
                if path_segments.len() >= 2 && path_segments[1] == "callback" {
                    let provider = path_segments[0];
                    let code = parsed
                        .query_pairs()
                        .find(|(key, _)| key == "code")
                        .map(|(_, value)| value.to_string());
                    if let Some(code) = code {
                        log::info!("OAuth callback for {}: code received", provider);
                        // TODO: pass to oauth module for token exchange
                        let _ = code;
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
