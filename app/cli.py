from __future__ import annotations

import argparse
import json
from typing import Any

from app.application.services.product_payload import BuildSavePayloadService
from app.infrastructure.db import SnapshotRepository, TaskRepository, configure_database, upgrade_database
from app.infrastructure.logging import bind_log_context, configure_logging, get_logger, reset_log_context
from app.infrastructure.settings import get_settings


def main() -> None:
    """Run the CLI flow that builds and prints a FOKS save payload."""
    settings = get_settings()
    configure_logging()
    configure_database(
        url=settings.sqlalchemy_database_url,
        echo=settings.db_echo,
    )
    upgrade_database(url=settings.sqlalchemy_database_url)
    tokens = bind_log_context()
    logger = get_logger("app.cli")
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--username", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--article", required=True)
    parser.add_argument("--mids", default="", help="comma-separated mids, e.g. prom,rozetka")
    parser.add_argument("--out", default="")
    parser.add_argument(
        "--payload-only",
        action="store_true",
        help="print only JSON payload without url/headers wrapper",
    )
    args = parser.parse_args()

    base_url = args.base_url or settings.foks_base_url
    username = args.username or settings.foks_username
    password = args.password or settings.foks_password

    if not username or not password:
        raise SystemExit("Set FOKS_USERNAME and FOKS_PASSWORD in .env/config or pass --username/--password")

    mids = [mid.strip() for mid in args.mids.split(",") if mid.strip()] or None
    service = BuildSavePayloadService(
        snapshot_repository=SnapshotRepository(),
        task_repository=TaskRepository(),
    )
    try:
        logger.info("cli_build_save_payload_started", extra={"event": "cli_build_save_payload_started", "article": args.article})
        save_request = service.build_save_payload(
            base_url=base_url,
            username=username,
            password=password,
            article=args.article,
            mids=mids,
        )
    finally:
        reset_log_context(tokens)

    output_obj: dict[str, Any] | Any
    if args.payload_only:
        output_obj = save_request["payload"]
    else:
        output_obj = save_request

    rendered = json.dumps(output_obj, ensure_ascii=False, indent=2)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as file_obj:
            file_obj.write(rendered)
            print(rendered)
    else:
        print(rendered)


if __name__ == "__main__":
    main()
