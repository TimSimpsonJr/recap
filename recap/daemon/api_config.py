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


# ---------------------------------------------------------------------------
# PATCH helpers (design §2.3)
# ---------------------------------------------------------------------------

_READ_ONLY_KEYS = frozenset({"default_org"})


def _field_names(cls: Any) -> set[str]:
    return {f.name for f in dataclasses.fields(cls)}


def find_unknown_keys(body: dict[str, Any]) -> list[str]:
    """Return dotted paths of keys not in the ApiConfig allowlist.

    Walks one level into ``orgs``, ``detection``, ``calendar``, and
    ``known_contacts`` so nested typos are caught with an actionable
    path (e.g. ``detection.google_meet.bogus``).
    """
    unknown: list[str] = []
    top_allowed = _field_names(ApiConfig)

    for key, value in body.items():
        if key in _READ_ONLY_KEYS:
            unknown.append(f"{key} (read-only)")
            continue
        if key not in top_allowed:
            unknown.append(key)
            continue

        if key == "orgs" and isinstance(value, list):
            allowed = _field_names(ApiOrgConfig)
            for entry in value:
                if not isinstance(entry, dict):
                    continue
                for k in entry:
                    if k not in allowed:
                        unknown.append(f"orgs[].{k}")
        elif key == "detection" and isinstance(value, dict):
            allowed = _field_names(ApiDetectionRule)
            for platform, rule in value.items():
                if not isinstance(rule, dict):
                    continue
                for k in rule:
                    if k not in allowed:
                        unknown.append(f"detection.{platform}.{k}")
        elif key == "calendar" and isinstance(value, dict):
            allowed = _field_names(ApiCalendarProvider)
            for provider, cfg in value.items():
                if not isinstance(cfg, dict):
                    continue
                for k in cfg:
                    if k not in allowed:
                        unknown.append(f"calendar.{provider}.{k}")
        elif key == "known_contacts" and isinstance(value, list):
            allowed = _field_names(ApiKnownContact)
            for entry in value:
                if not isinstance(entry, dict):
                    continue
                for k in entry:
                    if k not in allowed:
                        unknown.append(f"known_contacts[].{k}")

    return unknown


def apply_api_patch_to_yaml_doc(
    doc: CommentedMap, patch: dict[str, Any],
) -> None:
    """Apply a validated PATCH body to a ruamel doc, in place.

    Scalars map 1:1 onto top-level keys. ``orgs`` and ``known_contacts``
    are whole-list replacements. ``detection`` and ``calendar`` are
    per-platform/provider merges so sibling keys and comments survive.

    Flat keys backed by nested YAML (``recording_*``, ``logging_*``,
    ``plugin_port``) are routed to their respective sub-mapping.
    """
    for key, value in patch.items():
        if key in _READ_ONLY_KEYS:
            continue

        if key == "recording_silence_timeout_minutes":
            rec = doc.setdefault("recording", CommentedMap())
            rec["silence_timeout_minutes"] = value
            continue
        if key == "recording_max_duration_hours":
            rec = doc.setdefault("recording", CommentedMap())
            rec["max_duration_hours"] = value
            continue
        if key == "logging_retention_days":
            log = doc.setdefault("logging", CommentedMap())
            log["retention_days"] = value
            continue
        if key == "plugin_port":
            ports = doc.setdefault("daemon_ports", CommentedMap())
            ports["plugin_port"] = value
            continue

        if key == "orgs" and isinstance(value, list):
            new_list = CommentedSeq()
            for o in value:
                m = CommentedMap()
                m["name"] = o.get("name", "")
                m["subfolder"] = o.get("subfolder", "")
                m["default"] = bool(o.get("default", False))
                new_list.append(m)
            doc["orgs"] = new_list
            continue

        if key == "known_contacts" and isinstance(value, list):
            new_list = CommentedSeq()
            for kc in value:
                m = CommentedMap()
                m["name"] = kc.get("name", "")
                if "aliases" in kc:
                    m["aliases"] = list(kc["aliases"] or [])
                if "email" in kc:
                    m["email"] = kc["email"]
                new_list.append(m)
            doc["known_contacts"] = new_list
            continue

        if key == "detection" and isinstance(value, dict):
            det = doc.setdefault("detection", CommentedMap())
            for platform, rule in value.items():
                target = det.setdefault(platform, CommentedMap())
                for k in (
                    "enabled", "behavior", "default_org", "default_backend",
                ):
                    if k in rule:
                        target[k] = rule[k]
            continue

        if key == "calendar" and isinstance(value, dict):
            cal = doc.setdefault("calendar", CommentedMap())
            for provider, cfg in value.items():
                target = cal.setdefault(provider, CommentedMap())
                for k in ("enabled", "calendar_id", "org"):
                    if k in cfg:
                        target[k] = cfg[k]
            continue

        doc[key] = value


def validate_yaml_doc(doc: CommentedMap) -> None:
    """Smoke-validate a ruamel doc against the API shape.

    Re-projecting through ``yaml_doc_to_api_config`` exercises every
    required-field / type check the DTO enforces (``vault_path`` is a
    string, orgs entries have string names/subfolders, etc.). Any
    ``ValueError`` bubbles to the handler, which maps it to 400.
    """
    yaml_doc_to_api_config(doc)
