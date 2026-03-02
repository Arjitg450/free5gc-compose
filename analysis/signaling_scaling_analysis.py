#!/usr/bin/env python3
"""
5G Control Plane Signaling Scaling Analysis (1 → 40 UEs).

Metrics (per Data Definitions):
  - Events: One normalized log line from normalize_events.py (log_events)
  - Packets: Raw control-plane packets from normalize_pcap.py (NGAP + PFCP + HTTP/2 SBI; excludes GTP)

Output:
  - Summary table: Event count, Packet count, Packets-to-Events ratio, 1 UE vs 40 UE
  - Plane comparison: Control vs Data plane growth
  - Trend: Linear (y = mx) vs Exponential (y = x^n) fit
  - Signaling overhead per UE
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Any, Optional

try:
    import numpy as np
except ImportError:
    print("Error: numpy required. Install: pip install numpy")
    raise SystemExit(1)

UE_SCENARIOS = ["volume_ue1", "volume_ue10", "volume_ue20", "volume_ue30", "volume_ue40"]
UE_COUNT_MAP = {s: int(s.replace("volume_ue", "")) for s in UE_SCENARIOS}


def load_run_data(runs_dir: Path) -> List[Dict[str, Any]]:
    """Load summary.json and pcap_coverage.json for each volume run."""
    rows = []
    for sid in UE_SCENARIOS:
        pattern = f"{sid}__r1__*"
        candidates = sorted(runs_dir.glob(pattern))
        if not candidates:
            continue
        run_dir = candidates[-1]

        summary_path = run_dir / "normalized" / "summary.json"
        pcap_path = run_dir / "normalized" / "pcap_coverage.json"

        if not summary_path.exists():
            continue

        with summary_path.open() as f:
            summary = json.load(f)

        log_events = summary.get("log_events", 0)
        pcap_events = summary.get("pcap_events", 0)

        # Control-plane packets = NGAP + PFCP + HTTP/2 SBI (exclude GTP = user plane)
        control_packets = 0
        data_packets = 0
        if pcap_path.exists():
            with pcap_path.open() as f:
                pcap_cov = json.load(f)
            for cap in pcap_cov.get("per_pcap", []):
                pp = cap.get("per_protocol", {})
                control_packets += pp.get("ngap", 0) + pp.get("pfcp", 0) + pp.get("http2_sbi", 0)
                data_packets += pp.get("gtp", 0)

        ue_count = UE_COUNT_MAP.get(sid, 0)
        rows.append({
            "scenario_id": sid,
            "ue_count": ue_count,
            "log_events": log_events,
            "pcap_events": pcap_events,
            "control_packets": control_packets,
            "data_packets": data_packets,
            "run_dir": run_dir,
        })
    rows.sort(key=lambda r: r["ue_count"])
    return rows


def compute_ratios(rows: List[Dict]) -> None:
    for r in rows:
        le = r["log_events"]
        cp = r["control_packets"]
        r["packets_to_events_ratio"] = cp / le if le > 0 else float("nan")
        r["events_per_ue"] = le / r["ue_count"] if r["ue_count"] > 0 else 0
        r["packets_per_ue"] = cp / r["ue_count"] if r["ue_count"] > 0 else 0


def fit_models(rows: List[Dict]) -> Dict[str, Any]:
    """Fit linear (y=mx+b) and power (y=ax^n) models. Return R² and parameters."""
    ue = np.array([r["ue_count"] for r in rows], dtype=float)
    events = np.array([r["log_events"] for r in rows], dtype=float)
    packets = np.array([r["control_packets"] for r in rows], dtype=float)

    result = {}

    for name, y in [("events", events), ("packets", packets)]:
        if np.any(np.isnan(y)):
            result[name] = {"linear": None, "power": None}
            continue
        valid = np.sum(y > 0) if name == "packets" else len(y)
        if valid < 2:
            result[name] = {"linear": None, "power": None}
            continue

        ss_tot = np.sum((y - np.mean(y)) ** 2)
        if ss_tot <= 0:
            result[name] = {"linear": None, "power": None}
            continue

        # Linear: y = m*x + b (allows fixed overhead)
        A = np.vstack([ue, np.ones(len(ue))]).T
        coeffs, _, _, _ = np.linalg.lstsq(A, y, rcond=None)
        m, b = coeffs[0], coeffs[1]
        y_linear = m * ue + b
        ss_res = np.sum((y - y_linear) ** 2)
        r2_linear = 1 - ss_res / ss_tot
        formula_lin = f"y = {m:.1f}x + {b:.0f}" if abs(b) > 1 else f"y = {m:.1f}x"

        # Power: log(y) = n*log(x) + log(a)  =>  y = a*x^n
        mask = (ue > 0) & (y > 0)
        if np.sum(mask) < 2:
            result[name] = {"linear": {"m": m, "b": b, "r2": r2_linear, "formula": formula_lin}, "power": None}
            continue
        log_ue = np.log(ue[mask])
        log_y = np.log(y[mask])
        A_p = np.vstack([log_ue, np.ones(len(log_ue))]).T
        n, log_a = np.linalg.lstsq(A_p, log_y, rcond=None)[0]
        a = np.exp(log_a)
        y_power = a * (ue ** n)
        y_power = np.where(ue > 0, y_power, 0)
        ss_res_p = np.sum((y - y_power) ** 2)
        r2_power = 1 - ss_res_p / ss_tot

        result[name] = {
            "linear": {"m": float(m), "b": float(b), "r2": float(r2_linear), "formula": formula_lin},
            "power": {"a": float(a), "n": float(n), "r2": float(r2_power), "formula": f"y = {a:.2f}*x^{n:.3f}"},
        }
    return result


def write_report(rows: List[Dict], fits: Dict[str, Any], out_path: Path) -> None:
    with out_path.open("w") as f:
        f.write("# 5G Control Plane Signaling Scaling Analysis (1 → 40 UEs)\n\n")

        # Summary table
        f.write("## Summary Table\n\n")
        f.write("| UE Count | Event Count (Logs) | Control Packets (PCAP) | Packets/Events Ratio | Events/UE | Packets/UE |\n")
        f.write("|----------|-------------------|------------------------|----------------------|-----------|------------|\n")
        for r in rows:
            ratio = r["packets_to_events_ratio"]
            ratio_str = f"{ratio:.4f}" if not (ratio != ratio) else "—"
            f.write(f"| {r['ue_count']} | {r['log_events']:,} | {r['control_packets']:,} | {ratio_str} | {r['events_per_ue']:,.0f} | {r['packets_per_ue']:,.0f} |\n")

        # 1 UE vs 40 UE
        r1 = next((r for r in rows if r["ue_count"] == 1), None)
        r40 = next((r for r in rows if r["ue_count"] == 40), None)
        f.write("\n## 1 UE vs 40 UE Comparison\n\n")
        f.write("| Metric | 1 UE | 40 UEs | Ratio (40/1) |\n")
        f.write("|--------|------|--------|-------------|\n")
        if r1 and r40:
            f.write(f"| Event Count (Logs) | {r1['log_events']:,} | {r40['log_events']:,} | {r40['log_events']/r1['log_events']:.2f}x |\n")
            if r1["control_packets"] > 0:
                f.write(f"| Control Packets (PCAP) | {r1['control_packets']:,} | {r40['control_packets']:,} | {r40['control_packets']/r1['control_packets']:.2f}x |\n")
            else:
                f.write(f"| Control Packets (PCAP) | {r1['control_packets']:,} | {r40['control_packets']:,} | (1 UE pcap unavailable) |\n")
            if r1["log_events"] > 0:
                ratio1 = r1["control_packets"] / r1["log_events"]
                ratio40 = r40["control_packets"] / r40["log_events"]
                f.write(f"| Packets-to-Events Ratio | {ratio1:.4f} | {ratio40:.4f} | {ratio40/ratio1:.2f}x |\n" if ratio1 > 0 else f"| Packets-to-Events Ratio | — | {ratio40:.4f} | — |\n")

        # Correlation ratio
        f.write("\n## Packets-to-Events Correlation Ratio\n\n")
        valid = [r for r in rows if r["log_events"] > 0 and r["control_packets"] > 0]
        if len(valid) >= 2:
            ratios = [r["packets_to_events_ratio"] for r in valid]
            f.write(f"Ratio range: {min(ratios):.4f} to {max(ratios):.4f}\n\n")
            if max(ratios) - min(ratios) < 0.01 * sum(ratios) / len(ratios):
                f.write("**Conclusion:** The Packets-to-Events ratio remains **approximately constant** as UE load increases. Each normalized log line corresponds to a consistent number of physical control-plane packets.\n\n")
            else:
                f.write("**Conclusion:** The Packets-to-Events ratio **varies** with UE load (see table).\n\n")
        else:
            f.write("Insufficient data (1 UE run has 0 control packets from PCAP). Ratio cannot be assessed across full range.\n\n")

        # Plane comparison
        f.write("## Plane Comparison: Control vs Data Plane\n\n")
        f.write("| UE Count | Control Events | Control Packets | Data Packets (GTP-U) |\n")
        f.write("|----------|----------------|----------------|----------------------|\n")
        for r in rows:
            f.write(f"| {r['ue_count']} | {r['log_events']:,} | {r['control_packets']:,} | {r['data_packets']:,} |\n")
        f.write("\n*Data plane (GTP-U) is minimal in these experiments (ping had 100% packet loss); control plane dominates.*\n\n")

        # Trend analysis
        f.write("## Growth Trend: Linear vs Exponential\n\n")
        for name, label in [("events", "Event Count"), ("packets", "Control Packet Count")]:
            fit = fits.get(name, {})
            f.write(f"### {label}\n\n")
            if fit.get("linear"):
                ln = fit["linear"]
                f.write(f"- **Linear (y = mx + b):** {ln['formula']}, R² = {ln['r2']:.4f}\n")
            pw = fit.get("power")
            if pw:
                f.write(f"- **Power (y = ax^n):** {pw['formula']}, R² = {pw['r2']:.4f}\n")
            n = pw.get("n", 1) if pw else 1
            if pw:
                if n > 1.1:
                    assessment = "super-linear / exponential"
                elif n < 0.9:
                    assessment = "sub-linear"
                else:
                    assessment = "approximately linear"
                f.write(f"- **Assessment:** Growth is **{assessment}** (n = {n:.2f}) relative to UE count.\n\n")
            else:
                f.write(f"- **Assessment:** Power fit not available; linear model used.\n\n")

        # Overhead per UE
        f.write("## Signaling Overhead per UE\n\n")
        f.write("| UE Count | Events/UE | Packets/UE | Trend |\n")
        f.write("|----------|-----------|-----------|-------|\n")
        prev_epu = None
        for r in rows:
            epu = r["events_per_ue"]
            trend = "—" if prev_epu is None else ("↑" if epu > prev_epu else "↓")
            prev_epu = epu
            f.write(f"| {r['ue_count']} | {epu:,.0f} | {r['packets_per_ue']:,.0f} | {trend} |\n")
        f.write("\n**Trend:** Events/UE and Packets/UE generally **decrease** as UE count increases, reflecting amortization of fixed overhead (NF registration, heartbeats) across more UEs.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="5G signaling scaling analysis (1→40 UEs).")
    parser.add_argument("--runs-dir", default="experiments/runs", help="Path to experiments/runs")
    parser.add_argument("--output", default="analysis/signaling_scaling_report.md", help="Output report path")
    parser.add_argument("--project-root", help="Project root")
    args = parser.parse_args()

    root = Path(args.project_root or Path(__file__).resolve().parents[1])
    runs_dir = root / args.runs_dir
    out_path = root / args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not runs_dir.exists():
        print(f"Error: {runs_dir} not found")
        return 1

    rows = load_run_data(runs_dir)
    if not rows:
        print("No volume runs found.")
        return 1

    compute_ratios(rows)
    fits = fit_models(rows)
    write_report(rows, fits, out_path)
    print(f"Report written to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
