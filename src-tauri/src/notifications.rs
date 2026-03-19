use std::collections::HashSet;
use std::sync::Mutex;

use chrono::{DateTime, Utc};
use tauri::{AppHandle, Manager, Runtime};
use tauri_plugin_notification::NotificationExt;

use crate::calendar::{CalendarEvent, CalendarCache};

/// Track which event IDs have already had notifications sent.
static NOTIFIED_EVENTS: Mutex<Option<HashSet<String>>> = Mutex::new(None);

fn get_notified_set() -> std::sync::MutexGuard<'static, Option<HashSet<String>>> {
    NOTIFIED_EVENTS.lock().unwrap_or_else(|e| e.into_inner())
}

/// Read settings from the Tauri plugin-store to get notification preferences.
fn read_notification_settings(app: &AppHandle<impl Runtime>) -> (bool, u32) {
    let store_path = match app.path().app_data_dir() {
        Ok(dir) => dir.join("settings.json"),
        Err(_) => return (true, 10),
    };

    let content = match std::fs::read_to_string(&store_path) {
        Ok(c) => c,
        Err(_) => return (true, 10),
    };

    let store_data: serde_json::Value = match serde_json::from_str(&content) {
        Ok(v) => v,
        Err(_) => return (true, 10),
    };

    let enabled = store_data
        .get("meetingNotifications")
        .and_then(|v| v.as_bool())
        .unwrap_or(true);

    let lead_time = store_data
        .get("meetingLeadTimeMinutes")
        .and_then(|v| v.as_u64())
        .unwrap_or(10) as u32;

    (enabled, lead_time)
}

/// Read cached calendar events from disk.
fn read_calendar_cache(app: &AppHandle<impl Runtime>) -> Option<CalendarCache> {
    let cache_path = app
        .path()
        .app_data_dir()
        .ok()?
        .join("calendar_cache.json");

    let content = std::fs::read_to_string(&cache_path).ok()?;
    serde_json::from_str(&content).ok()
}

/// Check for upcoming meetings and send desktop notifications.
///
/// This should be called periodically (e.g., every minute on a timer or on
/// app focus) to check if any meetings are starting soon.
pub fn check_upcoming_notifications<R: Runtime>(app: &AppHandle<R>) -> Result<(), String> {
    let (enabled, lead_time_minutes) = read_notification_settings(app);

    if !enabled {
        return Ok(());
    }

    let cache = match read_calendar_cache(app) {
        Some(c) => c,
        None => return Ok(()), // No calendar data yet
    };

    let now = Utc::now();
    let lead_time = chrono::Duration::minutes(lead_time_minutes as i64);
    let horizon = now + lead_time;

    let mut notified = get_notified_set();
    let set = notified.get_or_insert_with(HashSet::new);

    for event in &cache.events {
        // Skip already-notified events
        if set.contains(&event.id) {
            continue;
        }

        let event_start = match DateTime::parse_from_rfc3339(&event.start) {
            Ok(dt) => dt.with_timezone(&Utc),
            Err(_) => continue,
        };

        // Event must be in the future and within the lead time window
        if event_start > now && event_start <= horizon {
            let minutes_until = (event_start - now).num_minutes();

            let participants_list: String = event
                .participants
                .iter()
                .map(|p| p.name.as_str())
                .collect::<Vec<_>>()
                .join(", ");

            let body = if participants_list.is_empty() {
                format!("In {} min", minutes_until)
            } else {
                format!("In {} min — {}", minutes_until, participants_list)
            };

            let _ = app
                .notification()
                .builder()
                .title(&format!("Upcoming: {}", event.title))
                .body(&body)
                .show();

            set.insert(event.id.clone());
        }
    }

    Ok(())
}
