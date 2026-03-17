use std::fs::File;
use std::io::{Seek, SeekFrom, Write};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread::{self, JoinHandle};

use windows::Win32::Media::Audio::{
    eCapture, eConsole, eRender, IAudioCaptureClient, IAudioClient, IMMDevice,
    IMMDeviceEnumerator, MMDeviceEnumerator, AUDCLNT_SHAREMODE_SHARED,
    AUDCLNT_STREAMFLAGS_LOOPBACK, WAVEFORMATEX,
};
use windows::Win32::System::Com::{
    CoCreateInstance, CoInitializeEx, CoUninitialize, CLSCTX_ALL, COINIT_MULTITHREADED,
};
use windows::Win32::System::Threading::{CreateEventW, WaitForSingleObject};

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
    /// Start capturing remote audio from the specified process via WASAPI loopback.
    ///
    /// Uses the default render endpoint in loopback mode to capture system audio.
    /// For per-process capture (Windows 10 21H1+), ActivateAudioInterfaceAsync
    /// would be used — here we use device loopback as a simpler first pass that
    /// can be upgraded to per-process loopback later.
    pub fn start_remote(_pid: u32, output_path: PathBuf) -> Result<Self, CaptureError> {
        let stop = Arc::new(AtomicBool::new(false));
        let stop_clone = stop.clone();

        let handle = thread::spawn(move || -> Result<(), CaptureError> {
            unsafe {
                let _ = CoInitializeEx(None, COINIT_MULTITHREADED);
            }

            let result = unsafe { capture_loopback(output_path, &stop_clone) };

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

/// Capture audio from the default render device in loopback mode.
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

/// Capture audio from the default recording device (microphone).
unsafe fn capture_microphone(
    output_path: PathBuf,
    stop: &AtomicBool,
) -> Result<(), CaptureError> {
    let enumerator: IMMDeviceEnumerator =
        CoCreateInstance(&MMDeviceEnumerator, None, CLSCTX_ALL)
            .map_err(|e| CaptureError::NoMicrophoneDevice(format!("Device enumerator: {}", e)))?;

    let device: IMMDevice = enumerator
        .GetDefaultAudioEndpoint(eCapture, eConsole)
        .map_err(|e| CaptureError::NoMicrophoneDevice(format!("No mic device: {}", e)))?;

    capture_from_device(device, 0, output_path, stop).map_err(|e| match e {
        CaptureError::WindowsError(msg) => CaptureError::NoMicrophoneDevice(msg),
        other => other,
    })
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
