#!/usr/bin/env python3
"""
Run volume experiment: 1, 10, 20, 30, 40 UEs with same duration and capture,
then produce a detailed analysis of how log and pcap volumes scale with UE count.

Usage:
  # Provision 40 subscribers once (requires webconsole up), then run all experiments:
  python experiments/run_volume_experiment.py --project-root . --provision 40

  # Run experiments only (subscribers already provisioned):
  python experiments/run_volume_experiment.py --project-root .

  # Analyze existing runs (e.g. after re-run):
  python experiments/run_volume_experiment.py --project-root . --analyze-only --runs-dir experiments/runs
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Any

DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ["volume_ue1", "volume_ue10", "volume_ue20", "volume_ue30", "volume_ue40"]
REPETITION = 1


def run_cmd(cmd: List[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    print(f"[run] {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=str(cwd), check=check, text=True)


def provision_subscribers(project_root: Path, count: int) -> bool:
    manifest = project_root / "experiments" / "subscribers.json"
    if manifest.exists():
        try:
            with manifest.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("count", 0) >= count:
                print(f"[provision] subscribers.json already has {data['count']} subscribers (>= {count}), skipping.")
                return True
        except Exception:
            pass
    print(f"[provision] Provisioning {count} subscribers...")
    try:
        run_cmd(
            [sys.executable, "experiments/provision_subscribers.py", "--count", str(count), "--output", "experiments/subscribers.json"],
            cwd=project_root,
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"[provision] Failed: {e}", file=sys.stderr)
        return False


def run_experiment(project_root: Path, scenario_id: str) -> str | None:
    scenario_path = project_root / "experiments" / "scenarios" / f"{scenario_id}.json"
    if not scenario_path.exists():
        print(f"[run] Scenario not found: {scenario_path}", file=sys.stderr)
        return None
    try:
        run_cmd(
            [
                sys.executable,
                "experiments/run_experiment.py",
                "--scenario", str(scenario_path),
                "--repetition", str(REPETITION),
                "--project-root", str(project_root),
            ],
            cwd=project_root,
        )
    except subprocess.CalledProcessError as e:
        print(f"[run] Experiment {scenario_id} failed: {e}", file=sys.stderr)
        return None
    runs_dir = project_root / "experiments" / "runs"
    pattern = f"{scenario_id}__r{REPETITION}__*"
    candidates = sorted(runs_dir.glob(pattern))
    if not candidates:
        print(f"[run] No run directory found for {pattern}", file=sys.stderr)
        return None
    return candidates[-1].name


def load_run_metadata(run_dir: Path) -> Dict[str, Any] | None:
    meta_path = run_dir / "run_metadata.json"
    if not meta_path.exists():
        return None
    with meta_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def extract_volume_from_run(run_dir: Path) -> Dict[str, Any]:
    meta = load_run_metadata(run_dir)
    if not meta:
        return {"run_id": run_dir.name, "error": "no run_metadata.json"}

    health = meta.get("capture_health", {})
    log_bytes: Dict[str, int] = {}
    total_log = 0
    for container, info in health.get("logs", {}).items():
        b = info.get("bytes", 0)
        log_bytes[container] = b
        total_log += b

    pcap_bytes: Dict[str, int] = dict(health.get("pcaps", {}))
    for name, info in list(pcap_bytes.items()):
        if isinstance(info, dict):
            pcap_bytes[name] = info.get("bytes", 0)
    total_pcap = sum(pcap_bytes.values())

    # Optional: actual file sizes from disk (in case metadata is stale)
    raw = run_dir / "raw"
    if raw.exists():
        logs_dir = raw / "logs"
        pcaps_dir = raw / "pcaps"
        if logs_dir.exists():
            for f in logs_dir.glob("*.log"):
                size = f.stat().st_size
                if f.stem not in log_bytes or log_bytes[f.stem] == 0:
                    log_bytes[f.stem] = size
                    total_log += size
        if pcaps_dir.exists():
            for f in pcaps_dir.glob("*.pcap"):
                size = f.stat().st_size
                pcap_bytes[f.name] = size
            total_pcap = sum(pcap_bytes.values())

    return {
        "run_id": run_dir.name,
        "scenario_id": meta.get("run_id", "").split("__")[0],
        "status": meta.get("status", "unknown"),
        "duration_seconds": meta.get("scenario", {}).get("duration_seconds"),
        "log_bytes_per_container": log_bytes,
        "total_log_bytes": total_log,
        "pcap_bytes_per_file": pcap_bytes,
        "total_pcap_bytes": total_pcap,
        "capture_health_status": health.get("status"),
    }


def analyze_runs(runs_dir: Path, run_ids: List[str] | None) -> List[Dict[str, Any]]:
    """Gather volume data from run directories. If run_ids is None, discover volume_ue* runs."""
    rows: List[Dict[str, Any]] = []
    if run_ids:
        for rid in run_ids:
            run_dir = runs_dir / rid
            if run_dir.is_dir():
                rows.append(extract_volume_from_run(run_dir))
            else:
                rows.append({"run_id": rid, "error": "directory not found"})
    else:
        for scenario_id in SCENARIOS:
            pattern = f"{scenario_id}__r{REPETITION}__*"
            candidates = sorted(runs_dir.glob(pattern))
            for run_dir in candidates[-1:]:  # latest only
                rows.append(extract_volume_from_run(run_dir))
                break
        # Sort by UE count inferred from scenario_id (match longer first: ue40 before ue4, ue10 before ue1)
        def ue_count(r):
            sid = r.get("scenario_id", "")
            if sid == "volume_ue40": return 40
            if sid == "volume_ue30": return 30
            if sid == "volume_ue20": return 20
            if sid == "volume_ue10": return 10
            if sid == "volume_ue1": return 1
            return 0
        rows.sort(key=ue_count)
    return rows


def format_size(b: int) -> str:
    if b >= 1_000_000_000:
        return f"{b / 1e9:.2f} GB"
    if b >= 1_000_000:
        return f"{b / 1e6:.2f} MB"
    if b >= 1_000:
        return f"{b / 1e3:.2f} KB"
    return f"{b} B"


def write_analysis_report(rows: List[Dict[str, Any]], out_path: Path) -> None:
    with out_path.open("w", encoding="utf-8") as f:
        f.write("# Log and PCAP Volume vs UE Count – Detailed Analysis\n\n")
        f.write("Experiment: same duration (300s), same capture (AMF/SMF/UPF logs + pcaps), UE count 1, 10, 20, 30, 40.\n\n")

        # Summary table
        f.write("## Summary: Total volumes per UE count\n\n")
        f.write("| UE count | Total logs | Total pcap | Run ID | Status |\n")
        f.write("|----------|------------|------------|--------|--------|\n")
        for r in rows:
            if "error" in r:
                f.write(f"| - | - | - | {r.get('run_id', '?')} | {r.get('error', '')} |\n")
                continue
            ue = r.get("scenario_id", "").replace("volume_ue", "") or "?"
            f.write(f"| {ue} | {format_size(r.get('total_log_bytes', 0))} | {format_size(r.get('total_pcap_bytes', 0))} | {r.get('run_id', '')} | {r.get('status', '')} |\n")

        # Per-container log breakdown
        f.write("\n## Per-container log sizes (bytes)\n\n")
        containers = set()
        for r in rows:
            if "error" not in r:
                containers.update(r.get("log_bytes_per_container", {}).keys())
        containers = sorted(containers)
        if containers:
            f.write("| UE scenario | " + " | ".join(containers) + " | **Total** |\n")
            f.write("|-------------|" + "|".join(["----------"] * (len(containers) + 1)) + "|\n")
            for r in rows:
                if "error" in r:
                    continue
                cells = [r.get("scenario_id", "")]
                for c in containers:
                    cells.append(str(r.get("log_bytes_per_container", {}).get(c, 0)))
                cells.append(str(r.get("total_log_bytes", 0)))
                f.write("| " + " | ".join(cells) + " |\n")

        # Per-pcap breakdown
        f.write("\n## Per-pcap file sizes (bytes)\n\n")
        pcap_files = set()
        for r in rows:
            if "error" not in r:
                pcap_files.update(r.get("pcap_bytes_per_file", {}).keys())
        pcap_files = sorted(pcap_files)
        if pcap_files:
            f.write("| UE scenario | " + " | ".join(pcap_files) + " | **Total** |\n")
            f.write("|-------------|" + "|".join(["----------"] * (len(pcap_files) + 1)) + "|\n")
            for r in rows:
                if "error" in r:
                    continue
                cells = [r.get("scenario_id", "")]
                for p in pcap_files:
                    cells.append(str(r.get("pcap_bytes_per_file", {}).get(p, 0)))
                cells.append(str(r.get("total_pcap_bytes", 0)))
                f.write("| " + " | ".join(cells) + " |\n")

        # Human-readable summary
        f.write("\n## Formatted totals\n\n")
        f.write("| UE count | Total logs | Total pcap |\n")
        f.write("|----------|------------|------------|\n")
        for r in rows:
            if "error" in r:
                continue
            ue = r.get("scenario_id", "").replace("volume_ue", "") or "?"
            f.write(f"| {ue} | {format_size(r.get('total_log_bytes', 0))} | {format_size(r.get('total_pcap_bytes', 0))} |\n")

        # Growth analysis
        f.write("\n## Scaling analysis\n\n")
        valid = [r for r in rows if "error" not in r and "total_log_bytes" in r and "total_pcap_bytes" in r]
        if len(valid) >= 2:
            base = valid[0]
            base_ue = base.get("scenario_id", "").replace("volume_ue", "")
            try:
                base_ue_n = int(base_ue) if base_ue.isdigit() else 1
            except Exception:
                base_ue_n = 1
            base_log = base.get("total_log_bytes", 0)
            base_pcap = base.get("total_pcap_bytes", 0)
            f.write(f"- Baseline ({base_ue} UE): logs {format_size(base_log)}, pcap {format_size(base_pcap)}\n")
            for r in valid[1:]:
                ue = r.get("scenario_id", "").replace("volume_ue", "")
                try:
                    ue_n = int(ue) if ue.isdigit() else 0
                except Exception:
                    ue_n = 0
                log_b = r.get("total_log_bytes", 0)
                pcap_b = r.get("total_pcap_bytes", 0)
                if base_ue_n and base_log:
                    log_ratio = log_b / base_log
                    pcap_ratio = pcap_b / base_pcap if base_pcap else 0
                    f.write(f"- {ue} UEs: logs {format_size(log_b)} ({log_ratio:.2f}x baseline), pcap {format_size(pcap_b)} ({pcap_ratio:.2f}x baseline)\n")
        f.write("\n")
    print(f"[analysis] Report written to {out_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run volume experiment (1–40 UEs) and analyze log/pcap scaling.")
    parser.add_argument("--project-root", default=str(DEFAULT_PROJECT_ROOT), help="free5gc-compose root")
    parser.add_argument("--provision", type=int, metavar="N", help="Provision N subscribers before running (e.g. 40)")
    parser.add_argument("--analyze-only", action="store_true", help="Only analyze existing runs, do not run experiments")
    parser.add_argument("--runs-dir", help="Runs directory (default: project_root/experiments/runs)")
    parser.add_argument("--run-ids", nargs="*", help="Specific run IDs to include in analysis (for analyze-only)")
    parser.add_argument("--output", default="experiments/runs/volume_analysis_report.md", help="Output report path")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    runs_dir = Path(args.runs_dir or str(project_root / "experiments" / "runs"))
    report_path = project_root / args.output if not Path(args.output).is_absolute() else Path(args.output)

    if not args.analyze_only:
        if args.provision:
            if not provision_subscribers(project_root, args.provision):
                return 1
        for scenario_id in SCENARIOS:
            run_experiment(project_root, scenario_id)
        print(f"[run] Completed experiments for {SCENARIOS}")

    rows = analyze_runs(runs_dir, run_ids=args.run_ids if args.analyze_only else None)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    write_analysis_report(rows, report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
