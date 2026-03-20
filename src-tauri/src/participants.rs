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
