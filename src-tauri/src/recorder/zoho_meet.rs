use serde::Deserialize;

use super::types::{MeetingMetadata, MeetingPlatform, Participant};

/// Errors from Zoho Meeting API calls. All are non-fatal — caller falls back to minimal metadata.
#[derive(Debug)]
pub enum ZohoMeetError {
    Request(String),
    Api(u16, String),
    Parse(String),
}

impl std::fmt::Display for ZohoMeetError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ZohoMeetError::Request(msg) => write!(f, "Zoho Meeting request error: {}", msg),
            ZohoMeetError::Api(status, body) => {
                write!(f, "Zoho Meeting API {}: {}", status, body)
            }
            ZohoMeetError::Parse(msg) => write!(f, "Zoho Meeting parse error: {}", msg),
        }
    }
}

/// Client for the Zoho Meeting REST API.
pub struct ZohoMeetClient {
    access_token: String,
    refresh_token: String,
    client_id: String,
    client_secret: String,
    region: String,
    http: reqwest::Client,
}

impl ZohoMeetClient {
    pub fn new(
        access_token: String,
        refresh_token: String,
        client_id: String,
        client_secret: String,
        region: String,
    ) -> Self {
        Self {
            access_token,
            refresh_token,
            client_id,
            client_secret,
            region,
            http: reqwest::Client::new(),
        }
    }

    fn api_base(&self) -> String {
        format!("https://meeting.zoho.{}/api/v1", self.region)
    }

    fn token_url(&self) -> String {
        format!("https://accounts.zoho.{}/oauth/v2/token", self.region)
    }

    /// Fetch the most recent completed meeting that ended around the given time.
    ///
    /// Returns None if no matching meeting is found (not an error).
    pub async fn fetch_recent_meeting(
        &mut self,
        ended_around: chrono::DateTime<chrono::Utc>,
    ) -> Result<Option<MeetingMetadata>, ZohoMeetError> {
        let url = format!("{}/meetings?status=completed", self.api_base());
        let body = self.authed_get(&url).await?;

        let response: MeetingListResponse = serde_json::from_str(&body)
            .map_err(|e| ZohoMeetError::Parse(format!("Meeting list: {}", e)))?;

        let meetings = response.session.unwrap_or_default();

        // Find the best match — meeting that ended within 5 minutes of our recording stop.
        let five_minutes = chrono::Duration::minutes(5);
        let mut best: Option<&ZohoMeeting> = None;
        let mut best_diff = chrono::TimeDelta::MAX;

        for meeting in &meetings {
            if let Some(ref end_time) = meeting.end_time {
                // Try RFC 3339 first, then fall back to a common Zoho datetime format.
                // NOTE: The actual format returned by the Zoho Meeting API should be
                // verified against real API responses and adjusted if needed.
                let parsed = chrono::DateTime::parse_from_rfc3339(end_time).or_else(|_| {
                    chrono::NaiveDateTime::parse_from_str(end_time, "%b %d, %Y %I:%M %p")
                        .map(|naive| {
                            naive
                                .and_utc()
                                .fixed_offset()
                        })
                });
                if let Ok(end) = parsed {
                    let diff = (end.signed_duration_since(ended_around)).abs();
                    if diff < five_minutes && diff < best_diff {
                        best_diff = diff;
                        best = Some(meeting);
                    }
                }
            }
        }

        let meeting = match best {
            Some(m) => m,
            None => return Ok(None),
        };

        let meeting_key = meeting.meeting_key.clone().unwrap_or_default();
        let title = meeting.topic.clone().unwrap_or_else(|| "Zoho Meeting".to_string());
        let start_time = meeting.start_time.clone().unwrap_or_default();
        let end_time = meeting.end_time.clone().unwrap_or_default();

        // Get attendees for this meeting.
        let participants = self.get_attendees(&meeting_key).await?;

        // Get presenter info if available.
        let user_name = meeting.presenter.as_ref()
            .and_then(|p| p.name.clone())
            .unwrap_or_default();
        let user_email = meeting.presenter.as_ref()
            .and_then(|p| p.email.clone())
            .unwrap_or_default();

        Ok(Some(MeetingMetadata {
            title,
            platform: MeetingPlatform::ZohoMeet,
            participants,
            user_name,
            user_email,
            start_time,
            end_time,
        }))
    }

    /// GET /meetings/{meetingKey}/attendees
    async fn get_attendees(
        &mut self,
        meeting_key: &str,
    ) -> Result<Vec<Participant>, ZohoMeetError> {
        let url = format!("{}/meetings/{}/attendees", self.api_base(), meeting_key);
        let body = self.authed_get(&url).await?;

        let response: AttendeeListResponse = serde_json::from_str(&body)
            .map_err(|e| ZohoMeetError::Parse(format!("Attendees: {}", e)))?;

        Ok(response
            .attendees
            .unwrap_or_default()
            .into_iter()
            .map(|a| Participant {
                name: a.name.unwrap_or_default(),
                email: a.email,
                join_time: a.join_time,
                leave_time: a.leave_time,
            })
            .collect())
    }

    /// Make an authenticated GET request. Retries once on 401 after refreshing the token.
    /// Zoho uses `Zoho-oauthtoken` header instead of Bearer.
    async fn authed_get(&mut self, url: &str) -> Result<String, ZohoMeetError> {
        let response = self
            .http
            .get(url)
            .header("Authorization", format!("Zoho-oauthtoken {}", self.access_token))
            .send()
            .await
            .map_err(|e| ZohoMeetError::Request(e.to_string()))?;

        let status = response.status().as_u16();

        if status == 401 {
            self.refresh_access_token().await?;

            let retry = self
                .http
                .get(url)
                .header("Authorization", format!("Zoho-oauthtoken {}", self.access_token))
                .send()
                .await
                .map_err(|e| ZohoMeetError::Request(e.to_string()))?;

            let retry_status = retry.status().as_u16();
            if !retry.status().is_success() {
                let body = retry.text().await.unwrap_or_default();
                return Err(ZohoMeetError::Api(retry_status, body));
            }

            return retry
                .text()
                .await
                .map_err(|e| ZohoMeetError::Request(e.to_string()));
        }

        if !response.status().is_success() {
            let body = response.text().await.unwrap_or_default();
            return Err(ZohoMeetError::Api(status, body));
        }

        response
            .text()
            .await
            .map_err(|e| ZohoMeetError::Request(e.to_string()))
    }

    /// Refresh the access token using the refresh_token grant type.
    async fn refresh_access_token(&mut self) -> Result<(), ZohoMeetError> {
        let token_url = self.token_url();
        let response = self
            .http
            .post(&token_url)
            .form(&[
                ("grant_type", "refresh_token"),
                ("refresh_token", self.refresh_token.as_str()),
                ("client_id", self.client_id.as_str()),
                ("client_secret", self.client_secret.as_str()),
            ])
            .send()
            .await
            .map_err(|e| ZohoMeetError::Request(format!("Token refresh: {}", e)))?;

        if !response.status().is_success() {
            let body = response.text().await.unwrap_or_default();
            return Err(ZohoMeetError::Api(
                401,
                format!("Token refresh failed: {}", body),
            ));
        }

        let token_resp: TokenRefreshResponse = response
            .json()
            .await
            .map_err(|e| ZohoMeetError::Parse(format!("Token refresh response: {}", e)))?;

        self.access_token = token_resp.access_token;
        Ok(())
    }
}

// ── Internal API response types ──────────────────────────────────────────────

#[derive(Deserialize)]
struct MeetingListResponse {
    #[serde(default)]
    session: Option<Vec<ZohoMeeting>>,
}

#[derive(Deserialize)]
struct ZohoMeeting {
    #[serde(default, rename = "meetingKey")]
    meeting_key: Option<String>,
    #[serde(default)]
    topic: Option<String>,
    #[serde(default, rename = "startTime")]
    start_time: Option<String>,
    #[serde(default, rename = "endTime")]
    end_time: Option<String>,
    #[serde(default)]
    presenter: Option<PresenterInfo>,
}

#[derive(Deserialize)]
struct PresenterInfo {
    #[serde(default)]
    name: Option<String>,
    #[serde(default)]
    email: Option<String>,
}

#[derive(Deserialize)]
struct AttendeeListResponse {
    #[serde(default)]
    attendees: Option<Vec<ZohoAttendee>>,
}

#[derive(Deserialize)]
struct ZohoAttendee {
    #[serde(default)]
    name: Option<String>,
    #[serde(default)]
    email: Option<String>,
    #[serde(default, rename = "joinTime")]
    join_time: Option<String>,
    #[serde(default, rename = "leaveTime")]
    leave_time: Option<String>,
}

#[derive(Deserialize)]
struct TokenRefreshResponse {
    access_token: String,
}
