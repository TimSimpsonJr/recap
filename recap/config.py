"""Configuration loading for Recap pipeline."""
from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass, field

import yaml


@dataclass
class WhisperXConfig:
    model: str = "large-v3"
    device: str = "cuda"
    compute_type: str = "float16"
    language: str = "en"


@dataclass
class TodoistConfig:
    api_token: str = ""
    default_project: str = "Recap"
    project_map: dict[str, str] = field(default_factory=dict)

    def project_for_type(self, meeting_type: str) -> str:
        return self.project_map.get(meeting_type, self.default_project)


@dataclass
class ClaudeConfig:
    command: str = "claude"
    model: str = "sonnet"


@dataclass
class RecapConfig:
    vault_path: pathlib.Path
    recordings_path: pathlib.Path
    frames_path: pathlib.Path
    user_name: str
    whisperx: WhisperXConfig
    huggingface_token: str
    todoist: TodoistConfig
    claude: ClaudeConfig

    @property
    def meetings_path(self) -> pathlib.Path:
        return self.vault_path / "Work" / "Meetings"

    @property
    def people_path(self) -> pathlib.Path:
        return self.vault_path / "Work" / "People"

    @property
    def companies_path(self) -> pathlib.Path:
        return self.vault_path / "Work" / "Companies"

    @property
    def logs_path(self) -> pathlib.Path:
        return self.recordings_path.parent / "logs"

    @property
    def retry_path(self) -> pathlib.Path:
        return self.recordings_path.parent / "todoist-retry.json"


def load_config(path: pathlib.Path) -> RecapConfig:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path) as f:
        raw = yaml.safe_load(f)

    wx = raw.get("whisperx", {})
    td = raw.get("todoist", {})
    cl = raw.get("claude", {})

    hf_token = os.environ.get("HUGGINGFACE_TOKEN", raw.get("huggingface_token", ""))

    return RecapConfig(
        vault_path=pathlib.Path(raw["vault_path"]),
        recordings_path=pathlib.Path(raw["recordings_path"]),
        frames_path=pathlib.Path(raw["frames_path"]),
        user_name=raw["user_name"],
        whisperx=WhisperXConfig(
            model=wx.get("model", "large-v3"),
            device=wx.get("device", "cuda"),
            compute_type=wx.get("compute_type", "float16"),
            language=wx.get("language", "en"),
        ),
        huggingface_token=hf_token,
        todoist=TodoistConfig(
            api_token=os.environ.get("TODOIST_API_TOKEN", td.get("api_token", "")),
            default_project=td.get("default_project", "Recap"),
            project_map=td.get("project_map", {}),
        ),
        claude=ClaudeConfig(
            command=cl.get("command", "claude"),
            model=cl.get("model", "sonnet"),
        ),
    )
