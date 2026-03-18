use std::process::Command;

#[tauri::command]
pub async fn check_nvenc() -> Result<String, String> {
    let output = Command::new("ffmpeg")
        .args(["-hide_banner", "-encoders"])
        .output()
        .map_err(|_| "ffmpeg not found".to_string())?;

    let stdout = String::from_utf8_lossy(&output.stdout);
    if stdout.contains("hevc_nvenc") {
        Ok("Available".to_string())
    } else {
        Ok("Not available — software encoding will be used".to_string())
    }
}

#[tauri::command]
pub async fn check_ffmpeg() -> Result<bool, String> {
    match Command::new("ffmpeg").arg("-version").output() {
        Ok(output) => Ok(output.status.success()),
        Err(_) => Ok(false),
    }
}
