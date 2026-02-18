#!/usr/bin/env python3
"""
Interactive CLI tool for human review of seeded gold labels.

Shows each segment with its events and asks the reviewer to accept, reject,
or edit. Reviewed labels become the ground truth for evaluation.

Usage:
    python gold_review_tool.py --run-dir experiments/runs/<run_id>
    python gold_review_tool.py --run-dir experiments/runs/<run_id> --resume
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import datetime
from typing import Dict, List, Optional


def load_json(path: pathlib.Path) -> Dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: pathlib.Path, data: Dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_events_by_id(events_path: pathlib.Path) -> Dict[int, Dict]:
    """Load events indexed by event_id for fast lookup."""
    index: Dict[int, Dict] = {}
    with events_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                event = json.loads(line)
                index[int(event["event_id"])] = event
    return index


def format_event(event: Dict) -> str:
    """Format a single event for display."""
    eid = event.get("event_id", "?")
    ts = event.get("timestamp", "?")[:23]
    src = event.get("source", "?")
    et = event.get("event_type", "?")
    ue = event.get("ue_key", "?")
    raw = event.get("raw_line", "")[:120]
    return f"  [{eid:>5}] {ts}  {src:<12} {et:<30} ue={ue}\n         {raw}"


def display_segment(seg: Dict, events_index: Dict[int, Dict], seg_num: int, total: int) -> None:
    """Print a segment with its events for review."""
    print(f"\n{'='*80}")
    print(f"Segment {seg_num}/{total}: {seg['segment_id']}")
    print(f"  Procedure: {seg['procedure']}")
    print(f"  UE Key:    {seg['ue_key']}")
    print(f"  Attempt:   {seg.get('attempt', 1)}")
    print(f"  Time:      {seg['start_ts'][:23]} -> {seg['end_ts'][:23]}")
    print(f"  Events ({len(seg['event_ids'])}):")
    print(f"  {'─'*76}")
    for eid in seg["event_ids"]:
        event = events_index.get(int(eid))
        if event:
            print(format_event(event))
        else:
            print(f"  [{eid:>5}] (event not found)")
    print(f"  {'─'*76}")


def prompt_review() -> str:
    """
    Prompt the reviewer for a decision.
    Returns: 'y' (accept), 'n' (reject), 'e' (edit), 's' (split),
             'm' (merge with next), 'q' (save and quit)
    """
    while True:
        choice = input(
            "\n  [y] Accept  [n] Reject  [e] Edit procedure  "
            "[s] Split  [m] Merge with next  [q] Save & quit\n  > "
        ).strip().lower()
        if choice in ("y", "n", "e", "s", "m", "q"):
            return choice
        print("  Invalid choice. Enter y/n/e/s/m/q.")


def edit_procedure(seg: Dict) -> Dict:
    """Let the reviewer change the procedure type."""
    current = seg["procedure"]
    print(f"  Current procedure: {current}")
    print("  Available: registration, pdu_session, deregistration, authentication_sub, retry_flow, handover")
    new_proc = input("  New procedure (or Enter to keep): ").strip()
    if new_proc and new_proc != current:
        seg["procedure"] = new_proc
        print(f"  Changed: {current} -> {new_proc}")
    return seg


def split_segment(seg: Dict, events_index: Dict[int, Dict]) -> List[Dict]:
    """Split a segment at a specified event_id boundary."""
    eids = seg["event_ids"]
    print(f"  Event IDs: {eids}")
    try:
        split_after = int(input("  Split AFTER event_id: ").strip())
    except (ValueError, EOFError):
        print("  Invalid input, keeping segment as-is.")
        return [seg]

    if split_after not in eids:
        print(f"  Event {split_after} not in this segment, keeping as-is.")
        return [seg]

    split_idx = eids.index(split_after) + 1
    if split_idx >= len(eids):
        print("  Cannot split at last event, keeping as-is.")
        return [seg]

    first_ids = eids[:split_idx]
    second_ids = eids[split_idx:]

    first_end_event = events_index.get(int(first_ids[-1]), {})
    second_start_event = events_index.get(int(second_ids[0]), {})

    seg1 = dict(seg)
    seg1["segment_id"] = seg["segment_id"] + "_a"
    seg1["event_ids"] = first_ids
    seg1["end_ts"] = first_end_event.get("timestamp", seg["start_ts"])

    seg2 = dict(seg)
    seg2["segment_id"] = seg["segment_id"] + "_b"
    seg2["event_ids"] = second_ids
    seg2["start_ts"] = second_start_event.get("timestamp", seg["end_ts"])

    print(f"  Split into {seg1['segment_id']} ({len(first_ids)} events) and {seg2['segment_id']} ({len(second_ids)} events)")
    new_proc = input(f"  Procedure for second segment (Enter for '{seg['procedure']}'): ").strip()
    if new_proc:
        seg2["procedure"] = new_proc

    return [seg1, seg2]


def main() -> int:
    parser = argparse.ArgumentParser(description="Interactive gold label review tool.")
    parser.add_argument("--run-dir", required=True, help="Path to experiments/runs/<run_id>.")
    parser.add_argument("--resume", action="store_true", help="Resume from last reviewed position.")
    args = parser.parse_args()

    run_dir = pathlib.Path(args.run_dir).resolve()
    gold_path = run_dir / "gold" / "segments_gold.json"
    events_path = run_dir / "normalized" / "events.jsonl"
    review_log_path = run_dir / "gold" / "review_log.json"

    if not gold_path.exists():
        raise SystemExit(f"No gold labels found at {gold_path}. Run bootstrap_gold.py or generate_s1_gold.py first.")
    if not events_path.exists():
        raise SystemExit(f"No events found at {events_path}. Run normalize_events.py first.")

    gold = load_json(gold_path)
    events_index = load_events_by_id(events_path)
    segments = gold.get("segments", [])

    # Load existing review log for resume
    review_log: List[Dict] = []
    start_idx = 0
    if args.resume and review_log_path.exists():
        existing_log = load_json(review_log_path)
        review_log = existing_log.get("decisions", [])
        reviewed_ids = {d["segment_id"] for d in review_log}
        for i, seg in enumerate(segments):
            if seg["segment_id"] not in reviewed_ids:
                start_idx = i
                break
        else:
            start_idx = len(segments)
        print(f"Resuming from segment {start_idx + 1}/{len(segments)} ({len(review_log)} already reviewed)")

    print(f"\nGold label source: {gold.get('label_source', 'unknown')}")
    print(f"Total segments to review: {len(segments)}")
    print(f"Total events indexed: {len(events_index)}")

    reviewed_segments: List[Dict] = list(segments[:start_idx])
    i = start_idx
    while i < len(segments):
        seg = segments[i]
        display_segment(seg, events_index, i + 1, len(segments))
        choice = prompt_review()

        if choice == "q":
            # Keep remaining unreviewed segments as-is
            reviewed_segments.extend(segments[i:])
            break
        elif choice == "y":
            review_log.append({
                "segment_id": seg["segment_id"],
                "decision": "accept",
                "timestamp": datetime.utcnow().isoformat(),
            })
            reviewed_segments.append(seg)
            i += 1
        elif choice == "n":
            reason = input("  Rejection reason (optional): ").strip()
            review_log.append({
                "segment_id": seg["segment_id"],
                "decision": "reject",
                "reason": reason,
                "timestamp": datetime.utcnow().isoformat(),
            })
            # Rejected segments are excluded from gold
            i += 1
        elif choice == "e":
            edited = edit_procedure(seg)
            review_log.append({
                "segment_id": seg["segment_id"],
                "decision": "edit",
                "original_procedure": segments[i]["procedure"],
                "new_procedure": edited["procedure"],
                "timestamp": datetime.utcnow().isoformat(),
            })
            reviewed_segments.append(edited)
            i += 1
        elif choice == "s":
            split_segs = split_segment(seg, events_index)
            for s in split_segs:
                review_log.append({
                    "segment_id": s["segment_id"],
                    "decision": "split",
                    "original_segment_id": seg["segment_id"],
                    "timestamp": datetime.utcnow().isoformat(),
                })
            reviewed_segments.extend(split_segs)
            i += 1
        elif choice == "m":
            if i + 1 < len(segments):
                next_seg = segments[i + 1]
                seg["event_ids"].extend(next_seg["event_ids"])
                seg["end_ts"] = next_seg["end_ts"]
                seg["segment_id"] = seg["segment_id"] + "_merged"
                review_log.append({
                    "segment_id": seg["segment_id"],
                    "decision": "merge",
                    "merged_segments": [segments[i]["segment_id"], next_seg["segment_id"]],
                    "timestamp": datetime.utcnow().isoformat(),
                })
                reviewed_segments.append(seg)
                i += 2
            else:
                print("  No next segment to merge with.")
                reviewed_segments.append(seg)
                i += 1

    # Save reviewed gold
    reviewed_gold = {
        "label_source": "human_reviewed",
        "original_source": gold.get("label_source", "unknown"),
        "review_required": False,
        "segments": reviewed_segments,
    }
    save_json(gold_path, reviewed_gold)

    # Save review log
    review_output = {
        "reviewer": "human",
        "total_segments": len(segments),
        "decisions_made": len(review_log),
        "decisions": review_log,
    }
    save_json(review_log_path, review_output)

    accepted = sum(1 for d in review_log if d["decision"] == "accept")
    rejected = sum(1 for d in review_log if d["decision"] == "reject")
    edited = sum(1 for d in review_log if d["decision"] == "edit")
    splits = sum(1 for d in review_log if d["decision"] == "split")
    merges = sum(1 for d in review_log if d["decision"] == "merge")

    print(f"\n{'='*80}")
    print(f"Review complete!")
    print(f"  Accepted: {accepted}  Rejected: {rejected}  Edited: {edited}  Split: {splits}  Merged: {merges}")
    print(f"  Final gold segments: {len(reviewed_segments)}")
    print(f"  Saved to: {gold_path}")
    print(f"  Review log: {review_log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
