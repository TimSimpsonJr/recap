use serde::Deserialize;

use super::types::{MeetingMetadata, MeetingPlatform, Participant};

const MEET_API_BASE: &str = "https://meet.googleapis.com/v2";
const GOOGLE_TOKEN_URL: &str = "https://oauth2.googleapis.com/token";

/// Errors from Google Meet API calls. All are non-fatal — caller falls back to minimal metadata.
#[derive(Debug)]
pub enum GoogleMeetError {
    Request(String),
    Api(u16, String),
    Parse(String),
}

impl std::fmt::Display for GoogleMeetError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            GoogleMeetError::Request(msg) => write!(f, "Google Meet request error: {}", msg),
            GoogleMeetError::Api(status, body) => {
                write!(f, "Google Meet API {}: {}", status, body)
            }
            GoogleMeetError::Parse(msg) => write!(f, "Google Meet parse error: {}", msg),
        }
    }
}

/// Client for the Google Meet REST API (Conference Records).
pub struct GoogleMeetClient {
    access_token: String,
    refresh_token: String,
    client_id: String,
    client_secret: String,
    http: reqwest::Client,
}

impl GoogleMeetClient {
    pub fn new(
        access_token: String,
        refresh_token: String,
        client_id: String,
        client_secret: String,
    ) -> Self {
        Self {
            access_token,
            refresh_token,
            client_id,
            client_secret,
            http: reqwest::Client::new(),
        }
    }

    /// Fetch the most recent completed meeting that ended around the given time.
    ///
    /// Returns None if no matching meeting is found (not an error).
    pub async fn fetch_recent_meeting(
        &mut self,
        ended_around: chrono::DateTime<chrono::Utc>,
    ) -> Result<Option<MeetingMetadata>, GoogleMeetError> {
        // Query conference records that ended after (ended_around - 5 min).
        let search_start = ended_around - chrono::Duration::minutes(5);
        let filter = format!("end_time>\"{}\"", search_start.to_rfc3339());
        let url = format!(
            "{}/conferenceRecords?filter={}&pageSize=10",
            MEET_API_BASE,
            urlencoding::encode(&filter)
        );

        let body = self.authed_get(&url).await?;
        let response: ConferenceRecordListResponse = serde_json::from_str(&body)
            .map_err(|e| GoogleMeetError::Parse(format!("Conference records: {}", e)))?;

        let records = response.conference_records.unwrap_or_default();

        // Find the best match — meeting that ended within 5 minutes of our recording stop.
        let five_minutes = chrono::Duration::minutes(5);
        let mut best: Option<&ConferenceRecord> = None;
        let mut best_diff = chrono::TimeDelta::MAX;

        for record in &records {
            if let Some(ref end_time) = record.end_time {
                if let Ok(end) = chrono::DateTime::parse_from_rfc3339(end_time) {
                    let diff = (end.signed_duration_since(ended_around)).abs();
                    if diff < five_minutes && diff < best_diff {
                        best_diff = diff;
                        best = Some(record);
                    }
                }
            }
        }

        let record = match best {
            Some(r) => r,
            None => return Ok(None),
        };

        // Extract the conference record ID from the resource name (e.g. "conferenceRecords/abc123").
        let record_id = record
            .name
            .as_deref()
            .and_then(|n| n.strip_prefix("conferenceRecords/"))
            .unwrap_or("");

        // Get participants for this meeting.
        let participants = self.get_participants(record_id).await?;

        let start_time = record.start_time.clone().unwrap_or_default();
        let end_time = record.end_time.clone().unwrap_or_default();

        Ok(Some(MeetingMetadata {
            title: record
                .space
                .as_ref()
                .and_then(|s| s.display_name.clone())
                .unwrap_or_else(|| "Google Meet".to_string()),
            platform: MeetingPlatform::GoogleMeet,
            participants,
            user_name: String::new(),
            user_email: String::new(),
            start_time,
            end_time,
        }))
    }

    /// GET conferenceRecords/{id}/participants
    async fn get_participants(
        &mut self,
        record_id: &str,
    ) -> Result<Vec<Participant>, GoogleMeetError> {
        let url = format!(
            "{}/conferenceRecords/{}/participants?pageSize=100",
            MEET_API_BASE, record_id
        );

        let body = self.authed_get(&url).await?;
        let response: ParticipantListResponse = serde_json::from_str(&body)
            .map_err(|e| GoogleMeetError::Parse(format!("Participants: {}", e)))?;

        Ok(response
            .participants
            .unwrap_or_default()
            .into_iter()
            .filter_map(|p| {
                // Skip participants without a display name.
                let name = p
                    .signin_user
                    .as_ref()
                    .and_then(|u| u.display_name.clone())
                    .or_else(|| p.anonymous_user.as_ref().and_then(|u| u.display_name.clone()))?;

                let email = p
                    .signin_user
                    .as_ref()
                    .and_then(|u| u.user.clone());

                let join_time = p.earliest_start_time;
                let leave_time = p.latest_end_time;

                Some(Participant {
                    name,
                    email,
                    join_time,
                    leave_time,
                })
            })
            .collect())
    }

    /// Make an authenticated GET request. Retries once on 401 after refreshing the token.
    async fn authed_get(&mut self, url: &str) -> Result<String, GoogleMeetError> {
        let response = self
            .http
            .get(url)
            .bearer_auth(&self.access_token)
            .send()
            .await
            .map_err(|e| GoogleMeetError::Request(e.to_string()))?;

        let status = response.status().as_u16();

        if status == 401 {
            self.refresh_access_token().await?;

            let retry = self
                .http
                .get(url)
                .bearer_auth(&self.access_token)
                .send()
                .await
                .map_err(|e| GoogleMeetError::Request(e.to_string()))?;

            let retry_status = retry.status().as_u16();
            if !retry.status().is_success() {
                let body = retry.text().await.unwrap_or_default();
                return Err(GoogleMeetError::Api(retry_status, body));
            }

            return retry
                .text()
                .await
                .map_err(|e| GoogleMeetError::Request(e.to_string()));
        }

        if !response.status().is_success() {
            let body = response.text().await.unwrap_or_default();
            return Err(GoogleMeetError::Api(status, body));
        }

        response
            .text()
            .await
            .map_err(|e| GoogleMeetError::Request(e.to_string()))
    }

    /// Refresh the access token using the refresh_token grant type.
    async fn refresh_access_token(&mut self) -> Result<(), GoogleMeetError> {
        let response = self
            .http
            .post(GOOGLE_TOKEN_URL)
            .form(&[
                ("grant_type", "refresh_token"),
                ("refresh_token", &self.refresh_token),
                ("client_id", &self.client_id),
                ("client_secret", &self.client_secret),
            ])
            .send()
            .await
            .map_err(|e| GoogleMeetError::Request(format!("Token refresh: {}", e)))?;

        if !response.status().is_success() {
            let body = response.text().await.unwrap_or_default();
            return Err(GoogleMeetError::Api(
                401,
                format!("Token refresh failed: {}", body),
            ));
        }

        let token_resp: TokenRefreshResponse = response
            .json()
            .await
            .map_err(|e| GoogleMeetError::Parse(format!("Token refresh response: {}", e)))?;

        self.access_token = token_resp.access_token;
        Ok(())
    }
}

// ── Internal API response types ──────────────────────────────────────────────

#[derive(Deserialize)]
struct ConferenceRecordListResponse {
    #[serde(default, rename = "conferenceRecords")]
    conference_records: Option<Vec<ConferenceRecord>>,
}

#[derive(Deserialize)]
struct ConferenceRecord {
    #[serde(default)]
    name: Option<String>,
    #[serde(default, rename = "startTime")]
    start_time: Option<String>,
    #[serde(default, rename = "endTime")]
    end_time: Option<String>,
    #[serde(default)]
    space: Option<SpaceInfo>,
}

#[derive(Deserialize)]
struct SpaceInfo {
    #[serde(default, rename = "displayName")]
    display_name: Option<String>,
}

#[derive(Deserialize)]
struct ParticipantListResponse {
    #[serde(default)]
    participants: Option<Vec<ApiParticipant>>,
}

#[derive(Deserialize)]
struct ApiParticipant {
    #[serde(default, rename = "signinUser")]
    signin_user: Option<SigninUser>,
    #[serde(default, rename = "anonymousUser")]
    anonymous_user: Option<AnonymousUser>,
    #[serde(default, rename = "earliestStartTime")]
    earliest_start_time: Option<String>,
    #[serde(default, rename = "latestEndTime")]
    latest_end_time: Option<String>,
}

#[derive(Deserialize)]
struct SigninUser {
    #[serde(default, rename = "displayName")]
    display_name: Option<String>,
    /// The user resource name — contains the email for Workspace users.
    #[serde(default)]
    user: Option<String>,
}

#[derive(Deserialize)]
struct AnonymousUser {
    #[serde(default, rename = "displayName")]
    display_name: Option<String>,
}

#[derive(Deserialize)]
struct TokenRefreshResponse {
    access_token: String,
}
