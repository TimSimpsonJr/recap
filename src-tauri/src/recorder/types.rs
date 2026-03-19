use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::time::Instant;

/// Recording session lifecycle states.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RecorderState {
    /// No meeting detected, monitoring for audio sessions.
    Idle,
    /// Armed for auto-record from a calendar event. Will start recording
    /// immediately when a meeting is detected, skipping the notification prompt.
    Armed {
        event_title: String,
        expected_platform: Option<MeetingPlatform>,
    },
    /// Meeting audio session detected, awaiting user response or auto-record.
    Detected { process_name: String, pid: u32 },
    /// Actively capturing audio + video.
    Recording,
    /// Capture stopped, merging and processing.
    Processing,
    /// User declined recording for this session.
    Declined,
}

/// Detected meeting platform, used for API enrichment routing.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MeetingPlatform {
    Zoom,
    Teams,
    GoogleMeet,
    ZohoMeet,
    Unknown,
}

impl MeetingPlatform {
    pub fn from_platform_str(s: &str) -> Self {
        match s {
            "zoom" => Self::Zoom,
            "teams" => Self::Teams,
            "google_meet" => Self::GoogleMeet,
            "zoho_meet" => Self::ZohoMeet,
            _ => Self::Unknown,
        }
    }

    pub fn from_process(name: &str) -> Self {
        match name {
            "Zoom.exe" => Self::Zoom,
            "Teams.exe" => Self::Teams,
            _ => Self::Unknown,
        }
    }
}

/// Unified meeting metadata from any platform's API.
/// Written to meeting.json alongside the recording.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MeetingMetadata {
    pub title: String,
    pub platform: MeetingPlatform,
    pub participants: Vec<Participant>,
    pub user_name: String,
    pub user_email: String,
    pub start_time: String,
    pub end_time: String,
}

/// A meeting participant from any platform.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Participant {
    pub name: String,
    pub email: Option<String>,
    pub join_time: Option<String>,
    pub leave_time: Option<String>,
}

/// Source for video capture — either a specific window or a display monitor.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CaptureSource {
    Window { pid: u32 },
    Display { monitor_index: u32 },
}

/// What to do when a meeting is detected.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DetectionAction {
    /// Show a notification and ask the user.
    Ask,
    /// Always start recording immediately.
    AlwaysRecord,
    /// Never record (monitoring still runs for manual start).
    NeverRecord,
}

/// What to do when the notification times out.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TimeoutAction {
    Record,
    Skip,
}

/// Configuration for recording behavior. Read from settings store.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RecordingConfig {
    pub auto_detect: bool,
    pub detection_action: DetectionAction,
    pub timeout_action: TimeoutAction,
    pub timeout_seconds: u64,
    /// Monitor index for screen share capture (0 = primary).
    pub screen_share_monitor: u32,
}

impl Default for RecordingConfig {
    fn default() -> Self {
        Self {
            auto_detect: true,
            detection_action: DetectionAction::Ask,
            timeout_action: TimeoutAction::Record,
            timeout_seconds: 60,
            screen_share_monitor: 0,
        }
    }
}

/// Info about an active recording session.
#[derive(Debug)]
pub struct RecordingSession {
    pub process_name: String,
    pub pid: u32,
    pub platform: MeetingPlatform,
    pub started_at: Instant,
    pub working_dir: PathBuf,
    pub remote_audio_path: PathBuf,
    pub local_audio_path: PathBuf,
    pub video_path: PathBuf,
}

/// Pipeline stage for restart support.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PipelineStage {
    Merge,
    Frames,
    Transcribe,
    Diarize,
    Analyze,
    Export,
}

/// Status of a pipeline run, written to status.json.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StageStatus {
    pub completed: bool,
    pub timestamp: Option<String>,
    pub error: Option<String>,
    pub waiting: Option<String>,
}

/// Full pipeline status for a recording.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PipelineStatus {
    pub merge: StageStatus,
    pub frames: StageStatus,
    pub transcribe: StageStatus,
    pub diarize: StageStatus,
    pub analyze: StageStatus,
    pub export: StageStatus,
}

impl Default for PipelineStatus {
    fn default() -> Self {
        let empty = || StageStatus {
            completed: false,
            timestamp: None,
            error: None,
            waiting: None,
        };
        Self {
            merge: empty(),
            frames: empty(),
            transcribe: empty(),
            diarize: empty(),
            analyze: empty(),
            export: empty(),
        }
    }
}
