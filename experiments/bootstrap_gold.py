#!/usr/bin/env python3
"""
Bootstrap provisional gold labels from a chosen baseline output.
"""

from __future__ import annotations

import argparse
import json
import pathlib


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap gold labels from baseline predictions.")
    parser.add_argument("--run-dir", required=True, help="Path to experiments/runs/<run_id>.")
    parser.add_argument(
        "--from-baseline",
        default="B2_FSMConstrained.json",
        help="Prediction file under predictions/ to seed gold labels.",
    )
    args = parser.parse_args()

    run_dir = pathlib.Path(args.run_dir).resolve()
    src = run_dir / "predictions" / args.from_baseline
    dst = run_dir / "gold" / "segments_gold.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        raise SystemExit(f"Missing baseline output: {src}")

    with src.open("r", encoding="utf-8") as f:
        pred = json.load(f)

    seeded = {
        "label_source": f"seeded_from_{args.from_baseline}",
        "review_required": True,
        "segments": pred.get("segments", []),
    }
    with dst.open("w", encoding="utf-8") as f:
        json.dump(seeded, f, indent=2)
    print(f"Wrote provisional gold labels: {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
