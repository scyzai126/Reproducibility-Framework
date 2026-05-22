"""Generate a static all-study hard-fail completeness report."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


API_ROOT = Path(__file__).resolve().parent
REPO_ROOT = API_ROOT.parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "data" / "generated" / "completeness" / "hard_fail_static_report.json"

sys.path.insert(0, str(API_ROOT))


def _load_local_env() -> None:
    """Load apps/api/.env when running the script from the repo root."""
    env_path = API_ROOT / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


async def _generate(args: argparse.Namespace) -> dict:
    _load_local_env()

    from app.agent.completeness_validator import build_static_completeness_report
    from app.database import async_session, engine

    async with async_session() as session:
        report = await build_static_completeness_report(
            session,
            limit=args.limit,
            include_checks=args.include_checks,
        )

    await engine.dispose()
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a static completeness report for every study in the ImmPort study table."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"JSON output path. Default: {DEFAULT_OUTPUT}",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit for testing the report on the first N study IDs.",
    )
    parser.add_argument(
        "--include-checks",
        action="store_true",
        help="Include full check objects for each study. This can make the output much larger.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    report = asyncio.run(_generate(args))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    summary = report["summary"]
    print(f"Wrote {args.output}")
    print(f"Studies checked: {summary['study_count']}")
    print(f"Overall status counts: {json.dumps(summary['overall_status_counts'], sort_keys=True)}")
    print(f"Flag counts: {json.dumps(summary['flag_counts'], sort_keys=True)}")


if __name__ == "__main__":
    main()
