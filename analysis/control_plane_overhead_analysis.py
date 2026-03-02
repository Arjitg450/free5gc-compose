#!/usr/bin/env python3
"""
5G Control Plane Overhead Analysis: How signaling overhead scales with UE count.

Analyzes volume_ue* runs to produce:
  - Total control signaling (bytes + message/event counts) vs UE count
  - Per-NF contribution to overhead (which NF dominates)
  - Per-procedure breakdown (registration, PDU session, etc.)
  - Scaling trend (linear/super-linear) and marginal cost per UE

Requires: existing volume experiment runs with normalized events.
  Run:  python experiments/run_volume_experiment.py --project-root . --provision 40
  Then: python experiments/run_pipeline.py  (or normalize_events on each run)
  Then: python analysis/control_plane_overhead_analysis.py --runs-dir experiments/runs

Output: analysis/control_plane_overhead_plots/ with PNG figures and report.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Any, Optional

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
except ImportError:
    print("Error: matplotlib and numpy required. Install: pip install matplotlib numpy")
    raise SystemExit(1)


# UE count from scenario_id
UE_COUNT_MAP = {
    "volume_ue1": 1,
    "volume_ue10": 10,
    "volume_ue20": 20,
    "volume_ue30": 30,
    "volume_ue40": 40,
}

# NF display order and colors (consistent across plots)
NF_ORDER = ["upf", "smf", "nrf", "amf", "udm", "ausf", "udr", "ueransim"]
NF_COLORS = {
    "upf": "#e74c3c",
    "smf": "#3498db",
    "nrf": "#2ecc71",
    "amf": "#9b59b6",
    "udm": "#f39c12",
    "ausf": "#1abc9c",
    "udr": "#34495e",
    "ueransim": "#95a5a6",
}
# Pcap roles
PCAP_ORDER = ["amf_0", "smf_1", "upf_2"]
PCAP_LABELS = {"amf_0": "N2/SBI (AMF)", "smf_1": "N4/SBI (SMF)", "upf_2": "N3/N4 (UPF)"}


def load_run_metadata(run_dir: Path) -> Optional[Dict[str, Any]]:
    meta_path = run_dir / "run_metadata.json"
    if not meta_path.exists():
        return None
    with meta_path.open("r") as f:
        return json.load(f)


def extract_ue_count(meta: Dict) -> int:
    sid = meta.get("run_id", meta.get("scenario_id", "") or "")
    if isinstance(sid, dict):
        sid = sid.get("scenario_id", "")
    if isinstance(sid, str) and "__" in sid:
        sid = sid.split("__")[0]
    return UE_COUNT_MAP.get(sid, 0)


def extract_volume_from_metadata(meta: Dict) -> Dict[str, Any]:
    health = meta.get("capture_health", {})
    log_bytes: Dict[str, int] = {}
    for container, info in health.get("logs", {}).items():
        b = info.get("bytes", 0) if isinstance(info, dict) else 0
        log_bytes[container] = b

    pcap_bytes: Dict[str, int] = {}
    for name, info in health.get("pcaps", {}).items():
        if isinstance(info, dict):
            pcap_bytes[name.replace(".pcap", "")] = info.get("bytes", 0)
        else:
            pcap_bytes[name.replace(".pcap", "")] = int(info) if isinstance(info, (int, float)) else 0

    return {
        "log_bytes_per_nf": log_bytes,
        "total_log_bytes": sum(log_bytes.values()),
        "pcap_bytes_per_file": pcap_bytes,
        "total_pcap_bytes": sum(pcap_bytes.values()),
    }


def load_events_summary(run_dir: Path) -> Optional[Dict[str, Any]]:
    """Load event counts per source and per procedure from events.jsonl."""
    events_path = run_dir / "normalized" / "events.jsonl"
    if not events_path.exists():
        return None

    events_by_source: Dict[str, int] = {}
    events_by_procedure: Dict[str, int] = {}
    events_by_nf: Dict[str, int] = {}  # map log sources to NF; pcap stays separate

    with events_path.open("r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue

            src = ev.get("source", "unknown")
            proc = ev.get("procedure_hint", "unknown")
            nf = ev.get("nf", "unknown")

            # Normalize source for NF grouping: pcap_amf_0 -> pcap_amf, etc.
            if src.startswith("pcap_"):
                key = src
            else:
                key = src.lower()

            events_by_source[key] = events_by_source.get(key, 0) + 1
            events_by_procedure[proc] = events_by_procedure.get(proc, 0) + 1

            # For NF: use source for logs, or derive from pcap container
            if src.startswith("pcap_"):
                nf_key = f"pcap_{src.split('_')[1]}"  # pcap_amf_0 -> pcap_amf
            else:
                nf_key = src.lower()
            events_by_nf[nf_key] = events_by_nf.get(nf_key, 0) + 1

    return {
        "events_by_source": events_by_source,
        "events_by_procedure": events_by_procedure,
        "events_by_nf": events_by_nf,
        "total_events": sum(events_by_source.values()),
    }


def discover_volume_runs(runs_dir: Path) -> List[Dict[str, Any]]:
    """Gather data from volume_ue* runs."""
    SCENARIOS = ["volume_ue1", "volume_ue10", "volume_ue20", "volume_ue30", "volume_ue40"]
    rows: List[Dict[str, Any]] = []

    for sid in SCENARIOS:
        pattern = f"{sid}__r1__*"
        candidates = sorted(runs_dir.glob(pattern))
        if not candidates:
            continue
        run_dir = candidates[-1]
        meta = load_run_metadata(run_dir)
        if not meta:
            continue

        ue_count = extract_ue_count(meta)
        vol = extract_volume_from_metadata(meta)
        events = load_events_summary(run_dir)

        row = {
            "run_id": run_dir.name,
            "scenario_id": sid,
            "ue_count": ue_count,
            "duration_seconds": meta.get("scenario", {}).get("duration_seconds", 300),
            **vol,
        }
        if events:
            row["event_counts"] = events
            row["total_events"] = events["total_events"]
        else:
            row["event_counts"] = None
            row["total_events"] = 0

        rows.append(row)

    rows.sort(key=lambda r: r["ue_count"])
    return rows


def format_size(b: int) -> str:
    if b >= 1_000_000_000:
        return f"{b / 1e9:.2f} GB"
    if b >= 1_000_000:
        return f"{b / 1e6:.2f} MB"
    if b >= 1_000:
        return f"{b / 1e3:.2f} KB"
    return f"{b} B"


# ---------------------------------------------------------------------------
# Plotting functions
# ---------------------------------------------------------------------------

def plot_total_overhead_vs_ue(rows: List[Dict], out_dir: Path) -> None:
    """Plot 1: Total log bytes and total events vs UE count."""
    ue_counts = [r["ue_count"] for r in rows]
    log_bytes = [r["total_log_bytes"] for r in rows]
    pcap_bytes = [r["total_pcap_bytes"] for r in rows]
    events = [r["total_events"] for r in rows]

    fig, axes = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

    ax1 = axes[0]
    ax1.plot(ue_counts, [b / 1e6 for b in log_bytes], "o-", color="#3498db", linewidth=2, markersize=8, label="Log volume (MB)")
    ax1.plot(ue_counts, [b / 1e6 for b in pcap_bytes], "s-", color="#e74c3c", linewidth=2, markersize=8, label="Pcap volume (MB)")
    ax1.set_ylabel("Volume (MB)")
    ax1.set_title("5G Control Plane Overhead vs UE Count\nTotal Log + Pcap Volume")
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    ax2 = axes[1]
    ax2.plot(ue_counts, events, "o-", color="#2ecc71", linewidth=2, markersize=8, label="Control-plane events (parsed)")
    ax2.set_xlabel("Number of UEs")
    ax2.set_ylabel("Event count")
    ax2.set_title("Control-Plane Message/Event Count vs UE Count")
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    fig.savefig(out_dir / "01_total_overhead_vs_ue.png", dpi=150, bbox_inches="tight")
    plt.close()


def plot_marginal_overhead(rows: List[Dict], out_dir: Path) -> None:
    """Plot 2: Overhead per UE (bytes/UE, events/UE) – marginal cost."""
    ue_counts = np.array([r["ue_count"] for r in rows])
    log_bytes = np.array([r["total_log_bytes"] for r in rows])
    events = np.array([r["total_events"] for r in rows])

    # Avoid div by zero
    bytes_per_ue = np.where(ue_counts > 0, log_bytes / ue_counts, 0)
    events_per_ue = np.where(ue_counts > 0, events / ue_counts, 0)

    fig, axes = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

    ax1 = axes[0]
    ax1.bar(ue_counts - 0.8, bytes_per_ue / 1e3, width=1.6, color="#3498db", edgecolor="white", label="Log bytes per UE")
    ax1.set_ylabel("Log volume per UE (KB)")
    ax1.set_title("Marginal Overhead: Bytes per UE")
    ax1.legend()
    ax1.grid(True, alpha=0.3, axis="y")

    ax2 = axes[1]
    ax2.bar(ue_counts - 0.8, events_per_ue, width=1.6, color="#2ecc71", edgecolor="white", label="Events per UE")
    ax2.set_xlabel("Number of UEs")
    ax2.set_ylabel("Events per UE")
    ax2.set_title("Marginal Overhead: Control-Plane Events per UE")
    ax2.legend()
    ax2.grid(True, alpha=0.3, axis="y")

    plt.tight_layout()
    fig.savefig(out_dir / "02_marginal_overhead_per_ue.png", dpi=150, bbox_inches="tight")
    plt.close()


def plot_nf_log_bytes_contribution(rows: List[Dict], out_dir: Path) -> None:
    """Plot 3: Stacked bar – log bytes per NF across UE counts."""
    ue_counts = [r["ue_count"] for r in rows]
    nf_order = [n for n in NF_ORDER if any(r.get("log_bytes_per_nf", {}).get(n) for r in rows)]
    if not nf_order:
        nf_order = NF_ORDER

    fig, ax = plt.subplots(figsize=(12, 6))
    bottom = np.zeros(len(rows))
    for nf in nf_order:
        vals = [r.get("log_bytes_per_nf", {}).get(nf, 0) for r in rows]
        ax.bar(ue_counts, vals, bottom=bottom, label=nf.upper(), color=NF_COLORS.get(nf, "#95a5a6"))
        bottom += np.array(vals)

    ax.set_xlabel("Number of UEs")
    ax.set_ylabel("Log volume (bytes)")
    ax.set_title("Per-NF Log Volume Contribution (Stacked)\nWhich NF Produces Most Control-Plane Log Overhead")
    ax.legend(loc="upper left", ncol=2)
    ax.grid(True, alpha=0.3, axis="y")
    plt.tight_layout()
    fig.savefig(out_dir / "03_nf_log_bytes_stacked.png", dpi=150, bbox_inches="tight")
    plt.close()


def plot_nf_contribution_pie(rows: List[Dict], out_dir: Path) -> None:
    """Plot 4: Pie chart – NF contribution % at max UE count."""
    if not rows:
        return
    last = rows[-1]
    lb = last.get("log_bytes_per_nf", {})
    total = sum(lb.values())
    if total == 0:
        return

    nf_order = [n for n in NF_ORDER if lb.get(n, 0) > 0]
    sizes = [lb.get(n, 0) for n in nf_order]
    labels = [f"{n.upper()} ({100 * s / total:.1f}%)" for n, s in zip(nf_order, sizes)]
    colors = [NF_COLORS.get(n, "#95a5a6") for n in nf_order]

    fig, ax = plt.subplots(figsize=(9, 9))
    wedges, texts, autotexts = ax.pie(sizes, labels=labels, colors=colors, autopct="", startangle=90)
    ax.set_title(f"NF Contribution to Control-Plane Log Overhead at {last['ue_count']} UEs\n"
                 f"Total: {format_size(total)}")
    plt.tight_layout()
    fig.savefig(out_dir / "04_nf_contribution_pie.png", dpi=150, bbox_inches="tight")
    plt.close()


def plot_nf_events_contribution(rows: List[Dict], out_dir: Path) -> None:
    """Plot 5: Events per NF across UE counts (grouped bar or stacked)."""
    # Use last run for event breakdown; aggregate sources into NF-like groups
    if not rows:
        return
    last = rows[-1]
    ec = last.get("event_counts")
    if not ec:
        return

    by_source = ec.get("events_by_source", {})
    nf_event_totals = dict(by_source)

    nf_order = sorted(nf_event_totals.keys(), key=lambda x: -nf_event_totals[x])
    vals = [nf_event_totals[n] for n in nf_order]
    def _nf_color(name: str) -> str:
        if name.startswith("pcap_"):
            return NF_COLORS.get(name.split("_")[1], "#95a5a6")
        return NF_COLORS.get(name, "#95a5a6")

    cols = [_nf_color(n) for n in nf_order]

    fig, ax = plt.subplots(figsize=(12, 6))
    x = np.arange(len(nf_order))
    ax.barh(x, vals, color=cols)
    ax.set_yticks(x)
    ax.set_yticklabels([n.upper().replace("PCAP_", "pcap ") for n in nf_order])
    ax.set_xlabel("Control-plane event count")
    ax.set_title(f"Per-NF/Per-Source Event Contribution at {last['ue_count']} UEs\n(Which NF/Source Emits Most Signaling Events)")
    ax.grid(True, alpha=0.3, axis="x")
    plt.tight_layout()
    fig.savefig(out_dir / "05_nf_events_contribution.png", dpi=150, bbox_inches="tight")
    plt.close()


def plot_procedure_breakdown(rows: List[Dict], out_dir: Path) -> None:
    """Plot 6: Procedure-level breakdown (registration, pdu_session, etc.) vs UE."""
    # Build procedure counts per UE scenario
    proc_data: Dict[str, List[int]] = {}
    ue_counts = []

    for r in rows:
        ue_counts.append(r["ue_count"])
        ec = r.get("event_counts")
        if not ec:
            continue
        by_proc = ec.get("events_by_procedure", {})
        for proc, count in by_proc.items():
            if proc not in proc_data:
                proc_data[proc] = [0] * len(rows)
            idx = rows.index(r)
            proc_data[proc][idx] = count

    if not proc_data or not ue_counts:
        return

    # Top procedures by total count
    proc_totals = [(p, sum(vals)) for p, vals in proc_data.items()]
    proc_totals.sort(key=lambda x: -x[1])
    top_procs = [p for p, _ in proc_totals[:10]]

    fig, ax = plt.subplots(figsize=(12, 7))
    x = np.arange(len(ue_counts))
    width = 0.08
    for i, proc in enumerate(top_procs):
        vals = proc_data.get(proc, [0] * len(ue_counts))
        offset = (i - len(top_procs) / 2) * width
        ax.bar(x + offset, vals, width, label=proc.replace("_", " ").title())

    ax.set_xticks(x)
    ax.set_xticklabels(ue_counts)
    ax.set_xlabel("Number of UEs")
    ax.set_ylabel("Event count")
    ax.set_title("Control-Plane Events by Procedure Type vs UE Count")
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(True, alpha=0.3, axis="y")
    plt.tight_layout()
    fig.savefig(out_dir / "06_procedure_breakdown.png", dpi=150, bbox_inches="tight")
    plt.close()


def plot_scaling_trend(rows: List[Dict], out_dir: Path) -> None:
    """Plot 7: Linear/super-linear scaling fit with R²."""
    ue_counts = np.array([r["ue_count"] for r in rows], dtype=float)
    log_bytes = np.array([r["total_log_bytes"] for r in rows], dtype=float)
    events = np.array([r["total_events"] for r in rows], dtype=float)

    if len(ue_counts) < 2:
        return

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    for ax, ydata, ylabel, color in [
        (axes[0], log_bytes / 1e6, "Log volume (MB)", "#3498db"),
        (axes[1], events, "Event count", "#2ecc71"),
    ]:
        ax.scatter(ue_counts, ydata, s=80, color=color, edgecolor="black", zorder=3)

        # Linear fit
        A = np.vstack([ue_counts, np.ones(len(ue_counts))]).T
        m, c = np.linalg.lstsq(A, ydata, rcond=None)[0]
        yfit = m * ue_counts + c
        r2 = 1 - np.sum((ydata - yfit) ** 2) / np.sum((ydata - np.mean(ydata)) ** 2) if len(ydata) > 1 else 0

        ax.plot(ue_counts, yfit, "--", color=color, linewidth=2, label=f"Linear fit: y={m:.1f}x+{c:.0f}, R²={r2:.3f}")
        ax.set_xlabel("Number of UEs")
        ax.set_ylabel(ylabel)
        ax.legend()
        ax.grid(True, alpha=0.3)

    axes[0].set_title("Log Volume Scaling Trend")
    axes[1].set_title("Event Count Scaling Trend")
    plt.suptitle("5G Control Plane Overhead: Scaling with UE Count (Linear Model)", fontsize=12, y=1.02)
    plt.tight_layout()
    fig.savefig(out_dir / "07_scaling_trend.png", dpi=150, bbox_inches="tight")
    plt.close()


def plot_pcap_breakdown(rows: List[Dict], out_dir: Path) -> None:
    """Plot 8: Pcap volume by interface (N2, N4, N3) vs UE."""
    ue_counts = [r["ue_count"] for r in rows]
    pcap_data = {k: [] for k in PCAP_ORDER}

    for r in rows:
        pb = r.get("pcap_bytes_per_file", {})
        for k in PCAP_ORDER:
            # Handle amf_0.pcap -> amf_0
            pk = k if k in pb else f"{k}.pcap"
            pcap_data[k].append(pb.get(k, pb.get(pk, 0)))

    fig, ax = plt.subplots(figsize=(10, 6))
    x = np.arange(len(ue_counts))
    width = 0.25
    for i, (k, lbl) in enumerate(PCAP_LABELS.items()):
        vals = pcap_data.get(k, [0] * len(ue_counts))
        ax.bar(x + (i - 1) * width, [v / 1e6 for v in vals], width, label=lbl)

    ax.set_xticks(x)
    ax.set_xticklabels(ue_counts)
    ax.set_xlabel("Number of UEs")
    ax.set_ylabel("Pcap volume (MB)")
    ax.set_title("Wire-Level Control/User Plane Traffic by Capture Point vs UE Count")
    ax.legend()
    ax.grid(True, alpha=0.3, axis="y")
    plt.tight_layout()
    fig.savefig(out_dir / "08_pcap_breakdown.png", dpi=150, bbox_inches="tight")
    plt.close()


def write_report(rows: List[Dict], out_dir: Path) -> None:
    """Write markdown report with key findings."""
    report_path = out_dir / "control_plane_overhead_report.md"
    with report_path.open("w") as f:
        f.write("# 5G Control Plane Overhead Analysis Report\n\n")
        f.write("Analysis of how control signaling overhead scales with the number of UEs in the 5G control plane.\n\n")

        f.write("## Summary Table\n\n")
        f.write("| UE count | Log volume | Pcap volume | Control events | Log/UE (KB) | Events/UE |\n")
        f.write("|---------|------------|-------------|----------------|-------------|----------|\n")
        for r in rows:
            ue = r["ue_count"]
            lb = r["total_log_bytes"]
            pb = r["total_pcap_bytes"]
            ev = r["total_events"]
            lb_per_ue = lb / ue / 1024 if ue > 0 else 0
            ev_per_ue = ev / ue if ue > 0 else 0
            f.write(f"| {ue} | {format_size(lb)} | {format_size(pb)} | {ev:,} | {lb_per_ue:.1f} | {ev_per_ue:.0f} |\n")

        if len(rows) >= 2:
            base = rows[0]
            f.write("\n## Scaling vs Baseline (1 UE)\n\n")
            for r in rows[1:]:
                lb_ratio = r["total_log_bytes"] / base["total_log_bytes"] if base["total_log_bytes"] else 0
                ev_ratio = r["total_events"] / base["total_events"] if base["total_events"] else 0
                f.write(f"- **{r['ue_count']} UEs**: Log volume {lb_ratio:.2f}x baseline, Events {ev_ratio:.2f}x baseline\n")

        # Top contributing NF
        if rows:
            last = rows[-1]
            lb = last.get("log_bytes_per_nf", {})
            total = sum(lb.values())
            if total > 0:
                sorted_nf = sorted(lb.items(), key=lambda x: -x[1])
                f.write("\n## Top NF Contributors (at max UE count)\n\n")
                for nf, b in sorted_nf:
                    pct = 100 * b / total
                    f.write(f"- **{nf.upper()}**: {format_size(b)} ({pct:.1f}%)\n")

        f.write("\n## Plots Generated\n\n")
        for name in ["01_total_overhead_vs_ue", "02_marginal_overhead_per_ue", "03_nf_log_bytes_stacked",
                     "04_nf_contribution_pie", "05_nf_events_contribution", "06_procedure_breakdown",
                     "07_scaling_trend", "08_pcap_breakdown"]:
            f.write(f"- `{name}.png`\n")

    print(f"Report written to {report_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="5G control plane overhead analysis with plots.")
    parser.add_argument("--runs-dir", default="experiments/runs", help="Path to experiments/runs")
    parser.add_argument("--output-dir", default="analysis/control_plane_overhead_plots", help="Output directory for plots")
    parser.add_argument("--project-root", help="Project root (default: parent of analysis/)")
    args = parser.parse_args()

    project_root = Path(args.project_root or Path(__file__).resolve().parents[1])
    runs_dir = project_root / args.runs_dir
    out_dir = project_root / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    if not runs_dir.exists():
        print(f"Error: runs directory not found: {runs_dir}", file=__import__("sys").stderr)
        return 1

    rows = discover_volume_runs(runs_dir)
    if not rows:
        print("No volume_ue* runs found. Run volume experiments first:", file=__import__("sys").stderr)
        print("  python experiments/run_volume_experiment.py --project-root . --provision 40")
        return 1

    print(f"Found {len(rows)} volume runs: UE counts {[r['ue_count'] for r in rows]}")

    plot_total_overhead_vs_ue(rows, out_dir)
    plot_marginal_overhead(rows, out_dir)
    plot_nf_log_bytes_contribution(rows, out_dir)
    plot_nf_contribution_pie(rows, out_dir)
    plot_nf_events_contribution(rows, out_dir)
    plot_procedure_breakdown(rows, out_dir)
    plot_scaling_trend(rows, out_dir)
    plot_pcap_breakdown(rows, out_dir)
    write_report(rows, out_dir)

    print(f"Plots saved to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
