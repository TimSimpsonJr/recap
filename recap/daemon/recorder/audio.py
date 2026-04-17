"""Audio capture module for dual-channel WASAPI recording to FLAC.

Uses PyAudioWPatch for WASAPI loopback + microphone capture, and pyFLAC
for real-time FLAC encoding with continuous flush to disk.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

try:
    import numpy as np
except Exception:  # pragma: no cover - depends on local env
    np = None  # type: ignore[assignment]

try:
    import pyaudiowpatch as pyaudio
except Exception:  # pragma: no cover - depends on local env
    pyaudio = None  # type: ignore[assignment]

try:
    import pyflac
except Exception:  # pragma: no cover - depends on local env
    pyflac = None  # type: ignore[assignment]


class AudioDeviceError(Exception):
    """Raised when no suitable audio device is found."""


def _require_audio_runtime() -> tuple[Any, Any]:
    global pyaudio, pyflac
    return _require_pyaudio(), _require_pyflac()


def _require_pyaudio() -> Any:
    global pyaudio
    if pyaudio is None:
        try:
            import pyaudiowpatch as imported_pyaudio
        except Exception as exc:  # pragma: no cover - depends on local env
            raise RuntimeError(
                "PyAudioWPatch is required for recording audio. Install the daemon extras.",
            ) from exc
        pyaudio = imported_pyaudio
    return pyaudio


def _require_pyflac() -> Any:
    global pyflac
    if pyflac is None:
        try:
            import pyflac as imported_pyflac
        except Exception as exc:  # pragma: no cover - depends on local env
            raise RuntimeError(
                "pyflac is required for FLAC recording. Install the daemon extras.",
            ) from exc
        pyflac = imported_pyflac
    return pyflac


def _require_numpy() -> Any:
    global np
    if np is None:
        try:
            import numpy as imported_np
        except Exception as exc:  # pragma: no cover - depends on local env
            raise RuntimeError(
                "numpy is required for audio processing. Install the daemon extras.",
            ) from exc
        np = imported_np
    return np


def find_loopback_device() -> dict[str, Any]:
    """Find the default WASAPI loopback device for system audio capture.

    Returns:
        Device info dict from PyAudioWPatch.

    Raises:
        AudioDeviceError: If no WASAPI loopback device is available.
    """
    runtime_pyaudio = _require_pyaudio()
    p = runtime_pyaudio.PyAudio()
    try:
        p.get_host_api_info_by_type(runtime_pyaudio.paWASAPI)
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
    runtime_pyaudio = _require_pyaudio()
    p = runtime_pyaudio.PyAudio()
    try:
        p.get_host_api_info_by_type(runtime_pyaudio.paWASAPI)
        device = p.get_default_wasapi_device(d_in=True)
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

    on_chunk: Callable[[bytes, int], None] | None = None

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
        self._pa: Any = None
        self._mic_stream: Any = None
        self._loopback_stream: Any = None
        self._encoder: Any = None
        self._output_file: Any = None
        self._mic_buffer: bytes = b""
        self._loopback_buffer: bytes = b""

        # Public callback invoked with (mono_chunk_bytes, sample_rate) after
        # each interleave/encode cycle. Consumers (e.g. streaming ASR/diarization)
        # can subscribe without reaching into private state.
        self.on_chunk = None

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
        numpy = _require_numpy()
        if samples.size == 0:
            return 0.0
        rms = numpy.sqrt(numpy.mean(samples.astype(numpy.float64) ** 2))
        # Normalize int16 range to 0.0-1.0
        return float(rms / 32768.0)

    def _combine_frames(self, chunk_frames: int) -> tuple[Any, Any, bytes]:
        """Drain both buffers and return mic/loopback samples plus a mono mix.

        Returns:
            (mic_samples, lb_samples, mono_chunk_bytes) where:
            - mic_samples and lb_samples are numpy int16 arrays of length chunk_frames
            - mono_chunk_bytes is the averaged (mic + loopback) mix as int16 bytes,
              suitable for feeding to streaming ASR/diarization models.
        """
        numpy = _require_numpy()
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

        mic_samples = numpy.frombuffer(mic_data, dtype=numpy.int16)[:chunk_frames]
        lb_samples = numpy.frombuffer(lb_data, dtype=numpy.int16)[:chunk_frames]

        # Build mono mix (mic + loopback averaged) for streaming consumers.
        # Widen to int32 before averaging to avoid int16 overflow.
        mono_combined = ((mic_samples.astype(numpy.int32) + lb_samples.astype(numpy.int32)) // 2).astype(numpy.int16)
        mono_chunk_bytes = mono_combined.tobytes()

        return mic_samples, lb_samples, mono_chunk_bytes

    def _interleave_and_encode(self, chunk_frames: int) -> None:
        """Take buffered mic and loopback data, interleave, and feed to encoder.

        Channel layout: [mic_sample, loopback_sample] per frame.
        Both sources are mono int16; output is stereo int16.

        After encoding, invokes ``on_chunk(mono_chunk_bytes, sample_rate)`` if
        a callback is registered. The callback runs in the recording thread;
        exceptions are logged and swallowed so a misbehaving consumer cannot
        crash capture.
        """
        numpy = _require_numpy()

        mic_samples, lb_samples, mono_chunk_bytes = self._combine_frames(chunk_frames)

        # Interleave: [mic0, lb0, mic1, lb1, ...]
        interleaved = numpy.empty(chunk_frames * 2, dtype=numpy.int16)
        interleaved[0::2] = mic_samples
        interleaved[1::2] = lb_samples

        # Update RMS from the interleaved audio
        self._current_rms = self._compute_rms(interleaved)

        # Reshape to (frames, channels) for pyFLAC
        frames = interleaved.reshape(-1, 2)
        if self._encoder is not None:
            self._encoder.process(frames)

        if self.on_chunk is not None:
            try:
                self.on_chunk(mono_chunk_bytes, self._sample_rate)
            except Exception:
                logger.exception("on_chunk callback raised")

    def _test_feed_mock_frames(
        self, mic_frame: bytes, system_frame: bytes
    ) -> None:  # pragma: no cover - test-only helper
        """Test helper: push raw mic/system bytes into the buffers and drive the
        interleave/encode cycle exactly as the drain loop would.

        Designed to exercise the real `_interleave_and_encode` path (including
        `on_chunk`) without requiring a live pyFLAC encoder or WASAPI streams.
        The encoder is expected to be ``None`` in tests, in which case the
        FLAC-encode step is skipped but the callback still fires.
        """
        if len(mic_frame) != len(system_frame):
            raise ValueError("mic_frame and system_frame must have the same length")
        chunk_frames = len(mic_frame) // 2  # int16 = 2 bytes per sample
        with self._lock:
            self._mic_buffer += mic_frame
            self._loopback_buffer += system_frame
        self._interleave_and_encode(chunk_frames)

    def _mic_callback(self, in_data: bytes, frame_count: int, time_info: dict, status: int) -> tuple[None, int]:
        """PyAudioWPatch callback for microphone stream."""
        runtime_pyaudio = _require_pyaudio()
        with self._lock:
            self._mic_buffer += in_data
        return (None, runtime_pyaudio.paContinue)

    def _loopback_callback(self, in_data: bytes, frame_count: int, time_info: dict, status: int) -> tuple[None, int]:
        """PyAudioWPatch callback for loopback stream."""
        runtime_pyaudio = _require_pyaudio()
        with self._lock:
            self._loopback_buffer += in_data
        return (None, runtime_pyaudio.paContinue)

    def start(self) -> None:
        """Open audio streams and begin recording to FLAC.

        Opens PyAudioWPatch streams for both the default WASAPI loopback
        (system audio) and default microphone, interleaving frames into
        a pyFLAC encoder that continuously flushes to disk.
        """
        if self._recording:
            return

        runtime_pyaudio = _require_pyaudio()
        runtime_pyflac = _require_pyflac()

        # Resolve the actual capture rate BEFORE creating the output file or
        # pyFLAC encoder so a rate mismatch exits cleanly without partial init.
        # WASAPI shared-mode refuses any rate that isn't the device's engine
        # rate (see `-9997 Invalid sample rate` in PyAudioWPatch); we must
        # therefore capture at the device-native rate rather than hardcoding
        # 16000. In-process resampling across differing mic/loopback clocks is
        # out of scope for Phase 7 -- we fail fast with a clear error instead.
        self._pa = runtime_pyaudio.PyAudio()
        loopback_info = self._pa.get_default_wasapi_loopback()
        mic_info = self._pa.get_default_wasapi_device(d_in=True)

        lb_rate = int(loopback_info["defaultSampleRate"])
        mic_rate = int(mic_info["defaultSampleRate"])
        if lb_rate != mic_rate:
            raise AudioDeviceError(
                f"Mic and loopback devices have different native sample rates "
                f"(mic={mic_rate} Hz, loopback={lb_rate} Hz); in-process "
                f"resampling is not yet implemented. Match device rates in "
                f"Windows sound settings (typically both 48000 Hz)."
            )
        self._sample_rate = lb_rate

        self._output_file = open(self._output_path, "wb")

        self._encoder = runtime_pyflac.StreamEncoder(
            write_callback=self._write_callback,
            sample_rate=self._sample_rate,
        )

        chunk_size = 1024

        # Open loopback stream (system audio)
        self._loopback_stream = self._pa.open(
            format=runtime_pyaudio.paInt16,
            channels=1,
            rate=self._sample_rate,
            input=True,
            input_device_index=loopback_info["index"],
            frames_per_buffer=chunk_size,
            stream_callback=self._loopback_callback,
        )

        # Open microphone stream
        self._mic_stream = self._pa.open(
            format=runtime_pyaudio.paInt16,
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
