use tauri::Manager;
use tauri_plugin_shell::ShellExt;
use tauri_plugin_store::StoreExt;
use tauri_plugin_window_state::{AppHandleExt, StateFlags, WindowExt};

mod briefing;
mod calendar;
mod config_gen;
mod credentials;
mod deep_link;
mod diagnostics;
mod display;
mod meetings;
mod notifications;
mod oauth;
mod recorder;
mod sidecar;
mod tray;

/// Run the Todoist completion sync via sidecar.
///
/// Generates a pipeline config, reads the Todoist API token from the
/// credential store, and launches the sidecar with `--only todoist-sync`.
async fn run_todoist_sync(app: &tauri::AppHandle) -> Result<String, String> {
    // Generate config so the sidecar has up-to-date settings
    let config_path = config_gen::generate_pipeline_config(app.clone()).await?;

    // Read Todoist API token from SecretStore
    let todoist_token = {
        let store = app.state::<credentials::SecretStoreState>();
        let store = store.lock().await;
        store.get("todoist.access_token")
    };

    let token = todoist_token.ok_or_else(|| "Todoist API token not configured".to_string())?;
    if token.is_empty() {
        return Err("Todoist API token is empty".to_string());
    }

    // We need a dummy recording path for the CLI — use the recordings folder
    let recordings_path = {
        let store = app
            .store("settings.json")
            .map_err(|e| format!("Failed to open settings store: {}", e))?;
        store
            .get("recordingsFolder")
            .and_then(|v| v.as_str().map(|s| s.to_string()))
            .ok_or_else(|| "recordingsFolder not set".to_string())?
    };

    // The CLI requires positional audio + metadata args even for --only todoist-sync
    // (they are not used). Pass recordings_path as a dummy for both.
    let args = vec![
        "process".to_string(),
        "--config".to_string(),
        config_path,
        "--only".to_string(),
        "todoist-sync".to_string(),
        recordings_path.clone(),
        recordings_path,
    ];

    let sidecar = app
        .shell()
        .sidecar("recap-pipeline")
        .map_err(|e| format!("Failed to create sidecar command: {}", e))?
        .args(&args)
        .env("TODOIST_API_TOKEN", &token);

    let output = sidecar
        .output()
        .await
        .map_err(|e| format!("Sidecar execution failed: {}", e))?;

    if output.status.success() {
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        Ok(stdout)
    } else {
        let stderr = String::from_utf8_lossy(&output.stderr).to_string();
        Err(format!("Todoist sync failed: {}", stderr))
    }
}

/// Tauri command: manually trigger a Todoist completion sync.
#[tauri::command]
async fn trigger_todoist_sync(app: tauri::AppHandle) -> Result<String, String> {
    run_todoist_sync(&app).await
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_store::Builder::default().build())
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            None,
        ))
        .plugin(
            tauri_plugin_window_state::Builder::default()
                .with_state_flags(
                    StateFlags::POSITION
                        | StateFlags::SIZE
                        | StateFlags::MAXIMIZED
                        | StateFlags::VISIBLE
                        | StateFlags::FULLSCREEN,
                )
                .build(),
        )
        .setup(|app| {
            // Ensure decorations are disabled (window-state plugin may restore them)
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_decorations(false);
            }

            // Encrypted credential store (AES-256-GCM, key derived from machine identity)
            credentials::init_secret_store(app)?;

            // Deep link plugin
            app.handle().plugin(tauri_plugin_deep_link::init())?;

            // Recorder managed state
            let recorder_handle = recorder::recorder::RecorderHandle::new(app.handle().clone());
            app.manage(recorder_handle);

            // Start localhost HTTP listener for browser extension
            let listener_tx = {
                // Create a channel for the listener — events will be processed
                // by the recorder when monitoring starts. For now we create a
                // standalone channel; events from the extension flow through the
                // same MonitorEvent enum as WASAPI polling.
                let (tx, mut rx) = tokio::sync::mpsc::channel::<recorder::monitor::MonitorEvent>(64);

                // Spawn a task that forwards listener events to the recorder.
                let forward_handle = app.state::<recorder::recorder::RecorderHandle<tauri::Wry>>().handle().clone();
                tauri::async_runtime::spawn(async move {
                    while let Some(event) = rx.recv().await {
                        let mut inner = forward_handle.lock().await;
                        match event {
                            recorder::monitor::MonitorEvent::BrowserMeetingDetected {
                                url, title, platform, tab_id,
                            } => {
                                inner.on_browser_meeting_detected(url, title, platform, tab_id);
                            }
                            recorder::monitor::MonitorEvent::BrowserMeetingEnded { tab_id } => {
                                inner.on_browser_meeting_ended(tab_id);
                            }
                            recorder::monitor::MonitorEvent::SharingStarted => {
                                inner.on_sharing_started();
                            }
                            recorder::monitor::MonitorEvent::SharingStopped => {
                                inner.on_sharing_stopped();
                            }
                            recorder::monitor::MonitorEvent::MeetingDetected { process_name, pid } => {
                                inner.on_meeting_detected(process_name, pid);
                            }
                            recorder::monitor::MonitorEvent::MeetingEnded { pid } => {
                                inner.on_meeting_ended(pid);
                            }
                        }
                    }
                });

                tx
            };
            tauri::async_runtime::spawn(async move {
                match recorder::listener::start_listener(listener_tx).await {
                    Ok(port) => log::info!("Extension listener on port {}", port),
                    Err(e) => log::warn!("Failed to start extension listener: {}", e),
                }
            });

            // System tray
            tray::create_tray(app.handle())?;

            // Deep link handler
            deep_link::setup_deep_links(app.handle())?;

            // Start periodic notification check (every 60 seconds)
            let notification_handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                let mut interval = tokio::time::interval(std::time::Duration::from_secs(60));
                loop {
                    interval.tick().await;
                    let _ = notifications::check_upcoming_notifications(&notification_handle);
                }
            });

            // Start periodic auto-record check (every 60 seconds)
            {
                let auto_record_handle = app.handle().clone();
                let auto_record_recorder = app
                    .state::<recorder::recorder::RecorderHandle<tauri::Wry>>()
                    .handle()
                    .clone();

                // Immediate check on startup (for late-start scenarios)
                let startup_handle = auto_record_handle.clone();
                let startup_recorder = auto_record_recorder.clone();
                tauri::async_runtime::spawn(async move {
                    recorder::recorder::check_auto_record_events(
                        &startup_handle,
                        &startup_recorder,
                    )
                    .await;
                });

                // Periodic check
                tauri::async_runtime::spawn(async move {
                    let mut interval =
                        tokio::time::interval(std::time::Duration::from_secs(60));
                    loop {
                        interval.tick().await;
                        recorder::recorder::check_auto_record_events(
                            &auto_record_handle,
                            &auto_record_recorder,
                        )
                        .await;
                    }
                });
            }

            // Todoist completion sync timer
            {
                let app_handle_todoist = app.handle().clone();
                tauri::async_runtime::spawn(async move {
                    loop {
                        // Read interval from settings store (default 15 min)
                        let interval_mins = {
                            let store = app_handle_todoist.store("settings.json").ok();
                            store
                                .and_then(|s| {
                                    s.get("todoistSyncInterval")
                                        .and_then(|v| v.as_u64())
                                })
                                .unwrap_or(15)
                        };
                        tokio::time::sleep(std::time::Duration::from_secs(
                            interval_mins * 60,
                        ))
                        .await;

                        // Check if Todoist is configured before syncing
                        let has_token = {
                            let store =
                                app_handle_todoist.state::<credentials::SecretStoreState>();
                            let store = store.lock().await;
                            store
                                .get("todoist.access_token")
                                .map(|t| !t.is_empty())
                                .unwrap_or(false)
                        };

                        if has_token {
                            match run_todoist_sync(&app_handle_todoist).await {
                                Ok(_) => log::info!("Todoist auto-sync completed"),
                                Err(e) => log::warn!("Todoist auto-sync failed: {}", e),
                            }
                        }
                    }
                });
            }

            // Show the main window on launch.
            // TODO: When auto-start-with-Windows is implemented, check if launched
            // via startup and hide instead (start in tray).
            if let Some(window) = app.get_webview_window("main") {
                // Restore saved window state (size, position) if available
                let _ = window.restore_state(StateFlags::all());
                let _ = window.show();
                let _ = window.set_focus();
            }

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            credentials::save_secret,
            credentials::get_secret,
            credentials::delete_secret,
            oauth::start_oauth,
            oauth::exchange_oauth_code,
            sidecar::run_pipeline,
            sidecar::check_sidecar_status,
            recorder::recorder::get_recorder_state,
            recorder::recorder::start_recording,
            recorder::recorder::stop_recording,
            recorder::recorder::cancel_recording,
            recorder::recorder::retry_processing,
            diagnostics::check_nvenc,
            diagnostics::check_ffmpeg,
            meetings::list_meetings,
            meetings::get_meeting_detail,
            meetings::search_meetings,
            meetings::get_filter_options,
            meetings::get_graph_data,
            meetings::get_known_participants,
            meetings::update_speaker_labels,
            meetings::delete_meetings,
            meetings::reprocess_meetings,
            meetings::bulk_rename_speaker,
            meetings::get_speakers_for_meetings,
            meetings::relink_vault_notes,
            calendar::fetch_calendar_events,
            calendar::get_upcoming_meetings,
            calendar::sync_calendar,
            calendar::get_calendar_last_synced,
            calendar::get_calendar_matches,
            calendar::set_auto_record,
            calendar::set_series_auto_record,
            calendar::get_auto_record_events,
            briefing::generate_briefing,
            briefing::invalidate_briefing_cache,
            display::list_monitors,
            config_gen::generate_pipeline_config,
            config_gen::check_drive_type,
            trigger_todoist_sync,
        ])
        .on_window_event(|window, event| {
            // Closing the window hides it instead of quitting
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                // Save window state before hiding (plugin won't save on hide)
                let _ = window.app_handle().save_window_state(StateFlags::all());
                let _ = window.hide();
                api.prevent_close();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
