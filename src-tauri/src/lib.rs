use tauri::Manager;

mod credentials;
mod deep_link;
mod diagnostics;
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
        .plugin(tauri_plugin_store::Builder::default().build())
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            None,
        ))
        .setup(|app| {
            // Stronghold with Argon2 password hashing
            let salt_path = app
                .path()
                .app_local_data_dir()
                .expect("could not resolve app local data path")
                .join("salt.txt");
            app.handle().plugin(
                tauri_plugin_stronghold::Builder::with_argon2(&salt_path).build(),
            )?;

            // Deep link plugin
            app.handle().plugin(tauri_plugin_deep_link::init())?;

            // Recorder managed state
            let recorder_handle = recorder::recorder::RecorderHandle::new(app.handle().clone());
            app.manage(recorder_handle);

            // System tray
            tray::create_tray(app.handle())?;

            // Deep link handler
            deep_link::setup_deep_links(app.handle())?;

            // Start minimized to tray — hide the main window
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.hide();
            }

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            credentials::store_credential,
            credentials::get_provider_status,
            oauth::start_oauth,
            oauth::exchange_oauth_code,
            sidecar::run_pipeline,
            sidecar::check_sidecar_status,
            recorder::recorder::get_recorder_state,
            recorder::recorder::start_recording,
            recorder::recorder::stop_recording,
            recorder::recorder::retry_processing,
            diagnostics::check_nvenc,
            diagnostics::check_ffmpeg,
        ])
        .on_window_event(|window, event| {
            // Closing the window hides it instead of quitting
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                let _ = window.hide();
                api.prevent_close();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
