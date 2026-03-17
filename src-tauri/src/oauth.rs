use serde::{Deserialize, Serialize};
use std::io::{Read, Write};
use std::net::TcpListener;

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
pub fn get_provider_config(provider: &str) -> Option<OAuthConfig> {
    match provider {
        "zoom" => Some(OAuthConfig {
            provider: "zoom".into(),
            auth_url: "https://zoom.us/oauth/authorize".into(),
            token_url: "https://zoom.us/oauth/token".into(),
            scopes: "meeting:read recording:read user:read".into(),
            redirect_method: RedirectMethod::DeepLink,
        }),
        "google" => Some(OAuthConfig {
            provider: "google".into(),
            auth_url: "https://accounts.google.com/o/oauth2/v2/auth".into(),
            token_url: "https://oauth2.googleapis.com/token".into(),
            scopes: "https://www.googleapis.com/auth/calendar.readonly".into(),
            redirect_method: RedirectMethod::Localhost,
        }),
        "microsoft" => Some(OAuthConfig {
            provider: "microsoft".into(),
            auth_url: "https://login.microsoftonline.com/common/oauth2/v2.0/authorize".into(),
            token_url: "https://login.microsoftonline.com/common/oauth2/v2.0/token".into(),
            scopes: "OnlineMeetings.Read User.Read".into(),
            redirect_method: RedirectMethod::Localhost,
        }),
        "zoho" => Some(OAuthConfig {
            provider: "zoho".into(),
            auth_url: "https://accounts.zoho.com/oauth/v2/auth".into(),
            token_url: "https://accounts.zoho.com/oauth/v2/token".into(),
            scopes: "ZohoMeeting.manageOrg.READ ZohoCalendar.calendar.READ".into(),
            redirect_method: RedirectMethod::DeepLink,
        }),
        "todoist" => Some(OAuthConfig {
            provider: "todoist".into(),
            auth_url: "https://todoist.com/oauth/authorize".into(),
            token_url: "https://todoist.com/oauth/access_token".into(),
            scopes: "data:read_write".into(),
            redirect_method: RedirectMethod::DeepLink,
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
    format!(
        "{}?client_id={}&redirect_uri={}&response_type=code&scope={}&state={}",
        config.auth_url,
        urlencoding::encode(client_id),
        urlencoding::encode(redirect_uri),
        urlencoding::encode(&config.scopes),
        urlencoding::encode(state),
    )
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

/// Start a temporary localhost HTTP server on a random port to receive
/// the OAuth callback. Returns (port, receiver) where receiver will get
/// the authorization code once the callback arrives.
pub fn start_localhost_server() -> Result<(u16, std::sync::mpsc::Receiver<String>), String> {
    let listener =
        TcpListener::bind("127.0.0.1:0").map_err(|e| format!("Failed to bind: {}", e))?;
    let port = listener
        .local_addr()
        .map_err(|e| format!("Failed to get local addr: {}", e))?
        .port();

    let (tx, rx) = std::sync::mpsc::channel();

    std::thread::spawn(move || {
        // Accept one connection, extract the code, send response, shut down
        if let Ok((mut stream, _)) = listener.accept() {
            let mut buf = [0u8; 4096];
            let n = stream.read(&mut buf).unwrap_or(0);
            let request = String::from_utf8_lossy(&buf[..n]);

            // Parse GET /?code=...&state=... HTTP/1.1
            let code = request
                .lines()
                .next()
                .and_then(|line| {
                    let path = line.split_whitespace().nth(1)?;
                    let query = path.split('?').nth(1)?;
                    url::form_urlencoded::parse(query.as_bytes())
                        .find(|(key, _)| key == "code")
                        .map(|(_, value)| value.to_string())
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
                let _ = tx.send(code);
            }
        }
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
) -> Result<(), String> {
    let config =
        get_provider_config(&provider).ok_or_else(|| format!("Unknown provider: {}", provider))?;

    let state = uuid::Uuid::new_v4().to_string();

    let redirect_uri = match &config.redirect_method {
        RedirectMethod::DeepLink => {
            format!("recap://oauth/{}/callback", provider)
        }
        RedirectMethod::Localhost => {
            let (port, rx) = start_localhost_server()?;
            let redirect = format!("http://127.0.0.1:{}", port);

            // Spawn a task to wait for the code from the localhost server
            let config_clone = config.clone();
            let client_id_clone = client_id.clone();
            let client_secret_clone = client_secret.clone();
            let redirect_clone = redirect.clone();
            let app_clone = app.clone();

            tokio::spawn(async move {
                // Wait for the code with a timeout
                let code = tokio::task::spawn_blocking(move || {
                    rx.recv_timeout(std::time::Duration::from_secs(300))
                })
                .await;

                match code {
                    Ok(Ok(code)) => {
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
                                let _ = app_clone.emit("oauth-tokens", &tokens);
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
    _app: tauri::AppHandle,
    provider: String,
    code: String,
    client_id: String,
    client_secret: String,
) -> Result<TokenResponse, String> {
    let config =
        get_provider_config(&provider).ok_or_else(|| format!("Unknown provider: {}", provider))?;

    let redirect_uri = format!("recap://oauth/{}/callback", provider);

    exchange_code(&config, &client_id, &client_secret, &code, &redirect_uri).await
}
