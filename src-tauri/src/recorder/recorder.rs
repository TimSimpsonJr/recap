use std::path::PathBuf;
use std::process::Command;
use std::sync::Arc;
use std::time::Instant;

use serde_json::json;
use tauri::{AppHandle, Emitter, Runtime};
use tauri_plugin_notification::NotificationExt;
use tokio::sync::{mpsc, Mutex};

use super::capture::{AudioCapture, CaptureError, VideoCapture};
use super::monitor::{self, MonitorEvent};
use super::types::{
    DetectionAction, PipelineStatus, RecorderState, RecordingConfig, RecordingSession,
    TimeoutAction,
};
use super::zoom;

/// Shared recorder handle stored in Tauri managed state.
pub struct RecorderHandle<R: Runtime> {
    inner: Arc<Mutex<RecorderInner<R>>>,
}

impl<R: Runtime> RecorderHandle<R> {
    pub fn new(app: AppHandle<R>) -> Self {
        Self {
            inner: Arc::new(Mutex::new(RecorderInner {
                app,
                state: RecorderState::Idle,
                config: RecordingConfig::default(),
                session: None,
                remote_audio: None,
                local_audio: None,
                video: None,
                monitor_stop: None,
                monitor_handle: None,
            })),
        }
    }

    pub fn handle(&self) -> &Arc<Mutex<RecorderInner<R>>> {
        &self.inner
    }
}

pub struct RecorderInner<R: Runtime> {
    app: AppHandle<R>,
    state: RecorderState,
    config: RecordingConfig,
    session: Option<RecordingSession>,
    remote_audio: Option<AudioCapture>,
    local_audio: Option<AudioCapture>,
    video: Option<VideoCapture>,
    monitor_stop: Option<Arc<std::sync::atomic::AtomicBool>>,
    monitor_handle: Option<std::thread::JoinHandle<()>>,
}

impl<R: Runtime> RecorderInner<R> {
    /// Get the current recorder state.
    pub fn state(&self) -> RecorderState {
        self.state.clone()
    }

    /// Update config from settings.
    pub fn set_config(&mut self, config: RecordingConfig) {
        self.config = config;
    }

    /// Transition state and emit event to frontend.
    fn set_state(&mut self, new_state: RecorderState) {
        self.state = new_state.clone();
        let _ = self.app.emit("recorder-state-changed", new_state);
    }

    /// Send a desktop notification.
    fn notify(&self, title: &str, body: &str) {
        let _ = self
            .app
            .notification()
            .builder()
            .title(title)
            .body(body)
            .show();
    }

    /// Start monitoring for meeting audio sessions.
    pub fn start_monitor(&mut self, tx: mpsc::Sender<MonitorEvent>) {
        let (handle, stop) = monitor::start_monitoring(tx);
        self.monitor_stop = Some(stop);
        self.monitor_handle = Some(handle);
    }

    /// Stop the monitor and join the thread.
    pub fn stop_monitor(&mut self) {
        if let Some(stop) = self.monitor_stop.take() {
            monitor::stop_monitoring(&stop);
        }
        if let Some(handle) = self.monitor_handle.take() {
            let _ = handle.join();
        }
    }

    /// Handle a meeting detection event.
    pub fn on_meeting_detected(&mut self, process_name: String, pid: u32) {
        if self.state != RecorderState::Idle {
            return; // Already handling a session.
        }

        match self.config.detection_action {
            DetectionAction::AlwaysRecord => {
                self.set_state(RecorderState::Detected {
                    process_name: process_name.clone(),
                    pid,
                });
                let _ = self.start_capture(process_name, pid);
            }
            DetectionAction::Ask => {
                self.set_state(RecorderState::Detected {
                    process_name: process_name.clone(),
                    pid,
                });
                self.notify(
                    "Meeting Detected",
                    &format!("{} is active. Open Recap to start recording.", process_name),
                );
            }
            DetectionAction::NeverRecord => {
                self.set_state(RecorderState::Declined);
            }
        }
    }

    /// Handle meeting ended event.
    pub fn on_meeting_ended(&mut self, _pid: u32) {
        if self.state == RecorderState::Recording {
            let _ = self.stop_capture();
        } else if matches!(self.state, RecorderState::Detected { .. }) {
            self.set_state(RecorderState::Idle);
        }
    }

    /// Handle notification timeout.
    pub fn on_timeout(&mut self) {
        if let RecorderState::Detected { ref process_name, pid } = self.state.clone() {
            match self.config.timeout_action {
                TimeoutAction::Record => {
                    let _ = self.start_capture(process_name.clone(), pid);
                }
                TimeoutAction::Skip => {
                    self.set_state(RecorderState::Declined);
                }
            }
        }
    }

    /// Start capturing audio and video for a detected meeting process.
    pub fn start_capture(
        &mut self,
        process_name: String,
        pid: u32,
    ) -> Result<(), String> {
        // Create working directory for this recording.
        let timestamp = chrono::Utc::now().format("%Y%m%d-%H%M%S").to_string();
        let working_dir = std::env::temp_dir()
            .join("recap-recordings")
            .join(&timestamp);
        std::fs::create_dir_all(&working_dir)
            .map_err(|e| format!("Failed to create working dir: {}", e))?;

        let remote_path = working_dir.join("remote.wav");
        let local_path = working_dir.join("local.wav");
        let video_path = working_dir.join("video.mp4");

        // Start remote audio capture (loopback).
        let remote_audio = AudioCapture::start_remote(pid, remote_path.clone())
            .map_err(|e| format!("Remote audio capture failed: {}", e))?;

        // Start local audio capture (mic) — non-fatal if no mic.
        let local_audio = match AudioCapture::start_local(local_path.clone()) {
            Ok(capture) => Some(capture),
            Err(CaptureError::NoMicrophoneDevice(msg)) => {
                log::warn!("No microphone available: {}", msg);
                None
            }
            Err(e) => {
                log::warn!("Local audio capture failed: {}", e);
                None
            }
        };

        // Start video capture.
        let video = match VideoCapture::start(pid, video_path.clone()) {
            Ok(capture) => Some(capture),
            Err(e) => {
                log::warn!("Video capture failed: {}", e);
                None
            }
        };

        self.session = Some(RecordingSession {
            process_name,
            pid,
            started_at: Instant::now(),
            working_dir,
            remote_audio_path: remote_path,
            local_audio_path: local_path,
            video_path,
        });

        self.remote_audio = Some(remote_audio);
        self.local_audio = local_audio;
        self.video = video;

        self.set_state(RecorderState::Recording);
        self.notify("Recording Started", "Capturing audio and video from your meeting.");
        Ok(())
    }

    /// Stop all capture streams and begin post-processing.
    pub fn stop_capture(&mut self) -> Result<Option<RecordingSession>, String> {
        // Stop all capture streams.
        if let Some(mut audio) = self.remote_audio.take() {
            let _ = audio.stop();
        }
        if let Some(mut audio) = self.local_audio.take() {
            let _ = audio.stop();
        }
        if let Some(mut video) = self.video.take() {
            let _ = video.stop();
        }

        let session = self.session.take();
        self.set_state(RecorderState::Processing);

        Ok(session)
    }

    /// Cancel recording — stop capture, delete temp files, return to idle.
    pub fn cancel_recording(&mut self) {
        if let Some(mut audio) = self.remote_audio.take() {
            let _ = audio.stop();
        }
        if let Some(mut audio) = self.local_audio.take() {
            let _ = audio.stop();
        }
        if let Some(mut video) = self.video.take() {
            let _ = video.stop();
        }

        if let Some(session) = self.session.take() {
            let _ = std::fs::remove_dir_all(&session.working_dir);
        }

        self.set_state(RecorderState::Idle);
    }

    /// Return to idle state (after processing completes or on decline).
    pub fn return_to_idle(&mut self) {
        self.set_state(RecorderState::Idle);
    }
}

/// Merge captured audio and video into a single MP4 using ffmpeg.
pub fn merge_recording(session: &RecordingSession) -> Result<PathBuf, String> {
    let output_path = session.working_dir.join("recording.mp4");

    let has_video = session.video_path.exists()
        && std::fs::metadata(&session.video_path)
            .map(|m| m.len() > 0)
            .unwrap_or(false);
    let has_remote = session.remote_audio_path.exists();
    let has_local = session.local_audio_path.exists()
        && std::fs::metadata(&session.local_audio_path)
            .map(|m| m.len() > 44) // WAV header is 44 bytes
            .unwrap_or(false);

    let mut cmd = Command::new("ffmpeg");
    cmd.arg("-y"); // Overwrite output.

    if has_video {
        cmd.args(["-i", session.video_path.to_str().unwrap()]);
    }
    if has_remote {
        cmd.args(["-i", session.remote_audio_path.to_str().unwrap()]);
    }
    if has_local {
        cmd.args(["-i", session.local_audio_path.to_str().unwrap()]);
    }

    // Build filter and mapping based on available streams.
    match (has_video, has_remote, has_local) {
        (true, true, true) => {
            cmd.args([
                "-filter_complex", "[1:a][2:a]amerge=inputs=2[a]",
                "-map", "0:v",
                "-map", "[a]",
                "-c:v", "copy",
                "-c:a", "aac",
            ]);
        }
        (true, true, false) => {
            cmd.args([
                "-map", "0:v",
                "-map", "1:a",
                "-c:v", "copy",
                "-c:a", "aac",
            ]);
        }
        (true, false, true) => {
            cmd.args([
                "-map", "0:v",
                "-map", "1:a",
                "-c:v", "copy",
                "-c:a", "aac",
            ]);
        }
        (false, true, true) => {
            cmd.args([
                "-filter_complex", "[0:a][1:a]amerge=inputs=2[a]",
                "-map", "[a]",
                "-c:a", "aac",
            ]);
        }
        (false, true, false) | (false, false, true) => {
            cmd.args(["-c:a", "aac"]);
        }
        (true, false, false) => {
            cmd.args(["-c:v", "copy"]);
        }
        (false, false, false) => {
            return Err("No capture streams available to merge".to_string());
        }
    }

    cmd.arg(output_path.to_str().unwrap());

    let output = cmd
        .output()
        .map_err(|e| format!("Failed to run ffmpeg: {}", e))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("ffmpeg merge failed: {}", stderr));
    }

    // Clean up temp files after successful merge.
    let _ = std::fs::remove_file(&session.remote_audio_path);
    let _ = std::fs::remove_file(&session.local_audio_path);
    if has_video {
        let _ = std::fs::remove_file(&session.video_path);
    }

    Ok(output_path)
}

/// Write meeting metadata JSON file.
pub fn write_meeting_json(
    working_dir: &PathBuf,
    meeting_info: Option<zoom::ZoomMeetingInfo>,
) -> Result<PathBuf, String> {
    let metadata = match meeting_info {
        Some(info) => json!({
            "title": info.title,
            "date": chrono::Utc::now().format("%Y-%m-%d").to_string(),
            "participants": info.participants,
            "user_email": info.user_email,
            "user_name": info.user_name,
            "platform": "zoom"
        }),
        None => zoom::fallback_metadata(),
    };

    let path = working_dir.join("meeting.json");
    std::fs::write(
        &path,
        serde_json::to_string_pretty(&metadata)
            .map_err(|e| format!("Failed to serialize metadata: {}", e))?,
    )
    .map_err(|e| format!("Failed to write meeting.json: {}", e))?;

    Ok(path)
}

/// Write initial pipeline status.json with all stages pending.
pub fn write_initial_status(working_dir: &PathBuf) -> Result<(), String> {
    let status = PipelineStatus::default();
    let path = working_dir.join("status.json");
    std::fs::write(
        &path,
        serde_json::to_string_pretty(&status)
            .map_err(|e| format!("Failed to serialize status: {}", e))?,
    )
    .map_err(|e| format!("Failed to write status.json: {}", e))
}

// ── IPC Commands ─────────────────────────────────────────────────────────────

#[tauri::command]
pub async fn get_recorder_state(
    state: tauri::State<'_, RecorderHandle<tauri::Wry>>,
) -> Result<RecorderState, String> {
    let inner = state.handle().lock().await;
    Ok(inner.state())
}

#[tauri::command]
pub async fn start_recording(
    state: tauri::State<'_, RecorderHandle<tauri::Wry>>,
) -> Result<(), String> {
    let mut inner = state.handle().lock().await;

    // If we're in Detected state, start capture for the detected process.
    if let RecorderState::Detected { ref process_name, pid } = inner.state().clone() {
        return inner.start_capture(process_name.clone(), pid);
    }

    // If idle, scan for known meeting processes.
    if inner.state() == RecorderState::Idle {
        // For now, return an error — the monitor should detect processes.
        return Err("No meeting detected. Start a Zoom or Teams meeting first.".to_string());
    }

    Err(format!(
        "Cannot start recording in state: {:?}",
        inner.state()
    ))
}

#[tauri::command]
pub async fn stop_recording(
    app: tauri::AppHandle,
    state: tauri::State<'_, RecorderHandle<tauri::Wry>>,
) -> Result<(), String> {
    let mut inner = state.handle().lock().await;

    match inner.state() {
        RecorderState::Recording => {
            // Stop capture and process the recording (merge, metadata, pipeline)
            if let Some(session) = inner.stop_capture()? {
                inner.set_state(RecorderState::Processing);
                let working_dir = session.working_dir.clone();

                // Merge audio/video into final MP4
                let merged = merge_recording(&session)?;

                // Write meeting metadata JSON
                let metadata_path = write_meeting_json(&working_dir, None)?;

                // Write initial pipeline status
                let _ = write_initial_status(&working_dir);

                inner.notify("Processing Recording", "Merging audio/video and running pipeline...");
                inner.return_to_idle();

                // Trigger pipeline sidecar asynchronously
                let config_path = working_dir.join("config.json");
                let merged_str = merged.to_string_lossy().to_string();
                let meta_str = metadata_path.to_string_lossy().to_string();
                let config_str = config_path.to_string_lossy().to_string();

                let app_clone = app.clone();
                tauri::async_runtime::spawn(async move {
                    match crate::sidecar::run_pipeline(
                        app.clone(),
                        config_str,
                        merged_str,
                        Some(meta_str),
                        None,
                    )
                    .await
                    {
                        Ok(result) if result.success => {
                            let _ = app_clone
                                .notification()
                                .builder()
                                .title("Meeting Note Ready")
                                .body("Your meeting has been processed. Check your vault.")
                                .show();
                        }
                        Ok(result) => {
                            let _ = app_clone
                                .notification()
                                .builder()
                                .title("Pipeline Failed")
                                .body(&format!("Processing error. Check logs for details."))
                                .show();
                            log::error!("Pipeline failed: {}", result.stderr);
                        }
                        Err(e) => {
                            let _ = app_clone
                                .notification()
                                .builder()
                                .title("Pipeline Error")
                                .body("Failed to run processing pipeline.")
                                .show();
                            log::error!("Pipeline error: {}", e);
                        }
                    }
                });
            }
            Ok(())
        }
        _ => Err(format!(
            "Cannot stop recording in state: {:?}",
            inner.state()
        )),
    }
}

/// Cancel recording: stop capture, delete temp files, return to idle.
#[tauri::command]
pub async fn cancel_recording(
    state: tauri::State<'_, RecorderHandle<tauri::Wry>>,
) -> Result<(), String> {
    let mut inner = state.handle().lock().await;

    match inner.state() {
        RecorderState::Recording => {
            inner.cancel_recording();
            Ok(())
        }
        _ => Err(format!(
            "Cannot cancel recording in state: {:?}",
            inner.state()
        )),
    }
}

#[tauri::command]
pub async fn retry_processing(
    app: tauri::AppHandle,
    _state: tauri::State<'_, RecorderHandle<tauri::Wry>>,
    recording_dir: String,
    from_stage: Option<String>,
) -> Result<(), String> {
    // Find the merged file and metadata in the recording dir
    let dir = std::path::PathBuf::from(&recording_dir);
    let merged = dir.join("recording.mp4");
    let metadata = dir.join("meeting.json");
    let config = dir.join("config.json");

    if !merged.exists() {
        return Err(format!("Recording not found: {}", merged.display()));
    }

    let merged_str = merged.to_string_lossy().to_string();
    let config_str = config.to_string_lossy().to_string();
    let meta_str = if metadata.exists() {
        Some(metadata.to_string_lossy().to_string())
    } else {
        None
    };

    crate::sidecar::run_pipeline(app, config_str, merged_str, meta_str, from_stage)
        .await
        .map(|_| ())
}
