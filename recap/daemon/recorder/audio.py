"""Audio capture module for dual-channel WASAPI recording to FLAC.

Uses PyAudioWPatch for WASAPI loopback + microphone capture, and pyFLAC
for real-time FLAC encoding with continuous flush to disk.
"""

from __future__ import annotations

import enum
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

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

try:
    import soxr
except Exception:  # pragma: no cover - depends on local env
    soxr = None  # type: ignore[assignment]


def _require_soxr() -> Any:
    global soxr
    if soxr is None:
        try:
            import soxr as imported_soxr
        except Exception as exc:  # pragma: no cover - depends on local env
            raise RuntimeError(
                "soxr is required for streaming audio resampling. "
                "Install the daemon extras.",
            ) from exc
        soxr = imported_soxr
    return soxr


class _SoxrResamplerWrapper:
    """Stateful streaming wrapper around ``soxr.ResampleStream``.

    Owns one resampler instance configured for (input_rate -> output_rate).
    ``process(pcm_bytes)`` accepts mono int16 LE bytes and returns mono
    int16 LE bytes at the output rate. State is preserved across calls
    so per-chunk edge artifacts are avoided.

    ``rebuild(input_rate=...)`` tears down the current resampler and
    builds a new one at the new input rate (output rate is fixed).
    Called by ``_SourceStream`` when a reopen lands on a device with a
    different native rate.
    """

    def __init__(self, *, input_rate: int, output_rate: int) -> None:
        self._output_rate = output_rate
        self._input_rate = input_rate
        self._stream = self._build_stream(input_rate)

    def _build_stream(self, input_rate: int) -> Any:
        runtime_soxr = _require_soxr()
        return runtime_soxr.ResampleStream(
            in_rate=float(input_rate),
            out_rate=float(self._output_rate),
            num_channels=1,
            dtype="int16",
            quality="HQ",
        )

    @property
    def input_rate(self) -> int:
        return self._input_rate

    @property
    def output_rate(self) -> int:
        return self._output_rate

    def process(self, pcm_bytes: bytes) -> bytes:
        """Feed mono int16 LE bytes in, get mono int16 LE bytes out."""
        numpy = _require_numpy()
        if not pcm_bytes:
            return b""
        arr = numpy.frombuffer(pcm_bytes, dtype=numpy.int16)
        out = self._stream.resample_chunk(arr, last=False)
        return out.tobytes() if out is not None and len(out) > 0 else b""

    def rebuild(self, *, input_rate: int) -> None:
        """Tear down and rebuild for a new input rate."""
        self._input_rate = input_rate
        self._stream = self._build_stream(input_rate)


class _SourceHealth(enum.Enum):
    """Health states of a capture source.

    STOPPED: start() not yet called, or stop() has been called.
    HEALTHY: stream open, delivering frames normally.
    RECONNECTING: transient failure detected; reopen in progress or
        awaiting backoff. Still silent-pads read_frames output.
    DEGRADED: reopen window (~5s) elapsed without success. Non-terminal
        -- subsequent attempt_reopen_if_due() calls can restore HEALTHY.
        Emits a one-shot journal warning on entry; silent afterwards
        until recovery or stop.
    """

    STOPPED = "stopped"
    HEALTHY = "healthy"
    RECONNECTING = "reconnecting"
    DEGRADED = "degraded"


_MAX_RECONNECT_ATTEMPTS = 20


class _SourceStream:
    """One capture source: either the mic or the WASAPI loopback.

    Owns a PyAudio stream, a stateful soxr resampler, a raw inbound
    buffer, a resampled 48 kHz buffer, a stable device identity, and
    health/reconnect state. See
    ``docs/plans/2026-04-17-audio-hotswap-resampling-design.md`` §2
    for the full contract.

    Private to this module -- nothing imports it from elsewhere.
    """

    def __init__(
        self,
        *,
        kind: str,
        output_rate: int,
        bind_to: tuple | None = None,
    ) -> None:
        self._kind = kind
        self._output_rate = output_rate
        self._state = _SourceHealth.STOPPED
        self._lock = threading.Lock()

        self._stream: Any = None
        self._pa: Any = None
        self._resampler: _SoxrResamplerWrapper | None = None
        self._bound_identity: tuple | None = None
        self._latest_default_identity: tuple | None = None
        # Channel count of the currently bound PyAudio stream. WASAPI
        # loopback devices and many USB mics report ``maxInputChannels=2``
        # and reject ``channels=1`` with ``paInvalidDevice`` (-9996), so
        # we open at the device's native channel count and downmix to
        # mono in the pump before feeding soxr.
        self._input_channels: int = 1

        self._raw_buffer = b""
        self._resampled_buffer = b""

        self._last_status_ok_ts: float | None = None
        self._reconnect_attempts = 0
        self._next_reopen_at: float = 0.0
        self._terminal: bool = False
        # Explicit per-endpoint binding. None means legacy default-following
        # behavior (``get_default_wasapi_loopback`` / ``get_default_wasapi_device``
        # on every open and reopen). A tuple is a stable identity produced by
        # ``_compute_identity``; ``_lookup_bound_device`` scans the WASAPI
        # enumeration for a match. Only loopback streams are expected to set
        # this; the mic path keeps default-following behavior.
        self._bind_to: tuple | None = bind_to

    @property
    def state(self) -> _SourceHealth:
        with self._lock:
            return self._state

    @property
    def kind(self) -> str:
        return self._kind

    def is_degraded(self) -> bool:
        return self.state == _SourceHealth.DEGRADED

    @property
    def is_terminal(self) -> bool:
        """True once the source has exhausted _MAX_RECONNECT_ATTEMPTS failed
        reopens. Sticky: never flips back to False.

        Lockless read: _terminal is a single-bool field, GIL guarantees the
        load is atomic. The write site in attempt_reopen_if_due runs on the
        drain thread (the only mutator), so no read-during-write race
        exists. Matches the file's single-writer-drain-thread convention for
        _reconnect_attempts and _next_reopen_at.
        """
        return self._terminal

    def _mark_terminal_for_test(self) -> None:  # pragma: no cover - test-only helper
        """Test hook: flip the terminal flag without going through the reopen loop."""
        self._terminal = True

    @staticmethod
    def _compute_identity(info: dict) -> tuple:
        """Stable device identity that survives hot-plug index reshuffles.
        Prefer a native endpoint ID if the info dict has one; otherwise
        fall back to (name, hostApi, maxInputChannels)."""
        endpoint_id = info.get("endpointId") or info.get("guid")
        if endpoint_id:
            return ("endpoint", endpoint_id)
        return (
            "composite",
            info.get("name", ""),
            info.get("hostApi", -1),
            info.get("maxInputChannels", 0),
        )

    def _lookup_bound_device(self) -> dict:
        """Return the PyAudio device-info dict for this stream's target.

        Three cases:

        * ``bind_to is None`` and ``kind == "loopback"``: return the default
          WASAPI loopback endpoint (legacy behavior -- the stream follows
          whatever the OS currently considers the default render device).
        * ``bind_to is None`` and ``kind == "mic"``: return the default
          WASAPI input device (the mic path always default-follows; it
          never takes an explicit ``bind_to``).
        * ``bind_to is not None``: scan the full WASAPI device
          enumeration and return the device whose identity tuple matches
          ``self._bind_to``. No kind-check is enforced here today; only
          loopback callers pass ``bind_to`` in the current change (mic
          binding is out of scope for this phase).

        Raises:
            AudioDeviceError: when ``bind_to`` is set but no device in the
                current enumeration produces a matching identity. Callers
                in the reopen path translate this into ``is_terminal=True``
                rather than burning through the full reconnect budget.
        """
        pa = _require_pyaudio().PyAudio()
        try:
            if self._bind_to is None:
                if self._kind == "loopback":
                    return pa.get_default_wasapi_loopback()
                return pa.get_default_wasapi_device(d_in=True)

            count = pa.get_device_count()
            for idx in range(count):
                info = pa.get_device_info_by_index(idx)
                if self._compute_identity(info) == self._bind_to:
                    return info
            raise AudioDeviceError(
                f"loopback bound endpoint {self._bind_to!r} not in current "
                f"WASAPI enumeration",
            )
        finally:
            try:
                pa.terminate()
            except Exception:
                pass

    def read_frames(self, target_frames: int) -> bytes:
        """Return target_frames worth of mono int16 bytes at output_rate.
        Silence-pads on underflow or when the source isn't HEALTHY.
        Never blocks."""
        byte_count = target_frames * 2
        with self._lock:
            if self._state != _SourceHealth.HEALTHY:
                return b"\x00" * byte_count
            if len(self._resampled_buffer) >= byte_count:
                out = self._resampled_buffer[:byte_count]
                self._resampled_buffer = self._resampled_buffer[byte_count:]
                return out
            have = self._resampled_buffer
            self._resampled_buffer = b""
            return have + b"\x00" * (byte_count - len(have))

    def drain_resampled(self, max_bytes: int) -> bytes:
        """Drain up to max_bytes from the resampled output buffer.

        Returns whatever is currently available up to max_bytes. May return
        less than requested (including empty) when the buffer has not yet
        filled. Caller is responsible for padding with zeros if alignment
        matters.
        """
        with self._lock:
            out = self._resampled_buffer[:max_bytes]
            self._resampled_buffer = self._resampled_buffer[max_bytes:]
        return out

    def start(self) -> None:
        """Open the underlying PyAudio stream and build the resampler.

        Transitions STOPPED -> HEALTHY on success. Raises on hard
        failure (no device available at all); transient failures that
        happen post-start are handled by attempt_reopen_if_due.
        """
        runtime_pyaudio = _require_pyaudio()
        # Device lookup goes through ``_lookup_bound_device``, which opens
        # and terminates its own short-lived PyAudio handle. That's a few
        # extra microseconds versus sharing ``pa`` below, but keeps the
        # default-following / bound-endpoint branching in one place.
        info = self._lookup_bound_device()
        pa = runtime_pyaudio.PyAudio()

        native_rate = int(info["defaultSampleRate"])
        native_channels = int(info.get("maxInputChannels", 1) or 1)
        self._bound_identity = self._compute_identity(info)
        self._latest_default_identity = self._bound_identity
        self._input_channels = native_channels

        self._resampler = _SoxrResamplerWrapper(
            input_rate=native_rate,
            output_rate=self._output_rate,
        )

        chunk_size = 1024
        self._stream = pa.open(
            format=runtime_pyaudio.paInt16,
            channels=native_channels,
            rate=native_rate,
            input=True,
            input_device_index=info["index"],
            frames_per_buffer=chunk_size,
            stream_callback=self._on_audio_callback,
        )
        self._pa = pa
        with self._lock:
            self._state = _SourceHealth.HEALTHY

    def _on_audio_callback(
        self,
        in_data: bytes,
        frame_count: int,
        time_info: dict,
        status: int,
    ) -> tuple[None, int]:
        """PyAudio callback. Minimal work: append raw bytes under the
        source's lock. Resampling happens on the drain thread, not
        here, to keep the callback thread fast (design §2 guardrail:
        no device enumeration, no reopen, no logging from the callback
        thread)."""
        runtime_pyaudio = _require_pyaudio()
        with self._lock:
            self._raw_buffer += in_data
            if status == 0:
                self._last_status_ok_ts = time.monotonic()
            else:
                self._mark_unhealthy_locked()
        return (None, runtime_pyaudio.paContinue)

    def _mark_unhealthy_locked(self) -> None:
        """Callback-thread entry point. Caller must hold self._lock."""
        if self._state == _SourceHealth.HEALTHY:
            self._state = _SourceHealth.RECONNECTING

    def _pump_raw_to_resampled(self) -> None:
        """Drain the raw inbound buffer through the resampler into the
        resampled buffer. Called by the drain thread each tick; the
        callback thread only appends to the raw buffer, never touches
        the resampler directly. Safe no-op when the source isn't
        HEALTHY or the raw buffer is empty.

        When the bound PyAudio stream was opened at >1 channel (common
        for WASAPI loopback endpoints and some USB mics), the raw bytes
        are interleaved multi-channel int16 frames. We average channels
        to mono BEFORE feeding soxr so the resampler and FLAC encoder
        both stay mono."""
        with self._lock:
            if self._state != _SourceHealth.HEALTHY or self._resampler is None:
                return
            raw = self._raw_buffer
            self._raw_buffer = b""
            input_channels = self._input_channels
        if not raw:
            return
        if input_channels > 1:
            try:
                numpy = _require_numpy()
                arr = numpy.frombuffer(raw, dtype=numpy.int16)
                # Drop any trailing bytes that don't form a complete
                # multi-channel frame (shouldn't happen in practice but
                # defensive against mid-frame buffer splits).
                usable = (len(arr) // input_channels) * input_channels
                if usable == 0:
                    return
                frames = arr[:usable].reshape(-1, input_channels)
                # Widen to int32 before averaging so large multi-channel
                # sums don't wrap around; narrow back to int16.
                mono = frames.astype(numpy.int32).mean(axis=1).astype(numpy.int16)
                raw = mono.tobytes()
            except Exception:
                logger.exception("%s stereo->mono downmix failed", self._kind)
                return
        try:
            resampled = self._resampler.process(raw)
        except Exception:
            logger.exception("%s resample failed", self._kind)
            return
        with self._lock:
            self._resampled_buffer += resampled

    # Backoff ladder (seconds).
    _BACKOFF_STEPS = (0.25, 0.5, 1.0, 2.0)
    # Degrade window: after this many seconds in RECONNECTING, flip to DEGRADED.
    _DEGRADE_AFTER_SECONDS = 5.0

    def attempt_reopen_if_due(self) -> None:
        """Drain-thread entry point for health maintenance.

        Cheap when healthy: probes the target identity (bound endpoint
        when ``_bind_to`` is set, else the current OS default) and
        compares it to ``_bound_identity``. Returns immediately if they
        match. Only does reopen work when needed AND the backoff window
        has elapsed. See design §3.

        For bound streams, a vanished identity (not in the current
        WASAPI enumeration) flips ``_terminal=True`` and returns without
        burning through the reconnect budget -- the membership watcher
        (Task 7) uses this signal to evict the source cleanly.
        """
        with self._lock:
            if self._state == _SourceHealth.STOPPED:
                return

            needs_reopen = False
            # Route the probe through _lookup_bound_device so bound streams
            # check their OWN identity instead of the OS default. Without
            # this, a bound non-default loopback would see the default
            # identity != its own bound identity on every 1s health tick
            # and thrash reopen. Legacy default-following streams (bind_to
            # is None) fall through to the default-lookup branch inside
            # _lookup_bound_device and keep today's behavior.
            try:
                info = self._lookup_bound_device()
            except AudioDeviceError as exc:
                # Bound identity is no longer in the enumeration. Don't
                # thrash the reconnect budget -- flip terminal so the
                # membership watcher (Task 7) evicts this source. Returning
                # here is the same control-flow shape as the STOPPED bail
                # above, so no post-lock work runs for this case.
                logger.warning(
                    "%s bound identity vanished during health probe: %s",
                    self._kind, exc,
                )
                self._terminal = True
                return
            except Exception:
                # Any OTHER failure (PyAudio init error, OS-level glitch,
                # transient device-count hiccup) keeps the legacy behavior:
                # assume the probe is stale and let the scheduling branch
                # below trigger a reopen attempt under backoff.
                logger.exception("%s identity probe failed", self._kind)
                needs_reopen = True
            else:
                # ``_latest_default_identity`` is a historical name -- since
                # bind_to landed it tracks the latest probed identity,
                # whether that's the bound endpoint (bound streams) or the
                # current OS default (legacy default-following streams).
                probe_identity = self._compute_identity(info)
                self._latest_default_identity = probe_identity
                if (
                    self._bound_identity is not None
                    and probe_identity != self._bound_identity
                ):
                    needs_reopen = True

            if self._state in (_SourceHealth.RECONNECTING, _SourceHealth.DEGRADED):
                needs_reopen = True

            if not needs_reopen:
                return

            now = time.monotonic()
            if now < self._next_reopen_at:
                return

            if self._state == _SourceHealth.HEALTHY:
                self._state = _SourceHealth.RECONNECTING
                self._reconnect_started_at = now
                self._reconnect_attempts = 0
                logger.warning("%s reconnecting", self._kind)
            elif not hasattr(self, "_reconnect_started_at"):
                self._reconnect_started_at = now

            step = self._BACKOFF_STEPS[
                min(self._reconnect_attempts, len(self._BACKOFF_STEPS) - 1)
            ]
            self._next_reopen_at = now + step
            self._reconnect_attempts += 1

            if (
                self._state == _SourceHealth.RECONNECTING
                and now - self._reconnect_started_at >= self._DEGRADE_AFTER_SECONDS
            ):
                self._state = _SourceHealth.DEGRADED
                logger.warning("%s degraded (silent)", self._kind)

        try:
            self._do_reopen()
        except Exception as exc:
            logger.warning("%s reopen failed: %s", self._kind, exc)
            # Lockless read: attempt_reopen_if_due is the single writer of
            # _reconnect_attempts (incremented above under self._lock) and
            # runs on the drain thread, so no read-during-write race exists.
            if self._reconnect_attempts >= _MAX_RECONNECT_ATTEMPTS:
                self._terminal = True
                logger.warning(
                    "%s exceeded reconnect budget (%d); marking terminal",
                    self._kind, _MAX_RECONNECT_ATTEMPTS,
                )
            return

        with self._lock:
            was_degraded = self._state == _SourceHealth.DEGRADED
            self._state = _SourceHealth.HEALTHY
            self._reconnect_attempts = 0
            self._next_reopen_at = 0.0
            if hasattr(self, "_reconnect_started_at"):
                delattr(self, "_reconnect_started_at")
        if was_degraded:
            logger.warning("%s recovered (from degraded)", self._kind)

    def _do_reopen(self) -> None:
        """Tear down the current stream, open a new one on the target
        device returned by ``_lookup_bound_device()`` (the bound endpoint
        when ``_bind_to`` is set, else the current default), rebuild the
        resampler if the native rate changed. No journaling here --
        caller owns state transitions.

        Ordering: close the old stream first, probe the new device,
        open the new stream, and ONLY THEN rewrite bound state under
        the lock. If ``pa.open`` raises mid-reopen, the source keeps
        its old identity/resampler so the next reopen attempt starts
        from a coherent baseline rather than a half-updated wedge.
        """
        old_stream = self._stream
        old_pa = self._pa
        if old_stream is not None:
            try:
                old_stream.stop_stream()
                old_stream.close()
            except Exception:
                pass
        if old_pa is not None:
            try:
                old_pa.terminate()
            except Exception:
                pass

        runtime_pyaudio = _require_pyaudio()
        # Probe the target device FIRST via the helper -- it owns its own
        # short-lived PyAudio handle. If the bound identity has vanished
        # from the enumeration, flip the terminal flag immediately (the
        # membership watcher evicts this source rather than waiting for
        # the full reopen budget to drain) and re-raise so the caller's
        # failure path runs instead of the HEALTHY-transition path.
        try:
            info = self._lookup_bound_device()
        except AudioDeviceError as exc:
            logger.warning("%s bound identity vanished: %s", self._kind, exc)
            self._terminal = True
            # Mirror the existing failure path: null the already-closed
            # stream/pa handles so the next call doesn't double-close.
            self._stream = None
            self._pa = None
            raise

        pa = runtime_pyaudio.PyAudio()
        try:
            native_rate = int(info["defaultSampleRate"])
            native_channels = int(info.get("maxInputChannels", 1) or 1)
            new_identity = self._compute_identity(info)

            chunk_size = 1024
            new_stream = pa.open(
                format=runtime_pyaudio.paInt16,
                channels=native_channels,
                rate=native_rate,
                input=True,
                input_device_index=info["index"],
                frames_per_buffer=chunk_size,
                stream_callback=self._on_audio_callback,
            )
        except Exception:
            # Probe or open failed; release the PyAudio handle we grabbed
            # and leave source state (identity, resampler) untouched so
            # the next attempt retries from a clean baseline.
            try:
                pa.terminate()
            except Exception:
                pass
            # Null _stream/_pa since the old ones were already closed at
            # the top of this method -- leaving the stale references in
            # place would trip double-close on the next reopen.
            self._stream = None
            self._pa = None
            raise

        # Reopen succeeded. Commit new state under the lock. Rebuild the
        # resampler unconditionally if the rate changed; also rebuild
        # when the rate matches but the device changed, so soxr's
        # streaming filter state doesn't carry a previous device's
        # sample tail across the reopen boundary.
        with self._lock:
            identity_changed = self._bound_identity != new_identity
            rate_changed = (
                self._resampler is None
                or self._resampler.input_rate != native_rate
            )
            if rate_changed or identity_changed:
                self._resampler = _SoxrResamplerWrapper(
                    input_rate=native_rate,
                    output_rate=self._output_rate,
                )
            self._bound_identity = new_identity
            self._latest_default_identity = new_identity
            self._input_channels = native_channels
            self._raw_buffer = b""
            self._resampled_buffer = b""
            self._stream = new_stream
            self._pa = pa

    def stop(self) -> None:
        """Transition to STOPPED before tearing down internals so a
        racing watchdog tick doesn't try to reopen a shutting-down
        source. PyAudio handles are released OUTSIDE the source lock
        so a callback waiting on the same lock can't deadlock teardown."""
        with self._lock:
            self._state = _SourceHealth.STOPPED
            stream = self._stream
            pa = self._pa
            self._stream = None
            self._pa = None
            self._resampler = None
            self._raw_buffer = b""
            self._resampled_buffer = b""
        if stream is not None:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                logger.exception("Error closing %s stream", self._kind)
        if pa is not None:
            try:
                pa.terminate()
            except Exception:
                logger.exception("Error terminating %s PyAudio", self._kind)


class AudioDeviceError(Exception):
    """Raised when no suitable audio device is found."""


class AudioCaptureBothSourcesFailedError(Exception):
    """The mic capture source has degraded past its reopen window.
    The recording cannot continue; recorder should stop cleanly and
    surface the error to the user.

    Name retained for backward compatibility with callers that import
    the symbol; in the multi-output design only mic degradation is
    fatal, since loopback absence/degradation is tracked via
    audio_warnings metadata rather than fatal state."""


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


# --- Multi-output loopback lifecycle constants ---
_LOOPBACK_PROBATION_S = 60.0
_LOOPBACK_MEMBERSHIP_TICK_S = 3.0
_LOOPBACK_DEVICE_GRACE_S = 6.0
_LOOPBACK_ACTIVE_RMS_DBFS = -40.0
# Derived once at module load:
#   10 ** (-40/20) = 0.01; 0.01 * 32768 ≈ 327.68
_LOOPBACK_ACTIVE_RMS_LINEAR = 10.0 ** (_LOOPBACK_ACTIVE_RMS_DBFS / 20.0) * 32768.0


@dataclass
class _LoopbackEntry:
    """Recorder-side policy wrapper around a loopback _SourceStream.

    Tracks PROBATION/ACTIVE lifecycle, wall-clock opened_at for probation
    expiry, last_active_at for telemetry, and missing_since for debounced
    device-disappearance. Does NOT introspect _SourceStream's private state;
    the only coupling is the public is_terminal property.
    """
    stream: "_SourceStream"
    state: Literal["probation", "active"]
    opened_at: float
    last_active_at: float | None
    device_name: str
    missing_since: float | None


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
        self._encoder: Any = None
        self._output_file: Any = None
        self._mic_buffer: bytes = b""
        self._mic_source: _SourceStream | None = None
        self._loopback_sources: dict[tuple, "_LoopbackEntry"] = {}
        self._last_membership_tick: float = 0.0
        self._fatal_error: Exception | None = None
        self._fatal_event: threading.Event = threading.Event()
        self._drain_thread: threading.Thread | None = None

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

    def _drain_and_mix(
        self, chunk_frames: int,
    ) -> tuple["np.ndarray", "np.ndarray", bytes]:
        """Drain mic + all loopback sources for one chunk and build channel-0
        (mic), channel-1 (system mix), and the mono chunk for on_chunk.

        Replaces _combine_frames for the multi-output design. Mic behavior is
        unchanged; system mix is an RMS-thresholded divide-by-active-count
        average of all loopback streams.

        Lifecycle side effect: a PROBATION _LoopbackEntry whose chunk RMS
        crosses _LOOPBACK_ACTIVE_RMS_LINEAR flips to ACTIVE here (the only
        place promotions happen).
        """
        numpy = _require_numpy()
        bytes_needed = chunk_frames * 2

        # --- Mic drain: unchanged. ---
        with self._lock:
            mic_data = self._mic_buffer[:bytes_needed]
            self._mic_buffer = self._mic_buffer[bytes_needed:]
        if len(mic_data) < bytes_needed:
            mic_data += b"\x00" * (bytes_needed - len(mic_data))
        mic_samples = numpy.frombuffer(mic_data, dtype=numpy.int16)[:chunk_frames]

        # --- Loopback drain + mix ---
        system_sum_i32 = numpy.zeros(chunk_frames, dtype=numpy.int32)
        active_count = 0
        now = time.monotonic()

        # Lockless iteration: _loopback_sources is drain-thread-owned.
        # _tick_membership (Task 7) is the only other mutator of this dict
        # and runs on the same drain thread, so no read-during-write race
        # exists. Matches the single-writer-drain-thread convention used
        # by _SourceStream.is_terminal and attempt_reopen_if_due.
        for key, entry in self._loopback_sources.items():
            stream_bytes = entry.stream.drain_resampled(bytes_needed)

            # Measure RMS on UNPADDED samples only -- padding zeros before
            # measurement would depress the level of a stream with a short
            # buffer and misclassify it as silent.
            real_samples = numpy.frombuffer(stream_bytes, dtype=numpy.int16)
            if real_samples.size > 0:
                rms_linear = float(
                    numpy.sqrt(numpy.mean(real_samples.astype(numpy.float64) ** 2)),
                )
            else:
                rms_linear = 0.0

            # Pad for alignment after measuring.
            if len(stream_bytes) < bytes_needed:
                stream_bytes = stream_bytes + b"\x00" * (bytes_needed - len(stream_bytes))
            stream_samples = numpy.frombuffer(
                stream_bytes, dtype=numpy.int16,
            )[:chunk_frames]

            if rms_linear > _LOOPBACK_ACTIVE_RMS_LINEAR:
                system_sum_i32 += stream_samples.astype(numpy.int32)
                active_count += 1
                if entry.state == "probation":
                    entry.state = "active"
                    entry.last_active_at = now
                    logger.info(
                        "loopback %s promoted to ACTIVE (elapsed=%.1fs)",
                        entry.device_name, now - entry.opened_at,
                    )
                else:
                    entry.last_active_at = now

        if active_count > 0:
            system_mix_i32 = system_sum_i32 // active_count
            system_mix = numpy.clip(system_mix_i32, -32768, 32767).astype(numpy.int16)
        else:
            system_mix = numpy.zeros(chunk_frames, dtype=numpy.int16)

        # Mono for on_chunk consumers: (mic + system_mix) / 2 in int32.
        mono_i32 = (
            mic_samples.astype(numpy.int32) + system_mix.astype(numpy.int32)
        ) // 2
        mono_bytes = numpy.clip(mono_i32, -32768, 32767).astype(numpy.int16).tobytes()

        return mic_samples, system_mix, mono_bytes

    def _enumerate_loopback_endpoints(self):
        """Yield (stable_identity, device_info_dict) pairs for every WASAPI
        render loopback endpoint currently available.

        Uses PyAudioWPatch's loopback-device generator. The stable identity
        is the same tuple that _SourceStream._compute_identity uses for
        hot-plug tracking.
        """
        pa = _require_pyaudio().PyAudio()
        try:
            for info in pa.get_loopback_device_info_generator():
                key = _SourceStream._compute_identity(info)
                yield key, info
        finally:
            pa.terminate()

    def _open_loopback_stream(self, bind_to: tuple, device_name: str) -> "_SourceStream":
        """Open a new _SourceStream bound to the given endpoint identity.

        Factored out so _tick_membership tests can override it without
        mocking PyAudio.
        """
        s = _SourceStream(
            kind="loopback", output_rate=self._sample_rate, bind_to=bind_to,
        )
        s.start()
        return s

    def _tick_membership(self, now: float) -> None:
        """Reconcile _loopback_sources against the current WASAPI enumeration.

        Runs from the drain thread with a wall-clock gate; owns the entire
        dict lifecycle outside of PROBATION->ACTIVE promotion (which lives
        in _drain_and_mix). Enumeration failures are logged and swallowed --
        a missed tick never tears streams down.
        """
        try:
            enumerated = dict(self._enumerate_loopback_endpoints())
        except Exception:
            logger.debug(
                "_tick_membership: enumeration failed, skipping this tick",
                exc_info=True,
            )
            return

        enumerated_keys = set(enumerated.keys())
        current_keys = set(self._loopback_sources.keys())

        # Adds: open new streams for newly-appeared endpoints.
        for key in enumerated_keys - current_keys:
            info = enumerated[key]
            try:
                stream = self._open_loopback_stream(
                    bind_to=key, device_name=info["name"],
                )
            except Exception:
                logger.warning(
                    "failed to open loopback %s; will retry next tick",
                    info.get("name", key), exc_info=True,
                )
                continue
            self._loopback_sources[key] = _LoopbackEntry(
                stream=stream, state="probation", opened_at=now,
                last_active_at=None, device_name=info["name"],
                missing_since=None,
            )
            native_rate = int(info.get("defaultSampleRate", 0))
            logger.info(
                "loopback opened: %s (identity=%s, native_rate=%d)",
                info["name"], key, native_rate,
            )

        # Debounced disappearance: a single missed enumeration must not evict.
        for key in list(current_keys):
            entry = self._loopback_sources.get(key)
            if entry is None:
                continue
            if key in enumerated_keys:
                # Present this tick -- clear any prior disappearance mark.
                if entry.missing_since is not None:
                    entry.missing_since = None
                continue
            # Absent this tick.
            if entry.missing_since is None:
                entry.missing_since = now
                continue
            if now - entry.missing_since > _LOOPBACK_DEVICE_GRACE_S:
                self._evict_entry(key, reason="device disappeared")

        # Terminal-stream evictions (_SourceStream exhausted its reconnect
        # budget or its bound identity permanently vanished).
        for key in list(self._loopback_sources.keys()):
            entry = self._loopback_sources[key]
            if entry.stream.is_terminal:
                self._evict_entry(
                    key, reason="stream terminal (reconnect exhausted)",
                )

        # Probation expiry: PROBATION entries past _LOOPBACK_PROBATION_S
        # with no signal ever seen are expected to evict (not a fault).
        for key in list(self._loopback_sources.keys()):
            entry = self._loopback_sources[key]
            if entry.state == "probation" and now - entry.opened_at > _LOOPBACK_PROBATION_S:
                self._evict_entry(
                    key, reason=(
                        f"probation expired after {now - entry.opened_at:.0f}s "
                        "without signal"
                    ),
                )

    def _evict_entry(self, key: tuple, reason: str) -> None:
        """Stop and drop a loopback entry, emitting one info line."""
        entry = self._loopback_sources.pop(key, None)
        if entry is None:
            return
        try:
            entry.stream.stop()
        except Exception:
            logger.debug(
                "stream.stop() raised during evict for %s",
                entry.device_name, exc_info=True,
            )
        logger.info("loopback removed: %s (%s)", entry.device_name, reason)

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

        mic_samples, system_mix, mono_chunk_bytes = self._drain_and_mix(chunk_frames)

        # Interleave: [mic0, sys0, mic1, sys1, ...]
        interleaved = numpy.empty(chunk_frames * 2, dtype=numpy.int16)
        interleaved[0::2] = mic_samples
        interleaved[1::2] = system_mix

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
        """Legacy single-loopback test helper. Constructs one synthetic
        _LoopbackEntry containing the system_frame and drives the normal
        _drain_and_mix + _interleave_and_encode path.

        Preserved for backwards compatibility with existing tests; new tests
        should use _test_feed_mock_frames_multi (Task 15) for per-stream
        control.

        The synthetic entry starts in state="active" so that even legacy
        tests using all-zero system_frame bytes still exercise the full
        interleave+encode cycle (though they produce an all-zero channel-1
        via the active_count=0 branch when the RMS of zeros is below
        threshold -- same observable result as before).
        """
        if len(mic_frame) != len(system_frame):
            raise ValueError("mic_frame and system_frame must have the same length")
        chunk_frames = len(mic_frame) // 2

        class _StubStream:
            def __init__(self, frame: bytes) -> None:
                self._buf = frame
                self.is_terminal = False

            def drain_resampled(self, max_bytes: int) -> bytes:
                out = self._buf[:max_bytes]
                self._buf = self._buf[max_bytes:]
                return out

        entry = _LoopbackEntry(
            stream=_StubStream(system_frame),
            state="active",
            opened_at=0.0,
            last_active_at=None,
            device_name="test",
            missing_since=None,
        )

        with self._lock:
            self._mic_buffer += mic_frame
        prior = self._loopback_sources
        self._loopback_sources = {("test",): entry}
        try:
            self._interleave_and_encode(chunk_frames)
        finally:
            self._loopback_sources = prior

    def _mic_callback(self, in_data: bytes, frame_count: int, time_info: dict, status: int) -> tuple[None, int]:
        """PyAudioWPatch callback for microphone stream."""
        runtime_pyaudio = _require_pyaudio()
        with self._lock:
            self._mic_buffer += in_data
        return (None, runtime_pyaudio.paContinue)

    def start(self) -> None:
        """Open mic stream + enumerated loopback streams; begin recording.

        Splits its work across helper methods that tests can override:
        ``_spawn_mic_source``, ``_start_encoder``, ``_spawn_drain_thread``.
        Initial population of loopback endpoints happens by calling
        ``_tick_membership`` once before the drain thread launches -- the
        same add path hot-plug uses, so there is only one enumeration
        code path under test.
        """
        if self._recording:
            return

        _require_pyflac()  # preflight: fail fast if pyflac is missing
        # Production always uses 48 kHz; warn once if __init__ got something else.
        if self._sample_rate != 48000:
            logger.warning(
                "AudioCapture.start() overriding sample_rate=%d to 48000 "
                "(production capture is 48 kHz fixed; see design doc)",
                self._sample_rate,
            )
            self._sample_rate = 48000

        self._mic_source = self._spawn_mic_source()
        self._start_encoder()

        # Cross-thread fatal state wiring.
        self._fatal_error = None
        self._fatal_event.clear()

        # Initial loopback population -- reuses the _tick_membership add path
        # so hot-plug and first-open share one enumeration code path.
        now = time.monotonic()
        self._tick_membership(now)
        self._last_membership_tick = now

        self._recording = True
        self._spawn_drain_thread()

    def _spawn_mic_source(self) -> "_SourceStream":
        """Open the microphone ``_SourceStream``. Extracted for test overrides.

        Preserves today's default-following mic behavior (``bind_to=None``).
        Any hard failure (no mic device at all) surfaces immediately.
        """
        s = _SourceStream(kind="mic", output_rate=48000)
        try:
            s.start()
        except Exception:
            try:
                s.stop()
            except Exception:
                pass
            raise
        return s

    def _start_encoder(self) -> None:
        """Open the FLAC output file and pyFLAC stream encoder. Extracted
        for test overrides."""
        runtime_pyflac = _require_pyflac()
        self._output_file = open(self._output_path, "wb")
        self._encoder = runtime_pyflac.StreamEncoder(
            write_callback=self._write_callback,
            sample_rate=self._sample_rate,
        )

    def _spawn_drain_thread(self) -> None:
        """Start the drain loop on a background thread. Extracted for
        test overrides."""
        self._drain_thread = threading.Thread(
            target=self._drain_loop,
            daemon=True,
            name="audio-drain",
        )
        self._drain_thread.start()

    def _drain_loop(self) -> None:
        """Wall-clock-driven drain loop. Produces stereo frames at a
        fixed 48 kHz output cadence regardless of source health.

        Health checks fire when time.monotonic() passes
        next_health_check_at -- NOT every N ticks -- so a back-logged
        drain catching up in rapid ticks doesn't spam
        attempt_reopen_if_due. Loopback membership reconciliation fires
        on its own _LOOPBACK_MEMBERSHIP_TICK_S wall-clock gate.
        """
        chunk_frames = 1024
        target_interval = chunk_frames / self._sample_rate

        start_time = time.monotonic()
        next_health_check_at = start_time + 1.0
        tick_index = 0

        while self._recording:
            now = time.monotonic()

            # Loopback membership reconciliation -- gated on wall clock so
            # a back-logged drain catching up in rapid ticks can't thrash
            # the enumeration. Runs BEFORE drain work so any dict mutation
            # (adds/evicts) settles before we iterate _loopback_sources.
            if now - self._last_membership_tick > _LOOPBACK_MEMBERSHIP_TICK_S:
                self._tick_membership(now)
                self._last_membership_tick = now

            if now >= next_health_check_at:
                # Check fatal state BEFORE reopen attempts: if the mic is
                # already degraded past its reopen window, the recording
                # is game-over. In the multi-output design, absent or
                # degraded loopback sources are handled via audio_warnings
                # metadata, not fatal state -- the user can still record a
                # mic-only meeting.
                if (
                    self._mic_source is not None
                    and self._mic_source.is_degraded()
                ):
                    self._fatal_error = AudioCaptureBothSourcesFailedError(
                        "Microphone source degraded past its reopen "
                        "window; stopping recording.",
                    )
                    self._fatal_event.set()
                    # Flush any resampled audio that landed in the
                    # per-source buffers before degradation so the user
                    # doesn't lose the last second of meeting audio on
                    # a hardware-induced fatal stop. Mirror the clean
                    # exit path at the bottom of this method.
                    self._drain_final_partial_tick()
                    return
                if self._mic_source is not None:
                    self._mic_source.attempt_reopen_if_due()
                for entry in self._loopback_sources.values():
                    entry.stream.attempt_reopen_if_due()
                next_health_check_at = now + 1.0

            if self._mic_source is not None:
                self._mic_source._pump_raw_to_resampled()
            for entry in self._loopback_sources.values():
                entry.stream._pump_raw_to_resampled()

            mic_bytes = (
                self._mic_source.read_frames(chunk_frames)
                if self._mic_source else b"\x00" * (chunk_frames * 2)
            )

            with self._lock:
                self._mic_buffer = mic_bytes
            self._interleave_and_encode(chunk_frames)

            tick_index += 1
            target = start_time + (tick_index * target_interval)
            sleep_for = max(0.0, target - time.monotonic())
            if sleep_for > 0:
                time.sleep(sleep_for)

        self._drain_final_partial_tick()

    def _drain_final_partial_tick(self) -> None:
        """Pump any remaining raw bytes, drain up to the max frames
        available across sources, silence-pad where needed so the final
        stereo frame count stays aligned, feed the encoder.

        With multi-output loopback, the per-stream _resampled_buffers stay
        intact under the stream locks; _drain_and_mix reads them on the
        next _interleave_and_encode call. We only need to lift the mic
        remainder into self._mic_buffer and size the target frame count
        off the widest remainder across mic + loopback streams.
        """
        if self._mic_source is None:
            return
        self._mic_source._pump_raw_to_resampled()
        for entry in self._loopback_sources.values():
            entry.stream._pump_raw_to_resampled()

        with self._mic_source._lock:
            mic_remaining = self._mic_source._resampled_buffer
            self._mic_source._resampled_buffer = b""

        mic_frames = len(mic_remaining) // 2
        max_lb_frames = 0
        for entry in self._loopback_sources.values():
            with entry.stream._lock:
                max_lb_frames = max(
                    max_lb_frames, len(entry.stream._resampled_buffer) // 2,
                )

        target = max(mic_frames, max_lb_frames)
        if target == 0:
            return

        mic_padded = mic_remaining + b"\x00" * ((target - mic_frames) * 2)
        with self._lock:
            self._mic_buffer = mic_padded
        self._interleave_and_encode(target)

    def stop(self) -> None:
        if not self._recording:
            return
        self._recording = False
        if self._drain_thread is not None:
            self._drain_thread.join(timeout=5.0)
            self._drain_thread = None
        if self._mic_source is not None:
            self._mic_source.stop()
            self._mic_source = None
        # Iterate via _evict_entry so loopback teardown uses the same
        # logging path as mid-recording removals.
        for key in list(self._loopback_sources.keys()):
            self._evict_entry(key, reason="recording stopped")
        if self._encoder is not None:
            try:
                self._encoder.finish()
            except Exception:
                logger.exception("pyflac encoder finish() raised")
            self._encoder = None
        if self._output_file is not None:
            try:
                self._output_file.close()
            except Exception:
                logger.exception("output file close() raised")
            self._output_file = None
