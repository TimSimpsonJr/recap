"""CLI test harness for the Recap pipeline."""
from __future__ import annotations

import argparse
import logging
import pathlib
import sys

from recap.config import RecapConfig, load_config
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


def _setup_logging(config: RecapConfig) -> None:
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    # Add file handler if logs_path is accessible
    try:
        config.logs_path.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(
            config.logs_path / "recap.log", encoding="utf-8"
        )
        file_handler.setFormatter(logging.Formatter(log_format))
        handlers.append(file_handler)
    except OSError:
        pass  # Fall back to stdout-only if log dir isn't writable

    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=handlers,
    )


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    config = load_config(pathlib.Path(args.config))
    _setup_logging(config)

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
        from recap.models import ActionItem
        from recap.todoist import load_retry_file, create_tasks

        retry_items = load_retry_file(config.retry_path)
        if not retry_items:
            logger.info("No pending Todoist tasks to retry")
            return

        logger.info("Retrying %d Todoist tasks", len(retry_items))

        # Convert retry items back to ActionItems and attempt creation
        action_items = [
            ActionItem(
                assignee=config.user_name,
                description=item["description"],
                due_date=item.get("due_date"),
                priority=item.get("priority", "normal"),
            )
            for item in retry_items
        ]

        project_name = retry_items[0].get("project", config.todoist.default_project)
        note_path = retry_items[0].get("note_path", "")

        try:
            task_ids = create_tasks(
                action_items=action_items,
                user_name=config.user_name,
                api_token=config.todoist.api_token,
                project_name=project_name,
                vault_name=config.vault_path.name,
                note_path=note_path,
            )
            logger.info("Successfully created %d Todoist tasks", len(task_ids))
            # Clear retry file on success
            config.retry_path.unlink(missing_ok=True)
        except Exception as e:
            logger.error("Retry failed: %s", e)
            sys.exit(1)


if __name__ == "__main__":
    main()
