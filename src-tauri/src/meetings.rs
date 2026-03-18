use std::collections::HashMap;
use std::path::{Path, PathBuf};

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

// ---------------------------------------------------------------------------
// Scanning helpers
// ---------------------------------------------------------------------------

const RECORDING_EXTENSIONS: &[&str] = &["mp4", "mkv", "webm", "wav"];

/// Read a `.meeting.json` file and convert it into a `MeetingSummary`.
///
/// The filename pattern is `{id}.meeting.json`, so we strip the `.meeting`
/// suffix from the file stem to recover the meeting ID. Sibling files
/// (recording, transcript, status) are discovered by probing the same
/// directory.
fn parse_meeting_json(path: &Path) -> Option<MeetingSummary> {
    let content = std::fs::read_to_string(path).ok()?;
    let meta: MeetingJson = serde_json::from_str(&content).ok()?;

    // Derive ID: filename stem minus the `.meeting` suffix.
    let stem = path.file_stem()?.to_str()?; // e.g. "abc123.meeting"
    let id = stem.strip_suffix(".meeting").unwrap_or(stem).to_string();

    let dir = path.parent()?;

    // Look for a recording file.
    let (has_video, recording_path) = find_recording(dir, &id);

    // Look for transcript.
    let transcript_path = dir.join(format!("{}.transcript.json", id));
    let has_transcript = transcript_path.exists();

    // Look for pipeline status.
    let pipeline_status = read_pipeline_status(dir, &id);

    Some(MeetingSummary {
        id,
        title: meta.title,
        date: meta.date,
        platform: meta.platform,
        participants: meta.participants.into_iter().map(|p| p.name).collect(),
        duration_seconds: None,
        pipeline_status,
        has_note: false,
        has_transcript,
        has_video,
        recording_path: recording_path.map(|p| p.to_string_lossy().into_owned()),
        note_path: None,
    })
}

/// For recordings without a `.meeting.json`. Extract date and title from
/// the filename pattern `YYYY-MM-DD-some-title.ext`.
fn summary_from_filename(path: &Path) -> Option<MeetingSummary> {
    let stem = path.file_stem()?.to_str()?;

    // Need at least `YYYY-MM-DD` (10 chars).
    if stem.len() < 10 {
        return None;
    }

    let date_part = &stem[..10];
    // Validate it looks like a date.
    if chrono::NaiveDate::parse_from_str(date_part, "%Y-%m-%d").is_err() {
        return None;
    }

    let title = if stem.len() > 11 {
        stem[11..].replace('-', " ")
    } else {
        "Untitled Recording".to_string()
    };

    let id = stem.to_string();
    let dir = path.parent()?;

    let pipeline_status = read_pipeline_status(dir, &id);
    let transcript_path = dir.join(format!("{}.transcript.json", id));

    Some(MeetingSummary {
        id,
        title,
        date: date_part.to_string(),
        platform: "unknown".to_string(),
        participants: Vec::new(),
        duration_seconds: None,
        pipeline_status,
        has_note: false,
        has_transcript: transcript_path.exists(),
        has_video: true,
        recording_path: Some(path.to_string_lossy().into_owned()),
        note_path: None,
    })
}

/// Scan a vault meetings directory and return a map of note filename stems
/// to their full paths.
fn scan_vault_notes(vault_meetings_dir: &Path) -> HashMap<String, PathBuf> {
    let mut map = HashMap::new();
    let entries = match std::fs::read_dir(vault_meetings_dir) {
        Ok(e) => e,
        Err(_) => return map,
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.extension().and_then(|e| e.to_str()) == Some("md") {
            if let Some(stem) = path.file_stem().and_then(|s| s.to_str()) {
                map.insert(stem.to_string(), path);
            }
        }
    }
    map
}

/// Try to match a `MeetingSummary` to a vault note by looking for
/// `{date} - {title}.md` in the vault notes map.
fn match_vault_note(summary: &mut MeetingSummary, vault_notes: &HashMap<String, PathBuf>) {
    let key = format!("{} - {}", summary.date, summary.title);
    if let Some(note_path) = vault_notes.get(&key) {
        summary.has_note = true;
        summary.note_path = Some(note_path.to_string_lossy().into_owned());
    }
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/// Find a recording file matching `{id}.{ext}` in `dir`.
fn find_recording(dir: &Path, id: &str) -> (bool, Option<PathBuf>) {
    for ext in RECORDING_EXTENSIONS {
        let candidate = dir.join(format!("{}.{}", id, ext));
        if candidate.exists() {
            return (true, Some(candidate));
        }
    }
    (false, None)
}

/// Read `{id}.status.json` from `dir`, falling back to default.
fn read_pipeline_status(dir: &Path, id: &str) -> PipelineStatus {
    let status_path = dir.join(format!("{}.status.json", id));
    if let Ok(content) = std::fs::read_to_string(&status_path) {
        if let Ok(status) = serde_json::from_str::<PipelineStatus>(&content) {
            return status;
        }
    }
    PipelineStatus::default()
}

// ---------------------------------------------------------------------------
// Screenshot scanning
// ---------------------------------------------------------------------------

const SCREENSHOT_EXTENSIONS: &[&str] = &["png", "jpg", "jpeg"];

/// Scan `frames_dir` for screenshot files whose name starts with `meeting_id`.
fn scan_screenshots(meeting_id: &str, frames_dir: &Path) -> Vec<Screenshot> {
    let entries = match std::fs::read_dir(frames_dir) {
        Ok(e) => e,
        Err(_) => return Vec::new(),
    };

    let mut screenshots: Vec<Screenshot> = Vec::new();
    for entry in entries.flatten() {
        let path = entry.path();
        let is_image = path
            .extension()
            .and_then(|e| e.to_str())
            .map(|e| SCREENSHOT_EXTENSIONS.contains(&e.to_ascii_lowercase().as_str()))
            .unwrap_or(false);
        if !is_image {
            continue;
        }
        let fname = match path.file_name().and_then(|n| n.to_str()) {
            Some(n) => n.to_string(),
            None => continue,
        };
        if fname.starts_with(meeting_id) {
            screenshots.push(Screenshot {
                path: path.to_string_lossy().into_owned(),
                caption: None,
            });
        }
    }
    screenshots.sort_by(|a, b| a.path.cmp(&b.path));
    screenshots
}

// ---------------------------------------------------------------------------
// IPC commands
// ---------------------------------------------------------------------------

#[tauri::command]
pub async fn get_meeting_detail(
    meeting_id: String,
    recordings_dir: String,
    vault_meetings_dir: Option<String>,
    frames_dir: Option<String>,
) -> Result<MeetingDetail, String> {
    let recordings_path = PathBuf::from(&recordings_dir);

    // 1. Try to load from {recordings_dir}/{meeting_id}.meeting.json
    let meeting_json_path = recordings_path.join(format!("{}.meeting.json", meeting_id));
    let mut summary = if meeting_json_path.exists() {
        parse_meeting_json(&meeting_json_path)
            .ok_or_else(|| format!("Failed to parse meeting.json for {}", meeting_id))?
    } else {
        // 2. Try to find a recording file and build summary from filename
        let mut found: Option<MeetingSummary> = None;
        for ext in RECORDING_EXTENSIONS {
            let candidate = recordings_path.join(format!("{}.{}", meeting_id, ext));
            if candidate.exists() {
                found = summary_from_filename(&candidate);
                break;
            }
        }
        found.ok_or_else(|| format!("Meeting not found: {}", meeting_id))?
    };

    // 3. Match vault note and read note content
    let vault_notes = vault_meetings_dir
        .as_deref()
        .map(|p| scan_vault_notes(Path::new(p)))
        .unwrap_or_default();
    match_vault_note(&mut summary, &vault_notes);

    let note_content = summary
        .note_path
        .as_ref()
        .and_then(|p| std::fs::read_to_string(p).ok());

    // 4. Read transcript JSON
    let transcript_path = recordings_path.join(format!("{}.transcript.json", meeting_id));
    let transcript: Option<Vec<Utterance>> = if transcript_path.exists() {
        std::fs::read_to_string(&transcript_path)
            .ok()
            .and_then(|content| serde_json::from_str(&content).ok())
    } else {
        None
    };

    // 5. Scan screenshots
    let screenshots = frames_dir
        .as_deref()
        .map(|d| scan_screenshots(&meeting_id, Path::new(d)))
        .unwrap_or_default();

    Ok(MeetingDetail {
        summary,
        note_content,
        transcript,
        screenshots,
    })
}

#[tauri::command]
pub async fn search_meetings(
    query: String,
    recordings_dir: String,
    vault_meetings_dir: Option<String>,
    limit: Option<usize>,
) -> Result<Vec<MeetingSummary>, String> {
    let limit = limit.unwrap_or(50);
    let query_lower = query.to_lowercase();

    // Reuse list_meetings logic with a large limit, then filter.
    let all = list_meetings(
        recordings_dir,
        vault_meetings_dir,
        None,
        Some(1000),
    )
    .await?;

    let results: Vec<MeetingSummary> = all
        .items
        .into_iter()
        .filter(|s| {
            s.title.to_lowercase().contains(&query_lower)
                || s.date.to_lowercase().contains(&query_lower)
                || s.participants
                    .iter()
                    .any(|p| p.to_lowercase().contains(&query_lower))
        })
        .take(limit)
        .collect();

    Ok(results)
}

#[tauri::command]
pub async fn list_meetings(
    recordings_dir: String,
    vault_meetings_dir: Option<String>,
    cursor: Option<String>,
    limit: Option<usize>,
) -> Result<MeetingListResponse, String> {
    let recordings_path = PathBuf::from(&recordings_dir);
    if !recordings_path.is_dir() {
        return Err(format!("Recordings directory does not exist: {}", recordings_dir));
    }

    let limit = limit.unwrap_or(50);

    // Scan vault notes if a path was provided.
    let vault_notes = vault_meetings_dir
        .as_deref()
        .map(|p| scan_vault_notes(Path::new(p)))
        .unwrap_or_default();

    // Collect meeting summaries. Track IDs we've already seen so that
    // recordings with a .meeting.json aren't duplicated by the filename
    // fallback pass.
    let mut summaries: Vec<MeetingSummary> = Vec::new();
    let mut seen_ids: std::collections::HashSet<String> = std::collections::HashSet::new();

    let entries: Vec<_> = std::fs::read_dir(&recordings_path)
        .map_err(|e| format!("Failed to read recordings directory: {}", e))?
        .filter_map(|e| e.ok())
        .collect();

    // First pass: .meeting.json files.
    for entry in &entries {
        let path = entry.path();
        if path
            .file_name()
            .and_then(|n| n.to_str())
            .map(|n| n.ends_with(".meeting.json"))
            .unwrap_or(false)
        {
            if let Some(mut summary) = parse_meeting_json(&path) {
                match_vault_note(&mut summary, &vault_notes);
                seen_ids.insert(summary.id.clone());
                summaries.push(summary);
            }
        }
    }

    // Second pass: recording files without a .meeting.json.
    for entry in &entries {
        let path = entry.path();
        let ext_match = path
            .extension()
            .and_then(|e| e.to_str())
            .map(|e| RECORDING_EXTENSIONS.contains(&e))
            .unwrap_or(false);
        if !ext_match {
            continue;
        }
        let stem = match path.file_stem().and_then(|s| s.to_str()) {
            Some(s) => s.to_string(),
            None => continue,
        };
        if seen_ids.contains(&stem) {
            continue;
        }
        // Check that no .meeting.json exists for this stem.
        let meeting_json_path = recordings_path.join(format!("{}.meeting.json", stem));
        if meeting_json_path.exists() {
            continue;
        }
        if let Some(mut summary) = summary_from_filename(&path) {
            match_vault_note(&mut summary, &vault_notes);
            seen_ids.insert(summary.id.clone());
            summaries.push(summary);
        }
    }

    // Sort by date descending.
    summaries.sort_by(|a, b| b.date.cmp(&a.date));

    // Apply cursor-based pagination.
    let start_index = if let Some(ref cursor_id) = cursor {
        match summaries.iter().position(|s| s.id == *cursor_id) {
            Some(pos) => pos + 1,
            None => 0,
        }
    } else {
        0
    };

    let page: Vec<MeetingSummary> = summaries
        .into_iter()
        .skip(start_index)
        .take(limit + 1) // take one extra to check if there are more
        .collect();

    let has_more = page.len() > limit;
    let items: Vec<MeetingSummary> = page.into_iter().take(limit).collect();
    let next_cursor = if has_more {
        items.last().map(|s| s.id.clone())
    } else {
        None
    };

    Ok(MeetingListResponse { items, next_cursor })
}
