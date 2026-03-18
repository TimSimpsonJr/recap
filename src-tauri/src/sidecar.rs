use tauri_plugin_shell::ShellExt;
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
    metadata_path: Option<String>,
    from_stage: Option<String>,
) -> Result<SidecarResult, String> {
    let mut args = vec![
        "process".to_string(),
        "--config".to_string(),
        config_path,
        recording_path,
    ];

    if let Some(meta) = metadata_path {
        args.push(meta);
    }

    if let Some(stage) = from_stage {
        args.push("--from".to_string());
        args.push(stage);
    }

    let sidecar = app
        .shell()
        .sidecar("recap-pipeline")
        .map_err(|e| format!("Failed to create sidecar command: {}", e))?
        .args(&args);

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
    match app.shell().sidecar("recap-pipeline") {
        Ok(_) => Ok(true),
        Err(_) => Ok(false),
    }
}
