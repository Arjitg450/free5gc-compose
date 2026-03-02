# 5G Control Plane Overhead Analysis Report

Analysis of how control signaling overhead scales with the number of UEs in the 5G control plane.

## Key Findings

### How much does control signaling overhead increase with UE count?

- **Log volume**: Increases from 26.93 MB (1 UE) to 34.40 MB (40 UEs) — **1.28x** at 40 UEs vs 1 UE baseline.
- **Control-plane events**: Increase from 27,947 to 63,884 — **2.29x** at 40 UEs (sub-linear in per-UE terms).
- **Marginal cost per UE**: Decreases as UE count grows — from ~26 MB/UE (1 UE) to ~840 KB/UE (40 UEs). This reflects shared overhead (NF registration, heartbeats, etc.) amortized across more UEs.

### Which NF contributes most to control-plane overhead?

| Rank | NF     | Share at 40 UEs |
|------|--------|-----------------|
| 1    | **UPF** | **40.6%**       |
| 2    | **SMF** | **29.6%**       |
| 3    | NRF    | 13.4%           |
| 4    | AMF    | 10.1%           |
| 5    | UDM    | 3.2%            |
| 6    | AUSF   | 1.6%            |
| 7    | UDR    | 1.4%            |
| 8    | UERANSIM | 0.1%          |

**UPF and SMF together account for ~70%** of log volume, driven by PFCP session reports, charging heartbeats, and periodic usage reporting.

### Scaling trend

- Event count scales **near-linearly** with UE count (R² typically > 0.95).
- Log volume scales **sub-linearly** due to fixed overhead (NRF, PFCP association, etc.) dominating at low UE counts.

---

## Summary Table

| UE count | Log volume | Pcap volume | Control events | Log/UE (KB) | Events/UE |
|---------|------------|-------------|----------------|-------------|----------|
| 1 | 26.93 MB | 485.10 KB | 27,947 | 26300.1 | 27947 |
| 10 | 28.08 MB | 2.17 MB | 33,335 | 2742.0 | 3334 |
| 20 | 29.34 MB | 2.31 MB | 38,299 | 1432.8 | 1915 |
| 30 | 31.62 MB | 3.70 MB | 50,058 | 1029.3 | 1669 |
| 40 | 34.40 MB | 4.27 MB | 63,884 | 839.8 | 1597 |

## Scaling vs Baseline (1 UE)

- **10 UEs**: Log volume 1.04x baseline, Events 1.19x baseline
- **20 UEs**: Log volume 1.09x baseline, Events 1.37x baseline
- **30 UEs**: Log volume 1.17x baseline, Events 1.79x baseline
- **40 UEs**: Log volume 1.28x baseline, Events 2.29x baseline

## Top NF Contributors (at max UE count)

- **UPF**: 13.95 MB (40.6%)
- **SMF**: 10.18 MB (29.6%)
- **NRF**: 4.60 MB (13.4%)
- **AMF**: 3.48 MB (10.1%)
- **UDM**: 1.10 MB (3.2%)
- **AUSF**: 554.31 KB (1.6%)
- **UDR**: 483.12 KB (1.4%)
- **UERANSIM**: 38.44 KB (0.1%)

## Plots Generated

- `01_total_overhead_vs_ue.png`
- `02_marginal_overhead_per_ue.png`
- `03_nf_log_bytes_stacked.png`
- `04_nf_contribution_pie.png`
- `05_nf_events_contribution.png`
- `06_procedure_breakdown.png`
- `07_scaling_trend.png`
- `08_pcap_breakdown.png`
