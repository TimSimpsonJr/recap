use crate::calendar::CalendarEvent;

use super::types::{MeetingMetadata, MeetingPlatform, Participant};

/// Build Teams meeting metadata from available sources.
///
/// Teams personal accounts can't access the Graph meeting APIs, so we use a
/// two-tier fallback:
/// 1. If a matching calendar event exists, use its title and participants.
/// 2. Otherwise, read the Teams window title via Win32 for the meeting name.
pub fn build_teams_metadata(
    calendar_match: Option<&CalendarEvent>,
    target_pid: Option<u32>,
    start_time: &str,
    end_time: &str,
) -> MeetingMetadata {
    if let Some(event) = calendar_match {
        return MeetingMetadata {
            title: event.title.clone(),
            platform: MeetingPlatform::Teams,
            participants: event
                .participants
                .iter()
                .map(|p| Participant {
                    name: p.name.clone(),
                    email: p.email.clone(),
                    join_time: None,
                    leave_time: None,
                })
                .collect(),
            user_name: String::new(),
            user_email: String::new(),
            start_time: start_time.to_string(),
            end_time: end_time.to_string(),
        };
    }

    // Fallback: read the Teams window title.
    let title = target_pid
        .and_then(get_teams_window_title)
        .unwrap_or_else(|| "Teams Meeting".to_string());

    MeetingMetadata {
        title,
        platform: MeetingPlatform::Teams,
        participants: Vec::new(),
        user_name: String::new(),
        user_email: String::new(),
        start_time: start_time.to_string(),
        end_time: end_time.to_string(),
    }
}

/// Find the visible Teams window for the given PID and return its title,
/// with the " | Microsoft Teams" suffix stripped.
fn get_teams_window_title(pid: u32) -> Option<String> {
    use std::sync::Mutex;
    use windows::Win32::Foundation::{BOOL, HWND, LPARAM};
    use windows::Win32::UI::WindowsAndMessaging::{
        EnumWindows, GetWindowTextW, GetWindowThreadProcessId, IsWindowVisible,
    };

    // Collect matching window titles via the EnumWindows callback.
    struct CallbackState {
        target_pid: u32,
        title: Option<String>,
    }

    let state = Mutex::new(CallbackState {
        target_pid: pid,
        title: None,
    });

    unsafe extern "system" fn enum_callback(hwnd: HWND, lparam: LPARAM) -> BOOL {
        let state = &*(lparam.0 as *const Mutex<CallbackState>);

        // Skip invisible windows.
        if !IsWindowVisible(hwnd).as_bool() {
            return BOOL(1); // Continue enumeration.
        }

        // Check if this window belongs to our target PID.
        let mut window_pid: u32 = 0;
        GetWindowThreadProcessId(hwnd, Some(&mut window_pid));
        let target_pid = {
            let s = state.lock().unwrap();
            s.target_pid
        };
        if window_pid != target_pid {
            return BOOL(1);
        }

        // Read the window title.
        let mut buf = [0u16; 512];
        let len = GetWindowTextW(hwnd, &mut buf);
        if len == 0 {
            return BOOL(1);
        }

        let raw_title = String::from_utf16_lossy(&buf[..len as usize]);

        // Teams meeting windows contain "| Microsoft Teams".
        if raw_title.contains("Microsoft Teams") {
            let title = raw_title
                .trim_end_matches("| Microsoft Teams")
                .trim_end_matches("- Microsoft Teams")
                .trim()
                .to_string();

            let mut s = state.lock().unwrap();
            if !title.is_empty() {
                s.title = Some(title);
            }
            return BOOL(0); // Stop enumeration.
        }

        BOOL(1) // Continue.
    }

    unsafe {
        let _ = EnumWindows(
            Some(enum_callback),
            LPARAM(&state as *const Mutex<CallbackState> as isize),
        );
    }

    state.into_inner().unwrap().title
}
