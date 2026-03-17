"""CLI test harness for the Recap pipeline."""
from __future__ import annotations

import argparse
import logging
import pathlib
import sys

from recap.config import load_config
from recap.pipeline import run_pipeline

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
        "--config", default="config.yaml", help="Path to config file (default: config.yaml)"
    )

    # retry-todoist command
    retry_parser = subparsers.add_parser("retry-todoist", help="Retry failed Todoist task creation")
    retry_parser.add_argument(
        "--config", default="config.yaml", help="Path to config file (default: config.yaml)"
    )

    return parser.parse_args(argv)


def _setup_logging(config_path: pathlib.Path) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    _setup_logging(pathlib.Path(args.config))
    config = load_config(pathlib.Path(args.config))

    if args.command == "process":
        audio_path = pathlib.Path(args.audio)
        metadata_path = pathlib.Path(args.metadata)

        if not audio_path.exists():
            logger.error("Audio file not found: %s", audio_path)
            sys.exit(1)
        if not metadata_path.exists():
            logger.error("Metadata file not found: %s", metadata_path)
            sys.exit(1)

        results = run_pipeline(audio_path, metadata_path, config)

        if results.get("meeting_note"):
            logger.info("Meeting note: %s", results["meeting_note"])
        if results.get("todoist_tasks"):
            logger.info("Created %d Todoist tasks", len(results["todoist_tasks"]))
        if results.get("profiles_created"):
            logger.info("Created profiles: %s", ", ".join(results["profiles_created"]))

    elif args.command == "retry-todoist":
        from recap.todoist import load_retry_file, create_tasks

        retry_items = load_retry_file(config.retry_path)
        if not retry_items:
            logger.info("No pending Todoist tasks to retry")
            return

        logger.info("Retrying %d Todoist tasks", len(retry_items))
        # Retry logic would go here — for now just log
        for item in retry_items:
            logger.info("Would retry: %s", item.get("description", "unknown"))


if __name__ == "__main__":
    main()
