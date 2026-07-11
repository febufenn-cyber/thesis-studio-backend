#!/usr/bin/env python3
"""Run the deterministic grounded-AI safety benchmark and print JSON metrics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.ai.evals import run_fixture


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "fixture",
        nargs="?",
        default="tests/fixtures/phase3_eval_cases.json",
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
