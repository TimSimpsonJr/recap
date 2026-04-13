"""Audio capture module for dual-channel WASAPI recording to FLAC.

Uses PyAudioWPatch for WASAPI loopback + microphone capture, and pyFLAC
for real-time FLAC encoding with continuous flush to disk.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import numpy as np
import pyaudiowpatch as pyaudio
import pyflac


class AudioDeviceError(Exception):
    """Raised when no suitable audio device is found."""


def find_loopback_device() -> dict[str, Any]:
    """Find the default WASAPI loopback device for system audio capture.

    Returns:
        Device info dict from PyAudioWPatch.

    Raises:
        AudioDeviceError: If no WASAPI loopback device is available.
    """
    p = pyaudio.PyAudio()
    try:
        p.get_host_api_info_by_type(pyaudio.paWASAPI)
        return p.get_default_wasapi_loopback()
    except OSError as exc:
        raise AudioDeviceError(f"No WASAPI loopback device found: {exc}") from exc
    finally:
        p.terminate()


def find_microphone_device() -> dict[str, Any]:
    """Find the default WASAPI input (microphone) device.

    Returns:
        Device info dict from PyAudioWPatch.

    Raises:
        AudioDeviceError: If no WASAPI microphone device is available.
    """
    p = pyaudio.PyAudio()
    try:
        p.get_host_api_info_by_type(pyaudio.paWASAPI)
        device = p.get_default_wasapi_device("input")
        if device.get("maxInputChannels", 0) < 1:
            raise AudioDeviceError(
                f"Default WASAPI input device has no input channels: {device.get('name')}"
            )
        return device
    except OSError as exc:
        raise AudioDeviceError(f"No WASAPI microphone device found: {exc}") from exc
    finally:
        p.terminate()


class AudioCapture:
    """Captures microphone and system audio into a single interleaved FLAC file.

    Opens two PyAudioWPatch WASAPI streams (loopback + mic), interleaves
    frames into a pyFLAC StreamEncoder that flushes continuously to disk.
    """

    def __init__(
        self,
        output_path: Path,
        sample_rate: int = 16000,
        channels: int = 2,
    ) -> None:
        self._output_path = output_path
        self._sample_rate = sample_rate
        self._channels = channels

        self._recording = False
        self._current_rms: float = 0.0
        self._lock = threading.Lock()

        # Initialized on start()
        self._pa: pyaudio.PyAudio | None = None
        self._mic_stream: Any = None
        self._loopback_stream: Any = None
        self._encoder: pyflac.StreamEncoder | None = None
        self._output_file: Any = None
        self._mic_buffer: bytes = b""
        self._loopback_buffer: bytes = b""

    @property
    def output_path(self) -> Path:
        return self._output_path

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def channels(self) -> int:
        return self._channels

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def current_rms(self) -> float:
        return self._current_rms

    def _write_callback(self, data: bytes, num_frames: int, num_samples: int, current_frame: int) -> None:
        """Called by pyFLAC encoder when compressed data is ready. Flush immediately."""
        if self._output_file is not None:
            self._output_file.write(data)
            self._output_file.flush()

    def _compute_rms(self, samples: np.ndarray) -> float:
        """Compute RMS level from audio samples."""
        if samples.size == 0:
            return 0.0
        rms = np.sqrt(np.mean(samples.astype(np.float64) ** 2))
        # Normalize int16 range to 0.0-1.0
        return float(rms / 32768.0)

    def _interleave_and_encode(self, chunk_frames: int) -> None:
        """Take buffered mic and loopback data, interleave, and feed to encoder.

        Channel layout: [mic_sample, loopback_sample] per frame.
        Both sources are mono int16; output is stereo int16.
        """
        bytes_needed = chunk_frames * 2  # 2 bytes per int16 sample

        with self._lock:
            mic_data = self._mic_buffer[:bytes_needed]
            self._mic_buffer = self._mic_buffer[bytes_needed:]
            lb_data = self._loopback_buffer[:bytes_needed]
            self._loopback_buffer = self._loopback_buffer[bytes_needed:]

        # Pad with silence if one source has less data
        if len(mic_data) < bytes_needed:
            mic_data += b"\x00" * (bytes_needed - len(mic_data))
        if len(lb_data) < bytes_needed:
            lb_data += b"\x00" * (bytes_needed - len(lb_data))

        mic_samples = np.frombuffer(mic_data, dtype=np.int16)
        lb_samples = np.frombuffer(lb_data, dtype=np.int16)

        # Interleave: [mic0, lb0, mic1, lb1, ...]
        interleaved = np.empty(chunk_frames * 2, dtype=np.int16)
        interleaved[0::2] = mic_samples[:chunk_frames]
        interleaved[1::2] = lb_samples[:chunk_frames]

        # Update RMS from the interleaved audio
        self._current_rms = self._compute_rms(interleaved)

        # Reshape to (frames, channels) for pyFLAC
        frames = interleaved.reshape(-1, 2)
        if self._encoder is not None:
            self._encoder.process(frames)

    def _mic_callback(self, in_data: bytes, frame_count: int, time_info: dict, status: int) -> tuple[None, int]:
        """PyAudioWPatch callback for microphone stream."""
        with self._lock:
            self._mic_buffer += in_data
        return (None, pyaudio.paContinue)

    def _loopback_callback(self, in_data: bytes, frame_count: int, time_info: dict, status: int) -> tuple[None, int]:
        """PyAudioWPatch callback for loopback stream."""
        with self._lock:
            self._loopback_buffer += in_data
        return (None, pyaudio.paContinue)

    def start(self) -> None:
        """Open audio streams and begin recording to FLAC.

        Opens PyAudioWPatch streams for both the default WASAPI loopback
        (system audio) and default microphone, interleaving frames into
        a pyFLAC encoder that continuously flushes to disk.
        """
        if self._recording:
            return

        self._output_file = open(self._output_path, "wb")

        self._encoder = pyflac.StreamEncoder(
            write_callback=self._write_callback,
            sample_rate=self._sample_rate,
            channels=self._channels,
        )

        self._pa = pyaudio.PyAudio()

        # Find devices
        loopback_info = self._pa.get_default_wasapi_loopback()
        mic_info = self._pa.get_default_wasapi_device("input")

        chunk_size = 1024

        # Open loopback stream (system audio)
        self._loopback_stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self._sample_rate,
            input=True,
            input_device_index=loopback_info["index"],
            frames_per_buffer=chunk_size,
            stream_callback=self._loopback_callback,
        )

        # Open microphone stream
        self._mic_stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self._sample_rate,
            input=True,
            input_device_index=mic_info["index"],
            frames_per_buffer=chunk_size,
            stream_callback=self._mic_callback,
        )

        self._recording = True

        # Start a background thread that periodically drains buffers
        self._drain_thread = threading.Thread(
            target=self._drain_loop,
            daemon=True,
            name="audio-drain",
        )
        self._drain_thread.start()

    def _drain_loop(self) -> None:
        """Background thread that drains audio buffers and feeds the encoder."""
        import time

        chunk_frames = 1024
        bytes_per_chunk = chunk_frames * 2  # int16 = 2 bytes

        while self._recording:
            with self._lock:
                has_data = (
                    len(self._mic_buffer) >= bytes_per_chunk
                    or len(self._loopback_buffer) >= bytes_per_chunk
                )

            if has_data:
                self._interleave_and_encode(chunk_frames)
            else:
                time.sleep(0.01)

    def stop(self) -> Path:
        """Stop recording, finalize FLAC, and return the output path.

        Returns:
            Path to the completed FLAC file.
        """
        self._recording = False

        if hasattr(self, "_drain_thread"):
            self._drain_thread.join(timeout=2.0)

        # Drain any remaining buffered audio
        with self._lock:
            remaining = max(
                len(self._mic_buffer) // 2,
                len(self._loopback_buffer) // 2,
            )
        if remaining > 0:
            self._interleave_and_encode(remaining)

        # Stop streams
        if self._loopback_stream is not None:
            self._loopback_stream.stop_stream()
            self._loopback_stream.close()
            self._loopback_stream = None

        if self._mic_stream is not None:
            self._mic_stream.stop_stream()
            self._mic_stream.close()
            self._mic_stream = None

        # Finalize encoder
        if self._encoder is not None:
            self._encoder.finish()
            self._encoder = None

        # Close output file
        if self._output_file is not None:
            self._output_file.close()
            self._output_file = None

        # Terminate PyAudio
        if self._pa is not None:
            self._pa.terminate()
            self._pa = None

        return self._output_path
