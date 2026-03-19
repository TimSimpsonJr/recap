use serde::Serialize;
use std::collections::HashMap;
use std::path::PathBuf;
use tauri_plugin_store::StoreExt;

/// Top-level pipeline config that serializes to config.yaml.
#[derive(Debug, Serialize)]
struct PipelineConfig {
    vault_path: String,
    recordings_path: String,
    frames_path: String,
    user_name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    whisperx: Option<WhisperxConfig>,
    #[serde(skip_serializing_if = "Option::is_none")]
    claude: Option<ClaudeConfig>,
    #[serde(skip_serializing_if = "Option::is_none")]
    todoist: Option<TodoistConfig>,
}

#[derive(Debug, Serialize)]
struct WhisperxConfig {
    #[serde(skip_serializing_if = "Option::is_none")]
    model: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    device: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    compute_type: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    language: Option<String>,
}

#[derive(Debug, Serialize)]
struct ClaudeConfig {
    #[serde(skip_serializing_if = "Option::is_none")]
    command: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    model: Option<String>,
}

#[derive(Debug, Serialize)]
struct TodoistConfig {
    #[serde(skip_serializing_if = "Option::is_none")]
    default_project: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    labels: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    project_map: Option<HashMap<String, String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    project_grouping: Option<String>,
}

/// Helper to read a string from the settings store.
fn get_string(store: &tauri_plugin_store::Store<tauri::Wry>, key: &str) -> Option<String> {
    store
        .get(key)
        .and_then(|v| v.as_str().map(|s| s.to_string()))
}

/// Helper to read a string array from the settings store.
fn get_string_array(store: &tauri_plugin_store::Store<tauri::Wry>, key: &str) -> Option<Vec<String>> {
    store.get(key).and_then(|v| {
        v.as_array().map(|arr| {
            arr.iter()
                .filter_map(|item| item.as_str().map(|s| s.to_string()))
                .collect()
        })
    })
}

/// Helper to read a string→string map from the settings store.
fn get_string_map(
    store: &tauri_plugin_store::Store<tauri::Wry>,
    key: &str,
) -> Option<HashMap<String, String>> {
    store.get(key).and_then(|v| {
        v.as_object().map(|obj| {
            obj.iter()
                .filter_map(|(k, v)| v.as_str().map(|s| (k.clone(), s.to_string())))
                .collect()
        })
    })
}

/// Tauri command: generate config.yaml from the app settings store.
///
/// Reads settings from `settings.json` (Tauri plugin-store) and writes
/// a YAML config file that the Python pipeline can consume.
/// Returns the absolute path to the generated config.yaml.
#[tauri::command]
pub async fn generate_pipeline_config(app: tauri::AppHandle) -> Result<String, String> {
    let store = app
        .store("settings.json")
        .map_err(|e| format!("Failed to open settings store: {}", e))?;

    let vault_path = get_string(&store, "vaultPath")
        .ok_or_else(|| "Setting 'vaultPath' is required but not set".to_string())?;
    let recordings_path = get_string(&store, "recordingsFolder")
        .ok_or_else(|| "Setting 'recordingsFolder' is required but not set".to_string())?;
    let user_name = get_string(&store, "userName")
        .ok_or_else(|| "Setting 'userName' is required but not set".to_string())?;

    let frames_path = format!("{}/frames", recordings_path);

    // Build WhisperX config (include section only if any field is set)
    let whisperx = {
        let model = get_string(&store, "whisperxModel");
        let device = get_string(&store, "whisperxDevice");
        let compute_type = get_string(&store, "whisperxComputeType");
        let language = get_string(&store, "whisperxLanguage");
        if model.is_some() || device.is_some() || compute_type.is_some() || language.is_some() {
            Some(WhisperxConfig {
                model,
                device,
                compute_type,
                language,
            })
        } else {
            None
        }
    };

    // Build Claude config
    let claude = {
        let command = get_string(&store, "claudeCommand");
        let model = get_string(&store, "claudeModel");
        if command.is_some() || model.is_some() {
            Some(ClaudeConfig { command, model })
        } else {
            None
        }
    };

    // Build Todoist config
    let todoist = {
        let default_project = get_string(&store, "todoistProject");
        let labels = get_string_array(&store, "todoistLabels");
        let project_map = get_string_map(&store, "todoistProjectMap");
        let project_grouping = get_string(&store, "todoistProjectGrouping");
        if default_project.is_some() || labels.is_some() || project_map.is_some() || project_grouping.is_some() {
            Some(TodoistConfig {
                default_project,
                labels,
                project_map,
                project_grouping,
            })
        } else {
            None
        }
    };

    let config = PipelineConfig {
        vault_path,
        recordings_path: recordings_path.clone(),
        frames_path,
        user_name,
        whisperx,
        claude,
        todoist,
    };

    let yaml =
        serde_yaml::to_string(&config).map_err(|e| format!("Failed to serialize config: {}", e))?;

    let config_path = PathBuf::from(&recordings_path).join("config.yaml");

    // Ensure the recordings directory exists
    if let Some(parent) = config_path.parent() {
        std::fs::create_dir_all(parent)
            .map_err(|e| format!("Failed to create recordings directory: {}", e))?;
    }

    std::fs::write(&config_path, &yaml)
        .map_err(|e| format!("Failed to write config.yaml: {}", e))?;

    Ok(config_path.to_string_lossy().to_string())
}

/// Tauri command: check whether a path resides on an SSD or HDD.
///
/// Uses PowerShell to query the physical disk media type for the drive
/// containing the given path. Returns "SSD", "HDD", or "Unknown".
#[tauri::command]
pub async fn check_drive_type(path: String) -> Result<String, String> {
    let drive_letter = path
        .chars()
        .next()
        .ok_or_else(|| "Path is empty".to_string())?;

    if !drive_letter.is_ascii_alphabetic() {
        return Err(format!("Invalid drive letter: {}", drive_letter));
    }

    let drive_letter = drive_letter.to_ascii_uppercase();

    let output = std::process::Command::new("powershell")
        .args([
            "-NoProfile",
            "-Command",
            &format!(
                "Get-PhysicalDisk | Where-Object {{ (Get-Partition -DiskNumber $_.DeviceId -ErrorAction SilentlyContinue | Get-Volume -ErrorAction SilentlyContinue).DriveLetter -eq '{}' }} | Select-Object -ExpandProperty MediaType",
                drive_letter
            ),
        ])
        .output()
        .map_err(|e| format!("Failed to run PowerShell: {}", e))?;

    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();

    if stdout.contains("SSD") || stdout.contains("Solid State") {
        Ok("SSD".to_string())
    } else if stdout.contains("HDD") || stdout.contains("Hard Disk") || stdout.contains("Unspecified") {
        // "Unspecified" is often returned for spinning disks on some systems
        Ok("HDD".to_string())
    } else if stdout.is_empty() {
        Ok("Unknown".to_string())
    } else {
        Ok(stdout)
    }
}
