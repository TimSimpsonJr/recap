use aes_gcm::{
    aead::{Aead, KeyInit},
    Aes256Gcm, Nonce,
};
use rand::RngCore;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;
use tauri::Manager;
use tokio::sync::Mutex;

/// Encrypted credential store backed by a JSON file on disk.
/// Values are encrypted with AES-256-GCM using a key derived from the machine identity.
pub struct SecretStore {
    data: HashMap<String, EncryptedValue>,
    path: PathBuf,
    cipher: Aes256Gcm,
}

#[derive(Clone, Serialize, Deserialize)]
struct EncryptedValue {
    nonce: Vec<u8>,
    ciphertext: Vec<u8>,
}

#[derive(Serialize, Deserialize, Default)]
struct StoreFile {
    entries: HashMap<String, EncryptedValue>,
}

impl SecretStore {
    pub fn new(app_data_dir: &std::path::Path) -> Result<Self, String> {
        let path = app_data_dir.join("secrets.enc");
        let key = derive_key();
        let cipher =
            Aes256Gcm::new_from_slice(&key).map_err(|e| format!("Failed to create cipher: {}", e))?;

        let data = if path.exists() {
            let contents =
                std::fs::read_to_string(&path).map_err(|e| format!("Failed to read secrets: {}", e))?;
            let store: StoreFile =
                serde_json::from_str(&contents).map_err(|e| format!("Failed to parse secrets: {}", e))?;
            store.entries
        } else {
            HashMap::new()
        };

        Ok(Self { data, path, cipher })
    }

    pub fn get(&self, key: &str) -> Option<String> {
        let entry = self.data.get(key)?;
        let nonce = Nonce::from_slice(&entry.nonce);
        let plaintext = self.cipher.decrypt(nonce, entry.ciphertext.as_ref()).ok()?;
        String::from_utf8(plaintext).ok()
    }

    pub fn set(&mut self, key: &str, value: &str) -> Result<(), String> {
        let mut nonce_bytes = [0u8; 12];
        rand::thread_rng().fill_bytes(&mut nonce_bytes);
        let nonce = Nonce::from_slice(&nonce_bytes);

        let ciphertext = self
            .cipher
            .encrypt(nonce, value.as_bytes())
            .map_err(|e| format!("Encryption failed: {}", e))?;

        self.data.insert(
            key.to_string(),
            EncryptedValue {
                nonce: nonce_bytes.to_vec(),
                ciphertext,
            },
        );

        self.save()
    }

    pub fn delete(&mut self, key: &str) -> Result<(), String> {
        self.data.remove(key);
        self.save()
    }

    fn save(&self) -> Result<(), String> {
        let store = StoreFile {
            entries: self.data.clone(),
        };
        let json =
            serde_json::to_string_pretty(&store).map_err(|e| format!("Failed to serialize: {}", e))?;

        // Ensure parent directory exists
        if let Some(parent) = self.path.parent() {
            std::fs::create_dir_all(parent).ok();
        }

        std::fs::write(&self.path, json).map_err(|e| format!("Failed to write secrets: {}", e))
    }
}

/// Derive a 256-bit encryption key from machine identity.
/// Uses computer name + Windows user profile path as entropy.
fn derive_key() -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(b"recap-secret-store-v1");

    if let Ok(name) = std::env::var("COMPUTERNAME") {
        hasher.update(name.as_bytes());
    }
    if let Ok(profile) = std::env::var("USERPROFILE") {
        hasher.update(profile.as_bytes());
    }

    hasher.finalize().into()
}

/// Managed state wrapper for thread-safe access.
pub type SecretStoreState = Arc<Mutex<SecretStore>>;

/// Initialize the secret store during app setup.
pub fn init_secret_store(app: &tauri::App) -> Result<(), String> {
    let app_data_dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("Failed to get app data dir: {}", e))?;
    let store = SecretStore::new(&app_data_dir)?;
    app.manage(Arc::new(Mutex::new(store)));
    Ok(())
}

// --- IPC Commands ---

#[tauri::command]
pub async fn save_secret(
    app: tauri::AppHandle,
    key: String,
    value: String,
) -> Result<(), String> {
    let store = app.state::<SecretStoreState>();
    let mut store = store.lock().await;
    store.set(&key, &value)
}

#[tauri::command]
pub async fn get_secret(
    app: tauri::AppHandle,
    key: String,
) -> Result<Option<String>, String> {
    let store = app.state::<SecretStoreState>();
    let store = store.lock().await;
    Ok(store.get(&key))
}

#[tauri::command]
pub async fn delete_secret(
    app: tauri::AppHandle,
    key: String,
) -> Result<(), String> {
    let store = app.state::<SecretStoreState>();
    let mut store = store.lock().await;
    store.delete(&key)
}

// --- Legacy types kept for compatibility with other modules ---

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

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProviderStatus {
    pub provider: String,
    pub connected: bool,
    pub display_name: Option<String>,
    pub needs_reconnect: bool,
}
