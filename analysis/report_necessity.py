#!/usr/bin/env python3
"""
Aggregate run metrics and generate a necessity decision report.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
from typing import Dict, List


THRESHOLDS = {
    "clean": {"segment_f1": 0.90, "completeness": 0.90, "over_merge_rate": 0.10, "over_split_rate": 0.10},
    "stressed": {"segment_f1": 0.80, "completeness": 0.85, "over_merge_rate": 0.10, "over_split_rate": 0.10},
}


def is_clean_run(run_id: str) -> bool:
    return run_id.startswith("S1_")


def load_metrics(runs_root: pathlib.Path) -> List[Dict]:
    metrics: List[Dict] = []
    for run_dir in sorted(runs_root.glob("*")):
        mpath = run_dir / "metrics" / "metrics_summary.json"
        if not mpath.exists():
            continue
        with mpath.open("r", encoding="utf-8") as f:
            metrics.append(json.load(f))
    return metrics


def aggregate_baseline(metrics: List[Dict], baseline_name: str) -> Dict:
    vals: Dict[str, List[float]] = {
        "segment_f1": [],
        "completeness": [],
        "over_merge_rate": [],
        "over_split_rate": [],
    }
    clean_violations = 0
    stressed_violations = 0
    stressed_total = 0
    for run in metrics:
        run_id = run["run_id"]
        base = run["baselines"].get(baseline_name)
        if not base:
            continue
        for k in vals:
            vals[k].append(float(base.get(k, 0.0)))

        threshold_group = "clean" if is_clean_run(run_id) else "stressed"
        th = THRESHOLDS[threshold_group]
        failed = (
            base["segment_f1"] < th["segment_f1"]
            or base["completeness"] < th["completeness"]
            or base["over_merge_rate"] > th["over_merge_rate"]
            or base["over_split_rate"] > th["over_split_rate"]
        )
        if threshold_group == "clean" and failed:
            clean_violations += 1
        if threshold_group == "stressed":
            stressed_total += 1
            if failed:
                stressed_violations += 1

    out = {}
    for k, arr in vals.items():
        out[k] = statistics.mean(arr) if arr else 0.0
    out["clean_violations"] = clean_violations
    out["stressed_violations"] = stressed_violations
    out["stressed_total"] = stressed_total
    out["needs_learned_model"] = stressed_violations >= 2
    return out


def render_report(metrics: List[Dict], agg: Dict[str, Dict]) -> str:
    lines = []
    lines.append("# NetSAM Necessity Report")
    lines.append("")
    lines.append("This report aggregates deterministic baseline performance across available runs.")
    lines.append("")
    lines.append("## Decision Rule")
    lines.append("")
    lines.append("- NetSAM is justified if deterministic baselines violate stressed thresholds in >=2 stressed runs.")
    lines.append("")
    lines.append("## Baseline Aggregates")
    lines.append("")
    for baseline_name, summary in agg.items():
        lines.append(f"### {baseline_name}")
        lines.append("")
        lines.append(f"- mean_segment_f1: {summary['segment_f1']:.4f}")
        lines.append(f"- mean_completeness: {summary['completeness']:.4f}")
        lines.append(f"- mean_over_merge_rate: {summary['over_merge_rate']:.4f}")
        lines.append(f"- mean_over_split_rate: {summary['over_split_rate']:.4f}")
        lines.append(f"- clean_violations: {summary['clean_violations']}")
        lines.append(f"- stressed_violations: {summary['stressed_violations']} / {summary['stressed_total']}")
        lines.append(f"- needs_learned_model: {summary['needs_learned_model']}")
        lines.append("")
    lines.append("## Runs Included")
    lines.append("")
    for run in metrics:
        lines.append(f"- {run['run_id']}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create aggregated necessity report.")
    parser.add_argument("--runs-root", required=True, help="Path to experiments/runs")
    parser.add_argument("--output", required=True, help="Output markdown file")
    args = parser.parse_args()

    runs_root = pathlib.Path(args.runs_root).resolve()
    output = pathlib.Path(args.output).resolve()

    metrics = load_metrics(runs_root)
    if not metrics:
        raise SystemExit("No run metrics found. Execute evaluation first.")

    baseline_names = sorted({b for run in metrics for b in run.get("baselines", {}).keys()})
    agg = {b: aggregate_baseline(metrics, b) for b in baseline_names}
    text = render_report(metrics, agg)

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        f.write(text)
    print(f"Wrote report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
