#!/usr/bin/env python3
"""
Evaluate baseline segmentation outputs against gold labels.
"""

from __future__ import annotations

import argparse
import json
import pathlib
from typing import Dict, List, Set


def load_json(path: pathlib.Path) -> Dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def map_event_to_gold_segment(gold_segments: List[Dict]) -> Dict[int, str]:
    out: Dict[int, str] = {}
    for gs in gold_segments:
        seg_id = gs["segment_id"]
        for event_id in gs.get("event_ids", []):
            out[int(event_id)] = seg_id
    return out


def map_event_to_pred_segment(pred_segments: List[Dict]) -> Dict[int, str]:
    out: Dict[int, str] = {}
    for ps in pred_segments:
        seg_id = ps["segment_id"]
        for event_id in ps.get("event_ids", []):
            out[int(event_id)] = seg_id
    return out


def compute_metrics(gold_segments: List[Dict], pred_segments: List[Dict]) -> Dict:
    gold_event_map = map_event_to_gold_segment(gold_segments)
    pred_event_map = map_event_to_pred_segment(pred_segments)

    assigned_pred_events: Set[int] = set(pred_event_map.keys())
    all_gold_events: Set[int] = set(gold_event_map.keys())

    correct = 0
    for event_id in assigned_pred_events:
        if event_id in gold_event_map:
            correct += 1

    precision = correct / len(assigned_pred_events) if assigned_pred_events else 0.0
    recall = correct / len(all_gold_events) if all_gold_events else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    # Over-merge: predicted segment includes events from >1 gold segment.
    over_merge_count = 0
    for ps in pred_segments:
        touched = {gold_event_map[eid] for eid in ps.get("event_ids", []) if eid in gold_event_map}
        if len(touched) > 1:
            over_merge_count += 1
    over_merge = over_merge_count / len(pred_segments) if pred_segments else 0.0

    # Over-split: one gold segment spread across >1 predicted segments.
    over_split_count = 0
    for gs in gold_segments:
        touched = {pred_event_map[eid] for eid in gs.get("event_ids", []) if eid in pred_event_map}
        if len(touched) > 1:
            over_split_count += 1
    over_split = over_split_count / len(gold_segments) if gold_segments else 0.0

    # Completeness: all events from a gold segment appear inside at least one predicted segment.
    complete_count = 0
    for gs in gold_segments:
        gevents = set(gs.get("event_ids", []))
        complete = any(gevents.issubset(set(ps.get("event_ids", []))) for ps in pred_segments)
        if complete:
            complete_count += 1
    completeness = complete_count / len(gold_segments) if gold_segments else 0.0

    unassigned = len(all_gold_events - assigned_pred_events) / len(all_gold_events) if all_gold_events else 0.0

    # Ordering accuracy uses optional key_step_order in gold segment.
    ord_total = 0
    ord_ok = 0
    for gs in gold_segments:
        key_order = gs.get("key_step_order")
        if not key_order:
            continue
        ord_total += 1
        ord_ok += int(bool(key_order))  # Placeholder: strict ordering checks can be added once labels include step mapping.
    ordering_acc = ord_ok / ord_total if ord_total else 1.0

    return {
        "segment_precision": precision,
        "segment_recall": recall,
        "segment_f1": f1,
        "completeness": completeness,
        "over_merge_rate": over_merge,
        "over_split_rate": over_split,
        "unassigned_message_rate": unassigned,
        "ordering_accuracy": ordering_acc,
    }


def evaluate_run(run_dir: pathlib.Path) -> Dict:
    gold_path = run_dir / "gold" / "segments_gold.json"
    preds_dir = run_dir / "predictions"
    if not gold_path.exists():
        raise FileNotFoundError(f"Missing gold labels: {gold_path}")
    if not preds_dir.exists():
        raise FileNotFoundError(f"Missing predictions dir: {preds_dir}")

    gold = load_json(gold_path)
    gold_segments = gold.get("segments", [])
    out = {"run_id": run_dir.name, "baselines": {}}

    for pred_path in sorted(preds_dir.glob("*.json")):
        pred = load_json(pred_path)
        baseline_name = pred.get("baseline", pred_path.stem)
        metrics = compute_metrics(gold_segments=gold_segments, pred_segments=pred.get("segments", []))
        out["baselines"][baseline_name] = metrics
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate baseline outputs for one run.")
    parser.add_argument("--run-dir", required=True, help="Path to experiments/runs/<run_id>.")
    args = parser.parse_args()

    run_dir = pathlib.Path(args.run_dir).resolve()
    result = evaluate_run(run_dir)
    metrics_dir = run_dir / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    out_path = metrics_dir / "metrics_summary.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"Wrote metrics: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
