# NetSAM Necessity Experiments

This folder contains a reproducible, deterministic-first evaluation harness to answer:

"Are rule-based control-plane segmenters sufficient, or does NetSAM become necessary?"

## What this implementation includes

- Scenario definitions in `experiments/scenarios/*.json`.
- Run orchestrator in `experiments/run_experiment.py`.
- Log/pcap-to-event normalizer in `experiments/normalize_events.py`.
- Deterministic baselines (B1/B2/B3) in `experiments/baselines.py`.
- Evaluator/report helpers in `analysis/`.

## Folder layout

- `experiments/scenarios/`: scenario configurations (`S1` to `S6` defaults).
- `experiments/runs/<run_id>/raw/`: raw logs and pcaps captured from containers.
- `experiments/runs/<run_id>/normalized/events.jsonl`: normalized events.
- `experiments/runs/<run_id>/predictions/`: baseline outputs.
- `experiments/runs/<run_id>/metrics/`: per-baseline metric JSON.
- `analysis/reports/necessity_report.md`: consolidated decision output.

## Prerequisites

- Python 3.10+
- Docker + Docker Compose v2
- free5gc stack files from this repository
- For pcap capture in containers: `tcpdump` installed in relevant containers

## Quick start (pilot, dry-run)

Run a no-side-effect pilot that only prepares run directories and command plan:

```bash
python3 experiments/run_experiment.py \
  --scenario experiments/scenarios/S1_clean_static.json \
  --repetition 1 \
  --dry-run
```

## Quick start (real capture run)

```bash
python3 experiments/run_experiment.py \
  --scenario experiments/scenarios/S1_clean_static.json \
  --repetition 1 \
  --project-root .
```

Then normalize and run baselines:

```bash
python3 experiments/normalize_events.py --run-dir experiments/runs/<run_id>
python3 experiments/baselines.py --run-dir experiments/runs/<run_id>
```

If gold labels exist at `experiments/runs/<run_id>/gold/segments_gold.json`, compute metrics:

```bash
python3 analysis/evaluate.py --run-dir experiments/runs/<run_id>
```

Generate a consolidated report across runs:

```bash
python3 analysis/report_necessity.py --runs-root experiments/runs --output analysis/reports/necessity_report.md
```

## Baseline summary

- B1 `IDWindow`: UE identifier + temporal window matching.
- B2 `FSMConstrained`: B1 plus deterministic procedure state machine validity checks.
- B3 `RetryAwareFSM`: B2 plus retry/duplicate handling and attempt tracking.

## Important note on realism

These scripts are intentionally deterministic and transparent. The purpose is to measure where deterministic correlation fails before introducing any learned model.
