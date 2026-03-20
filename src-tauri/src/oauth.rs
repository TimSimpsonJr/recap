use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::sync::Arc;
use tauri::Manager;
use tokio::sync::Mutex;

/// Managed state holding pending OAuth state parameters keyed by provider.
/// Used to verify the `state` query param on callbacks (CSRF protection).
pub type OAuthStateStore = Arc<Mutex<HashMap<String, String>>>;

pub struct OAuthStateStoreState(pub OAuthStateStore);

impl OAuthStateStoreState {
    pub fn new() -> Self {
        Self(Arc::new(Mutex::new(HashMap::new())))
    }
}

/// How we receive the OAuth callback.
#[derive(Debug, Clone)]
pub enum RedirectMethod {
    /// Use recap://oauth/{provider}/callback deep link
    DeepLink,
    /// Spin up a localhost HTTP server on a random port
    Localhost,
}

/// OAuth configuration for a specific provider.
#[derive(Debug, Clone)]
pub struct OAuthConfig {
    pub provider: String,
    pub auth_url: String,
    pub token_url: String,
    pub scopes: String,
    pub redirect_method: RedirectMethod,
}

/// Token response from the OAuth token endpoint.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TokenResponse {
    pub access_token: String,
    pub token_type: Option<String>,
    pub expires_in: Option<u64>,
    pub refresh_token: Option<String>,
    pub scope: Option<String>,
}

/// Get OAuth config for a given provider name.
/// For Zoho, pass the region (e.g. "com", "eu", "in", "com.au") to select the correct datacenter.
pub fn get_provider_config(provider: &str, zoho_region: Option<&str>) -> Option<OAuthConfig> {
    match provider {
        "zoom" => Some(OAuthConfig {
            provider: "zoom".into(),
            auth_url: "https://zoom.us/oauth/authorize".into(),
            token_url: "https://zoom.us/oauth/token".into(),
            scopes: "meeting:read:meeting recording:read:recording user:read:user".into(),
            redirect_method: RedirectMethod::Localhost,
        }),
        "google" => Some(OAuthConfig {
            provider: "google".into(),
            auth_url: "https://accounts.google.com/o/oauth2/v2/auth".into(),
            token_url: "https://oauth2.googleapis.com/token".into(),
            scopes: "https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/meetings.space.readonly".into(),
            redirect_method: RedirectMethod::Localhost,
        }),
        "microsoft" => Some(OAuthConfig {
            provider: "microsoft".into(),
            auth_url: "https://login.microsoftonline.com/common/oauth2/v2.0/authorize".into(),
            token_url: "https://login.microsoftonline.com/common/oauth2/v2.0/token".into(),
            scopes: "OnlineMeetings.Read User.Read".into(),
            redirect_method: RedirectMethod::Localhost,
        }),
        "zoho" => {
            let region = zoho_region.unwrap_or("com");
            Some(OAuthConfig {
                provider: "zoho".into(),
                auth_url: format!("https://accounts.zoho.{}/oauth/v2/auth", region),
                token_url: format!("https://accounts.zoho.{}/oauth/v2/token", region),
                scopes: "ZohoMeeting.manageOrg.READ ZohoCalendar.calendar.READ ZohoCalendar.event.READ".into(),
                redirect_method: RedirectMethod::Localhost,
            })
        }
        "todoist" => Some(OAuthConfig {
            provider: "todoist".into(),
            auth_url: "https://todoist.com/oauth/authorize".into(),
            token_url: "https://todoist.com/oauth/access_token".into(),
            scopes: "data:read_write".into(),
            redirect_method: RedirectMethod::Localhost,
        }),
        _ => None,
    }
}

/// Build the authorization URL for the given provider config.
pub fn build_auth_url(
    config: &OAuthConfig,
    client_id: &str,
    redirect_uri: &str,
    state: &str,
) -> String {
    let mut url = format!(
        "{}?client_id={}&redirect_uri={}&response_type=code&scope={}&state={}",
        config.auth_url,
        urlencoding::encode(client_id),
        urlencoding::encode(redirect_uri),
        urlencoding::encode(&config.scopes),
        urlencoding::encode(state),
    );

    // Zoho and Google require access_type=offline to return a refresh token.
    // prompt=consent ensures the consent screen is shown (required for re-auth).
    match config.provider.as_str() {
        "zoho" | "google" => {
            url.push_str("&access_type=offline&prompt=consent");
        }
        "microsoft" => {
            url.push_str("&prompt=consent");
        }
        _ => {}
    }

    url
}

/// Exchange an authorization code for tokens.
pub async fn exchange_code(
    config: &OAuthConfig,
    client_id: &str,
    client_secret: &str,
    code: &str,
    redirect_uri: &str,
) -> Result<TokenResponse, String> {
    let client = reqwest::Client::new();
    let params = [
        ("grant_type", "authorization_code"),
        ("code", code),
        ("redirect_uri", redirect_uri),
        ("client_id", client_id),
        ("client_secret", client_secret),
    ];

    let response = client
        .post(&config.token_url)
        .form(&params)
        .send()
        .await
        .map_err(|e| format!("Token exchange request failed: {}", e))?;

    if !response.status().is_success() {
        let status = response.status();
        let body = response
            .text()
            .await
            .unwrap_or_else(|_| "no body".to_string());
        return Err(format!(
            "Token exchange failed with status {}: {}",
            status, body
        ));
    }

    response
        .json::<TokenResponse>()
        .await
        .map_err(|e| format!("Failed to parse token response: {}", e))
}

/// Refresh an expired access token.
pub async fn refresh_token(
    config: &OAuthConfig,
    client_id: &str,
    client_secret: &str,
    refresh_token: &str,
) -> Result<TokenResponse, String> {
    let client = reqwest::Client::new();
    let params = [
        ("grant_type", "refresh_token"),
        ("refresh_token", refresh_token),
        ("client_id", client_id),
        ("client_secret", client_secret),
    ];

    let response = client
        .post(&config.token_url)
        .form(&params)
        .send()
        .await
        .map_err(|e| format!("Token refresh request failed: {}", e))?;

    if !response.status().is_success() {
        let status = response.status();
        let body = response
            .text()
            .await
            .unwrap_or_else(|_| "no body".to_string());
        return Err(format!(
            "Token refresh failed with status {}: {}",
            status, body
        ));
    }

    response
        .json::<TokenResponse>()
        .await
        .map_err(|e| format!("Failed to parse token response: {}", e))
}

/// Fixed port for OAuth localhost callback. Must match the redirect URI
/// registered with each provider (e.g. http://localhost:8399).
const OAUTH_CALLBACK_PORT: u16 = 8399;

/// Start a temporary localhost HTTP server on a fixed port to receive
/// the OAuth callback. Returns (port, receiver) where receiver will get
/// the (code, state) pair once the callback arrives.
///
/// If the port is already in use (e.g. from a previous OAuth flow still in
/// TIME_WAIT), we briefly connect to the old listener to unblock it, then
/// rebind.
pub fn start_localhost_server() -> Result<(u16, std::sync::mpsc::Receiver<(String, String)>), String> {
    let listener = match TcpListener::bind(format!("127.0.0.1:{}", OAUTH_CALLBACK_PORT)) {
        Ok(l) => l,
        Err(_) => {
            // Port is held by a previous listener — poke it to unblock accept()
            let _ = TcpStream::connect(format!("127.0.0.1:{}", OAUTH_CALLBACK_PORT));
            // Brief pause for the old thread to exit
            std::thread::sleep(std::time::Duration::from_millis(100));
            TcpListener::bind(format!("127.0.0.1:{}", OAUTH_CALLBACK_PORT))
                .map_err(|e| format!("Failed to bind port {}: {}", OAUTH_CALLBACK_PORT, e))?
        }
    };

    // Set a timeout so the accept thread doesn't block forever
    listener
        .set_nonblocking(false)
        .ok();
    let _ = listener.set_ttl(60);

    let port = listener
        .local_addr()
        .map_err(|e| format!("Failed to get local addr: {}", e))?
        .port();

    let (tx, rx) = std::sync::mpsc::channel();

    std::thread::spawn(move || {
        // Accept one connection, extract the code, send response, shut down
        // Set a 5 minute timeout so the thread eventually dies
        let _ = listener.set_nonblocking(false);

        if let Ok((mut stream, _)) = listener.accept() {
            let mut buf = [0u8; 4096];
            let n = stream.read(&mut buf).unwrap_or(0);
            let request = String::from_utf8_lossy(&buf[..n]);

            // Parse GET /?code=...&state=... HTTP/1.1
            let (code, state) = request
                .lines()
                .next()
                .map(|line| {
                    let path = line.split_whitespace().nth(1).unwrap_or("");
                    let query = path.split('?').nth(1).unwrap_or("");
                    let params: Vec<(String, String)> = url::form_urlencoded::parse(query.as_bytes())
                        .map(|(k, v)| (k.to_string(), v.to_string()))
                        .collect();
                    let code = params.iter().find(|(k, _)| k == "code").map(|(_, v)| v.clone()).unwrap_or_default();
                    let state = params.iter().find(|(k, _)| k == "state").map(|(_, v)| v.clone()).unwrap_or_default();
                    (code, state)
                })
                .unwrap_or_default();

            let html = "<html><body><h1>Authorization complete</h1><p>You can close this tab.</p></body></html>";
            let response = format!(
                "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                html.len(),
                html
            );
            let _ = stream.write_all(response.as_bytes());
            let _ = stream.flush();

            if !code.is_empty() {
                let _ = tx.send((code, state));
            }
        }
        // listener is dropped here, releasing the port
    });

    Ok((port, rx))
}

/// Tauri command: initiate OAuth flow for a provider.
/// Opens the browser to the authorization URL.
#[tauri::command]
pub async fn start_oauth(
    app: tauri::AppHandle,
    provider: String,
    client_id: String,
    client_secret: String,
    zoho_region: Option<String>,
) -> Result<(), String> {
    let config =
        get_provider_config(&provider, zoho_region.as_deref())
            .ok_or_else(|| format!("Unknown provider: {}", provider))?;

    let state = uuid::Uuid::new_v4().to_string();

    // Store the state for CSRF verification on callback
    {
        let state_store = app.state::<OAuthStateStoreState>();
        let mut store = state_store.0.lock().await;
        store.insert(provider.clone(), state.clone());
    }

    let redirect_uri = match &config.redirect_method {
        RedirectMethod::DeepLink => {
            format!("recap://oauth/{}/callback", provider)
        }
        RedirectMethod::Localhost => {
            let (port, rx) = start_localhost_server()?;
            let redirect = format!("http://localhost:{}", port);

            // Spawn a task to wait for the code from the localhost server
            let config_clone = config.clone();
            let client_id_clone = client_id.clone();
            let client_secret_clone = client_secret.clone();
            let redirect_clone = redirect.clone();
            let app_clone = app.clone();
            let expected_state = state.clone();

            tokio::spawn(async move {
                // Wait for the code with a timeout
                let result = tokio::task::spawn_blocking(move || {
                    rx.recv_timeout(std::time::Duration::from_secs(300))
                })
                .await;

                match result {
                    Ok(Ok((code, callback_state))) => {
                        // Verify CSRF state parameter
                        if callback_state != expected_state {
                            log::error!(
                                "OAuth state mismatch for {}: expected {}, got {}",
                                config_clone.provider, expected_state, callback_state
                            );
                            // Clean up stored state
                            let state_store = app_clone.state::<OAuthStateStoreState>();
                            let mut s = state_store.0.lock().await;
                            s.remove(&config_clone.provider);
                            return;
                        }

                        // Clean up stored state
                        {
                            let state_store = app_clone.state::<OAuthStateStoreState>();
                            let mut s = state_store.0.lock().await;
                            s.remove(&config_clone.provider);
                        }

                        match exchange_code(
                            &config_clone,
                            &client_id_clone,
                            &client_secret_clone,
                            &code,
                            &redirect_clone,
                        )
                        .await
                        {
                            Ok(tokens) => {
                                use tauri::Emitter;
                                let payload = serde_json::json!({
                                    "provider": config_clone.provider,
                                    "access_token": tokens.access_token,
                                    "refresh_token": tokens.refresh_token,
                                    "expires_in": tokens.expires_in,
                                });
                                let _ = app_clone.emit("oauth-tokens", payload);
                                log::info!(
                                    "OAuth tokens received for {}",
                                    config_clone.provider
                                );
                            }
                            Err(e) => {
                                log::error!("Token exchange failed: {}", e);
                            }
                        }
                    }
                    _ => {
                        log::error!("Timed out waiting for OAuth callback");
                        // Clean up stored state on timeout
                        let state_store = app_clone.state::<OAuthStateStoreState>();
                        let mut s = state_store.0.lock().await;
                        s.remove(&config_clone.provider);
                    }
                }
            });

            redirect
        }
    };

    let auth_url = build_auth_url(&config, &client_id, &redirect_uri, &state);

    open::that(&auth_url).map_err(|e| format!("Failed to open browser: {}", e))?;

    Ok(())
}

/// Tauri command: exchange an OAuth authorization code for tokens.
/// Called from the deep link handler when a callback is received.
#[tauri::command]
pub async fn exchange_oauth_code(
    app: tauri::AppHandle,
    provider: String,
    code: String,
    state: String,
    client_id: String,
    client_secret: String,
    zoho_region: Option<String>,
) -> Result<TokenResponse, String> {
    // Verify CSRF state parameter
    {
        let state_store = app.state::<OAuthStateStoreState>();
        let mut store = state_store.0.lock().await;
        let expected = store
            .remove(&provider)
            .ok_or_else(|| format!("No pending OAuth state for provider {}", provider))?;
        if state != expected {
            return Err(format!(
                "OAuth state mismatch for {}: possible CSRF attack",
                provider
            ));
        }
    }

    let config =
        get_provider_config(&provider, zoho_region.as_deref())
            .ok_or_else(|| format!("Unknown provider: {}", provider))?;

    let redirect_uri = format!("recap://oauth/{}/callback", provider);

    exchange_code(&config, &client_id, &client_secret, &code, &redirect_uri).await
}
