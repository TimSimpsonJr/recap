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
    """Project a kebab-case, dict-orgs on-disk doc into the snake_case,
    list-orgs API DTO.

    Translation boundary: the loader in :mod:`recap.daemon.config` is the
    single source of truth for what the daemon reads; this DTO adapts
    that shape for the plugin. Any non-allowlisted keys (e.g.
    ``auth_token``) are ignored so they never leak through the API.
    """
    # orgs: dict-keyed-by-name on disk → list-of-entries in DTO.
    orgs: list[ApiOrgConfig] = []
    raw_orgs = _get(doc, "orgs", {}) or {}
    if isinstance(raw_orgs, (CommentedMap, dict)):
        for name, data in raw_orgs.items():
            if data is None:
                data = {}
            orgs.append(
                ApiOrgConfig(
                    name=str(name),
                    subfolder=_to_str(
                        _get(data, "subfolder", ""),
                        f"orgs.{name}.subfolder",
                    ),
                    default=bool(_get(data, "default", False)),
                ),
            )

    # detection: same shape on disk and DTO; translate kebab defaults
    # back to snake DTO fields.
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
            default_org=_get(cfg, "default-org"),
            default_backend=_get(cfg, "default-backend"),
        )

    # calendar (DTO) sources from ``calendars`` (YAML); per-provider
    # fields translate calendar-id → calendar_id. ``enabled`` is a DTO
    # affordance that defaults True when a provider block is present.
    calendar: dict[str, ApiCalendarProvider] = {}
    for provider, cfg in (_get(doc, "calendars", {}) or {}).items():
        if cfg is None:
            continue
        calendar[provider] = ApiCalendarProvider(
            enabled=bool(_get(cfg, "enabled", True)),
            calendar_id=_get(cfg, "calendar-id"),
            org=_get(cfg, "org"),
        )

    # known_contacts (DTO) sources from ``known-contacts`` (YAML).
    # ``display-name`` on disk is not surfaced; the DTO exposes
    # ``aliases`` + ``email`` as forward-compatible fields the loader
    # tolerates as unused extras.
    contacts: list[ApiKnownContact] = []
    for item in _get(doc, "known-contacts", []) or []:
        if not isinstance(item, (CommentedMap, dict)):
            continue
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
    daemon_raw = _get(doc, "daemon", {}) or {}
    derived_default_org = next((o.name for o in orgs if o.default), None)

    return ApiConfig(
        vault_path=_to_str(_get(doc, "vault-path", ""), "vault_path"),
        recordings_path=_to_str(
            _get(doc, "recordings-path", ""), "recordings_path",
        ),
        plugin_port=int(_get(daemon_raw, "plugin-port", 9847)),
        orgs=orgs,
        detection=detection,
        calendar=calendar,
        known_contacts=contacts,
        recording_silence_timeout_minutes=int(
            _get(recording, "silence-timeout-minutes", 5),
        ),
        recording_max_duration_hours=float(
            _get(recording, "max-duration-hours", 3),
        ),
        logging_retention_days=int(_get(logging_cfg, "retention-days", 7)),
        user_name=_get(doc, "user-name"),
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
    """Apply a validated snake_case PATCH body to a kebab-case ruamel doc.

    The daemon loader (:func:`recap.daemon.config.load_daemon_config`)
    is the source of truth for on-disk shape, so this function writes
    kebab-case keys, routes flat API fields (``recording_*``,
    ``logging_*``, ``plugin_port``, ``vault_path``, ...) to their nested
    YAML parents, and translates the DTO's list-orgs back to
    dict-keyed-by-name. Whole-list replacement preserves non-DTO
    sibling fields (e.g. ``llm-backend``) on orgs that match an existing
    entry by name.
    """
    for key, value in patch.items():
        if key in _READ_ONLY_KEYS:
            continue

        # Flat API fields routed to nested YAML sections.
        if key == "recording_silence_timeout_minutes":
            rec = doc.setdefault("recording", CommentedMap())
            rec["silence-timeout-minutes"] = value
            continue
        if key == "recording_max_duration_hours":
            rec = doc.setdefault("recording", CommentedMap())
            rec["max-duration-hours"] = value
            continue
        if key == "logging_retention_days":
            log = doc.setdefault("logging", CommentedMap())
            log["retention-days"] = value
            continue
        if key == "plugin_port":
            daemon_raw = doc.setdefault("daemon", CommentedMap())
            daemon_raw["plugin-port"] = value
            continue

        # Snake DTO top-level fields → kebab YAML top-level keys.
        if key == "vault_path":
            doc["vault-path"] = value
            continue
        if key == "recordings_path":
            doc["recordings-path"] = value
            continue
        if key == "user_name":
            doc["user-name"] = value
            continue

        # orgs: DTO list → YAML dict-keyed-by-name. Preserve non-DTO
        # sibling fields (``llm-backend``) from matching existing orgs.
        if key == "orgs" and isinstance(value, list):
            existing = doc.get("orgs", None)
            if not isinstance(existing, (CommentedMap, dict)):
                existing = {}
            new_map = CommentedMap()
            for o in value:
                name = str(o.get("name", ""))
                m = CommentedMap()
                m["subfolder"] = o.get("subfolder", "")
                prev = existing.get(name) if isinstance(existing, (CommentedMap, dict)) else None
                if isinstance(prev, (CommentedMap, dict)) and "llm-backend" in prev:
                    m["llm-backend"] = prev["llm-backend"]
                if o.get("default"):
                    m["default"] = True
                new_map[name] = m
            doc["orgs"] = new_map
            continue

        # known_contacts: whole-list replacement; keep ``display-name``
        # populated (defaults to name) so the existing loader's
        # ``KnownContact`` projection doesn't lose information.
        if key == "known_contacts" and isinstance(value, list):
            new_list = CommentedSeq()
            for kc in value:
                m = CommentedMap()
                name = kc.get("name", "")
                m["name"] = name
                m["display-name"] = name
                if "aliases" in kc:
                    m["aliases"] = list(kc["aliases"] or [])
                if "email" in kc:
                    m["email"] = kc["email"]
                new_list.append(m)
            doc["known-contacts"] = new_list
            continue

        # detection: per-platform merge; snake DTO fields → kebab YAML.
        if key == "detection" and isinstance(value, dict):
            det = doc.setdefault("detection", CommentedMap())
            for platform, rule in value.items():
                target = det.setdefault(platform, CommentedMap())
                if "enabled" in rule:
                    target["enabled"] = rule["enabled"]
                if "behavior" in rule:
                    target["behavior"] = rule["behavior"]
                if "default_org" in rule:
                    target["default-org"] = rule["default_org"]
                if "default_backend" in rule:
                    target["default-backend"] = rule["default_backend"]
            continue

        # calendar (DTO) → calendars (YAML); per-provider merge.
        if key == "calendar" and isinstance(value, dict):
            cal = doc.setdefault("calendars", CommentedMap())
            for provider, cfg in value.items():
                target = cal.setdefault(provider, CommentedMap())
                if "enabled" in cfg:
                    target["enabled"] = cfg["enabled"]
                if "calendar_id" in cfg:
                    target["calendar-id"] = cfg["calendar_id"]
                if "org" in cfg:
                    target["org"] = cfg["org"]
            continue

        # No translation known for this key — fall through. Unknown
        # top-level keys are caught by ``find_unknown_keys`` before this
        # function runs, so reaching here is a programming error.
        doc[key] = value


def _to_plain_dict(obj: Any) -> Any:
    """Recursively unwrap ruamel ``CommentedMap``/``CommentedSeq`` to
    plain ``dict``/``list`` so consumers (like ``parse_daemon_config_dict``)
    that do ``isinstance`` checks against builtins behave correctly.
    """
    if isinstance(obj, (CommentedMap, dict)):
        return {k: _to_plain_dict(v) for k, v in obj.items()}
    if isinstance(obj, (CommentedSeq, list)):
        return [_to_plain_dict(v) for v in obj]
    return obj


def validate_yaml_doc(doc: CommentedMap) -> None:
    """Ensure a post-PATCH doc still parses through the canonical loader.

    Runs the plain dict through :func:`parse_daemon_config_dict` so any
    shape that would crash the daemon on next restart (missing
    ``vault-path``, malformed ``orgs``, bad ``config-version``, ...)
    surfaces as a ``ValueError`` here and is converted to a 400 by the
    handler.
    """
    from recap.daemon.config import parse_daemon_config_dict
    parse_daemon_config_dict(_to_plain_dict(doc))
