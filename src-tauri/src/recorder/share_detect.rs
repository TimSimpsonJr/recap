use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread::{self, JoinHandle};
use std::time::Duration;

use tokio::sync::mpsc;

use super::monitor::MonitorEvent;
use windows::Win32::Foundation::{BOOL, HWND, LPARAM, TRUE};
use windows::Win32::UI::WindowsAndMessaging::{EnumWindows, GetClassNameW, IsWindowVisible};

/// Known screen-sharing toolbar window classes by platform.
const ZOOM_SHARE_CLASS: &str = "ZPToolBarParentWndClass";
const TEAMS_SHARE_CLASS_FRAGMENT: &str = "TeamsShareToolbar";

/// Start monitoring for screen-sharing toolbar windows on a background thread.
///
/// Polls `EnumWindows` every 1 second, checking visible windows for known
/// sharing indicator classes (Zoom, Teams). Emits `MonitorEvent::SharingStarted`
/// when a toolbar appears and `MonitorEvent::SharingStopped` when it disappears.
///
/// Returns a join handle and a stop flag (same pattern as `monitor.rs`).
pub fn start_share_monitor(
    tx: mpsc::Sender<MonitorEvent>,
    _target_pid: u32,
) -> (JoinHandle<()>, Arc<AtomicBool>) {
    let stop = Arc::new(AtomicBool::new(false));
    let stop_clone = stop.clone();

    let handle = thread::spawn(move || {
        let mut was_sharing = false;

        while !stop_clone.load(Ordering::Relaxed) {
            let sharing_now = detect_sharing_toolbar();

            if sharing_now && !was_sharing {
                let _ = tx.blocking_send(MonitorEvent::SharingStarted);
            } else if !sharing_now && was_sharing {
                let _ = tx.blocking_send(MonitorEvent::SharingStopped);
            }

            was_sharing = sharing_now;
            thread::sleep(Duration::from_secs(1));
        }
    });

    (handle, stop)
}

/// Check if any visible window matches a known screen-sharing toolbar class.
fn detect_sharing_toolbar() -> bool {
    struct EnumState {
        found: bool,
    }

    let mut state = EnumState { found: false };

    unsafe extern "system" fn enum_callback(hwnd: HWND, lparam: LPARAM) -> BOOL {
        let state = &mut *(lparam.0 as *mut EnumState);

        if !IsWindowVisible(hwnd).as_bool() {
            return TRUE;
        }

        let mut class_buf = [0u16; 256];
        let len = GetClassNameW(hwnd, &mut class_buf);
        if len == 0 {
            return TRUE;
        }

        let class_name = String::from_utf16_lossy(&class_buf[..len as usize]);

        if class_name == ZOOM_SHARE_CLASS || class_name.contains(TEAMS_SHARE_CLASS_FRAGMENT) {
            state.found = true;
            // Stop enumerating — we found a match.
            return BOOL(0);
        }

        TRUE
    }

    unsafe {
        let _ = EnumWindows(
            Some(enum_callback),
            LPARAM(&mut state as *mut EnumState as isize),
        );
    }

    state.found
}
