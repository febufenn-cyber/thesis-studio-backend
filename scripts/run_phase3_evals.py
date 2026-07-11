#!/usr/bin/env python3
"""Run the deterministic grounded-AI safety benchmark and print JSON metrics."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.ai.evals import run_fixture  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "fixture",
        nargs="?",
        default=str(REPO_ROOT / "tests" / "fixtures" / "phase3_eval_cases.json"),
        help="Path to the evaluation case JSON file.",
    )
    parser.add_argument(
        "--minimum-match-rate",
        type=float,
        default=1.0,
        help="Return non-zero when expectation match rate is below this value.",
    )
    args = parser.parse_args()
    report = run_fixture(Path(args.fixture))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["expectation_match_rate"] >= args.minimum_match_rate else 1


if __name__ == "__main__":
    raise SystemExit(main())
