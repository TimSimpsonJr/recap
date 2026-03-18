use tauri::{
    menu::{Menu, MenuItem, PredefinedMenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Emitter, Manager, Runtime,
};

use crate::recorder::recorder::RecorderHandle;
use crate::recorder::types::RecorderState;

pub fn create_tray<R: Runtime>(app: &tauri::AppHandle<R>) -> tauri::Result<()> {
    let start_recording =
        MenuItem::with_id(app, "start_recording", "Start Recording", false, None::<&str>)?;
    let stop_recording =
        MenuItem::with_id(app, "stop_recording", "Stop Recording", false, None::<&str>)?;
    let separator1 = PredefinedMenuItem::separator(app)?;
    let open_dashboard =
        MenuItem::with_id(app, "open_dashboard", "Open Dashboard", true, None::<&str>)?;
    let settings = MenuItem::with_id(app, "settings", "Settings", true, None::<&str>)?;
    let separator2 = PredefinedMenuItem::separator(app)?;
    let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;

    let menu = Menu::with_items(
        app,
        &[
            &start_recording,
            &stop_recording,
            &separator1,
            &open_dashboard,
            &settings,
            &separator2,
            &quit,
        ],
    )?;

    let icon = app
        .default_window_icon()
        .cloned()
        .expect("app should have a default icon");

    TrayIconBuilder::new()
        .icon(icon)
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "start_recording" => {
                let app = app.clone();
                tauri::async_runtime::spawn(async move {
                    let state = app.state::<RecorderHandle<tauri::Wry>>();
                    let mut inner = state.handle().lock().await;
                    if let RecorderState::Detected { ref process_name, pid } = inner.state().clone() {
                        if let Err(e) = inner.start_capture(process_name.clone(), pid) {
                            log::error!("Failed to start recording: {}", e);
                        }
                    }
                });
            }
            "stop_recording" => {
                let app = app.clone();
                tauri::async_runtime::spawn(async move {
                    let state = app.state::<RecorderHandle<tauri::Wry>>();
                    let mut inner = state.handle().lock().await;
                    if inner.state() == RecorderState::Recording {
                        inner.cancel_recording();
                    }
                });
            }
            "open_dashboard" => {
                show_main_window(app);
            }
            "settings" => {
                show_main_window(app);
                let _ = app.emit("navigate", "/settings");
            }
            "quit" => {
                app.exit(0);
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                let app = tray.app_handle();
                show_main_window(app);
            }
        })
        .build(app)?;

    Ok(())
}

fn show_main_window<R: Runtime>(app: &tauri::AppHandle<R>) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}
