"""Static agreement between background.js default patterns,
options.js defaults, manifest content_scripts.matches, and
manifest host_permissions.

If any of these drift apart, a user-visible detection either won't
record (host_permissions miss) or will record but never refresh its
participant roster (content_scripts miss)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

EXTENSION_DIR = Path(__file__).resolve().parent.parent / "extension"

# The canonical built-in set. Updating this is the single-place
# mechanism for adding a host. Lockstep tests fail until background.js,
# options.js, and manifest.json agree.
BUILT_IN_HOSTS: set[str] = {
    "meet.google.com",
    "meeting.zoho.com",
    "meeting.zoho.eu",
    "meeting.zoho.in",
    "meeting.zoho.com.au",
    "meeting.tranzpay.io",
}

# Teams-via-browser is the explicit v1 gap - detected but not refreshed.
EXPECTED_V1_GAPS: set[str] = {"teams.microsoft.com"}


def _extract_default_patterns(js_path: Path, const_name: str) -> list[dict[str, str]]:
    """Parse a meeting-patterns constant from a JS file.

    The two files use different constant names:
      - extension/background.js uses DEFAULT_MEETING_PATTERNS
      - extension/options.js uses DEFAULT_PATTERNS

    Fragile by design - the regex breaks if the constant is restructured,
    which is exactly what these tests want to catch.
    """
    text = js_path.read_text()
    match = re.search(
        rf"{re.escape(const_name)}\s*=\s*\[(.*?)\];",
        text, re.DOTALL,
    )
    assert match, f"{const_name} not found in {js_path}"
    block = match.group(1)
    entries = re.findall(
        r"\{\s*pattern:\s*\"([^\"]+)\"\s*,\s*platform:\s*\"([^\"]+)\"",
        block,
    )
    return [{"pattern": p, "platform": pf} for p, pf in entries]


def test_background_defaults_cover_built_in_hosts():
    patterns = _extract_default_patterns(
        EXTENSION_DIR / "background.js", "DEFAULT_MEETING_PATTERNS",
    )
    hosts = {p["pattern"].split("/")[0] for p in patterns}
    missing = BUILT_IN_HOSTS - hosts
    assert not missing, f"BUILT_IN_HOSTS missing from background.js: {missing}"


def test_options_defaults_agree_with_background():
    bg = _extract_default_patterns(
        EXTENSION_DIR / "background.js", "DEFAULT_MEETING_PATTERNS",
    )
    opts = _extract_default_patterns(
        EXTENSION_DIR / "options.js", "DEFAULT_PATTERNS",
    )
    bg_set = {(p["pattern"], p["platform"]) for p in bg}
    opts_set = {(p["pattern"], p["platform"]) for p in opts}
    bg_built_in = {pp for pp in bg_set if pp[0].split("/")[0] in BUILT_IN_HOSTS}
    opts_built_in = {pp for pp in opts_set if pp[0].split("/")[0] in BUILT_IN_HOSTS}
    assert bg_built_in == opts_built_in, (
        f"background and options disagree on built-in patterns: "
        f"bg={bg_built_in} opts={opts_built_in}"
    )


def test_manifest_content_scripts_cover_built_in_hosts():
    manifest = json.loads((EXTENSION_DIR / "manifest.json").read_text())
    matches = {m for cs in manifest.get("content_scripts", []) for m in cs["matches"]}
    for host in BUILT_IN_HOSTS:
        assert any(host in m for m in matches), (
            f"built-in host {host} missing from manifest content_scripts.matches"
        )


def test_manifest_host_permissions_cover_content_script_matches():
    manifest = json.loads((EXTENSION_DIR / "manifest.json").read_text())
    host_perms = set(manifest.get("host_permissions", []))
    cs_matches = {m for cs in manifest.get("content_scripts", []) for m in cs["matches"]}
    missing = cs_matches - host_perms
    assert not missing, (
        f"content_scripts.matches not covered by host_permissions: {missing}"
    )


def test_teams_via_browser_stays_a_known_gap():
    """teams.microsoft.com is in background.js detection patterns but
    deliberately NOT in BUILT_IN_HOSTS or content_scripts.matches.
    If someone adds it, they must update this test + design docs."""
    manifest = json.loads((EXTENSION_DIR / "manifest.json").read_text())
    matches = {m for cs in manifest.get("content_scripts", []) for m in cs["matches"]}
    for gap in EXPECTED_V1_GAPS:
        assert not any(gap in m for m in matches), (
            f"{gap} is covered by content_scripts but documented as v1 gap; "
            f"update BUILT_IN_HOSTS + design docs intentionally."
        )
