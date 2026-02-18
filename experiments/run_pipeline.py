#!/usr/bin/env python3
"""
Convenience wrapper: run scenario -> normalize -> baselines -> optional evaluation.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys


def run(cmd: list[str], cwd: pathlib.Path) -> None:
    print(f"[pipeline] {' '.join(cmd)}")
    subprocess.run(cmd, cwd=str(cwd), check=True)


def latest_run_id(runs_root: pathlib.Path, scenario_prefix: str, repetition: int) -> str:
    pattern = f"{scenario_prefix}__r{repetition}__*"
    candidates = sorted(runs_root.glob(pattern))
    if not candidates:
        raise RuntimeError(f"No run directory found for pattern: {pattern}")
    return candidates[-1].name


def load_scenario_id(path: pathlib.Path) -> str:
    with path.open("r", encoding="utf-8") as f:
        scenario = json.load(f)
    return scenario["scenario_id"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run full necessity pipeline for one scenario repetition.")
    parser.add_argument("--scenario", required=True, help="Scenario JSON path")
    parser.add_argument("--repetition", type=int, required=True, help="Repetition index")
    parser.add_argument("--project-root", default=".", help="free5gc-compose root")
    parser.add_argument("--dry-run", action="store_true", help="Pass dry-run to run_experiment")
    parser.add_argument("--seed-gold", action="store_true", help="Seed gold from B2 and evaluate")
    args = parser.parse_args()

    root = pathlib.Path(args.project_root).resolve()
    scenario_path = (root / args.scenario).resolve() if not pathlib.Path(args.scenario).is_absolute() else pathlib.Path(args.scenario)
    scenario_id = load_scenario_id(scenario_path)

    run_cmd = [
        sys.executable,
        "experiments/run_experiment.py",
        "--scenario",
        str(scenario_path),
        "--repetition",
        str(args.repetition),
        "--project-root",
        str(root),
    ]
    if args.dry_run:
        run_cmd.append("--dry-run")
    run(run_cmd, cwd=root)

    runs_root = root / "experiments" / "runs"
    run_id = latest_run_id(runs_root, scenario_id, args.repetition)
    run_dir = runs_root / run_id

    run([sys.executable, "experiments/normalize_pcap.py", "--run-dir", str(run_dir)], cwd=root)
    run([sys.executable, "experiments/normalize_events.py", "--run-dir", str(run_dir)], cwd=root)
    run([sys.executable, "experiments/baselines.py", "--run-dir", str(run_dir)], cwd=root)

    if args.seed_gold:
        run([sys.executable, "experiments/bootstrap_gold.py", "--run-dir", str(run_dir)], cwd=root)
        run([sys.executable, "analysis/evaluate.py", "--run-dir", str(run_dir)], cwd=root)
    print(f"[pipeline] complete run_id={run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
