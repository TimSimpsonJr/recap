use std::path::PathBuf;
use std::process::Command;
use std::sync::Arc;
use std::time::Instant;

use serde_json::json;
use tauri::{AppHandle, Emitter, Manager, Runtime};
use tauri_plugin_notification::NotificationExt;
use tokio::sync::{mpsc, Mutex};

use super::capture::{AudioCapture, CaptureError, VideoCapture};
use super::monitor::{self, MonitorEvent};
use super::share_detect;
use super::types::{
    CaptureSource, DetectionAction, MeetingMetadata, MeetingPlatform, Participant, PipelineStatus,
    RecorderState, RecordingConfig, RecordingSession, TimeoutAction,
};
use crate::calendar::{self, CalendarEvent};

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
                share_monitor_stop: None,
                share_monitor_handle: None,
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
    share_monitor_stop: Option<Arc<std::sync::atomic::AtomicBool>>,
    share_monitor_handle: Option<std::thread::JoinHandle<()>>,
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

    /// Arm the recorder for auto-record from a calendar event.
    /// When armed, meeting detection will skip the notification prompt and
    /// start recording immediately.
    pub fn arm_for_event(&mut self, event_title: String, expected_platform: Option<MeetingPlatform>) {
        if self.state == RecorderState::Idle {
            self.set_state(RecorderState::Armed {
                event_title: event_title.clone(),
                expected_platform,
            });
            self.notify("Recap Armed", &format!("Ready to record: {}", event_title));
        }
    }

    /// Disarm the recorder, returning to Idle if currently Armed.
    pub fn disarm(&mut self) {
        if matches!(self.state, RecorderState::Armed { .. }) {
            self.set_state(RecorderState::Idle);
        }
    }

    /// Handle a meeting detection event.
    pub fn on_meeting_detected(&mut self, process_name: String, pid: u32) {
        // When Armed, skip the notification and start recording immediately
        if matches!(self.state, RecorderState::Armed { .. }) {
            log::info!("Armed auto-record: starting capture for {} (PID {})", process_name, pid);
            self.set_state(RecorderState::Detected {
                process_name: process_name.clone(),
                pid,
            });
            let _ = self.start_capture(process_name, pid);
            return;
        }

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

    /// Handle a browser-based meeting detection from the extension.
    pub fn on_browser_meeting_detected(
        &mut self,
        url: String,
        title: String,
        platform: MeetingPlatform,
        _tab_id: Option<u32>,
    ) {
        // Allow Armed state to proceed (auto-record)
        if self.state != RecorderState::Idle && !matches!(self.state, RecorderState::Armed { .. }) {
            log::info!(
                "Browser meeting detected but already in state {:?}, ignoring",
                self.state
            );
            return;
        }

        // Find a browser PID from WASAPI audio sessions.
        let browser_pid = find_browser_audio_pid();
        match browser_pid {
            Some(pid) => {
                log::info!(
                    "Browser meeting detected: {} ({}) — browser PID {}",
                    title,
                    url,
                    pid
                );
                let process_name = format!("{:?} (browser)", platform);
                self.on_meeting_detected(process_name, pid);
            }
            None => {
                log::warn!(
                    "Browser meeting detected ({}) but no browser audio session found",
                    url
                );
            }
        }
    }

    /// Handle a browser meeting ended event.
    pub fn on_browser_meeting_ended(&mut self, _tab_id: Option<u32>) {
        // Only act if we have a session with a browser-based platform.
        if let Some(ref session) = self.session {
            match session.platform {
                MeetingPlatform::GoogleMeet | MeetingPlatform::ZohoMeet => {}
                _ => return,
            }
        } else {
            return;
        }

        if self.state == RecorderState::Recording {
            log::info!("Browser meeting ended, stopping recording");
            let _ = self.stop_capture();
        } else if matches!(self.state, RecorderState::Detected { .. }) {
            self.set_state(RecorderState::Idle);
        }
    }

    /// Handle screen sharing started — switch video to display capture.
    pub fn on_sharing_started(&mut self) {
        if self.state != RecorderState::Recording {
            return;
        }
        if let Some(ref mut video) = self.video {
            let target = CaptureSource::Display {
                monitor_index: self.config.screen_share_monitor,
            };
            match video.switch_source(target) {
                Ok(()) => log::info!(
                    "Switched to display capture (monitor {})",
                    self.config.screen_share_monitor
                ),
                Err(e) => log::warn!("Failed to switch to display capture: {}", e),
            }
        }
    }

    /// Handle screen sharing stopped — switch video back to window capture.
    pub fn on_sharing_stopped(&mut self) {
        if self.state != RecorderState::Recording {
            return;
        }
        if let Some(ref session) = self.session {
            let pid = session.pid;
            if let Some(ref mut video) = self.video {
                let target = CaptureSource::Window { pid };
                match video.switch_source(target) {
                    Ok(()) => log::info!("Switched back to window capture (PID {})", pid),
                    Err(e) => log::warn!("Failed to switch back to window capture: {}", e),
                }
            }
        }
    }

    /// Start the share monitor for desktop meeting apps (Zoom/Teams).
    pub fn start_share_monitor(&mut self, tx: mpsc::Sender<MonitorEvent>) {
        if let Some(ref session) = self.session {
            if matches!(
                session.platform,
                MeetingPlatform::Zoom | MeetingPlatform::Teams
            ) {
                let (handle, stop) =
                    share_detect::start_share_monitor(tx, session.pid);
                self.share_monitor_handle = Some(handle);
                self.share_monitor_stop = Some(stop);
            }
        }
    }

    /// Stop the share monitor if running.
    pub fn stop_share_monitor(&mut self) {
        if let Some(stop) = self.share_monitor_stop.take() {
            stop.store(true, std::sync::atomic::Ordering::Relaxed);
        }
        if let Some(handle) = self.share_monitor_handle.take() {
            let _ = handle.join();
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
            process_name: process_name.clone(),
            pid,
            platform: MeetingPlatform::from_process(&process_name),
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
        // Stop share monitor if running.
        self.stop_share_monitor();

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
        self.stop_share_monitor();

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
    meeting_info: Option<MeetingMetadata>,
) -> Result<PathBuf, String> {
    let metadata = match meeting_info {
        Some(info) => serde_json::to_value(&info)
            .map_err(|e| format!("Failed to serialize metadata: {}", e))?,
        None => json!({
            "title": "Meeting",
            "date": chrono::Utc::now().format("%Y-%m-%d").to_string(),
            "participants": [],
            "platform": "unknown"
        }),
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

/// Known browser process names for meeting audio detection.
const KNOWN_BROWSER_PROCESSES: &[&str] = &["chrome.exe", "msedge.exe", "firefox.exe"];

/// Scan WASAPI audio sessions for a browser process and return its PID.
///
/// Uses the same WASAPI enumeration as `monitor::enumerate_meeting_sessions` but
/// looks for browser executables instead of meeting apps.
fn find_browser_audio_pid() -> Option<u32> {
    use windows::Win32::Media::Audio::{
        eConsole, eRender, IAudioSessionControl, IAudioSessionControl2,
        IAudioSessionEnumerator, IAudioSessionManager2, IMMDeviceEnumerator,
        MMDeviceEnumerator,
    };
    use windows::Win32::System::Com::{CoCreateInstance, CLSCTX_ALL};
    use windows::Win32::System::Threading::{
        OpenProcess, QueryFullProcessImageNameW, PROCESS_NAME_WIN32,
        PROCESS_QUERY_LIMITED_INFORMATION,
    };
    use windows::Win32::Foundation::HANDLE;
    use windows::core::{Interface, PWSTR};

    unsafe {
        let enumerator: IMMDeviceEnumerator =
            CoCreateInstance(&MMDeviceEnumerator, None, CLSCTX_ALL).ok()?;

        let device = enumerator
            .GetDefaultAudioEndpoint(eRender, eConsole)
            .ok()?;

        let manager: IAudioSessionManager2 = device.Activate(CLSCTX_ALL, None).ok()?;

        let session_enum: IAudioSessionEnumerator =
            manager.GetSessionEnumerator().ok()?;

        let count = session_enum.GetCount().ok()?;

        for i in 0..count {
            let session: IAudioSessionControl = match session_enum.GetSession(i) {
                Ok(s) => s,
                Err(_) => continue,
            };

            let session2: IAudioSessionControl2 = match session.cast() {
                Ok(s) => s,
                Err(_) => continue,
            };

            let pid = match session2.GetProcessId() {
                Ok(p) => p,
                Err(_) => continue,
            };

            if pid == 0 {
                continue;
            }

            // Get the process name for this PID.
            let handle: HANDLE =
                match OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid) {
                    Ok(h) => h,
                    Err(_) => continue,
                };

            let mut buf = [0u16; 260];
            let mut size = buf.len() as u32;

            let result = QueryFullProcessImageNameW(
                handle,
                PROCESS_NAME_WIN32,
                PWSTR(buf.as_mut_ptr()),
                &mut size,
            );

            let _ = windows::Win32::Foundation::CloseHandle(handle);

            if result.is_err() {
                continue;
            }

            let full_path = String::from_utf16_lossy(&buf[..size as usize]);
            let filename = full_path
                .rsplit('\\')
                .next()
                .unwrap_or(&full_path);

            if KNOWN_BROWSER_PROCESSES
                .iter()
                .any(|&known| known.eq_ignore_ascii_case(filename))
            {
                return Some(pid);
            }
        }

        None
    }
}

// ── Enrichment routing ───────────────────────────────────────────────────────

/// Display name for a meeting platform.
fn platform_display_name(p: &MeetingPlatform) -> &str {
    match p {
        MeetingPlatform::Zoom => "Zoom",
        MeetingPlatform::Teams => "Teams",
        MeetingPlatform::GoogleMeet => "Google Meet",
        MeetingPlatform::ZohoMeet => "Zoho Meet",
        MeetingPlatform::Unknown => "Unknown",
    }
}

/// Read provider credentials from the settings store JSON file.
fn read_provider_credentials(
    app: &tauri::AppHandle,
    provider: &str,
) -> Option<(String, String, String, String)> {
    let store_path = app
        .path()
        .app_data_dir()
        .ok()?
        .join("settings.json");

    let content = std::fs::read_to_string(&store_path).ok()?;
    let store: serde_json::Value = serde_json::from_str(&content).ok()?;

    let access_token = store.get(&format!("{}_access_token", provider))?.as_str()?.to_string();
    let refresh_token = store.get(&format!("{}_refresh_token", provider))?.as_str()?.to_string();
    let client_id = store.get(&format!("{}_client_id", provider))?.as_str()?.to_string();
    let client_secret = store.get(&format!("{}_client_secret", provider))?.as_str()?.to_string();

    Some((access_token, refresh_token, client_id, client_secret))
}

/// Try Zoom API enrichment. Returns None on any error.
async fn try_zoom_enrichment(
    app: &tauri::AppHandle,
    ended_at: chrono::DateTime<chrono::Utc>,
) -> Option<MeetingMetadata> {
    let (access_token, refresh_token, client_id, client_secret) =
        read_provider_credentials(app, "zoom")?;

    let mut client = super::zoom::ZoomClient::new(
        access_token, refresh_token, client_id, client_secret,
    );

    match client.fetch_recent_meeting(ended_at).await {
        Ok(metadata) => metadata,
        Err(e) => {
            log::warn!("Zoom enrichment failed: {}", e);
            None
        }
    }
}

/// Try Google Meet API enrichment. Returns None on any error.
async fn try_google_meet_enrichment(
    app: &tauri::AppHandle,
    ended_at: chrono::DateTime<chrono::Utc>,
) -> Option<MeetingMetadata> {
    let (access_token, refresh_token, client_id, client_secret) =
        read_provider_credentials(app, "google")?;

    let mut client = super::google_meet::GoogleMeetClient::new(
        access_token, refresh_token, client_id, client_secret,
    );

    match client.fetch_recent_meeting(ended_at).await {
        Ok(metadata) => metadata,
        Err(e) => {
            log::warn!("Google Meet enrichment failed: {}", e);
            None
        }
    }
}

/// Try Zoho Meet API enrichment. Returns None on any error.
async fn try_zoho_meet_enrichment(
    app: &tauri::AppHandle,
    ended_at: chrono::DateTime<chrono::Utc>,
) -> Option<MeetingMetadata> {
    let (access_token, refresh_token, client_id, client_secret) =
        read_provider_credentials(app, "zoho")?;

    // Read the Zoho region from settings, defaulting to "com".
    let region = app
        .path()
        .app_data_dir()
        .ok()
        .and_then(|p| std::fs::read_to_string(p.join("settings.json")).ok())
        .and_then(|c| serde_json::from_str::<serde_json::Value>(&c).ok())
        .and_then(|s| s.get("zoho_region")?.as_str().map(String::from))
        .unwrap_or_else(|| "com".to_string());

    let mut client = super::zoho_meet::ZohoMeetClient::new(
        access_token, refresh_token, client_id, client_secret, region,
    );

    match client.fetch_recent_meeting(ended_at).await {
        Ok(metadata) => metadata,
        Err(e) => {
            log::warn!("Zoho Meet enrichment failed: {}", e);
            None
        }
    }
}

/// Find a calendar event overlapping the recording end time.
async fn find_calendar_match(
    app: &tauri::AppHandle,
    ended_at: chrono::DateTime<chrono::Utc>,
) -> Option<CalendarEvent> {
    let cache_path = app
        .path()
        .app_data_dir()
        .ok()?
        .join("calendar_cache.json");

    let content = std::fs::read_to_string(&cache_path).ok()?;
    let cache: calendar::CalendarCache = serde_json::from_str(&content).ok()?;

    let ended_str = ended_at.to_rfc3339();

    // Find an event that overlaps with the recording end time (within 1 hour window).
    cache.events.into_iter().find(|event| {
        calendar::match_event_to_recording(event, &ended_str, Some(3600.0))
    })
}

/// Route metadata enrichment based on meeting platform, with cascade fallback.
///
/// Priority:
/// 1. Platform-specific API (Zoom, Google Meet, Zoho Meet, Teams)
/// 2. Calendar event matching
/// 3. Minimal metadata (screenshot extraction happens in the Python pipeline)
async fn enrich_metadata(
    app: &tauri::AppHandle,
    platform: &MeetingPlatform,
    ended_at: chrono::DateTime<chrono::Utc>,
    pid: Option<u32>,
) -> MeetingMetadata {
    // 1. Try platform-specific API
    let api_result = match platform {
        MeetingPlatform::Zoom => try_zoom_enrichment(app, ended_at).await,
        MeetingPlatform::GoogleMeet => try_google_meet_enrichment(app, ended_at).await,
        MeetingPlatform::ZohoMeet => try_zoho_meet_enrichment(app, ended_at).await,
        MeetingPlatform::Teams => {
            // Teams personal: calendar + window title
            let calendar_match = find_calendar_match(app, ended_at).await;
            Some(super::teams::build_teams_metadata(
                calendar_match.as_ref(),
                pid,
                &chrono::Utc::now().to_rfc3339(),
                &ended_at.to_rfc3339(),
            ))
        }
        MeetingPlatform::Unknown => None,
    };

    if let Some(metadata) = api_result {
        return metadata;
    }

    // 2. Fallback: calendar event matching
    if let Some(event) = find_calendar_match(app, ended_at).await {
        return MeetingMetadata {
            title: event.title,
            platform: platform.clone(),
            participants: event
                .participants
                .iter()
                .map(|p| Participant {
                    name: p.name.clone(),
                    email: p.email.clone(),
                    join_time: None,
                    leave_time: None,
                })
                .collect(),
            user_name: String::new(),
            user_email: String::new(),
            start_time: event.start,
            end_time: event.end,
        };
    }

    // 3. Minimal metadata (screenshot extraction happens in pipeline)
    MeetingMetadata {
        title: format!("{} Meeting", platform_display_name(platform)),
        platform: platform.clone(),
        participants: vec![],
        user_name: String::new(),
        user_email: String::new(),
        start_time: String::new(),
        end_time: ended_at.to_rfc3339(),
    }
}

// ── Auto-record periodic check ───────────────────────────────────────────────

/// Check upcoming calendar events and arm/disarm the recorder accordingly.
///
/// Called periodically (every 60s) from the setup loop in lib.rs.
/// Reads the calendar cache and settings store directly rather than going
/// through IPC commands.
pub async fn check_auto_record_events(
    app: &AppHandle<tauri::Wry>,
    recorder: &Arc<Mutex<RecorderInner<tauri::Wry>>>,
) {
    // Read settings from the store
    let store_path = match app.path().app_data_dir() {
        Ok(p) => p.join("settings.json"),
        Err(_) => return,
    };
    let content = match std::fs::read_to_string(&store_path) {
        Ok(c) => c,
        Err(_) => return,
    };
    let store: serde_json::Value = match serde_json::from_str(&content) {
        Ok(v) => v,
        Err(_) => return,
    };

    let lead_time_minutes = store
        .get("meetingLeadTimeMinutes")
        .and_then(|v| v.as_f64())
        .unwrap_or(10.0);
    let auto_record_all = store
        .get("autoRecordAllCalendar")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);

    // Read calendar cache directly
    let cache_path = match app.path().app_data_dir() {
        Ok(p) => p.join("calendar_cache.json"),
        Err(_) => return,
    };
    let cache_content = match std::fs::read_to_string(&cache_path) {
        Ok(c) => c,
        Err(_) => return, // No cache yet
    };
    let cache: calendar::CalendarCache = match serde_json::from_str(&cache_content) {
        Ok(c) => c,
        Err(_) => return,
    };

    let now = chrono::Utc::now();
    let lead_duration = chrono::Duration::seconds((lead_time_minutes * 60.0) as i64);
    let horizon = now + lead_duration;
    let grace = chrono::Duration::minutes(5);

    // Find qualifying events: start within lead time, end not yet passed (+ 5 min grace)
    let qualifying_event = cache.events.iter().find(|event| {
        // Must be auto_record enabled, OR auto_record_all is on
        if !event.auto_record && !auto_record_all {
            return false;
        }

        let start_ok = chrono::DateTime::parse_from_rfc3339(&event.start)
            .map(|dt| dt.with_timezone(&chrono::Utc) <= horizon)
            .unwrap_or(false);
        let end_ok = chrono::DateTime::parse_from_rfc3339(&event.end)
            .map(|dt| dt.with_timezone(&chrono::Utc) + grace >= now)
            .unwrap_or(false);

        start_ok && end_ok
    });

    let mut inner = recorder.lock().await;

    match (&inner.state, qualifying_event) {
        (RecorderState::Idle, Some(event)) => {
            let expected_platform = event
                .detected_platform
                .as_deref()
                .map(MeetingPlatform::from_str);
            inner.arm_for_event(event.title.clone(), expected_platform);
        }
        (RecorderState::Armed { .. }, None) => {
            // No qualifying events remain — disarm
            inner.disarm();
        }
        _ => {
            // Either already armed with events remaining, or in a non-idle/armed state
        }
    }
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

    // If idle or armed, scan for known meeting processes.
    if inner.state() == RecorderState::Idle || matches!(inner.state(), RecorderState::Armed { .. }) {
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
                let platform = session.platform.clone();
                let session_pid = session.pid;

                // Merge audio/video into final MP4
                let merged = merge_recording(&session)?;

                // Enrich metadata via platform API / calendar / fallback
                let ended_at = chrono::Utc::now();
                let enriched = enrich_metadata(&app, &platform, ended_at, Some(session_pid)).await;
                let metadata_path = write_meeting_json(&working_dir, Some(enriched))?;

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
                            let _ = app_clone.emit("pipeline-completed", json!({
                                "success": true,
                            }));
                        }
                        Ok(result) => {
                            let _ = app_clone
                                .notification()
                                .builder()
                                .title("Pipeline Failed")
                                .body(&format!("Processing error. Check logs for details."))
                                .show();
                            log::error!("Pipeline failed: {}", result.stderr);
                            let _ = app_clone.emit("pipeline-completed", json!({
                                "success": false,
                            }));
                        }
                        Err(e) => {
                            let _ = app_clone
                                .notification()
                                .builder()
                                .title("Pipeline Error")
                                .body("Failed to run processing pipeline.")
                                .show();
                            log::error!("Pipeline error: {}", e);
                            let _ = app_clone.emit("pipeline-completed", json!({
                                "success": false,
                            }));
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
