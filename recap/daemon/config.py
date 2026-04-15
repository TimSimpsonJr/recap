"""Daemon configuration loading from YAML."""
from __future__ import annotations

import pathlib
from dataclasses import dataclass, field
from typing import Any, Optional

import yaml


@dataclass
class OrgConfig:
    name: str
    subfolder: str
    llm_backend: str = "claude"
    default: bool = False

    def resolve_subfolder(self, vault_path: pathlib.Path) -> pathlib.Path:
        """Return the absolute path to this org's subfolder under the vault."""
        if not self.subfolder:
            return vault_path
        return vault_path / self.subfolder


@dataclass
class CalendarProviderConfig:
    org: Optional[str] = None
    default_org: Optional[str] = None
    calendar_id: Optional[str] = None
    # Default True so existing configs (which predate this flag) keep
    # syncing exactly as before. The Settings UI exposes this toggle so
    # users can pause a provider without disconnecting OAuth.
    enabled: bool = True


@dataclass
class DetectionAppConfig:
    enabled: bool = True
    behavior: str = "auto-record"
    default_org: Optional[str] = None
    default_backend: Optional[str] = None


@dataclass
class DetectionConfig:
    teams: DetectionAppConfig = field(
        default_factory=lambda: DetectionAppConfig(
            enabled=True, behavior="auto-record",
        ),
    )
    zoom: DetectionAppConfig = field(
        default_factory=lambda: DetectionAppConfig(
            enabled=True, behavior="auto-record",
        ),
    )
    signal: DetectionAppConfig = field(
        default_factory=lambda: DetectionAppConfig(
            enabled=True, behavior="prompt",
        ),
    )


@dataclass
class RecordingConfig:
    format: str = "flac"
    archive_format: str = "aac"
    delete_source_after_archive: bool = False
    silence_timeout_minutes: int = 5
    max_duration_hours: int = 4


@dataclass
class PipelineSettings:
    transcription_model: str = "nvidia/parakeet-tdt-0.6b-v2"
    diarization_model: str = "nvidia/diar_streaming_sortformer_4spk-v2.1"
    auto_retry: bool = True
    max_retries: int = 1


@dataclass
class CalendarSyncConfig:
    interval_minutes: int = 15
    sync_on_startup: bool = True


@dataclass
class LoggingConfig:
    path: str = "_Recap/.recap/logs"
    retention_days: int = 7


@dataclass
class DaemonPortConfig:
    # Deprecated compatibility fields. The extension now uses plugin_port directly.
    extension_port_start: int = 17839
    extension_port_end: int = 17845
    plugin_port: int = 9847
    auto_start: bool = False


@dataclass
class KnownContact:
    name: str
    display_name: str = ""


@dataclass
class DaemonConfig:
    vault_path: pathlib.Path
    recordings_path: pathlib.Path
    user_name: str = "Tim"
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    recording: RecordingConfig = field(default_factory=RecordingConfig)
    pipeline: PipelineSettings = field(default_factory=PipelineSettings)
    calendar_sync: CalendarSyncConfig = field(default_factory=CalendarSyncConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    daemon_ports: DaemonPortConfig = field(default_factory=DaemonPortConfig)
    known_contacts: list[KnownContact] = field(default_factory=list)
    calendars: dict[str, CalendarProviderConfig] = field(default_factory=dict)
    _orgs: list[OrgConfig] = field(default_factory=list)

    @property
    def orgs(self) -> list[OrgConfig]:
        return list(self._orgs)

    @property
    def default_org(self) -> Optional[OrgConfig]:
        if not self._orgs:
            return None
        for org in self._orgs:
            if org.default:
                return org
        return self._orgs[0]

    def org_by_slug(self, slug: str) -> Optional[OrgConfig]:
        """Return the org config with matching slug, or None. Case-sensitive."""
        for org in self._orgs:
            if org.name == slug:
                return org
        return None


def _parse_detection_app(raw: dict) -> DetectionAppConfig:
    return DetectionAppConfig(
        enabled=raw.get("enabled", True),
        behavior=raw.get("behavior", "auto-record"),
        default_org=raw.get("default-org"),
        default_backend=raw.get("default-backend"),
    )


def _parse_detection(raw: dict) -> DetectionConfig:
    teams_raw = raw.get("teams", {})
    zoom_raw = raw.get("zoom", {})
    signal_raw = raw.get("signal", {})

    # Signal defaults to "prompt" behavior
    if "behavior" not in signal_raw:
        signal_raw["behavior"] = "prompt"

    return DetectionConfig(
        teams=_parse_detection_app(teams_raw),
        zoom=_parse_detection_app(zoom_raw),
        signal=_parse_detection_app(signal_raw),
    )


def parse_daemon_config_dict(raw: dict[str, Any]) -> DaemonConfig:
    """Parse a raw config dict into a :class:`DaemonConfig`.

    Pure function; does no file I/O. Kebab-case keys are the source of
    truth on disk (see ``config.example.yaml``).

    Raises:
        ValueError: If required fields are missing or ``config-version``
            is unsupported.
    """
    # Validate config version
    version = raw.get("config-version")
    if version != 1:
        raise ValueError(
            f"Unsupported config-version: {version}. Expected 1."
        )

    # Required fields
    if "vault-path" not in raw:
        raise ValueError("Missing required field: vault-path")
    if "recordings-path" not in raw:
        raise ValueError("Missing required field: recordings-path")

    # Parse orgs
    orgs_raw = raw.get("orgs", {})
    orgs = [
        OrgConfig(
            name=name,
            subfolder=org_data.get("subfolder", ""),
            llm_backend=org_data.get("llm-backend", "claude"),
            default=org_data.get("default", False),
        )
        for name, org_data in orgs_raw.items()
    ]

    # Parse calendars
    calendars_raw = raw.get("calendars", {})
    calendars = {
        name: CalendarProviderConfig(
            org=cal_data.get("org"),
            default_org=cal_data.get("default-org"),
            calendar_id=cal_data.get("calendar-id"),
            enabled=cal_data.get("enabled", True),
        )
        for name, cal_data in calendars_raw.items()
    }

    # Parse detection
    detection = _parse_detection(raw.get("detection", {}))

    # Parse recording
    rec_raw = raw.get("recording", {})
    recording = RecordingConfig(
        format=rec_raw.get("format", "flac"),
        archive_format=rec_raw.get("archive-format", "aac"),
        delete_source_after_archive=rec_raw.get(
            "delete-source-after-archive", False,
        ),
        silence_timeout_minutes=rec_raw.get("silence-timeout-minutes", 5),
        max_duration_hours=rec_raw.get("max-duration-hours", 4),
    )

    # Parse pipeline
    pipe_raw = raw.get("pipeline", {})
    pipeline = PipelineSettings(
        transcription_model=pipe_raw.get(
            "transcription-model", "nvidia/parakeet-tdt-0.6b-v2",
        ),
        diarization_model=pipe_raw.get(
            "diarization-model",
            "nvidia/diar_streaming_sortformer_4spk-v2.1",
        ),
        auto_retry=pipe_raw.get("auto-retry", True),
        max_retries=pipe_raw.get("max-retries", 1),
    )

    # Parse calendar-sync
    cs_raw = raw.get("calendar-sync", {})
    calendar_sync = CalendarSyncConfig(
        interval_minutes=cs_raw.get("interval-minutes", 15),
        sync_on_startup=cs_raw.get("sync-on-startup", True),
    )

    # Parse logging
    log_raw = raw.get("logging", {})
    logging_config = LoggingConfig(
        path=log_raw.get("path", "_Recap/.recap/logs"),
        retention_days=log_raw.get("retention-days", 7),
    )

    # Parse daemon ports
    daemon_raw = raw.get("daemon", {})
    daemon_ports = DaemonPortConfig(
        extension_port_start=daemon_raw.get("extension-port-start", 17839),
        extension_port_end=daemon_raw.get("extension-port-end", 17845),
        plugin_port=daemon_raw.get("plugin-port", 9847),
        auto_start=daemon_raw.get("auto-start", False),
    )

    # Parse known contacts
    contacts_raw = raw.get("known-contacts", [])
    known_contacts = [
        KnownContact(
            name=c.get("name", ""),
            display_name=c.get("display-name", ""),
        )
        for c in contacts_raw
    ]

    return DaemonConfig(
        vault_path=pathlib.Path(raw["vault-path"]),
        recordings_path=pathlib.Path(raw["recordings-path"]),
        user_name=raw.get("user-name", "Tim"),
        detection=detection,
        recording=recording,
        pipeline=pipeline,
        calendar_sync=calendar_sync,
        logging=logging_config,
        daemon_ports=daemon_ports,
        known_contacts=known_contacts,
        calendars=calendars,
        _orgs=orgs,
    )


def load_daemon_config(path: pathlib.Path) -> DaemonConfig:
    """Load daemon configuration from a YAML file.

    Raises:
        FileNotFoundError: If the config file does not exist.
        ValueError: If required fields are missing or ``config-version``
            is wrong.
    """
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    return parse_daemon_config_dict(raw)
