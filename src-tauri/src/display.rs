use serde::Serialize;
use windows::Win32::Foundation::{BOOL, LPARAM, RECT, TRUE};
use windows::Win32::Graphics::Gdi::{
    EnumDisplayMonitors, GetMonitorInfoW, HDC, HMONITOR, MONITORINFOEXW,
};
use windows::Win32::UI::WindowsAndMessaging::MONITORINFOF_PRIMARY;

/// Information about a display monitor.
#[derive(Debug, Clone, Serialize)]
pub struct MonitorInfo {
    pub index: u32,
    pub name: String,
    pub width: u32,
    pub height: u32,
    pub is_primary: bool,
}

/// Enumerate available display monitors via Win32 EnumDisplayMonitors.
#[tauri::command]
pub async fn list_monitors() -> Result<Vec<MonitorInfo>, String> {
    let mut monitors: Vec<MonitorInfo> = Vec::new();

    unsafe {
        let result = EnumDisplayMonitors(
            HDC::default(),
            None,
            Some(enum_monitor_callback),
            LPARAM(&mut monitors as *mut Vec<MonitorInfo> as isize),
        );

        if !result.as_bool() {
            return Err("EnumDisplayMonitors failed".to_string());
        }
    }

    // Assign indices after enumeration (order matches Windows enumeration order).
    for (i, monitor) in monitors.iter_mut().enumerate() {
        monitor.index = i as u32;
    }

    Ok(monitors)
}

unsafe extern "system" fn enum_monitor_callback(
    hmonitor: HMONITOR,
    _hdc: HDC,
    _lprect: *mut RECT,
    lparam: LPARAM,
) -> BOOL {
    let monitors = &mut *(lparam.0 as *mut Vec<MonitorInfo>);

    let mut info = MONITORINFOEXW::default();
    info.monitorInfo.cbSize = std::mem::size_of::<MONITORINFOEXW>() as u32;

    if GetMonitorInfoW(hmonitor, &mut info as *mut MONITORINFOEXW as *mut _).as_bool() {
        let rc = info.monitorInfo.rcMonitor;
        let width = (rc.right - rc.left) as u32;
        let height = (rc.bottom - rc.top) as u32;
        let is_primary = (info.monitorInfo.dwFlags & MONITORINFOF_PRIMARY) != 0;

        // Extract display name from szDevice (null-terminated UTF-16).
        let name_len = info
            .szDevice
            .iter()
            .position(|&c| c == 0)
            .unwrap_or(info.szDevice.len());
        let name = String::from_utf16_lossy(&info.szDevice[..name_len]);

        monitors.push(MonitorInfo {
            index: 0, // Will be assigned after enumeration.
            name,
            width,
            height,
            is_primary,
        });
    }

    TRUE
}
