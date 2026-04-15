"""API DTO + translation layer for /api/config (design §2.3).

The plugin consumes a snake_case, list-of-orgs DTO. This module owns
the translation between that external contract and the on-disk YAML.
Secrets like ``auth_token`` are stripped from every returned shape.
"""
from __future__ import annotations

import dataclasses
import pathlib
from dataclasses import dataclass, field
from typing import Any, Optional

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq


@dataclass
class ApiOrgConfig:
    name: str
    subfolder: str
    default: bool = False


@dataclass
class ApiDetectionRule:
    enabled: bool
    behavior: str
    default_org: Optional[str] = None
    default_backend: Optional[str] = None


@dataclass
class ApiCalendarProvider:
    enabled: bool
    calendar_id: Optional[str] = None
    org: Optional[str] = None


@dataclass
class ApiKnownContact:
    name: str
    aliases: list[str] = field(default_factory=list)
    email: Optional[str] = None


@dataclass
class ApiConfig:
    vault_path: str
    recordings_path: str
    plugin_port: int
    orgs: list[ApiOrgConfig]
    detection: dict[str, ApiDetectionRule]
    calendar: dict[str, ApiCalendarProvider]
    known_contacts: list[ApiKnownContact]
    recording_silence_timeout_minutes: int
    recording_max_duration_hours: float
    logging_retention_days: int
    user_name: Optional[str] = None
    default_org: Optional[str] = None


def _rt_yaml() -> YAML:
    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.width = 4096
    return y


def load_yaml_doc(path: pathlib.Path) -> CommentedMap:
    """Ruamel round-trip load. Returns an empty mapping for empty files."""
    y = _rt_yaml()
    with path.open("r", encoding="utf-8") as f:
        doc = y.load(f)
    if doc is None:
        return CommentedMap()
    if not isinstance(doc, CommentedMap):
        raise ValueError(
            f"config root must be a mapping; got {type(doc).__name__}",
        )
    return doc


def dump_yaml_doc(doc: CommentedMap, fh) -> None:
    _rt_yaml().dump(doc, fh)


def _to_str(v: Any, field_name: str) -> str:
    if not isinstance(v, str):
        raise ValueError(f"{field_name} must be a string")
    return v


def _get(d: Any, key: str, default: Any = None) -> Any:
    if isinstance(d, (CommentedMap, dict)):
        return d.get(key, default)
    return default


def yaml_doc_to_api_config(doc: CommentedMap) -> ApiConfig:
    """Extract the allowlisted API fields from a ruamel doc.

    Reads snake_case keys from the doc; any non-allowlisted keys (e.g.
    ``auth_token``) are ignored so they never leak through the API.
    """
    orgs: list[ApiOrgConfig] = []
    for item in _get(doc, "orgs", []) or []:
        orgs.append(
            ApiOrgConfig(
                name=_to_str(_get(item, "name", ""), "orgs[].name"),
                subfolder=_to_str(
                    _get(item, "subfolder", ""), "orgs[].subfolder",
                ),
                default=bool(_get(item, "default", False)),
            ),
        )

    detection: dict[str, ApiDetectionRule] = {}
    for platform, cfg in (_get(doc, "detection", {}) or {}).items():
        if cfg is None:
            continue
        detection[platform] = ApiDetectionRule(
            enabled=bool(_get(cfg, "enabled", False)),
            behavior=_to_str(
                _get(cfg, "behavior", "prompt"),
                f"detection.{platform}.behavior",
            ),
            default_org=_get(cfg, "default_org"),
            default_backend=_get(cfg, "default_backend"),
        )

    calendar: dict[str, ApiCalendarProvider] = {}
    for provider, cfg in (_get(doc, "calendar", {}) or {}).items():
        if cfg is None:
            continue
        calendar[provider] = ApiCalendarProvider(
            enabled=bool(_get(cfg, "enabled", False)),
            calendar_id=_get(cfg, "calendar_id"),
            org=_get(cfg, "org"),
        )

    contacts: list[ApiKnownContact] = []
    for item in _get(doc, "known_contacts", []) or []:
        contacts.append(
            ApiKnownContact(
                name=_to_str(
                    _get(item, "name", ""), "known_contacts[].name",
                ),
                aliases=list(_get(item, "aliases", []) or []),
                email=_get(item, "email"),
            ),
        )

    recording = _get(doc, "recording", {}) or {}
    logging_cfg = _get(doc, "logging", {}) or {}
    daemon_ports = _get(doc, "daemon_ports", {}) or {}
    derived_default_org = next((o.name for o in orgs if o.default), None)

    return ApiConfig(
        vault_path=_to_str(_get(doc, "vault_path", ""), "vault_path"),
        recordings_path=_to_str(
            _get(doc, "recordings_path", ""), "recordings_path",
        ),
        plugin_port=int(_get(daemon_ports, "plugin_port", 9847)),
        orgs=orgs,
        detection=detection,
        calendar=calendar,
        known_contacts=contacts,
        recording_silence_timeout_minutes=int(
            _get(recording, "silence_timeout_minutes", 5),
        ),
        recording_max_duration_hours=float(
            _get(recording, "max_duration_hours", 3),
        ),
        logging_retention_days=int(_get(logging_cfg, "retention_days", 7)),
        user_name=_get(doc, "user_name"),
        default_org=derived_default_org,
    )


def api_config_to_json_dict(cfg: ApiConfig) -> dict[str, Any]:
    return dataclasses.asdict(cfg)
