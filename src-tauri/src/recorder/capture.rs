use std::fs::File;
use std::io::{Seek, SeekFrom, Write as IoWrite};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread::{self, JoinHandle};

use windows::core::{implement, IUnknown, Interface, PCWSTR};
use windows::Win32::Media::Audio::{
    eCapture, eConsole, eRender, ActivateAudioInterfaceAsync,
    IAudioCaptureClient, IAudioClient, IActivateAudioInterfaceAsyncOperation,
    IActivateAudioInterfaceCompletionHandler,
    IActivateAudioInterfaceCompletionHandler_Impl, IMMDevice,
    IMMDeviceEnumerator, IMMNotificationClient, IMMNotificationClient_Impl,
    MMDeviceEnumerator, AUDCLNT_SHAREMODE_SHARED,
    AUDCLNT_STREAMFLAGS_LOOPBACK, AUDIOCLIENT_ACTIVATION_PARAMS,
    AUDIOCLIENT_ACTIVATION_PARAMS_0, AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK,
    AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS, PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE,
    VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK, WAVEFORMATEX,
};
use windows::Win32::System::Com::{
    CoCreateInstance, CoInitializeEx, CoUninitialize, CLSCTX_ALL, COINIT_MULTITHREADED,
};
use windows_core::PROPVARIANT;
use windows::Win32::System::Threading::{CreateEventW, WaitForSingleObject};
use windows::Win32::System::Variant::VT_BLOB;

/// Errors that can occur during capture.
#[derive(Debug)]
pub enum CaptureError {
    RemoteAttachFailed(String),
    NoMicrophoneDevice(String),
    IoError(std::io::Error),
    WindowsError(String),
    VideoError(String),
}

impl std::fmt::Display for CaptureError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            CaptureError::RemoteAttachFailed(msg) => write!(f, "Remote attach failed: {}", msg),
            CaptureError::NoMicrophoneDevice(msg) => write!(f, "No microphone: {}", msg),
            CaptureError::IoError(e) => write!(f, "IO error: {}", e),
            CaptureError::WindowsError(msg) => write!(f, "Windows error: {}", msg),
            CaptureError::VideoError(msg) => write!(f, "Video error: {}", msg),
        }
    }
}

impl From<std::io::Error> for CaptureError {
    fn from(e: std::io::Error) -> Self {
        CaptureError::IoError(e)
    }
}

/// Handle for an active audio capture stream.
pub struct AudioCapture {
    stop: Arc<AtomicBool>,
    handle: Option<JoinHandle<Result<(), CaptureError>>>,
}

impl AudioCapture {
    /// Start capturing remote audio from the specified process via per-process WASAPI loopback.
    ///
    /// Uses ActivateAudioInterfaceAsync with AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS
    /// to capture only audio from the target process tree (Windows 10 2004+).
    /// Falls back to device-wide loopback if per-process activation fails.
    pub fn start_remote(pid: u32, output_path: PathBuf) -> Result<Self, CaptureError> {
        let stop = Arc::new(AtomicBool::new(false));
        let stop_clone = stop.clone();

        let handle = thread::spawn(move || -> Result<(), CaptureError> {
            unsafe {
                let _ = CoInitializeEx(None, COINIT_MULTITHREADED);
            }

            // Try per-process loopback first, fall back to device-wide
            let result = unsafe {
                match capture_process_loopback(pid, &output_path, &stop_clone) {
                    Ok(()) => Ok(()),
                    Err(e) => {
                        eprintln!("Per-process loopback failed ({}), falling back to device loopback", e);
                        capture_loopback(output_path, &stop_clone)
                    }
                }
            };

            unsafe {
                CoUninitialize();
            }

            result
        });

        Ok(AudioCapture {
            stop,
            handle: Some(handle),
        })
    }

    /// Start capturing local microphone audio via WASAPI.
    pub fn start_local(output_path: PathBuf) -> Result<Self, CaptureError> {
        let stop = Arc::new(AtomicBool::new(false));
        let stop_clone = stop.clone();

        let handle = thread::spawn(move || -> Result<(), CaptureError> {
            unsafe {
                let _ = CoInitializeEx(None, COINIT_MULTITHREADED);
            }

            let result = unsafe { capture_microphone(output_path, &stop_clone) };

            unsafe {
                CoUninitialize();
            }

            result
        });

        Ok(AudioCapture {
            stop,
            handle: Some(handle),
        })
    }

    /// Stop capture, finalize WAV header, close file.
    pub fn stop(&mut self) -> Result<(), CaptureError> {
        self.stop.store(true, Ordering::Relaxed);

        if let Some(handle) = self.handle.take() {
            match handle.join() {
                Ok(result) => result,
                Err(_) => Err(CaptureError::WindowsError(
                    "Capture thread panicked".to_string(),
                )),
            }
        } else {
            Ok(())
        }
    }
}

/// Write a WAV header with placeholder sizes. Returns the file for streaming PCM data.
fn write_wav_header(
    file: &mut File,
    channels: u16,
    sample_rate: u32,
    bits_per_sample: u16,
) -> Result<(), CaptureError> {
    let byte_rate = sample_rate * channels as u32 * bits_per_sample as u32 / 8;
    let block_align = channels * bits_per_sample / 8;

    // RIFF header
    file.write_all(b"RIFF")?;
    file.write_all(&0u32.to_le_bytes())?; // placeholder file size
    file.write_all(b"WAVE")?;

    // fmt chunk
    file.write_all(b"fmt ")?;
    file.write_all(&16u32.to_le_bytes())?; // chunk size
    file.write_all(&1u16.to_le_bytes())?; // PCM format
    file.write_all(&channels.to_le_bytes())?;
    file.write_all(&sample_rate.to_le_bytes())?;
    file.write_all(&byte_rate.to_le_bytes())?;
    file.write_all(&block_align.to_le_bytes())?;
    file.write_all(&bits_per_sample.to_le_bytes())?;

    // data chunk header
    file.write_all(b"data")?;
    file.write_all(&0u32.to_le_bytes())?; // placeholder data size

    Ok(())
}

/// Finalize a WAV file by seeking back and writing correct sizes.
fn finalize_wav_header(file: &mut File) -> Result<(), CaptureError> {
    let file_size = file.seek(SeekFrom::End(0))?;
    let data_size = (file_size - 44) as u32;

    // Update RIFF chunk size (file_size - 8)
    file.seek(SeekFrom::Start(4))?;
    file.write_all(&(file_size as u32 - 8).to_le_bytes())?;

    // Update data chunk size
    file.seek(SeekFrom::Start(40))?;
    file.write_all(&data_size.to_le_bytes())?;

    Ok(())
}

type ActivationResult = Arc<(
    std::sync::Mutex<Option<Result<IAudioClient, String>>>,
    std::sync::Condvar,
)>;

/// COM completion handler for ActivateAudioInterfaceAsync.
#[implement(IActivateAudioInterfaceCompletionHandler)]
struct ActivationHandler {
    shared: ActivationResult,
}

impl IActivateAudioInterfaceCompletionHandler_Impl for ActivationHandler_Impl {
    fn ActivateCompleted(
        &self,
        activate_operation: Option<&IActivateAudioInterfaceAsyncOperation>,
    ) -> windows::core::Result<()> {
        let op = activate_operation.ok_or(windows::core::Error::from(
            windows::Win32::Foundation::E_POINTER,
        ))?;

        let mut hr = windows::core::HRESULT(0);
        let mut activated_interface: Option<IUnknown> = None;
        unsafe {
            op.GetActivateResult(&mut hr, &mut activated_interface)?;
        }

        let result = if hr.is_ok() {
            match activated_interface {
                Some(iface) => match iface.cast::<IAudioClient>() {
                    Ok(client) => Ok(client),
                    Err(e) => Err(format!("Cast to IAudioClient failed: {}", e)),
                },
                None => Err("No interface returned".to_string()),
            }
        } else {
            Err(format!("Activation failed: HRESULT {:?}", hr))
        };

        let (lock, cvar) = &*self.shared;
        *lock.lock().unwrap() = Some(result);
        cvar.notify_one();

        Ok(())
    }
}

/// Capture audio from a specific process via per-process WASAPI loopback.
/// Requires Windows 10 version 2004 (build 19041) or later.
unsafe fn capture_process_loopback(
    pid: u32,
    output_path: &PathBuf,
    stop: &AtomicBool,
) -> Result<(), CaptureError> {
    // Set up process loopback activation params
    let loopback_params = AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS {
        TargetProcessId: pid,
        ProcessLoopbackMode: PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE,
    };

    let activation_params = AUDIOCLIENT_ACTIVATION_PARAMS {
        ActivationType: AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK,
        Anonymous: AUDIOCLIENT_ACTIVATION_PARAMS_0 {
            ProcessLoopbackParams: loopback_params,
        },
    };

    // Wrap in PROPVARIANT as a VT_BLOB using raw memory layout
    // PROPVARIANT layout: u16 vt, u16 reserved1, u16 reserved2, u16 reserved3, then union data
    let params_ptr = &activation_params as *const AUDIOCLIENT_ACTIVATION_PARAMS;
    let params_size = std::mem::size_of::<AUDIOCLIENT_ACTIVATION_PARAMS>() as u32;

    #[repr(C)]
    struct RawPropVariantBlob {
        vt: u16,
        reserved1: u16,
        reserved2: u16,
        reserved3: u16,
        cb_size: u32,
        p_blob_data: *mut u8,
    }

    let raw_pv = RawPropVariantBlob {
        vt: VT_BLOB.0,
        reserved1: 0,
        reserved2: 0,
        reserved3: 0,
        cb_size: params_size,
        p_blob_data: params_ptr as *mut u8,
    };

    let propvariant_ptr = &raw_pv as *const RawPropVariantBlob as *const PROPVARIANT;

    // Create shared state for completion handler
    let shared: ActivationResult = Arc::new((
        std::sync::Mutex::new(None),
        std::sync::Condvar::new(),
    ));

    let handler = ActivationHandler {
        shared: shared.clone(),
    };
    let handler: IActivateAudioInterfaceCompletionHandler = handler.into();

    // Call ActivateAudioInterfaceAsync
    let _operation = ActivateAudioInterfaceAsync(
        PCWSTR(VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK.as_ptr()),
        &IAudioClient::IID,
        Some(propvariant_ptr),
        &handler,
    )
    .map_err(|e| CaptureError::RemoteAttachFailed(format!("ActivateAudioInterfaceAsync: {}", e)))?;

    // Wait for completion (5 second timeout)
    let (lock, cvar) = &*shared;
    let guard = lock.lock().unwrap();
    let mut result = cvar
        .wait_timeout(guard, std::time::Duration::from_secs(5))
        .unwrap();
    let result = result.0.take()
        .ok_or_else(|| CaptureError::RemoteAttachFailed("Activation timed out".to_string()))?;

    let audio_client = result
        .map_err(|e| CaptureError::RemoteAttachFailed(e))?;

    // Now use the activated audio client for capture (same as capture_from_device but with existing client)
    let mix_format: *mut WAVEFORMATEX = audio_client
        .GetMixFormat()
        .map_err(|e| CaptureError::RemoteAttachFailed(format!("GetMixFormat: {}", e)))?;

    let format = &*mix_format;
    let channels = format.nChannels;
    let sample_rate = format.nSamplesPerSec;
    let bits_per_sample = format.wBitsPerSample;

    audio_client
        .Initialize(
            AUDCLNT_SHAREMODE_SHARED,
            0, // No special flags needed for process loopback
            10_000_000,
            0,
            mix_format,
            None,
        )
        .map_err(|e| CaptureError::RemoteAttachFailed(format!("Initialize: {}", e)))?;

    let capture_client: IAudioCaptureClient = audio_client
        .GetService()
        .map_err(|e| CaptureError::RemoteAttachFailed(format!("GetService: {}", e)))?;

    let capture_event = CreateEventW(None, false, false, None)
        .map_err(|e| CaptureError::RemoteAttachFailed(format!("CreateEvent: {}", e)))?;

    audio_client
        .SetEventHandle(capture_event)
        .map_err(|e| CaptureError::RemoteAttachFailed(format!("SetEventHandle: {}", e)))?;

    let mut file = File::create(output_path)?;
    write_wav_header(&mut file, channels, sample_rate, bits_per_sample)?;

    audio_client
        .Start()
        .map_err(|e| CaptureError::RemoteAttachFailed(format!("Start: {}", e)))?;

    while !stop.load(Ordering::Relaxed) {
        WaitForSingleObject(capture_event, 100);

        loop {
            let mut buffer_ptr = std::ptr::null_mut();
            let mut num_frames = 0u32;
            let mut flags = 0u32;

            match capture_client.GetBuffer(
                &mut buffer_ptr,
                &mut num_frames,
                &mut flags,
                None,
                None,
            ) {
                Ok(()) => {}
                Err(_) => break,
            }

            if num_frames > 0 {
                let bytes_per_frame = channels as usize * bits_per_sample as usize / 8;
                let data_len = num_frames as usize * bytes_per_frame;
                let data = std::slice::from_raw_parts(buffer_ptr, data_len);
                let _ = file.write_all(data);
            }

            let _ = capture_client.ReleaseBuffer(num_frames);

            if num_frames == 0 {
                break;
            }
        }
    }

    let _ = audio_client.Stop();
    finalize_wav_header(&mut file)?;
    windows::Win32::System::Com::CoTaskMemFree(Some(mix_format as *const _));
    let _ = windows::Win32::Foundation::CloseHandle(capture_event);

    Ok(())
}

/// Capture audio from the default render device in loopback mode (fallback).
unsafe fn capture_loopback(
    output_path: PathBuf,
    stop: &AtomicBool,
) -> Result<(), CaptureError> {
    let enumerator: IMMDeviceEnumerator =
        CoCreateInstance(&MMDeviceEnumerator, None, CLSCTX_ALL)
            .map_err(|e| CaptureError::RemoteAttachFailed(format!("Device enumerator: {}", e)))?;

    let device: IMMDevice = enumerator
        .GetDefaultAudioEndpoint(eRender, eConsole)
        .map_err(|e| CaptureError::RemoteAttachFailed(format!("Default endpoint: {}", e)))?;

    capture_from_device(device, AUDCLNT_STREAMFLAGS_LOOPBACK, output_path, stop)
        .map_err(|e| match e {
            CaptureError::WindowsError(msg) => CaptureError::RemoteAttachFailed(msg),
            other => other,
        })
}

/// COM notification client that sets a flag when the default capture device changes.
#[implement(IMMNotificationClient)]
struct DeviceChangeNotifier {
    device_changed: Arc<AtomicBool>,
}

impl IMMNotificationClient_Impl for DeviceChangeNotifier_Impl {
    fn OnDeviceStateChanged(
        &self,
        _pwstrdeviceid: &windows::core::PCWSTR,
        _dwnewstate: windows::Win32::Media::Audio::DEVICE_STATE,
    ) -> windows::core::Result<()> {
        Ok(())
    }

    fn OnDeviceAdded(
        &self,
        _pwstrdeviceid: &windows::core::PCWSTR,
    ) -> windows::core::Result<()> {
        Ok(())
    }

    fn OnDeviceRemoved(
        &self,
        _pwstrdeviceid: &windows::core::PCWSTR,
    ) -> windows::core::Result<()> {
        Ok(())
    }

    fn OnDefaultDeviceChanged(
        &self,
        flow: windows::Win32::Media::Audio::EDataFlow,
        _role: windows::Win32::Media::Audio::ERole,
        _pwstrdefaultdeviceid: &windows::core::PCWSTR,
    ) -> windows::core::Result<()> {
        if flow == eCapture {
            self.device_changed.store(true, Ordering::Relaxed);
        }
        Ok(())
    }

    fn OnPropertyValueChanged(
        &self,
        _pwstrdeviceid: &windows::core::PCWSTR,
        _key: &windows::Win32::UI::Shell::PropertiesSystem::PROPERTYKEY,
    ) -> windows::core::Result<()> {
        Ok(())
    }
}

/// Capture audio from the default recording device (microphone).
/// Re-attaches to new default device if it changes mid-capture.
unsafe fn capture_microphone(
    output_path: PathBuf,
    stop: &AtomicBool,
) -> Result<(), CaptureError> {
    let enumerator: IMMDeviceEnumerator =
        CoCreateInstance(&MMDeviceEnumerator, None, CLSCTX_ALL)
            .map_err(|e| CaptureError::NoMicrophoneDevice(format!("Device enumerator: {}", e)))?;

    // Register device change notification
    let device_changed = Arc::new(AtomicBool::new(false));
    let notifier = DeviceChangeNotifier {
        device_changed: device_changed.clone(),
    };
    let notifier_client: IMMNotificationClient = notifier.into();
    let _ = enumerator.RegisterEndpointNotificationCallback(&notifier_client);

    // Open WAV file once — we'll keep writing across device switches
    let device: IMMDevice = enumerator
        .GetDefaultAudioEndpoint(eCapture, eConsole)
        .map_err(|e| CaptureError::NoMicrophoneDevice(format!("No mic device: {}", e)))?;

    let result = capture_from_device_with_reattach(
        &enumerator,
        device,
        &device_changed,
        output_path,
        stop,
    );

    let _ = enumerator.UnregisterEndpointNotificationCallback(&notifier_client);

    result.map_err(|e| match e {
        CaptureError::WindowsError(msg) => CaptureError::NoMicrophoneDevice(msg),
        other => other,
    })
}

/// Capture from a device, re-attaching to the new default if it changes.
unsafe fn capture_from_device_with_reattach(
    enumerator: &IMMDeviceEnumerator,
    initial_device: IMMDevice,
    device_changed: &AtomicBool,
    output_path: PathBuf,
    stop: &AtomicBool,
) -> Result<(), CaptureError> {
    let audio_client: IAudioClient = initial_device
        .Activate(CLSCTX_ALL, None)
        .map_err(|e| CaptureError::WindowsError(format!("Activate audio client: {}", e)))?;

    let mix_format: *mut WAVEFORMATEX = audio_client
        .GetMixFormat()
        .map_err(|e| CaptureError::WindowsError(format!("GetMixFormat: {}", e)))?;

    let format = &*mix_format;
    let channels = format.nChannels;
    let sample_rate = format.nSamplesPerSec;
    let bits_per_sample = format.wBitsPerSample;

    audio_client
        .Initialize(AUDCLNT_SHAREMODE_SHARED, 0, 10_000_000, 0, mix_format, None)
        .map_err(|e| CaptureError::WindowsError(format!("Initialize: {}", e)))?;

    let capture_client: IAudioCaptureClient = audio_client
        .GetService()
        .map_err(|e| CaptureError::WindowsError(format!("GetService: {}", e)))?;

    let event = CreateEventW(None, false, false, None)
        .map_err(|e| CaptureError::WindowsError(format!("CreateEvent: {}", e)))?;

    audio_client
        .SetEventHandle(event)
        .map_err(|e| CaptureError::WindowsError(format!("SetEventHandle: {}", e)))?;

    let mut file = File::create(&output_path)?;
    write_wav_header(&mut file, channels, sample_rate, bits_per_sample)?;

    audio_client
        .Start()
        .map_err(|e| CaptureError::WindowsError(format!("Start: {}", e)))?;

    while !stop.load(Ordering::Relaxed) {
        // Check for device change
        if device_changed.swap(false, Ordering::Relaxed) {
            log::info!("Default capture device changed, re-attaching...");
            let _ = audio_client.Stop();
            windows::Win32::System::Com::CoTaskMemFree(Some(mix_format as *const _));
            let _ = windows::Win32::Foundation::CloseHandle(event);

            // Get the new default device and restart capture into the same file
            match enumerator.GetDefaultAudioEndpoint(eCapture, eConsole) {
                Ok(new_device) => {
                    // Finalize current WAV and return — caller will need to handle
                    // For simplicity, we continue writing to the same file with the
                    // assumption the new device has the same format. If not, we just
                    // log and continue with whatever data we get.
                    let new_client: IAudioClient = match new_device.Activate(CLSCTX_ALL, None) {
                        Ok(c) => c,
                        Err(e) => {
                            log::warn!("Failed to activate new device: {}", e);
                            continue;
                        }
                    };

                    let new_format = match new_client.GetMixFormat() {
                        Ok(f) => f,
                        Err(e) => {
                            log::warn!("Failed to get new device format: {}", e);
                            continue;
                        }
                    };

                    let _ = new_client.Initialize(
                        AUDCLNT_SHAREMODE_SHARED, 0, 10_000_000, 0, new_format, None,
                    );

                    let new_capture: IAudioCaptureClient = match new_client.GetService() {
                        Ok(c) => c,
                        Err(e) => {
                            log::warn!("Failed to get capture client from new device: {}", e);
                            continue;
                        }
                    };

                    let new_event = match CreateEventW(None, false, false, None) {
                        Ok(e) => e,
                        Err(_) => continue,
                    };
                    let _ = new_client.SetEventHandle(new_event);
                    let _ = new_client.Start();

                    // Continue capture loop with new device
                    // We drain the new device's buffers in the same loop
                    while !stop.load(Ordering::Relaxed) {
                        if device_changed.swap(false, Ordering::Relaxed) {
                            // Another device change — break to outer function
                            let _ = new_client.Stop();
                            let _ = windows::Win32::Foundation::CloseHandle(new_event);
                            windows::Win32::System::Com::CoTaskMemFree(Some(new_format as *const _));
                            break;
                        }

                        WaitForSingleObject(new_event, 100);
                        drain_capture_buffer(&new_capture, channels, bits_per_sample, &mut file);
                    }

                    let _ = new_client.Stop();
                    let _ = windows::Win32::Foundation::CloseHandle(new_event);
                    windows::Win32::System::Com::CoTaskMemFree(Some(new_format as *const _));
                    break; // Exit outer loop
                }
                Err(e) => {
                    log::warn!("No default capture device available: {}", e);
                    // Continue — maybe a device comes back
                }
            }
            continue;
        }

        WaitForSingleObject(event, 100);
        drain_capture_buffer(&capture_client, channels, bits_per_sample, &mut file);
    }

    let _ = audio_client.Stop();
    finalize_wav_header(&mut file)?;
    windows::Win32::System::Com::CoTaskMemFree(Some(mix_format as *const _));
    let _ = windows::Win32::Foundation::CloseHandle(event);

    Ok(())
}

/// Drain all available buffers from a capture client into a file.
unsafe fn drain_capture_buffer(
    capture_client: &IAudioCaptureClient,
    channels: u16,
    bits_per_sample: u16,
    file: &mut File,
) {
    loop {
        let mut buffer_ptr = std::ptr::null_mut();
        let mut num_frames = 0u32;
        let mut flags = 0u32;

        match capture_client.GetBuffer(
            &mut buffer_ptr,
            &mut num_frames,
            &mut flags,
            None,
            None,
        ) {
            Ok(()) => {}
            Err(_) => break,
        }

        if num_frames > 0 {
            let bytes_per_frame = channels as usize * bits_per_sample as usize / 8;
            let data_len = num_frames as usize * bytes_per_frame;
            let data = std::slice::from_raw_parts(buffer_ptr, data_len);
            let _ = file.write_all(data);
        }

        let _ = capture_client.ReleaseBuffer(num_frames);

        if num_frames == 0 {
            break;
        }
    }
}

/// Generic WASAPI capture from a device with specified stream flags.
unsafe fn capture_from_device(
    device: IMMDevice,
    stream_flags: u32,
    output_path: PathBuf,
    stop: &AtomicBool,
) -> Result<(), CaptureError> {
    let audio_client: IAudioClient = device
        .Activate(CLSCTX_ALL, None)
        .map_err(|e| CaptureError::WindowsError(format!("Activate audio client: {}", e)))?;

    let mix_format: *mut WAVEFORMATEX = audio_client
        .GetMixFormat()
        .map_err(|e| CaptureError::WindowsError(format!("GetMixFormat: {}", e)))?;

    let format = &*mix_format;
    let channels = format.nChannels;
    let sample_rate = format.nSamplesPerSec;
    let bits_per_sample = format.wBitsPerSample;

    // Initialize in shared mode.
    audio_client
        .Initialize(
            AUDCLNT_SHAREMODE_SHARED,
            stream_flags,
            10_000_000, // 1 second buffer in 100ns units
            0,
            mix_format,
            None,
        )
        .map_err(|e| CaptureError::WindowsError(format!("Initialize: {}", e)))?;

    let capture_client: IAudioCaptureClient = audio_client
        .GetService()
        .map_err(|e| CaptureError::WindowsError(format!("GetService: {}", e)))?;

    // Create event for buffer-ready notifications.
    let event = CreateEventW(None, false, false, None)
        .map_err(|e| CaptureError::WindowsError(format!("CreateEvent: {}", e)))?;

    audio_client
        .SetEventHandle(event)
        .map_err(|e| CaptureError::WindowsError(format!("SetEventHandle: {}", e)))?;

    // Open output WAV file.
    let mut file = File::create(&output_path)?;
    write_wav_header(&mut file, channels, sample_rate, bits_per_sample)?;

    // Start capturing.
    audio_client
        .Start()
        .map_err(|e| CaptureError::WindowsError(format!("Start: {}", e)))?;

    while !stop.load(Ordering::Relaxed) {
        // Wait for audio data (100ms timeout).
        WaitForSingleObject(event, 100);

        loop {
            let mut buffer_ptr = std::ptr::null_mut();
            let mut num_frames = 0u32;
            let mut flags = 0u32;

            match capture_client.GetBuffer(
                &mut buffer_ptr,
                &mut num_frames,
                &mut flags,
                None,
                None,
            ) {
                Ok(()) => {}
                Err(_) => break, // No more data available.
            }

            if num_frames > 0 {
                let bytes_per_frame = channels as usize * bits_per_sample as usize / 8;
                let data_len = num_frames as usize * bytes_per_frame;
                let data = std::slice::from_raw_parts(buffer_ptr, data_len);
                let _ = file.write_all(data);
            }

            let _ = capture_client.ReleaseBuffer(num_frames);

            if num_frames == 0 {
                break;
            }
        }
    }

    // Stop and finalize.
    let _ = audio_client.Stop();
    finalize_wav_header(&mut file)?;

    // Clean up the mix format.
    windows::Win32::System::Com::CoTaskMemFree(Some(mix_format as *const _));
    let _ = windows::Win32::Foundation::CloseHandle(event);

    Ok(())
}

// ──────────────────────────────────────────────────────────────────────────────
// Video capture via ffmpeg subprocess + Windows Graphics Capture API
// ──────────────────────────────────────────────────────────────────────────────

use windows::Win32::UI::WindowsAndMessaging::{
    EnumWindows, GetWindowThreadProcessId, IsWindowVisible, GetWindowRect,
};
use windows::Win32::Foundation::{BOOL, HWND, LPARAM, RECT, TRUE};
use windows::Graphics::Capture::GraphicsCaptureItem;
use windows::Graphics::DirectX::DirectXPixelFormat;
use windows::Graphics::DirectX::Direct3D11::IDirect3DDevice;

/// Wrapper around HWND raw pointer so it can be sent across threads.
/// SAFETY: HWND is just a handle value — safe to send between threads.
struct SendableHwnd(isize);
unsafe impl Send for SendableHwnd {}

/// Handle for an active video capture session.
pub struct VideoCapture {
    stop: Arc<AtomicBool>,
    handle: Option<JoinHandle<Result<(), CaptureError>>>,
}

impl VideoCapture {
    /// Start capturing the window belonging to the given PID at 30fps.
    ///
    /// Finds the largest visible window for the PID, captures frames using the
    /// Windows Graphics Capture API, and pipes raw BGRA frames to an ffmpeg
    /// subprocess for H.265 encoding.
    pub fn start(pid: u32, output_path: PathBuf) -> Result<Self, CaptureError> {
        let hwnd = find_window_for_pid(pid)
            .ok_or_else(|| CaptureError::VideoError(format!("No window found for PID {}", pid)))?;

        // Extract raw handle so we can send it across threads.
        let sendable = SendableHwnd(hwnd.0 as isize);

        let stop = Arc::new(AtomicBool::new(false));
        let stop_clone = stop.clone();

        let handle = thread::spawn(move || -> Result<(), CaptureError> {
            let hwnd = HWND(sendable.0 as *mut _);
            capture_window_video(hwnd, output_path, &stop_clone)
        });

        Ok(VideoCapture {
            stop,
            handle: Some(handle),
        })
    }

    /// Stop capture, close ffmpeg stdin, wait for encoding to finish.
    pub fn stop(&mut self) -> Result<(), CaptureError> {
        self.stop.store(true, Ordering::Relaxed);

        if let Some(handle) = self.handle.take() {
            match handle.join() {
                Ok(result) => result,
                Err(_) => Err(CaptureError::VideoError(
                    "Video capture thread panicked".to_string(),
                )),
            }
        } else {
            Ok(())
        }
    }

    /// Check if NVENC (NVIDIA hardware encoder) is available.
    pub fn nvenc_available() -> bool {
        Command::new("ffmpeg")
            .args(["-hide_banner", "-encoders"])
            .output()
            .map(|output| {
                String::from_utf8_lossy(&output.stdout).contains("hevc_nvenc")
            })
            .unwrap_or(false)
    }
}

/// Find the largest visible window belonging to the given PID.
fn find_window_for_pid(target_pid: u32) -> Option<HWND> {
    struct EnumState {
        target_pid: u32,
        best_hwnd: Option<HWND>,
        best_area: i64,
    }

    let mut state = EnumState {
        target_pid,
        best_hwnd: None,
        best_area: 0,
    };

    unsafe extern "system" fn enum_callback(hwnd: HWND, lparam: LPARAM) -> BOOL {
        let state = &mut *(lparam.0 as *mut EnumState);

        let mut pid = 0u32;
        GetWindowThreadProcessId(hwnd, Some(&mut pid));

        if pid != state.target_pid {
            return TRUE;
        }

        if !IsWindowVisible(hwnd).as_bool() {
            return TRUE;
        }

        let mut rect = RECT::default();
        if GetWindowRect(hwnd, &mut rect).is_ok() {
            let area = (rect.right - rect.left) as i64 * (rect.bottom - rect.top) as i64;
            if area > state.best_area {
                state.best_area = area;
                state.best_hwnd = Some(hwnd);
            }
        }

        TRUE
    }

    unsafe {
        let _ = EnumWindows(
            Some(enum_callback),
            LPARAM(&mut state as *mut EnumState as isize),
        );
    }

    state.best_hwnd
}

/// Build the ffmpeg encoder command for the given dimensions and output path.
fn build_ffmpeg_command(width: u32, height: u32, output_path: &PathBuf) -> Result<Child, CaptureError> {
    let encoder = if VideoCapture::nvenc_available() {
        vec!["-c:v", "hevc_nvenc", "-preset", "p4", "-cq", "28"]
    } else {
        vec!["-c:v", "libx265", "-crf", "28", "-preset", "fast"]
    };

    let size = format!("{}x{}", width, height);

    let mut cmd = Command::new("ffmpeg");
    cmd.args([
        "-f", "rawvideo",
        "-pix_fmt", "bgra",
        "-s", &size,
        "-r", "30",
        "-i", "pipe:0",
    ]);
    for arg in &encoder {
        cmd.arg(arg);
    }
    cmd.arg("-y")
        .arg(output_path.to_str().unwrap_or("output.mp4"))
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null());

    cmd.spawn().map_err(|e| CaptureError::VideoError(format!("Failed to spawn ffmpeg: {}", e)))
}

/// Capture video from a window using Graphics Capture API, piping frames to ffmpeg.
fn capture_window_video(
    hwnd: HWND,
    output_path: PathBuf,
    stop: &AtomicBool,
) -> Result<(), CaptureError> {
    unsafe {
        let _ = CoInitializeEx(None, COINIT_MULTITHREADED);
    }

    let result = capture_window_video_inner(hwnd, output_path, stop);

    unsafe {
        CoUninitialize();
    }

    result
}

fn capture_window_video_inner(
    hwnd: HWND,
    output_path: PathBuf,
    stop: &AtomicBool,
) -> Result<(), CaptureError> {
    // Get window dimensions for frame size.
    let (width, height) = unsafe {
        let mut rect = RECT::default();
        GetWindowRect(hwnd, &mut rect)
            .map_err(|e| CaptureError::VideoError(format!("GetWindowRect: {}", e)))?;
        (
            (rect.right - rect.left).max(1) as u32,
            (rect.bottom - rect.top).max(1) as u32,
        )
    };

    // Start ffmpeg encoder subprocess.
    let mut ffmpeg = build_ffmpeg_command(width, height, &output_path)?;
    let mut stdin = ffmpeg.stdin.take()
        .ok_or_else(|| CaptureError::VideoError("Failed to open ffmpeg stdin".to_string()))?;

    // Create the Graphics Capture item from the window handle.
    let item = create_capture_item_for_window(hwnd)?;

    // Create D3D11 device for frame pool.
    let d3d_device = create_d3d_device()?;

    // Create frame pool and session.
    let frame_pool = windows::Graphics::Capture::Direct3D11CaptureFramePool::CreateFreeThreaded(
        &d3d_device,
        DirectXPixelFormat::B8G8R8A8UIntNormalized,
        1,
        item.Size().map_err(|e| CaptureError::VideoError(format!("Item size: {}", e)))?,
    )
    .map_err(|e| CaptureError::VideoError(format!("CreateFramePool: {}", e)))?;

    let session = frame_pool
        .CreateCaptureSession(&item)
        .map_err(|e| CaptureError::VideoError(format!("CreateCaptureSession: {}", e)))?;

    let _ = session.SetIsCursorCaptureEnabled(false);

    session
        .StartCapture()
        .map_err(|e| CaptureError::VideoError(format!("StartCapture: {}", e)))?;

    // Pre-create staging resources for efficient frame readback
    let staging = create_staging_resources(width, height)?;

    let frame_interval = std::time::Duration::from_millis(33); // ~30fps

    while !stop.load(Ordering::Relaxed) {
        if let Ok(frame) = frame_pool.TryGetNextFrame() {
            if let Ok(surface) = frame.Surface() {
                if let Ok(data) = read_surface_pixels_staged(&surface, &staging, width, height) {
                    if stdin.write_all(&data).is_err() {
                        log::warn!("ffmpeg stdin write failed — encoder may have exited");
                        break;
                    }
                }
            }
        }

        thread::sleep(frame_interval);
    }

    drop(stdin);
    let _ = ffmpeg.wait();

    let _ = session.Close();
    let _ = frame_pool.Close();

    Ok(())
}

/// Create a GraphicsCaptureItem from an HWND using the interop interface.
fn create_capture_item_for_window(hwnd: HWND) -> Result<GraphicsCaptureItem, CaptureError> {
    use windows::Win32::System::WinRT::Graphics::Capture::IGraphicsCaptureItemInterop;

    unsafe {
        let interop: IGraphicsCaptureItemInterop =
            windows::core::factory::<GraphicsCaptureItem, IGraphicsCaptureItemInterop>()
                .map_err(|e| CaptureError::VideoError(format!("CaptureItem interop: {}", e)))?;

        interop
            .CreateForWindow(hwnd)
            .map_err(|e| CaptureError::VideoError(format!("CreateForWindow: {}", e)))
    }
}

/// Create a Direct3D 11 device for the frame pool.
fn create_d3d_device() -> Result<IDirect3DDevice, CaptureError> {
    use windows::Win32::Graphics::Direct3D::D3D_DRIVER_TYPE_HARDWARE;
    use windows::Win32::Graphics::Direct3D11::{
        D3D11CreateDevice, D3D11_CREATE_DEVICE_BGRA_SUPPORT, D3D11_SDK_VERSION,
    };
    use windows::Win32::Graphics::Dxgi::IDXGIDevice;
    use windows::Win32::System::WinRT::Direct3D11::CreateDirect3D11DeviceFromDXGIDevice;
    use windows::core::Interface;

    unsafe {
        let mut d3d_device = None;

        D3D11CreateDevice(
            None,
            D3D_DRIVER_TYPE_HARDWARE,
            None,
            D3D11_CREATE_DEVICE_BGRA_SUPPORT,
            None,
            D3D11_SDK_VERSION,
            Some(&mut d3d_device),
            None,
            None,
        )
        .map_err(|e| CaptureError::VideoError(format!("D3D11CreateDevice: {}", e)))?;

        let d3d_device = d3d_device
            .ok_or_else(|| CaptureError::VideoError("D3D11 device was null".to_string()))?;

        let dxgi_device: IDXGIDevice = d3d_device
            .cast()
            .map_err(|e| CaptureError::VideoError(format!("Cast to IDXGIDevice: {}", e)))?;

        let inspectable = CreateDirect3D11DeviceFromDXGIDevice(&dxgi_device)
            .map_err(|e| CaptureError::VideoError(format!("CreateDirect3D11Device: {}", e)))?;

        inspectable
            .cast()
            .map_err(|e| CaptureError::VideoError(format!("Cast to IDirect3DDevice: {}", e)))
    }
}

/// Pre-created D3D11 resources for efficient frame readback (avoids per-frame allocation).
struct StagingResources {
    context: windows::Win32::Graphics::Direct3D11::ID3D11DeviceContext,
    staging_resource: windows::Win32::Graphics::Direct3D11::ID3D11Resource,
}

/// Create staging resources once for reuse across all frames.
fn create_staging_resources(width: u32, height: u32) -> Result<StagingResources, CaptureError> {
    use windows::Win32::Graphics::Direct3D::{D3D_DRIVER_TYPE_HARDWARE, D3D_FEATURE_LEVEL_11_0};
    use windows::Win32::Graphics::Direct3D11::{
        D3D11CreateDevice, ID3D11Device, ID3D11DeviceContext,
        D3D11_CPU_ACCESS_READ, D3D11_CREATE_DEVICE_BGRA_SUPPORT,
        D3D11_SDK_VERSION, D3D11_TEXTURE2D_DESC, D3D11_USAGE_STAGING,
    };
    use windows::Win32::Graphics::Dxgi::Common::{
        DXGI_FORMAT_B8G8R8A8_UNORM, DXGI_SAMPLE_DESC,
    };
    use windows::core::Interface;

    unsafe {
        let mut device_opt: Option<ID3D11Device> = None;
        let mut context_opt: Option<ID3D11DeviceContext> = None;
        let feature_levels = [D3D_FEATURE_LEVEL_11_0];

        D3D11CreateDevice(
            None,
            D3D_DRIVER_TYPE_HARDWARE,
            None,
            D3D11_CREATE_DEVICE_BGRA_SUPPORT,
            Some(&feature_levels),
            D3D11_SDK_VERSION,
            Some(&mut device_opt),
            None,
            Some(&mut context_opt),
        )
        .map_err(|e| CaptureError::VideoError(format!("D3D11CreateDevice for staging: {}", e)))?;

        let device = device_opt
            .ok_or_else(|| CaptureError::VideoError("Staging D3D device was null".to_string()))?;
        let context = context_opt
            .ok_or_else(|| CaptureError::VideoError("Staging D3D context was null".to_string()))?;

        let desc = D3D11_TEXTURE2D_DESC {
            Width: width,
            Height: height,
            MipLevels: 1,
            ArraySize: 1,
            Format: DXGI_FORMAT_B8G8R8A8_UNORM,
            SampleDesc: DXGI_SAMPLE_DESC {
                Count: 1,
                Quality: 0,
            },
            Usage: D3D11_USAGE_STAGING,
            BindFlags: 0,
            CPUAccessFlags: D3D11_CPU_ACCESS_READ.0 as u32,
            MiscFlags: 0,
        };

        let mut staging_opt = None;
        device
            .CreateTexture2D(&desc, None, Some(&mut staging_opt))
            .map_err(|e| CaptureError::VideoError(format!("CreateTexture2D staging: {}", e)))?;
        let staging = staging_opt
            .ok_or_else(|| CaptureError::VideoError("Staging texture was null".to_string()))?;

        let staging_resource = staging
            .cast()
            .map_err(|e| CaptureError::VideoError(format!("Cast staging to Resource: {}", e)))?;

        Ok(StagingResources {
            context,
            staging_resource,
        })
    }
}

/// Read raw BGRA pixel data from a Direct3D surface using pre-created staging resources.
fn read_surface_pixels_staged(
    surface: &windows::Graphics::DirectX::Direct3D11::IDirect3DSurface,
    staging: &StagingResources,
    width: u32,
    height: u32,
) -> Result<Vec<u8>, CaptureError> {
    use windows::Win32::Graphics::Direct3D11::{
        ID3D11Resource, D3D11_MAPPED_SUBRESOURCE, D3D11_MAP_READ,
    };
    use windows::Win32::System::WinRT::Direct3D11::IDirect3DDxgiInterfaceAccess;
    use windows::core::Interface;

    unsafe {
        let access: IDirect3DDxgiInterfaceAccess = surface
            .cast()
            .map_err(|e| CaptureError::VideoError(format!("Cast to DxgiAccess: {}", e)))?;

        let texture: windows::Win32::Graphics::Direct3D11::ID3D11Texture2D = access
            .GetInterface()
            .map_err(|e| CaptureError::VideoError(format!("GetInterface texture: {}", e)))?;

        let texture_resource: ID3D11Resource = texture
            .cast()
            .map_err(|e| CaptureError::VideoError(format!("Cast texture to Resource: {}", e)))?;

        staging.context.CopyResource(&staging.staging_resource, &texture_resource);

        let mut mapped = D3D11_MAPPED_SUBRESOURCE::default();
        staging.context
            .Map(&staging.staging_resource, 0, D3D11_MAP_READ, 0, Some(&mut mapped))
            .map_err(|e| CaptureError::VideoError(format!("Map staging: {}", e)))?;

        let row_pitch = mapped.RowPitch as usize;
        let bytes_per_pixel = 4usize; // BGRA
        let expected_row = width as usize * bytes_per_pixel;
        let mut pixels = Vec::with_capacity(height as usize * expected_row);

        for y in 0..height as usize {
            let src = std::slice::from_raw_parts(
                (mapped.pData as *const u8).add(y * row_pitch),
                expected_row,
            );
            pixels.extend_from_slice(src);
        }

        staging.context.Unmap(&staging.staging_resource, 0);

        Ok(pixels)
    }
}
