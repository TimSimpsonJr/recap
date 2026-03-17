use serde::{Deserialize, Serialize};

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
#[tauri::command]
pub async fn store_credential(
    _app: tauri::AppHandle,
    _key: String,
    _value: String,
) -> Result<(), String> {
    // Frontend calls Stronghold directly via @tauri-apps/plugin-stronghold
    // This is a pass-through placeholder for Rust-side credential needs
    Ok(())
}

/// Tauri command: get provider connection status.
#[tauri::command]
pub async fn get_provider_status(
    _app: tauri::AppHandle,
    _provider: String,
) -> Result<ProviderStatus, String> {
    Ok(ProviderStatus {
        provider: _provider,
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
