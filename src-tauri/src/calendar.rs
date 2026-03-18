use std::path::{Path, PathBuf};

use chrono::{DateTime, Duration, Utc};
use serde::{Deserialize, Serialize};
use tauri::Manager;

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
            Some(CalendarEvent {
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
            })
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

    // The cache was already written by fetch_calendar_events, but read it back
    // to return the full CalendarCache struct.
    let cp = cache_path(&app);
    read_cache(&cp)
}
