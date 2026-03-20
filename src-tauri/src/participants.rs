use std::collections::HashMap;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use tauri::Manager;
use tauri_plugin_store::StoreExt;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ParticipantMeeting {
    pub id: String,
    pub title: String,
    pub date: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ParticipantInfo {
    pub name: String,
    pub email: Option<String>,
    pub company: Option<String>,
    pub recent_meetings: Vec<ParticipantMeeting>,
}

#[derive(Debug, Clone)]
pub(crate) struct ParticipantRecord {
    pub name: String,
    pub email: Option<String>,
    pub company: Option<String>,
    pub meetings: Vec<ParticipantMeeting>,
}

pub struct ParticipantIndex {
    pub(crate) records: HashMap<String, ParticipantRecord>,
    pub(crate) initialized: bool,
}

impl ParticipantIndex {
    pub fn new() -> Self {
        Self {
            records: HashMap::new(),
            initialized: false,
        }
    }
}

pub type ParticipantIndexState = std::sync::Mutex<ParticipantIndex>;

fn company_from_email(email: &str) -> Option<String> {
    let domain = email.split('@').nth(1)?;
    let name = domain.split('.').next()?;
    if ["gmail", "yahoo", "hotmail", "outlook", "icloud", "aol", "protonmail", "live"]
        .contains(&name)
    {
        return None;
    }
    let mut chars = name.chars();
    let first = chars.next()?.to_uppercase().to_string();
    Some(first + chars.as_str())
}

pub(crate) fn build_index(recordings_dir: &Path) -> HashMap<String, ParticipantRecord> {
    let mut records: HashMap<String, ParticipantRecord> = HashMap::new();

    let entries = match std::fs::read_dir(recordings_dir) {
        Ok(e) => e,
        Err(_) => return records,
    };

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
        let meta: serde_json::Value = match serde_json::from_str(&content) {
            Ok(m) => m,
            Err(_) => continue,
        };

        let meeting_id = path
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or("")
            .replace(".meeting", "")
            .to_string();

        let title = meta
            .get("title")
            .and_then(|v| v.as_str())
            .unwrap_or("Untitled")
            .to_string();
        let date = meta
            .get("date")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let company_from_meta = meta
            .get("company")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());

        let participants: Vec<String> = meta
            .get("participants")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(|s| s.to_string()))
                    .collect()
            })
            .unwrap_or_default();

        let meeting_entry = ParticipantMeeting {
            id: meeting_id,
            title,
            date,
        };

        for participant_name in &participants {
            let key = participant_name.to_lowercase();
            let record = records.entry(key).or_insert_with(|| ParticipantRecord {
                name: participant_name.clone(),
                email: None,
                company: company_from_meta.clone(),
                meetings: Vec::new(),
            });
            if record.company.is_none() {
                record.company = company_from_meta.clone();
            }
            record.meetings.push(meeting_entry.clone());
        }
    }

    // Sort meetings by date descending
    for record in records.values_mut() {
        record.meetings.sort_by(|a, b| b.date.cmp(&a.date));
    }

    records
}

#[tauri::command]
pub async fn get_participant_info(
    app: tauri::AppHandle,
    name: String,
    email: Option<String>,
) -> Result<ParticipantInfo, String> {
    let recordings_dir = {
        let store = app
            .store("settings.json")
            .map_err(|e| format!("Failed to open settings store: {}", e))?;
        store
            .get("recordingsFolder")
            .and_then(|v| v.as_str().map(|s| s.to_string()))
            .ok_or("Recordings folder not configured")?
    };

    let index = app.state::<ParticipantIndexState>();
    let mut index = index.lock().map_err(|e| format!("Index lock failed: {}", e))?;

    if !index.initialized {
        index.records = build_index(Path::new(&recordings_dir));
        index.initialized = true;
    }

    let key = name.to_lowercase();
    let info = if let Some(record) = index.records.get(&key) {
        let company = record
            .company
            .clone()
            .or_else(|| email.as_deref().and_then(company_from_email));
        ParticipantInfo {
            name: record.name.clone(),
            email: email.or(record.email.clone()),
            company,
            recent_meetings: record.meetings.iter().take(3).cloned().collect(),
        }
    } else {
        let company = email.as_deref().and_then(company_from_email);
        ParticipantInfo {
            name,
            email,
            company,
            recent_meetings: Vec::new(),
        }
    };

    Ok(info)
}

#[tauri::command]
pub async fn update_participant_index(
    app: tauri::AppHandle,
    meeting_id: String,
) -> Result<(), String> {
    let recordings_dir = {
        let store = app
            .store("settings.json")
            .map_err(|e| format!("Failed to open settings store: {}", e))?;
        store
            .get("recordingsFolder")
            .and_then(|v| v.as_str().map(|s| s.to_string()))
            .ok_or("Recordings folder not configured")?
    };

    let json_path = PathBuf::from(&recordings_dir).join(format!("{}.meeting.json", meeting_id));
    if !json_path.exists() {
        return Ok(());
    }

    let content = std::fs::read_to_string(&json_path)
        .map_err(|e| format!("Failed to read meeting file: {}", e))?;
    let meta: serde_json::Value =
        serde_json::from_str(&content).map_err(|e| format!("Failed to parse meeting file: {}", e))?;

    let title = meta
        .get("title")
        .and_then(|v| v.as_str())
        .unwrap_or("Untitled")
        .to_string();
    let date = meta
        .get("date")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let company = meta
        .get("company")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());

    let participants: Vec<String> = meta
        .get("participants")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(|s| s.to_string()))
                .collect()
        })
        .unwrap_or_default();

    let meeting_entry = ParticipantMeeting {
        id: meeting_id,
        title,
        date,
    };

    let index = app.state::<ParticipantIndexState>();
    let mut index = index.lock().map_err(|e| format!("Index lock failed: {}", e))?;

    for participant_name in &participants {
        let key = participant_name.to_lowercase();
        let record = index.records.entry(key).or_insert_with(|| ParticipantRecord {
            name: participant_name.clone(),
            email: None,
            company: company.clone(),
            meetings: Vec::new(),
        });
        if !record.meetings.iter().any(|m| m.id == meeting_entry.id) {
            record.meetings.insert(0, meeting_entry.clone());
        }
        if record.company.is_none() {
            record.company = company.clone();
        }
    }

    Ok(())
}
