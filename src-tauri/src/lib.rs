use tauri::Manager;
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
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .setup(|app| {
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
