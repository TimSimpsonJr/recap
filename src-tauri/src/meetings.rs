use serde::{Deserialize, Serialize};

use crate::recorder::types::PipelineStatus;

/// Summary of a meeting for the list view.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MeetingSummary {
    pub id: String,
    pub title: String,
    pub date: String,
    pub platform: String,
    pub participants: Vec<String>,
    pub duration_seconds: Option<f64>,
    pub pipeline_status: PipelineStatus,
    pub has_note: bool,
    pub has_transcript: bool,
    pub has_video: bool,
    pub recording_path: Option<String>,
    pub note_path: Option<String>,
}

/// A single transcript utterance.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Utterance {
    pub speaker: String,
    pub start: f64,
    pub end: f64,
    pub text: String,
}

/// A screenshot with optional caption.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Screenshot {
    pub path: String,
    pub caption: Option<String>,
}

/// Full meeting detail for the detail view.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MeetingDetail {
    pub summary: MeetingSummary,
    pub note_content: Option<String>,
    pub transcript: Option<Vec<Utterance>>,
    pub screenshots: Vec<Screenshot>,
}

/// Paginated list response.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MeetingListResponse {
    pub items: Vec<MeetingSummary>,
    pub next_cursor: Option<String>,
}

/// Internal: meeting metadata from meeting.json (matches Python's MeetingMetadata).
#[derive(Debug, Clone, Deserialize)]
pub(crate) struct MeetingJson {
    pub title: String,
    pub date: String,
    pub participants: Vec<ParticipantJson>,
    pub platform: String,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct ParticipantJson {
    pub name: String,
}
