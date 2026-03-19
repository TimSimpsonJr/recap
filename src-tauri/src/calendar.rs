use std::collections::HashMap;
use std::path::{Path, PathBuf};

use chrono::{DateTime, Duration, Utc};
use serde::{Deserialize, Serialize};
use tauri::Manager;

use crate::meetings::MeetingSummary;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CalendarEvent {
    pub id: String,
    pub title: String,
    pub description: Option<String>,
    pub start: String,  // ISO 8601
    pub end: String,    // ISO 8601
    pub participants: Vec<CalendarParticipant>,
    pub location: Option<String>,
    #[serde(default)]
    pub auto_record: bool,
    pub recurring_series_id: Option<String>,
    pub meeting_url: Option<String>,
    pub detected_platform: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CalendarParticipant {
    pub name: String,
    pub email: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CalendarCache {
    pub events: Vec<CalendarEvent>,
    pub last_synced: String,
}

/// Zoho Calendar API response shape for event listing.
#[derive(Debug, Deserialize)]
struct ZohoEventsResponse {
    events: Option<Vec<ZohoEvent>>,
}

#[derive(Debug, Deserialize)]
struct ZohoEvent {
    uid: Option<String>,
    title: Option<String>,
    description: Option<String>,
    dateandtime: Option<ZohoDateAndTime>,
    attendees: Option<Vec<ZohoAttendee>>,
    location: Option<String>,
}

#[derive(Debug, Deserialize)]
struct ZohoDateAndTime {
    start: Option<String>,
    end: Option<String>,
}

#[derive(Debug, Deserialize)]
struct ZohoAttendee {
    name: Option<String>,
    email: Option<String>,
}

// ---------------------------------------------------------------------------
// Meeting URL detection
// ---------------------------------------------------------------------------

/// Known meeting URL patterns and their platform names.
const MEETING_URL_PATTERNS: &[(&str, &str)] = &[
    ("zoom.us/j/", "zoom"),
    ("meet.google.com/", "google_meet"),
    ("teams.microsoft.com/", "teams"),
    ("meeting.tranzpay.io/", "zoho_meet"),
    ("meeting.zoho.com/meeting/", "zoho_meet"),
    ("meeting.zoho.eu/meeting/", "zoho_meet"),
    ("meeting.zoho.in/meeting/", "zoho_meet"),
    ("meeting.zoho.com.au/meeting/", "zoho_meet"),
    ("meeting.zoho.jp/meeting/", "zoho_meet"),
];

/// Scan text for a known meeting URL. Returns (url, platform) if found.
fn parse_meeting_url(text: &str) -> Option<(String, String)> {
    for (pattern, platform) in MEETING_URL_PATTERNS {
        if let Some(start_idx) = text.find(pattern) {
            // Walk backwards to find the start of the URL (https:// or http://)
            let before = &text[..start_idx];
            let url_start = before.rfind("https://")
                .or_else(|| before.rfind("http://"))
                .unwrap_or(start_idx);
            // Walk forward to find end of URL (whitespace or common delimiters)
            let url_region = &text[url_start..];
            let url_end = url_region
                .find(|c: char| c.is_whitespace() || c == '"' || c == '\'' || c == '>' || c == ')' || c == ']')
                .unwrap_or(url_region.len());
            let url = &url_region[..url_end];
            return Some((url.to_string(), platform.to_string()));
        }
    }
    None
}

/// Enrich a CalendarEvent with meeting URL and detected platform by scanning
/// its description and location fields.
fn enrich_meeting_url(event: &mut CalendarEvent) {
    // Check description first, then location
    let text_to_scan: Vec<&str> = [
        event.description.as_deref(),
        event.location.as_deref(),
    ]
    .iter()
    .filter_map(|s| *s)
    .collect();

    for text in text_to_scan {
        if let Some((url, platform)) = parse_meeting_url(text) {
            event.meeting_url = Some(url);
            event.detected_platform = Some(platform);
            return;
        }
    }
}

// ---------------------------------------------------------------------------
// Cache helpers
// ---------------------------------------------------------------------------

fn cache_path(app: &tauri::AppHandle) -> PathBuf {
    app.path()
        .app_data_dir()
        .expect("could not resolve app data dir")
        .join("calendar_cache.json")
}

fn write_cache(path: &Path, cache: &CalendarCache) -> Result<(), String> {
    let json = serde_json::to_string_pretty(cache)
        .map_err(|e| format!("Failed to serialize calendar cache: {}", e))?;
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)
            .map_err(|e| format!("Failed to create cache directory: {}", e))?;
    }
    std::fs::write(path, json)
        .map_err(|e| format!("Failed to write calendar cache: {}", e))?;
    Ok(())
}

fn read_cache(path: &Path) -> Result<CalendarCache, String> {
    let content = std::fs::read_to_string(path)
        .map_err(|e| format!("Failed to read calendar cache: {}", e))?;
    serde_json::from_str(&content)
        .map_err(|e| format!("Failed to parse calendar cache: {}", e))
}

// ---------------------------------------------------------------------------
// Zoho API helpers
// ---------------------------------------------------------------------------

/// Read the Zoho OAuth access token from the Tauri plugin-store JSON file.
///
/// The frontend persists tokens via `@tauri-apps/plugin-stronghold` and also
/// mirrors the access token into the Tauri plugin-store so Rust-side code can
/// read it without needing direct Stronghold access.  The store key follows
/// the pattern `zoho_access_token`.
///
/// TODO: If the project migrates to reading directly from Stronghold on the
/// Rust side, update this helper accordingly.
fn get_zoho_access_token(app: &tauri::AppHandle) -> Result<String, String> {
    // The store file is written by the frontend via @tauri-apps/plugin-store.
    let store_path = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("Could not resolve app data dir: {}", e))?
        .join("settings.json");

    let content = std::fs::read_to_string(&store_path)
        .map_err(|e| format!("Could not read settings store: {}", e))?;
    let store_data: serde_json::Value = serde_json::from_str(&content)
        .map_err(|e| format!("Could not parse settings store: {}", e))?;

    store_data
        .get("zoho_access_token")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string())
        .ok_or_else(|| "Zoho access token not found — please connect Zoho in Settings".to_string())
}

/// Convert Zoho API event objects into our CalendarEvent structs.
fn parse_zoho_events(response: ZohoEventsResponse) -> Vec<CalendarEvent> {
    let zoho_events = match response.events {
        Some(events) => events,
        None => return Vec::new(),
    };

    zoho_events
        .into_iter()
        .filter_map(|e| {
            let dt = e.dateandtime?;
            let mut event = CalendarEvent {
                id: e.uid.unwrap_or_default(),
                title: e.title.unwrap_or_else(|| "Untitled".to_string()),
                description: e.description,
                start: dt.start.unwrap_or_default(),
                end: dt.end.unwrap_or_default(),
                participants: e
                    .attendees
                    .unwrap_or_default()
                    .into_iter()
                    .map(|a| CalendarParticipant {
                        name: a.name.unwrap_or_default(),
                        email: a.email,
                    })
                    .collect(),
                location: e.location,
                auto_record: false,
                recurring_series_id: None,
                meeting_url: None,
                detected_platform: None,
            };
            enrich_meeting_url(&mut event);
            Some(event)
        })
        .collect()
}

// ---------------------------------------------------------------------------
// Tauri commands — sync & fetch
// ---------------------------------------------------------------------------

/// Fetch calendar events from the Zoho Calendar API for a date range.
///
/// Reads the Zoho access token from the app store, calls the Zoho Calendar
/// events endpoint, caches the result locally, and returns the events.
#[tauri::command]
pub async fn fetch_calendar_events(
    app: tauri::AppHandle,
    start_date: String,
    end_date: String,
) -> Result<Vec<CalendarEvent>, String> {
    let access_token = get_zoho_access_token(&app)?;

    // TODO: Allow the user to configure their Zoho calendar ID in Settings.
    // For now, use the primary calendar placeholder.
    let calendar_id = "primary";

    let url = format!(
        "https://calendar.zoho.com/api/v1/calendars/{}/events?range={},{}",
        calendar_id, start_date, end_date,
    );

    let client = reqwest::Client::new();
    let response = client
        .get(&url)
        .header("Authorization", format!("Zoho-oauthtoken {}", access_token))
        .header("Accept", "application/json+large")
        .send()
        .await
        .map_err(|e| format!("Zoho Calendar API request failed: {}", e))?;

    if !response.status().is_success() {
        let status = response.status();
        let body = response
            .text()
            .await
            .unwrap_or_else(|_| "no body".to_string());
        return Err(format!(
            "Zoho Calendar API returned status {}: {}",
            status, body
        ));
    }

    let zoho_response: ZohoEventsResponse = response
        .json()
        .await
        .map_err(|e| format!("Failed to parse Zoho Calendar response: {}", e))?;

    let events = parse_zoho_events(zoho_response);

    // Write to cache
    let cache = CalendarCache {
        events: events.clone(),
        last_synced: Utc::now().to_rfc3339(),
    };
    let cp = cache_path(&app);
    write_cache(&cp, &cache)?;

    Ok(events)
}

/// Return upcoming meetings from the local cache that start within
/// `hours_ahead` hours from now.
#[tauri::command]
pub async fn get_upcoming_meetings(
    app: tauri::AppHandle,
    hours_ahead: f64,
) -> Result<Vec<CalendarEvent>, String> {
    let cp = cache_path(&app);
    let cache = read_cache(&cp)?;

    let now = Utc::now();
    let horizon = now + Duration::seconds((hours_ahead * 3600.0) as i64);

    let upcoming: Vec<CalendarEvent> = cache
        .events
        .into_iter()
        .filter(|event| {
            if let Ok(start) = DateTime::parse_from_rfc3339(&event.start) {
                let start_utc = start.with_timezone(&Utc);
                start_utc >= now && start_utc <= horizon
            } else {
                false
            }
        })
        .collect();

    Ok(upcoming)
}

/// Sync the calendar by fetching the next 14 days of events.
#[tauri::command]
pub async fn sync_calendar(
    app: tauri::AppHandle,
) -> Result<CalendarCache, String> {
    let now = Utc::now();
    let start_date = now.format("%Y-%m-%dT%H:%M:%S%z").to_string();
    let end_date = (now + Duration::days(14))
        .format("%Y-%m-%dT%H:%M:%S%z")
        .to_string();

    let events = fetch_calendar_events(app.clone(), start_date, end_date).await?;

    // Build the CalendarCache directly from the fetched events instead of
    // re-reading the cache file that fetch_calendar_events just wrote.
    Ok(CalendarCache {
        events,
        last_synced: Utc::now().to_rfc3339(),
    })
}

// ---------------------------------------------------------------------------
// Calendar-recording matching (D2)
// ---------------------------------------------------------------------------

/// Check whether a calendar event overlaps a recording by at least 5 minutes.
///
/// `meeting_date` is the recording start time in ISO 8601 (or date string from
/// the meeting metadata). `duration_seconds` is the recording duration; if
/// `None`, we assume a 1-hour recording for matching purposes.
pub fn match_event_to_recording(
    event: &CalendarEvent,
    meeting_date: &str,
    duration_seconds: Option<f64>,
) -> bool {
    let event_start = match DateTime::parse_from_rfc3339(&event.start) {
        Ok(dt) => dt.with_timezone(&Utc),
        Err(_) => return false,
    };
    let event_end = match DateTime::parse_from_rfc3339(&event.end) {
        Ok(dt) => dt.with_timezone(&Utc),
        Err(_) => return false,
    };

    // Try parsing as full RFC 3339 first, then fall back to date-only.
    let recording_start = if let Ok(dt) = DateTime::parse_from_rfc3339(meeting_date) {
        dt.with_timezone(&Utc)
    } else if let Ok(date) = chrono::NaiveDate::parse_from_str(meeting_date, "%Y-%m-%d") {
        // Assume midnight UTC for date-only strings.
        date.and_hms_opt(0, 0, 0)
            .map(|ndt| DateTime::<Utc>::from_naive_utc_and_offset(ndt, Utc))
            .unwrap_or(return false)
    } else {
        return false;
    };

    let duration_secs = duration_seconds.unwrap_or(3600.0); // default 1 hour
    let recording_end = recording_start + Duration::seconds(duration_secs as i64);

    // Compute overlap: max(0, min(end1, end2) - max(start1, start2))
    let overlap_start = event_start.max(recording_start);
    let overlap_end = event_end.min(recording_end);

    if overlap_end > overlap_start {
        let overlap_minutes = (overlap_end - overlap_start).num_minutes();
        overlap_minutes >= 5
    } else {
        false
    }
}

/// Return the last_synced timestamp from the calendar cache, or null if no cache exists.
#[tauri::command]
pub async fn get_calendar_last_synced(
    app: tauri::AppHandle,
) -> Result<Option<String>, String> {
    let cp = cache_path(&app);
    if !cp.exists() {
        return Ok(None);
    }
    let cache = read_cache(&cp)?;
    if cache.last_synced.is_empty() {
        Ok(None)
    } else {
        Ok(Some(cache.last_synced))
    }
}

/// Scan recordings and match them against cached calendar events.
///
/// Returns a map of `{ event_id: meeting_id }` for every match found.
#[tauri::command]
pub async fn get_calendar_matches(
    app: tauri::AppHandle,
    recordings_dir: String,
) -> Result<HashMap<String, String>, String> {
    let cp = cache_path(&app);
    let cache = read_cache(&cp)?;

    let recordings_path = PathBuf::from(&recordings_dir);
    if !recordings_path.is_dir() {
        return Err(format!(
            "Recordings directory does not exist: {}",
            recordings_dir
        ));
    }

    // Scan for .meeting.json files (same pattern as meetings.rs).
    let entries = std::fs::read_dir(&recordings_path)
        .map_err(|e| format!("Failed to read recordings directory: {}", e))?;

    let mut meetings: Vec<MeetingSummary> = Vec::new();
    for entry in entries.flatten() {
        let path = entry.path();
        let is_meeting_json = path
            .file_name()
            .and_then(|n| n.to_str())
            .map(|n| n.ends_with(".meeting.json"))
            .unwrap_or(false);
        if !is_meeting_json {
            continue;
        }
        let content = match std::fs::read_to_string(&path) {
            Ok(c) => c,
            Err(_) => continue,
        };
        // We only need id, date, and duration_seconds for matching, so parse
        // just the fields we need from the meeting.json.
        let meta: serde_json::Value = match serde_json::from_str(&content) {
            Ok(m) => m,
            Err(_) => continue,
        };

        let stem = match path.file_stem().and_then(|s| s.to_str()) {
            Some(s) => s,
            None => continue,
        };
        let id = stem
            .strip_suffix(".meeting")
            .unwrap_or(stem)
            .to_string();
        let date = meta
            .get("date")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let duration = meta
            .get("duration_seconds")
            .and_then(|v| v.as_f64());

        if date.is_empty() {
            continue;
        }

        // We only use id, date, and duration_seconds for matching, so build a
        // lightweight placeholder. Using a default MeetingSummary avoids
        // exposing parse_meeting_json as pub.
        meetings.push(MeetingSummary {
            id,
            title: String::new(),
            date,
            platform: String::new(),
            participants: Vec::new(),
            company: None,
            duration_seconds: duration,
            pipeline_status: Default::default(),
            has_note: false,
            has_transcript: false,
            has_video: false,
            recording_path: None,
            note_path: None,
        });
    }

    // Match events to meetings.
    let mut matches: HashMap<String, String> = HashMap::new();
    for event in &cache.events {
        for meeting in &meetings {
            if match_event_to_recording(event, &meeting.date, meeting.duration_seconds) {
                matches.insert(event.id.clone(), meeting.id.clone());
                break; // one match per event
            }
        }
    }

    Ok(matches)
}

// ---------------------------------------------------------------------------
// Auto-record IPC commands
// ---------------------------------------------------------------------------

/// Set the auto_record flag on a single calendar event.
#[tauri::command]
pub async fn set_auto_record(
    app: tauri::AppHandle,
    event_id: String,
    auto_record: bool,
) -> Result<(), String> {
    let cp = cache_path(&app);
    let mut cache = read_cache(&cp)?;

    let found = cache.events.iter_mut().find(|e| e.id == event_id);
    match found {
        Some(event) => {
            event.auto_record = auto_record;
            write_cache(&cp, &cache)?;
            Ok(())
        }
        None => Err(format!("Event not found: {}", event_id)),
    }
}

/// Set the auto_record flag on all events sharing the same recurring_series_id.
#[tauri::command]
pub async fn set_series_auto_record(
    app: tauri::AppHandle,
    series_id: String,
    auto_record: bool,
) -> Result<(), String> {
    let cp = cache_path(&app);
    let mut cache = read_cache(&cp)?;

    let mut count = 0;
    for event in cache.events.iter_mut() {
        if event.recurring_series_id.as_deref() == Some(&series_id) {
            event.auto_record = auto_record;
            count += 1;
        }
    }

    if count == 0 {
        return Err(format!("No events found for series: {}", series_id));
    }

    write_cache(&cp, &cache)?;
    Ok(())
}

/// Return calendar events that have auto_record enabled and start within
/// `hours_ahead` hours from now (or have already started but not yet ended).
#[tauri::command]
pub async fn get_auto_record_events(
    app: tauri::AppHandle,
    hours_ahead: f64,
) -> Result<Vec<CalendarEvent>, String> {
    let cp = cache_path(&app);
    if !cp.exists() {
        return Ok(Vec::new());
    }
    let cache = read_cache(&cp)?;

    let now = Utc::now();
    let horizon = now + Duration::seconds((hours_ahead * 3600.0) as i64);

    let events: Vec<CalendarEvent> = cache
        .events
        .into_iter()
        .filter(|event| {
            if !event.auto_record {
                return false;
            }
            // Event must start before the horizon and end after now
            let start_ok = DateTime::parse_from_rfc3339(&event.start)
                .map(|dt| dt.with_timezone(&Utc) <= horizon)
                .unwrap_or(false);
            let end_ok = DateTime::parse_from_rfc3339(&event.end)
                .map(|dt| dt.with_timezone(&Utc) >= now)
                .unwrap_or(false);
            start_ok && end_ok
        })
        .collect();

    Ok(events)
}
