use std::collections::HashMap;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

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
