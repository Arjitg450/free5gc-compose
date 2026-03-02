# 5G Control Plane Signaling Scaling Analysis (1 → 40 UEs)

## Summary Table

| UE Count | Event Count (Logs) | Control Packets (PCAP) | Packets/Events Ratio | Events/UE | Packets/UE |
|----------|-------------------|------------------------|----------------------|-----------|------------|
| 1 | 27,947 | 0 | 0.0000 | 27,947 | 0 |
| 10 | 32,441 | 893 | 0.0275 | 3,244 | 89 |
| 20 | 37,384 | 914 | 0.0244 | 1,869 | 46 |
| 30 | 48,232 | 1,825 | 0.0378 | 1,608 | 61 |
| 40 | 61,763 | 2,120 | 0.0343 | 1,544 | 53 |

## 1 UE vs 40 UE Comparison

| Metric | 1 UE | 40 UEs | Ratio (40/1) |
|--------|------|--------|-------------|
| Event Count (Logs) | 27,947 | 61,763 | 2.21x |
| Control Packets (PCAP) | 0 | 2,120 | (1 UE pcap unavailable) |
| Packets-to-Events Ratio | — | 0.0343 | — |

## Packets-to-Events Correlation Ratio

Ratio range: 0.0244 to 0.0378

**Conclusion:** The Packets-to-Events ratio **varies** with UE load (see table).

## Plane Comparison: Control vs Data Plane

| UE Count | Control Events | Control Packets | Data Packets (GTP-U) |
|----------|----------------|----------------|----------------------|
| 1 | 27,947 | 0 | 0 |
| 10 | 32,441 | 893 | 1 |
| 20 | 37,384 | 914 | 1 |
| 30 | 48,232 | 1,825 | 1 |
| 40 | 61,763 | 2,120 | 1 |

*Data plane (GTP-U) is minimal in these experiments (ping had 100% packet loss); control plane dominates.*

## Growth Trend: Linear vs Exponential

### Event Count

- **Linear (y = mx + b):** y = 854.1x + 24300, R² = 0.9490
- **Power (y = ax^n):** y = 25444.47*x^0.181, R² = 0.6846
- **Assessment:** Growth is **sub-linear** (n = 0.18) relative to UE count.

### Control Packet Count

- **Linear (y = mx + b):** y = 52.6x + 87, R² = 0.9369
- **Power (y = ax^n):** y = 167.26*x^0.670, R² = 0.9277
- **Assessment:** Growth is **sub-linear** (n = 0.67) relative to UE count.

## Signaling Overhead per UE

| UE Count | Events/UE | Packets/UE | Trend |
|----------|-----------|-----------|-------|
| 1 | 27,947 | 0 | — |
| 10 | 3,244 | 89 | ↓ |
| 20 | 1,869 | 46 | ↓ |
| 30 | 1,608 | 61 | ↓ |
| 40 | 1,544 | 53 | ↓ |

**Trend:** Events/UE and Packets/UE generally **decrease** as UE count increases, reflecting amortization of fixed overhead (NF registration, heartbeats) across more UEs.
