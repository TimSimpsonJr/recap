"""CLI test harness for the Recap pipeline."""
from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sys

from recap.models import MeetingMetadata
from recap.pipeline import PipelineRuntimeConfig, run_pipeline

logger = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="recap",
        description="Recap: Meeting recording analysis pipeline",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # process command
    process_parser = subparsers.add_parser("process", help="Process a meeting recording")
    process_parser.add_argument("audio", help="Path to audio/video file")
    process_parser.add_argument("metadata", help="Path to meeting metadata JSON")
    process_parser.add_argument(
        "--vault", required=True, help="Path to Obsidian vault"
    )
    process_parser.add_argument(
        "--org", default="Work", help="Org subfolder (default: Work)"
    )
    process_parser.add_argument(
        "--user", default="Tim", help="User name (default: Tim)"
    )
    process_parser.add_argument(
        "--from", dest="from_stage",
        choices=["transcribe", "diarize", "analyze", "export", "convert"],
        help="Restart from this stage (skip earlier completed stages)",
    )
    process_parser.add_argument(
        "--backend", default="claude",
        choices=["claude", "ollama"],
        help="LLM backend (default: claude)",
    )
    process_parser.add_argument(
        "--device", default="cuda",
        help="Compute device (default: cuda)",
    )

    return parser.parse_args(argv)


def _setup_logging() -> None:
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    _setup_logging()

    if args.command == "process":
        audio_path = pathlib.Path(args.audio)
        metadata_path = pathlib.Path(args.metadata)
        vault_path = pathlib.Path(args.vault)

        if not audio_path.exists():
            logger.error("Audio file not found: %s", audio_path)
            sys.exit(1)
        if not metadata_path.exists():
            logger.error("Metadata file not found: %s", metadata_path)
            sys.exit(1)

        metadata = MeetingMetadata.from_dict(
            json.loads(metadata_path.read_text(encoding="utf-8"))
        )

        pipeline_config = PipelineRuntimeConfig(
            device=args.device,
            llm_backend=args.backend,
        )

        note_path = run_pipeline(
            audio_path=audio_path,
            metadata=metadata,
            config=pipeline_config,
            org_subfolder=args.org,
            vault_path=vault_path,
            user_name=args.user,
            from_stage=args.from_stage,
        )

        logger.info("Meeting note: %s", note_path)


if __name__ == "__main__":
    main()
