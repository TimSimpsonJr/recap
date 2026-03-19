use std::collections::HashSet;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread::{self, JoinHandle};
use std::time::Duration;

use tokio::sync::mpsc;

use super::types::MeetingPlatform;
use windows::Win32::Media::Audio::{
    eRender, eConsole,
    IAudioSessionControl, IAudioSessionControl2, IAudioSessionEnumerator,
    IAudioSessionManager2, IMMDevice, IMMDeviceEnumerator, MMDeviceEnumerator,
};
use windows::Win32::System::Com::{
    CoCreateInstance, CoInitializeEx, CoUninitialize, CLSCTX_ALL,
    COINIT_MULTITHREADED,
};
use windows::Win32::System::Threading::{
    OpenProcess, QueryFullProcessImageNameW, PROCESS_NAME_WIN32, PROCESS_QUERY_LIMITED_INFORMATION,
};
use windows::Win32::Foundation::HANDLE;
use windows::core::{Interface, PWSTR};

/// Known meeting process names to detect.
const KNOWN_MEETING_PROCESSES: &[&str] = &["Zoom.exe", "Teams.exe"];

/// Events emitted by the process monitor.
#[derive(Debug, Clone)]
pub enum MonitorEvent {
    MeetingDetected { process_name: String, pid: u32 },
    MeetingEnded { pid: u32 },
    BrowserMeetingDetected { url: String, title: String, platform: MeetingPlatform, tab_id: Option<u32> },
    BrowserMeetingEnded { tab_id: Option<u32> },
    SharingStarted,
    SharingStopped,
}

/// Start monitoring for meeting audio sessions on a background thread.
///
/// Polls WASAPI audio sessions every 2 seconds looking for known meeting processes.
/// Sends `MonitorEvent`s through the provided channel.
///
/// Returns a join handle for the monitoring thread and a stop flag.
pub fn start_monitoring(
    tx: mpsc::Sender<MonitorEvent>,
) -> (JoinHandle<()>, Arc<AtomicBool>) {
    let stop = Arc::new(AtomicBool::new(false));
    let stop_clone = stop.clone();

    let handle = thread::spawn(move || {
        // COM must be initialized per-thread.
        unsafe {
            let _ = CoInitializeEx(None, COINIT_MULTITHREADED);
        }

        let mut active_pids: HashSet<u32> = HashSet::new();

        while !stop_clone.load(Ordering::Relaxed) {
            match enumerate_meeting_sessions() {
                Ok(current) => {
                    // Detect new meetings.
                    for &(ref name, pid) in &current {
                        if !active_pids.contains(&pid) {
                            let _ = tx.blocking_send(MonitorEvent::MeetingDetected {
                                process_name: name.clone(),
                                pid,
                            });
                        }
                    }

                    let current_pids: HashSet<u32> = current.iter().map(|(_, pid)| *pid).collect();

                    // Detect ended meetings.
                    for &pid in &active_pids {
                        if !current_pids.contains(&pid) {
                            let _ = tx.blocking_send(MonitorEvent::MeetingEnded { pid });
                        }
                    }

                    active_pids = current_pids;
                }
                Err(e) => {
                    log::warn!("Monitor enumerate error: {}", e);
                }
            }

            thread::sleep(Duration::from_secs(2));
        }

        unsafe {
            CoUninitialize();
        }
    });

    (handle, stop)
}

/// Stop the monitor by setting the stop flag.
pub fn stop_monitoring(stop: &AtomicBool) {
    stop.store(true, Ordering::Relaxed);
}

/// Enumerate audio sessions and return (process_name, pid) pairs for known meeting processes.
fn enumerate_meeting_sessions() -> Result<Vec<(String, u32)>, String> {
    unsafe {
        let enumerator: IMMDeviceEnumerator =
            CoCreateInstance(&MMDeviceEnumerator, None, CLSCTX_ALL)
                .map_err(|e| format!("Failed to create device enumerator: {}", e))?;

        let device: IMMDevice = enumerator
            .GetDefaultAudioEndpoint(eRender, eConsole)
            .map_err(|e| format!("Failed to get default audio endpoint: {}", e))?;

        let manager: IAudioSessionManager2 = device
            .Activate(CLSCTX_ALL, None)
            .map_err(|e| format!("Failed to activate session manager: {}", e))?;

        let session_enum: IAudioSessionEnumerator = manager
            .GetSessionEnumerator()
            .map_err(|e| format!("Failed to get session enumerator: {}", e))?;

        let count = session_enum
            .GetCount()
            .map_err(|e| format!("Failed to get session count: {}", e))?;

        let mut results = Vec::new();

        for i in 0..count {
            let session: IAudioSessionControl = match session_enum.GetSession(i) {
                Ok(s) => s,
                Err(_) => continue,
            };

            let session2: IAudioSessionControl2 = match session.cast() {
                Ok(s) => s,
                Err(_) => continue,
            };

            let pid = match session2.GetProcessId() {
                Ok(p) => p,
                Err(_) => continue,
            };

            if pid == 0 {
                continue;
            }

            if let Some(name) = get_process_name(pid) {
                // Extract just the filename from the full path.
                let filename = name
                    .rsplit('\\')
                    .next()
                    .unwrap_or(&name)
                    .to_string();

                if KNOWN_MEETING_PROCESSES
                    .iter()
                    .any(|&known| known.eq_ignore_ascii_case(&filename))
                {
                    results.push((filename, pid));
                }
            }
        }

        Ok(results)
    }
}

/// Get the full process image name for a given PID.
fn get_process_name(pid: u32) -> Option<String> {
    unsafe {
        let handle: HANDLE =
            OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid).ok()?;

        let mut buf = [0u16; 260];
        let mut size = buf.len() as u32;

        let result = QueryFullProcessImageNameW(
            handle,
            PROCESS_NAME_WIN32,
            PWSTR(buf.as_mut_ptr()),
            &mut size,
        );

        let _ = windows::Win32::Foundation::CloseHandle(handle);

        result.ok()?;

        Some(String::from_utf16_lossy(&buf[..size as usize]))
    }
}
