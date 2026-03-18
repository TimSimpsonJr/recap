use serde::{Deserialize, Serialize};

const ZOOM_API_BASE: &str = "https://api.zoom.us/v2";

/// Errors from Zoom API calls. All are non-fatal — caller falls back to minimal metadata.
#[derive(Debug)]
pub enum ZoomError {
    Request(String),
    Api(u16, String),
    Parse(String),
}

impl std::fmt::Display for ZoomError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ZoomError::Request(msg) => write!(f, "Zoom request error: {}", msg),
            ZoomError::Api(status, body) => write!(f, "Zoom API {}: {}", status, body),
            ZoomError::Parse(msg) => write!(f, "Zoom parse error: {}", msg),
        }
    }
}

/// Meeting metadata retrieved from Zoom API.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ZoomMeetingInfo {
    pub title: String,
    pub participants: Vec<ZoomParticipant>,
    pub user_email: String,
    pub user_name: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ZoomParticipant {
    pub name: String,
    pub email: Option<String>,
    pub join_time: String,
    pub leave_time: String,
}

/// Client for the Zoom REST API.
pub struct ZoomClient {
    access_token: String,
    refresh_token: String,
    client_id: String,
    client_secret: String,
    http: reqwest::Client,
}

impl ZoomClient {
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
    ) -> Result<Option<ZoomMeetingInfo>, ZoomError> {
        // Get user info first.
        let user = self.get_user_info().await?;

        // Get recent completed meetings.
        let meetings = self.get_recent_meetings().await?;

        // Find the best match — meeting that ended within 5 minutes of our recording stop.
        let five_minutes = chrono::Duration::minutes(5);
        let mut best: Option<&PastMeeting> = None;
        let mut best_diff = chrono::TimeDelta::MAX;

        for meeting in &meetings {
            if let Ok(end_time) = chrono::DateTime::parse_from_rfc3339(&meeting.end_time) {
                let diff = (end_time.signed_duration_since(ended_around)).abs();
                if diff < five_minutes && diff < best_diff {
                    best_diff = diff;
                    best = Some(meeting);
                }
            }
        }

        let meeting = match best {
            Some(m) => m,
            None => return Ok(None),
        };

        // Get participants for this meeting.
        let participants = self.get_participants(&meeting.id.to_string()).await?;

        Ok(Some(ZoomMeetingInfo {
            title: meeting.topic.clone(),
            participants,
            user_email: user.email,
            user_name: user.display_name,
        }))
    }

    /// GET /v2/users/me
    async fn get_user_info(&mut self) -> Result<UserInfo, ZoomError> {
        let body = self
            .api_get(&format!("{}/users/me", ZOOM_API_BASE))
            .await?;

        serde_json::from_str(&body)
            .map_err(|e| ZoomError::Parse(format!("User info: {}", e)))
    }

    /// GET /v2/users/me/meetings?type=previous_meetings
    async fn get_recent_meetings(&mut self) -> Result<Vec<PastMeeting>, ZoomError> {
        let body = self
            .api_get(&format!(
                "{}/users/me/meetings?type=previous_meetings&page_size=10",
                ZOOM_API_BASE
            ))
            .await?;

        let response: MeetingListResponse = serde_json::from_str(&body)
            .map_err(|e| ZoomError::Parse(format!("Meeting list: {}", e)))?;

        Ok(response.meetings)
    }

    /// GET /v2/past_meetings/{meetingId}/participants
    async fn get_participants(
        &mut self,
        meeting_id: &str,
    ) -> Result<Vec<ZoomParticipant>, ZoomError> {
        let body = self
            .api_get(&format!(
                "{}/past_meetings/{}/participants",
                ZOOM_API_BASE, meeting_id
            ))
            .await?;

        let response: ParticipantListResponse = serde_json::from_str(&body)
            .map_err(|e| ZoomError::Parse(format!("Participants: {}", e)))?;

        Ok(response
            .participants
            .into_iter()
            .map(|p| ZoomParticipant {
                name: p.name,
                email: if p.user_email.is_empty() {
                    None
                } else {
                    Some(p.user_email)
                },
                join_time: p.join_time,
                leave_time: p.leave_time,
            })
            .collect())
    }

    /// Make an authenticated GET request. Retries once on 401 after refreshing the token.
    async fn api_get(&mut self, url: &str) -> Result<String, ZoomError> {
        let response = self
            .http
            .get(url)
            .bearer_auth(&self.access_token)
            .send()
            .await
            .map_err(|e| ZoomError::Request(e.to_string()))?;

        let status = response.status().as_u16();

        if status == 401 {
            // Try refreshing the token once.
            self.refresh_access_token().await?;

            let retry = self
                .http
                .get(url)
                .bearer_auth(&self.access_token)
                .send()
                .await
                .map_err(|e| ZoomError::Request(e.to_string()))?;

            let retry_status = retry.status().as_u16();
            if !retry.status().is_success() {
                let body = retry.text().await.unwrap_or_default();
                return Err(ZoomError::Api(retry_status, body));
            }

            return retry
                .text()
                .await
                .map_err(|e| ZoomError::Request(e.to_string()));
        }

        if !response.status().is_success() {
            let body = response.text().await.unwrap_or_default();
            return Err(ZoomError::Api(status, body));
        }

        response
            .text()
            .await
            .map_err(|e| ZoomError::Request(e.to_string()))
    }

    /// Refresh the access token using the refresh_token grant type.
    async fn refresh_access_token(&mut self) -> Result<(), ZoomError> {
        let response = self
            .http
            .post("https://zoom.us/oauth/token")
            .basic_auth(&self.client_id, Some(&self.client_secret))
            .form(&[
                ("grant_type", "refresh_token"),
                ("refresh_token", &self.refresh_token),
            ])
            .send()
            .await
            .map_err(|e| ZoomError::Request(format!("Token refresh: {}", e)))?;

        if !response.status().is_success() {
            let body = response.text().await.unwrap_or_default();
            return Err(ZoomError::Api(401, format!("Token refresh failed: {}", body)));
        }

        let token_resp: TokenRefreshResponse = response
            .json()
            .await
            .map_err(|e| ZoomError::Parse(format!("Token refresh response: {}", e)))?;

        self.access_token = token_resp.access_token;
        Ok(())
    }
}

/// Generate fallback metadata when Zoom API is unavailable.
pub fn fallback_metadata() -> serde_json::Value {
    serde_json::json!({
        "title": "Zoom Meeting",
        "date": chrono::Local::now().format("%Y-%m-%d").to_string(),
        "participants": [],
        "platform": "zoom"
    })
}

// ── Internal API response types ──────────────────────────────────────────────

#[derive(Deserialize)]
struct UserInfo {
    #[serde(default)]
    email: String,
    #[serde(default)]
    display_name: String,
}

#[derive(Deserialize)]
struct MeetingListResponse {
    #[serde(default)]
    meetings: Vec<PastMeeting>,
}

#[derive(Deserialize)]
struct PastMeeting {
    id: u64,
    #[serde(default)]
    topic: String,
    #[serde(default)]
    end_time: String,
}

#[derive(Deserialize)]
struct ParticipantListResponse {
    #[serde(default)]
    participants: Vec<ApiParticipant>,
}

#[derive(Deserialize)]
struct ApiParticipant {
    #[serde(default)]
    name: String,
    #[serde(default)]
    user_email: String,
    #[serde(default)]
    join_time: String,
    #[serde(default)]
    leave_time: String,
}

#[derive(Deserialize)]
struct TokenRefreshResponse {
    access_token: String,
}
