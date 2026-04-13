# Phase 1: Daemon Foundation

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the daemon skeleton: config loading, logging with rotation, system tray icon, HTTP server with health endpoint, startup validation, and auth token generation.

**Architecture:** The daemon is a single Python process running an asyncio event loop. pystray runs in its own thread. aiohttp serves HTTP/WebSocket. Config is loaded from `_Recap/.recap/config.yaml` in the vault.

**Tech Stack:** Python 3.10+, aiohttp, pystray, Pillow, keyring, plyer, pyyaml

---

### Task 1: Add new daemon dependencies to pyproject.toml

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add daemon dependency group**

Add a `daemon` optional dependency group:

```toml
[project.optional-dependencies]
daemon = [
    "aiohttp>=3.9",
    "pystray>=0.19",
    "Pillow>=10.0",
    "keyring>=25.0",
    "plyer>=2.1",
    "authlib>=1.3",
    "pywin32>=306",
]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]
```

**Step 2: Install dependencies**

```bash
uv sync --extra daemon --extra dev
```

**Step 3: Verify imports work**

```bash
python -c "import aiohttp; import pystray; import keyring; print('OK')"
```

Expected: `OK`

**Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add daemon dependencies (aiohttp, pystray, keyring, authlib, pywin32)"
```

---

### Task 2: Config system

**Files:**
- Create: `recap/daemon/config.py`
- Create: `recap/daemon/__init__.py`
- Test: `tests/test_daemon_config.py`

**Step 1: Write the failing tests**

Test config loading from a YAML file, default values, org routing, and config-version validation.

```python
"""Tests for daemon config loading."""
import pathlib
import tempfile
import pytest
import yaml

from recap.daemon.config import DaemonConfig, load_daemon_config, OrgConfig


class TestLoadDaemonConfig:
    def test_loads_minimal_config(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "config-version": 1,
            "vault-path": str(tmp_path / "vault"),
            "recordings-path": str(tmp_path / "recordings"),
        }))
        config = load_daemon_config(config_file)
        assert config.vault_path == tmp_path / "vault"
        assert config.recordings_path == tmp_path / "recordings"

    def test_default_org_is_identified(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "config-version": 1,
            "vault-path": str(tmp_path),
            "recordings-path": str(tmp_path),
            "orgs": {
                "work": {"subfolder": "_Recap/Work", "llm-backend": "claude", "default": True},
                "personal": {"subfolder": "_Recap/Personal", "llm-backend": "claude"},
            },
        }))
        config = load_daemon_config(config_file)
        assert config.default_org.name == "work"
        assert config.default_org.llm_backend == "claude"

    def test_rejects_unknown_config_version(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "config-version": 99,
            "vault-path": str(tmp_path),
            "recordings-path": str(tmp_path),
        }))
        with pytest.raises(ValueError, match="config-version"):
            load_daemon_config(config_file)

    def test_missing_vault_path_raises(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "config-version": 1,
            "recordings-path": str(tmp_path),
        }))
        with pytest.raises(ValueError, match="vault-path"):
            load_daemon_config(config_file)

    def test_detection_defaults(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "config-version": 1,
            "vault-path": str(tmp_path),
            "recordings-path": str(tmp_path),
        }))
        config = load_daemon_config(config_file)
        assert config.detection.teams.enabled is True
        assert config.detection.teams.behavior == "auto-record"
        assert config.detection.signal.behavior == "prompt"

    def test_recording_defaults(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "config-version": 1,
            "vault-path": str(tmp_path),
            "recordings-path": str(tmp_path),
        }))
        config = load_daemon_config(config_file)
        assert config.recording.format == "flac"
        assert config.recording.archive_format == "aac"
        assert config.recording.silence_timeout_minutes == 5
        assert config.recording.max_duration_hours == 4
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_daemon_config.py -v
```

Expected: FAIL (module not found)

**Step 3: Implement config module**

Create `recap/daemon/__init__.py` (empty) and `recap/daemon/config.py` with:

- `DaemonConfig` dataclass with nested dataclasses for each config section (orgs, detection, recording, calendar-sync, logging, daemon ports)
- `OrgConfig` dataclass (name, subfolder, llm_backend, default flag)
- `DetectionConfig`, `DetectionAppConfig` (per-app: enabled, behavior, default-org, default-backend)
- `RecordingConfig` (format, archive_format, delete_source, silence_timeout, max_duration)
- `CalendarSyncConfig` (interval, sync_on_startup)
- `LoggingConfig` (path, retention_days)
- `load_daemon_config(path: Path) -> DaemonConfig` that reads YAML, validates version, applies defaults
- `default_org` property that returns the org with `default: True` (or first org if none marked)

Use the config structure from the design doc as the spec.

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_daemon_config.py -v
```

Expected: all PASS

**Step 5: Commit**

```bash
git add recap/daemon/ tests/test_daemon_config.py
git commit -m "feat: add daemon config system with org routing and defaults"
```

---

### Task 3: Logging with rotation

**Files:**
- Create: `recap/daemon/logging_setup.py`
- Test: `tests/test_daemon_logging.py`

**Step 1: Write the failing tests**

```python
"""Tests for daemon logging setup."""
import logging
import pathlib
from recap.daemon.logging_setup import setup_logging


class TestSetupLogging:
    def test_creates_log_directory(self, tmp_path):
        log_dir = tmp_path / "logs"
        setup_logging(log_dir, retention_days=7)
        assert log_dir.exists()

    def test_configures_root_logger(self, tmp_path):
        log_dir = tmp_path / "logs"
        setup_logging(log_dir, retention_days=7)
        logger = logging.getLogger("recap")
        assert logger.level == logging.INFO
        # Should have both file and console handlers
        handler_types = [type(h).__name__ for h in logger.handlers]
        assert "TimedRotatingFileHandler" in handler_types
        assert "StreamHandler" in handler_types

    def test_log_file_created_on_first_message(self, tmp_path):
        log_dir = tmp_path / "logs"
        setup_logging(log_dir, retention_days=7)
        logger = logging.getLogger("recap.test")
        logger.info("test message")
        log_files = list(log_dir.glob("recap.log*"))
        assert len(log_files) >= 1
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_daemon_logging.py -v
```

**Step 3: Implement logging setup**

`setup_logging(log_dir: Path, retention_days: int)`:
- Create log directory if it doesn't exist
- Configure `recap` logger with INFO level
- Add `TimedRotatingFileHandler` (daily rotation, `backupCount=retention_days`)
- Add `StreamHandler` for console output
- Formatter: `%(asctime)s [%(levelname)s] %(name)s: %(message)s`
- Purge old log files beyond retention on setup (handles logs from before rotation was configured)

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_daemon_logging.py -v
```

**Step 5: Commit**

```bash
git add recap/daemon/logging_setup.py tests/test_daemon_logging.py
git commit -m "feat: add daemon logging with daily rotation and retention"
```

---

### Task 4: Auth token generation

**Files:**
- Create: `recap/daemon/auth.py`
- Test: `tests/test_daemon_auth.py`

**Step 1: Write the failing tests**

```python
"""Tests for daemon auth token management."""
from recap.daemon.auth import ensure_auth_token, validate_token


class TestAuthToken:
    def test_creates_token_file_if_missing(self, tmp_path):
        token_path = tmp_path / "auth-token"
        token = ensure_auth_token(token_path)
        assert token_path.exists()
        assert len(token) >= 32

    def test_reads_existing_token(self, tmp_path):
        token_path = tmp_path / "auth-token"
        token_path.write_text("my-existing-token")
        token = ensure_auth_token(token_path)
        assert token == "my-existing-token"

    def test_validate_token_accepts_correct(self, tmp_path):
        token_path = tmp_path / "auth-token"
        token = ensure_auth_token(token_path)
        assert validate_token(token, token_path) is True

    def test_validate_token_rejects_wrong(self, tmp_path):
        token_path = tmp_path / "auth-token"
        ensure_auth_token(token_path)
        assert validate_token("wrong-token", token_path) is False
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_daemon_auth.py -v
```

**Step 3: Implement auth module**

- `ensure_auth_token(path: Path) -> str`: if file exists, read and return. Otherwise generate a `secrets.token_urlsafe(32)`, write to file, return it.
- `validate_token(token: str, token_path: Path) -> bool`: read expected token from file, constant-time compare with `hmac.compare_digest`.

**Step 4: Run tests, commit**

```bash
pytest tests/test_daemon_auth.py -v
git add recap/daemon/auth.py tests/test_daemon_auth.py
git commit -m "feat: add daemon auth token generation and validation"
```

---

### Task 5: HTTP server skeleton

**Files:**
- Create: `recap/daemon/server.py`
- Test: `tests/test_daemon_server.py`

**Step 1: Write the failing tests**

```python
"""Tests for daemon HTTP server."""
import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from recap.daemon.server import create_app


class TestHealthEndpoint:
    @pytest.fixture
    async def client(self, aiohttp_client, tmp_path):
        token_path = tmp_path / "auth-token"
        token_path.write_text("test-token")
        app = create_app(auth_token="test-token")
        return await aiohttp_client(app)

    @pytest.mark.asyncio
    async def test_health_returns_ok(self, client):
        resp = await client.get("/health")
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_api_requires_auth(self, client):
        resp = await client.get("/api/status")
        assert resp.status == 401

    @pytest.mark.asyncio
    async def test_api_accepts_valid_token(self, client):
        resp = await client.get(
            "/api/status",
            headers={"Authorization": "Bearer test-token"}
        )
        assert resp.status == 200

    @pytest.mark.asyncio
    async def test_api_rejects_invalid_token(self, client):
        resp = await client.get(
            "/api/status",
            headers={"Authorization": "Bearer wrong-token"}
        )
        assert resp.status == 401
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_daemon_server.py -v
```

**Step 3: Implement server module**

`create_app(auth_token: str) -> web.Application`:
- `GET /health` — returns `{"status": "ok", "version": "0.2.0"}`. No auth required (browser extension uses this).
- Auth middleware: checks `Authorization: Bearer <token>` on all `/api/*` routes. Returns 401 if missing or invalid.
- `GET /api/status` — returns `{"state": "idle", "recording": null, "daemon_uptime": ..., "last_calendar_sync": null, "errors": []}`. Placeholder for now.

**Step 4: Run tests, commit**

```bash
pytest tests/test_daemon_server.py -v
git add recap/daemon/server.py tests/test_daemon_server.py
git commit -m "feat: add daemon HTTP server with health endpoint and auth middleware"
```

---

### Task 6: Startup validation

**Files:**
- Create: `recap/daemon/startup.py`
- Test: `tests/test_daemon_startup.py`

**Step 1: Write the failing tests**

```python
"""Tests for daemon startup validation."""
from unittest.mock import patch, MagicMock
from recap.daemon.startup import validate_startup, StartupCheck, StartupResult


class TestStartupValidation:
    def test_vault_path_exists(self, tmp_path):
        result = validate_startup(vault_path=tmp_path, check_gpu=False)
        vault_check = next(c for c in result.checks if c.name == "vault_path")
        assert vault_check.passed is True

    def test_vault_path_missing(self, tmp_path):
        result = validate_startup(
            vault_path=tmp_path / "nonexistent", check_gpu=False
        )
        vault_check = next(c for c in result.checks if c.name == "vault_path")
        assert vault_check.passed is False
        assert "not found" in vault_check.message.lower()

    def test_vault_path_missing_is_fatal(self, tmp_path):
        result = validate_startup(
            vault_path=tmp_path / "nonexistent", check_gpu=False
        )
        assert result.can_start is False

    def test_gpu_missing_is_non_fatal(self, tmp_path):
        with patch("recap.daemon.startup._check_cuda", return_value=False):
            result = validate_startup(vault_path=tmp_path, check_gpu=True)
        gpu_check = next(c for c in result.checks if c.name == "gpu")
        assert gpu_check.passed is False
        assert result.can_start is True  # non-fatal

    def test_result_contains_all_checks(self, tmp_path):
        result = validate_startup(vault_path=tmp_path, check_gpu=False)
        check_names = {c.name for c in result.checks}
        assert "vault_path" in check_names
        assert "audio_devices" in check_names
        assert "keyring" in check_names
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_daemon_startup.py -v
```

**Step 3: Implement startup validation**

- `StartupCheck` dataclass: `name: str, passed: bool, message: str, fatal: bool`
- `StartupResult` dataclass: `checks: list[StartupCheck]`, property `can_start` (True if no fatal checks failed), property `warnings` (non-fatal failures)
- `validate_startup(vault_path, check_gpu=True) -> StartupResult`: runs all checks:
  - `vault_path`: exists and is a directory. **Fatal** if missing.
  - `gpu`: `torch.cuda.is_available()`. Non-fatal (calendar/detection still work).
  - `audio_devices`: try to enumerate PyAudioWPatch devices. Non-fatal (recording disabled).
  - `keyring`: try `keyring.get_password("recap-test", "test")`. Non-fatal (OAuth disabled).
  - `models`: check if Parakeet/NeMo model files exist in cache. Non-fatal (pipeline disabled, recording still works).

**Step 4: Run tests, commit**

```bash
pytest tests/test_daemon_startup.py -v
git add recap/daemon/startup.py tests/test_daemon_startup.py
git commit -m "feat: add daemon startup validation with fatal/non-fatal checks"
```

---

### Task 7: System tray

**Files:**
- Create: `recap/daemon/tray.py`
- Create: `recap/daemon/notifications.py`

**Step 1: Implement tray module**

This can't be easily unit-tested (GUI thread, system tray interaction). Implement directly.

`recap/daemon/tray.py`:
- `RecapTray` class wrapping pystray
- Icon: generate a simple colored circle via Pillow (red when recording, green when idle, yellow when processing)
- Menu items:
  - "Status: Idle" (disabled, informational)
  - Separator
  - "Start Recording >" submenu with org names from config
  - "Stop Recording" (disabled when not recording)
  - Separator
  - "Settings" (placeholder — opens config file in editor for now)
  - "Quit"
- `update_state(state: str)` method to change icon color and status text
- Runs in its own thread (pystray requirement)

`recap/daemon/notifications.py`:
- `notify(title: str, message: str)` — uses `plyer.notification.notify()` for Windows toast notifications
- Wraps in try/except so a notification failure never crashes the daemon

**Step 2: Manual test**

```bash
python -c "
from recap.daemon.tray import RecapTray
tray = RecapTray(orgs=['disbursecloud', 'personal'])
tray.run()  # Should show tray icon, Ctrl+C to exit
"
```

Verify: tray icon appears, right-click shows menu, "Quit" exits cleanly.

**Step 3: Commit**

```bash
git add recap/daemon/tray.py recap/daemon/notifications.py
git commit -m "feat: add system tray with recording controls and toast notifications"
```

---

### Task 8: Daemon entry point

**Files:**
- Create: `recap/daemon/__main__.py`
- Modify: `recap/daemon/__init__.py`

**Step 1: Implement daemon entry point**

`recap/daemon/__main__.py`:

```python
"""Entry point: python -m recap.daemon"""
import asyncio
import logging
import pathlib
import sys
import threading

from recap.daemon.config import load_daemon_config
from recap.daemon.logging_setup import setup_logging
from recap.daemon.auth import ensure_auth_token
from recap.daemon.server import create_app
from recap.daemon.startup import validate_startup
from recap.daemon.tray import RecapTray
from recap.daemon.notifications import notify

logger = logging.getLogger("recap.daemon")


def main():
    # Load config
    # Default config path: vault's _Recap/.recap/config.yaml
    config_path = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if config_path is None:
        print("Usage: python -m recap.daemon <config-path>")
        sys.exit(1)

    config = load_daemon_config(config_path)

    # Setup logging
    log_path = config.vault_path / config.logging.path
    setup_logging(log_path, config.logging.retention_days)

    # Startup validation
    result = validate_startup(
        vault_path=config.vault_path,
        check_gpu=True,
    )
    for check in result.warnings:
        logger.warning("Startup: %s — %s", check.name, check.message)
        notify("Recap", check.message)

    if not result.can_start:
        for check in result.checks:
            if check.fatal and not check.passed:
                logger.error("Fatal: %s — %s", check.name, check.message)
                notify("Recap — Cannot Start", check.message)
        sys.exit(1)

    # Auth token
    auth_token_path = config.vault_path / "_Recap/.recap/auth-token"
    auth_token = ensure_auth_token(auth_token_path)

    # Create HTTP app
    app = create_app(auth_token=auth_token)

    # Start tray in background thread
    org_names = [org.name for org in config.orgs]
    tray = RecapTray(orgs=org_names)
    tray_thread = threading.Thread(target=tray.run, daemon=True)
    tray_thread.start()

    # Run HTTP server
    logger.info("Daemon starting on port %d", config.daemon.plugin_port)
    from aiohttp import web
    web.run_app(app, host="127.0.0.1", port=config.daemon.plugin_port)


if __name__ == "__main__":
    main()
```

**Step 2: Manual test**

Create a minimal test config and run:

```bash
python -m recap.daemon path/to/test-config.yaml
```

Verify: tray icon appears, `http://localhost:9847/health` returns `{"status": "ok"}`, Ctrl+C exits cleanly.

**Step 3: Commit**

```bash
git add recap/daemon/__main__.py recap/daemon/__init__.py
git commit -m "feat: add daemon entry point with config, logging, tray, and HTTP server"
```

---

### Task 9: Push and verify

**Step 1: Run all daemon tests**

```bash
pytest tests/test_daemon_*.py -v
```

Expected: all PASS

**Step 2: Push**

```bash
git push
```
