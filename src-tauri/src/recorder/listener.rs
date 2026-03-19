use axum::{
    extract::{Request, State},
    http::StatusCode,
    middleware::{self, Next},
    response::{IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use serde::Deserialize;
use std::net::SocketAddr;
use std::sync::Arc;
use tokio::sync::mpsc;

use super::monitor::MonitorEvent;
use super::types::MeetingPlatform;

#[derive(Debug, Deserialize)]
pub struct MeetingDetectedPayload {
    pub url: String,
    pub title: String,
    pub platform: String,
    pub tab_id: Option<u32>,
}

#[derive(Debug, Deserialize)]
pub struct MeetingEndedPayload {
    pub tab_id: Option<u32>,
}

#[derive(Debug, Deserialize)]
pub struct SharingPayload {
    pub tab_id: Option<u32>,
}

struct ListenerState {
    tx: mpsc::Sender<MonitorEvent>,
}

/// Validate the Origin header on incoming requests.
///
/// Allows requests with no Origin header (e.g. curl, testing) or with an Origin
/// from a browser extension (`chrome-extension://` or `moz-extension://`).
/// Rejects all other origins to prevent malicious websites from triggering
/// recording via cross-origin fetch.
fn validate_origin(headers: &axum::http::HeaderMap) -> bool {
    match headers.get("origin") {
        None => true, // No origin = not a browser request, allow
        Some(origin) => {
            let val = origin.to_str().unwrap_or("");
            val.starts_with("chrome-extension://") || val.starts_with("moz-extension://")
        }
    }
}

/// Axum middleware layer that rejects requests with disallowed Origin headers.
async fn origin_check(req: Request, next: Next) -> Response {
    if !validate_origin(req.headers()) {
        log::warn!(
            "Rejected request with disallowed Origin: {:?}",
            req.headers().get("origin")
        );
        return StatusCode::FORBIDDEN.into_response();
    }
    next.run(req).await
}

/// Start the localhost HTTP listener for browser extension communication.
/// Tries ports 17839-17845. Returns the port that was bound.
pub async fn start_listener(tx: mpsc::Sender<MonitorEvent>) -> Result<u16, String> {
    let state = Arc::new(ListenerState { tx });

    let app = Router::new()
        .route("/health", get(health))
        .route("/meeting-detected", post(meeting_detected))
        .route("/meeting-ended", post(meeting_ended))
        .route("/sharing-started", post(sharing_started))
        .route("/sharing-stopped", post(sharing_stopped))
        .layer(middleware::from_fn(origin_check))
        .with_state(state);

    for port in 17839..=17845 {
        let addr = SocketAddr::from(([127, 0, 0, 1], port));
        match tokio::net::TcpListener::bind(addr).await {
            Ok(tcp_listener) => {
                log::info!("Recap listener started on port {}", port);
                tokio::spawn(async move {
                    axum::serve(tcp_listener, app)
                        .await
                        .unwrap_or_else(|e| log::error!("Listener error: {}", e));
                });
                return Ok(port);
            }
            Err(_) => continue,
        }
    }

    Err("Could not bind to any port in range 17839-17845".to_string())
}

async fn health() -> impl IntoResponse {
    StatusCode::OK
}

async fn meeting_detected(
    State(state): State<Arc<ListenerState>>,
    Json(payload): Json<MeetingDetectedPayload>,
) -> impl IntoResponse {
    let platform = MeetingPlatform::from_platform_str(&payload.platform);
    let _ = state
        .tx
        .send(MonitorEvent::BrowserMeetingDetected {
            url: payload.url,
            title: payload.title,
            platform,
            tab_id: payload.tab_id,
        })
        .await;
    StatusCode::OK
}

async fn meeting_ended(
    State(state): State<Arc<ListenerState>>,
    Json(payload): Json<MeetingEndedPayload>,
) -> impl IntoResponse {
    let _ = state
        .tx
        .send(MonitorEvent::BrowserMeetingEnded {
            tab_id: payload.tab_id,
        })
        .await;
    StatusCode::OK
}

async fn sharing_started(
    State(state): State<Arc<ListenerState>>,
    Json(_payload): Json<SharingPayload>,
) -> impl IntoResponse {
    let _ = state.tx.send(MonitorEvent::SharingStarted).await;
    StatusCode::OK
}

async fn sharing_stopped(
    State(state): State<Arc<ListenerState>>,
    Json(_payload): Json<SharingPayload>,
) -> impl IntoResponse {
    let _ = state.tx.send(MonitorEvent::SharingStopped).await;
    StatusCode::OK
}
