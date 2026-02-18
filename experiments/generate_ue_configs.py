#!/usr/bin/env python3
"""
Generate per-UE or per-group UERANSIM config files from a subscriber manifest.

Single-container mode: generates one config with the base SUPI; UERANSIM's
-n flag auto-increments from there.

Multi-container mode (>30 UEs): generates per-group configs, each with a
different starting SUPI for use with separate nr-ue processes/containers.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
from typing import Dict, List


def load_manifest(path: pathlib.Path) -> Dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_base_config(path: pathlib.Path) -> str:
    with path.open("r", encoding="utf-8") as f:
        return f.read()


def replace_supi(config_text: str, new_supi: str) -> str:
    """Replace the supi line in a UERANSIM YAML config."""
    return re.sub(
        r'^supi:\s*"imsi-\d+"',
        f'supi: "{new_supi}"',
        config_text,
        count=1,
        flags=re.MULTILINE,
    )


def generate_single_container(
    base_config: str, base_imsi: int, out_dir: pathlib.Path
) -> List[Dict]:
    """Generate one config for use with `nr-ue -n N`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    supi = f"imsi-{base_imsi}"
    config = replace_supi(base_config, supi)
    path = out_dir / "uecfg_all.yaml"
    path.write_text(config, encoding="utf-8")
    return [{"config_file": str(path), "start_supi": supi, "mode": "single"}]


def generate_multi_container(
    base_config: str,
    base_imsi: int,
    total_ues: int,
    group_size: int,
    out_dir: pathlib.Path,
) -> List[Dict]:
    """Generate per-group configs, each with a different starting SUPI."""
    out_dir.mkdir(parents=True, exist_ok=True)
    groups: List[Dict] = []
    offset = 0
    group_idx = 1
    while offset < total_ues:
        n = min(group_size, total_ues - offset)
        supi = f"imsi-{base_imsi + offset}"
        config = replace_supi(base_config, supi)
        path = out_dir / f"ue-group-{group_idx}.yaml"
        path.write_text(config, encoding="utf-8")
        groups.append({
            "config_file": str(path),
            "start_supi": supi,
            "ue_count": n,
            "group_index": group_idx,
            "mode": "multi",
        })
        offset += n
        group_idx += 1
    return groups


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate UERANSIM UE config files.")
    parser.add_argument(
        "--manifest",
        default="experiments/subscribers.json",
        help="Path to subscriber manifest from provision_subscribers.py.",
    )
    parser.add_argument(
        "--base-config",
        default="config/uecfg.yaml",
        help="Path to base UERANSIM UE config.",
    )
    parser.add_argument(
        "--output-dir",
        default="experiments/ue_configs",
        help="Directory to write generated configs.",
    )
    parser.add_argument(
        "--group-size",
        type=int,
        default=10,
        help="UEs per group in multi-container mode.",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=30,
        help="Switch to multi-container mode above this UE count.",
    )
    args = parser.parse_args()

    manifest = load_manifest(pathlib.Path(args.manifest))
    base_config = load_base_config(pathlib.Path(args.base_config))
    out_dir = pathlib.Path(args.output_dir)
    total_ues = manifest["count"]
    base_imsi = manifest["base_imsi"]

    if total_ues <= args.threshold:
        groups = generate_single_container(base_config, base_imsi, out_dir)
        print(f"Single-container mode: wrote 1 config for {total_ues} UEs")
    else:
        groups = generate_multi_container(
            base_config, base_imsi, total_ues, args.group_size, out_dir
        )
        print(f"Multi-container mode: wrote {len(groups)} group configs ({args.group_size} UEs each)")

    summary = {"total_ues": total_ues, "groups": groups}
    summary_path = out_dir / "ue_config_summary.json"
    out_dir.mkdir(parents=True, exist_ok=True)
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"Summary written to {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
