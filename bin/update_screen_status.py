#!/usr/bin/env python3
"""Atomically publish a compact, PII-free Agent Screen status."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

STATES = ("idle", "working", "waiting_approval", "error", "offline")
AGENT_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9 _-]{0,31}$")
MAX_TASK_LENGTH = 120


def bounded_text(value: str, *, field: str, maximum: int) -> str:
    value = " ".join(value.split())
    if not value:
        raise ValueError(f"{field} must not be empty")
    if len(value) > maximum:
        raise ValueError(f"{field} must be at most {maximum} characters")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default=os.environ.get("AGENT_SCREEN_STATUS_DIR", "/var/www/agent-screen/status"),
    )
    parser.add_argument("--screen", type=int, required=True)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--state", choices=STATES, required=True)
    parser.add_argument("--task", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not 1 <= args.screen <= 99:
        raise SystemExit("screen must be between 1 and 99")
    agent = bounded_text(args.agent, field="agent", maximum=32)
    if not AGENT_PATTERN.fullmatch(agent):
        raise SystemExit("agent contains unsupported characters")
    task = bounded_text(args.task, field="task", maximum=MAX_TASK_LENGTH)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"screen-{args.screen}.json"
    payload = {
        "schema": 1,
        "screen": args.screen,
        "agent": agent,
        "state": args.state,
        "task": task,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }

    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_dir,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            json.dump(payload, temporary, ensure_ascii=True, separators=(",", ":"))
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_name, 0o644)
        os.replace(temporary_name, destination)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)

    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
