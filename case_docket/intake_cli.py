from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence, TextIO

from case_docket.application import (
    ApplicationError,
    IntakeCommand,
    ListIntakeInventoryQuery,
)
from case_docket.runtime import build_intake_runtime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="varta-intake",
        description="VARTA C06 file/folder/ZIP intake та SQLite inventory",
    )
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)

    intake = commands.add_parser("add", help="Прийняти file, folder або top-level ZIP")
    intake.add_argument("source", type=Path)
    intake.add_argument("--idempotency-key", required=True)

    inventory = commands.add_parser("inventory", help="Прочитати inventory лише з SQLite")
    inventory.add_argument("--batch-id")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        runtime = build_intake_runtime(args.workspace)
        if args.command == "add":
            batch = runtime.intake_service.intake(
                IntakeCommand(
                    source=args.source,
                    idempotency_key=args.idempotency_key,
                )
            )
            _write_json({"ok": True, "batch": batch.to_dict()})
            return 0 if batch.status == "succeeded" else 2
        inventory = runtime.intake_service.inventory(
            ListIntakeInventoryQuery(batch_id=args.batch_id)
        )
        _write_json({"ok": True, "inventory": inventory.to_dict()})
        return 0
    except ApplicationError as exc:
        _write_json(
            {
                "ok": False,
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                },
            },
            stream=sys.stderr,
        )
        return 2
    except Exception as exc:
        _write_json(
            {
                "ok": False,
                "error": {
                    "code": "internal_error",
                    "message": f"Intake CLI завершився помилкою {type(exc).__name__}",
                },
            },
            stream=sys.stderr,
        )
        return 1


def _write_json(payload: object, *, stream: TextIO | None = None) -> None:
    print(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        file=stream or sys.stdout,
    )


if __name__ == "__main__":
    raise SystemExit(main())
