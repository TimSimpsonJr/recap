"""CPU-safe contract smoke tests."""
import inspect
import pytest

pytestmark = pytest.mark.integration


def test_nemo_asr_imports_cleanly():
    """Catches datasets/pyarrow import chain. RED today; GREEN after Task 3."""
    from nemo.collections import asr  # noqa: F401


def test_pyflac_streamencoder_has_no_channels_kwarg():
    """Documents pyflac 3.0 API contract."""
    import pyflac
    params = inspect.signature(pyflac.StreamEncoder.__init__).parameters
    assert "channels" not in params


def test_pyflac_write_callback_signature():
    """Documents write_callback parameter exists."""
    import pyflac
    params = inspect.signature(pyflac.StreamEncoder.__init__).parameters
    assert "write_callback" in params


def test_parakeet_stream_not_installed():
    """parakeet-stream removed in Task 7. RED today; GREEN after Task 7."""
    from importlib.metadata import PackageNotFoundError, distribution
    with pytest.raises(PackageNotFoundError):
        distribution("parakeet-stream")


def test_uiautomation_control_from_handle_exists():
    """call_state.py depends on uiautomation.ControlFromHandle."""
    import uiautomation
    assert hasattr(uiautomation, "ControlFromHandle")


def test_win32gui_required_apis():
    """detection.py depends on IsWindow, IsWindowVisible, EnumWindows, GetWindowText."""
    import win32gui
    for name in ("IsWindow", "IsWindowVisible", "EnumWindows", "GetWindowText"):
        assert hasattr(win32gui, name), f"win32gui missing {name}"


def test_pyaudiowpatch_get_default_wasapi_device_uses_kw_only():
    """PyAudioWPatch renamed the positional 'input'/'output' arg to
    keyword-only d_in/d_out. Regression guard for the 2026-04-17 bug
    where the recorder passed positional 'input' and every record/start
    failed with 'takes 1 positional argument but 2 were given'.
    """
    import inspect
    import pyaudiowpatch as pa
    p = pa.PyAudio()
    try:
        sig = inspect.signature(p.get_default_wasapi_device)
        # Both params must be KEYWORD_ONLY
        for name in ("d_in", "d_out"):
            assert name in sig.parameters, f"missing {name}"
            assert (
                sig.parameters[name].kind == inspect.Parameter.KEYWORD_ONLY
            ), f"{name} should be keyword-only"
    finally:
        p.terminate()
