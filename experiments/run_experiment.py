#!/usr/bin/env python3
"""
Run one experiment scenario repetition and capture raw artifacts.

Includes pre/post capture health checks and environment metadata collection.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import platform
import shlex
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional


DEFAULT_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]

CRITICAL_LOG_CONTAINERS = {"amf", "smf", "ueransim"}
MIN_LOG_BYTES = 100


@dataclass
class RunningCapture:
    container: str
    local_log_path: pathlib.Path
    process: subprocess.Popen


def now_utc_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def run_cmd(command: str, cwd: pathlib.Path, check: bool = True, dry_run: bool = False) -> subprocess.CompletedProcess:
    print(f"[cmd] {command}")
    if dry_run:
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
    return subprocess.run(
        command,
        cwd=str(cwd),
        check=check,
        text=True,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def load_scenario(path: pathlib.Path) -> Dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def make_run_id(scenario_id: str, repetition: int) -> str:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{scenario_id}__r{repetition}__{stamp}"


def ensure_dirs(run_root: pathlib.Path) -> Dict[str, pathlib.Path]:
    raw = run_root / "raw"
    logs = raw / "logs"
    pcaps = raw / "pcaps"
    normalized = run_root / "normalized"
    gold = run_root / "gold"
    preds = run_root / "predictions"
    metrics = run_root / "metrics"
    for d in [run_root, raw, logs, pcaps, normalized, gold, preds, metrics]:
        d.mkdir(parents=True, exist_ok=True)
    return {
        "run_root": run_root,
        "raw": raw,
        "logs": logs,
        "pcaps": pcaps,
        "normalized": normalized,
        "gold": gold,
        "predictions": preds,
        "metrics": metrics,
    }


# ---------------------------------------------------------------------------
# Environment / version metadata (Gap 6)
# ---------------------------------------------------------------------------

def collect_environment_metadata(project_root: pathlib.Path, dry_run: bool) -> Dict:
    """Capture software versions and image digests for reproducibility."""
    env: Dict = {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "kernel": platform.release(),
    }

    cp = run_cmd("docker compose version --short 2>/dev/null || docker-compose version --short 2>/dev/null || echo unknown",
                 cwd=project_root, check=False, dry_run=dry_run)
    env["docker_compose_version"] = cp.stdout.strip()

    cp = run_cmd("docker version --format '{{.Server.Version}}' 2>/dev/null || echo unknown",
                 cwd=project_root, check=False, dry_run=dry_run)
    env["docker_version"] = cp.stdout.strip()

    cp = run_cmd("uname -r", cwd=project_root, check=False, dry_run=dry_run)
    env["kernel_version"] = cp.stdout.strip()

    cp = run_cmd(
        "docker image ls --format '{{.Repository}}:{{.Tag}} {{.Digest}}' | grep -E 'free5gc|ueransim' || true",
        cwd=project_root, check=False, dry_run=dry_run,
    )
    env["image_digests"] = cp.stdout.strip().splitlines() if cp.stdout.strip() else []

    cp = run_cmd("lsmod | grep '^gtp5g' || echo 'gtp5g not loaded'",
                 cwd=project_root, check=False, dry_run=dry_run)
    env["gtp5g_module"] = cp.stdout.strip()

    cp = run_cmd("git rev-parse HEAD 2>/dev/null || echo no-git",
                 cwd=project_root, check=False, dry_run=dry_run)
    env["git_commit"] = cp.stdout.strip()

    return env


# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------

def preflight(project_root: pathlib.Path, dry_run: bool) -> Dict[str, str]:
    checks = {}
    cp = run_cmd("docker compose ps --format json", cwd=project_root, check=False, dry_run=dry_run)
    checks["docker_compose_ps_rc"] = str(cp.returncode)
    checks["docker_compose_ps_stdout"] = cp.stdout[:3000]
    checks["docker_compose_ps_stderr"] = cp.stderr[:3000]
    return checks


# ---------------------------------------------------------------------------
# Pre-capture health check: verify tcpdump is available (Gap 3)
# ---------------------------------------------------------------------------

def check_tcpdump_available(pcap_targets: List[Dict], project_root: pathlib.Path, dry_run: bool) -> Dict:
    """Verify tcpdump is installed in containers that need pcap capture."""
    result = {"checked": [], "all_ok": True}
    if dry_run:
        return result
    seen = set()
    for target in pcap_targets:
        container = target["container"]
        if container in seen:
            continue
        seen.add(container)
        cp = run_cmd(
            f"docker exec {shlex.quote(container)} which tcpdump",
            cwd=project_root, check=False, dry_run=False,
        )
        if cp.returncode != 0:
            print(f"[warn] tcpdump not found in {container}, attempting install...")
            run_cmd(
                f"docker exec {shlex.quote(container)} bash -c 'apt-get update -qq && apt-get install -y -qq tcpdump' 2>/dev/null || true",
                cwd=project_root, check=False, dry_run=False,
            )
            cp2 = run_cmd(
                f"docker exec {shlex.quote(container)} which tcpdump",
                cwd=project_root, check=False, dry_run=False,
            )
            ok = cp2.returncode == 0
            result["checked"].append({"container": container, "status": "installed" if ok else "missing"})
            if not ok:
                result["all_ok"] = False
        else:
            result["checked"].append({"container": container, "status": "present"})
    return result


# ---------------------------------------------------------------------------
# Log and pcap capture
# ---------------------------------------------------------------------------

def start_log_captures(
    containers: List[str],
    logs_dir: pathlib.Path,
    project_root: pathlib.Path,
    dry_run: bool,
) -> List[RunningCapture]:
    running: List[RunningCapture] = []
    for container in containers:
        out_path = logs_dir / f"{container}.log"
        command = f"docker logs -f {shlex.quote(container)}"
        print(f"[capture][logs] {command} -> {out_path}")
        if dry_run:
            continue
        f = out_path.open("w", encoding="utf-8")
        proc = subprocess.Popen(
            command,
            cwd=str(project_root),
            shell=True,
            stdout=f,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
        )
        running.append(RunningCapture(container=container, local_log_path=out_path, process=proc))
    return running


def stop_log_captures(captures: List[RunningCapture], dry_run: bool) -> None:
    for capture in captures:
        if dry_run:
            continue
        try:
            os.killpg(os.getpgid(capture.process.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass


def start_pcap_captures(
    pcap_targets: List[Dict],
    project_root: pathlib.Path,
    dry_run: bool,
) -> List[Dict]:
    started: List[Dict] = []
    for idx, target in enumerate(pcap_targets):
        container = target["container"]
        iface = target["interface"]
        pkt_filter = target.get("filter", "")
        remote = f"/tmp/netsam_run_{idx}.pcap"
        command = (
            f"docker exec {shlex.quote(container)} bash -lc "
            f"\"tcpdump -i {shlex.quote(iface)} -w {remote} {pkt_filter} -Z root >/tmp/tcpdump_run.log 2>&1 &\""
        )
        run_cmd(command, cwd=project_root, check=False, dry_run=dry_run)
        started.append({"container": container, "remote_path": remote, "target_index": idx})
    return started


def stop_and_collect_pcaps(
    started_pcaps: List[Dict],
    pcaps_dir: pathlib.Path,
    project_root: pathlib.Path,
    dry_run: bool,
) -> List[str]:
    local_paths: List[str] = []
    for target in started_pcaps:
        container = target["container"]
        remote = target["remote_path"]
        idx = target["target_index"]
        local = pcaps_dir / f"{container}_{idx}.pcap"
        run_cmd(
            f"docker exec {shlex.quote(container)} killall tcpdump || true",
            cwd=project_root, check=False, dry_run=dry_run,
        )
        time.sleep(1) if not dry_run else None
        run_cmd(
            f"docker cp {shlex.quote(container)}:{shlex.quote(remote)} {shlex.quote(str(local))} || true",
            cwd=project_root, check=False, dry_run=dry_run,
        )
        local_paths.append(str(local))
    return local_paths


# ---------------------------------------------------------------------------
# Post-capture health check (Gap 3)
# ---------------------------------------------------------------------------

def verify_capture_health(
    logs_dir: pathlib.Path,
    pcaps_dir: pathlib.Path,
    expected_log_containers: List[str],
    dry_run: bool,
) -> Dict:
    """Check that captured artifacts are non-empty. Returns health report."""
    health: Dict = {"logs": {}, "pcaps": {}, "critical_missing": [], "status": "ok"}

    if dry_run:
        return health

    for container in expected_log_containers:
        log_path = logs_dir / f"{container}.log"
        if not log_path.exists():
            health["logs"][container] = {"status": "missing", "bytes": 0}
            if container in CRITICAL_LOG_CONTAINERS:
                health["critical_missing"].append(f"log:{container}")
        else:
            size = log_path.stat().st_size
            ok = size >= MIN_LOG_BYTES
            health["logs"][container] = {
                "status": "ok" if ok else "too_small",
                "bytes": size,
            }
            if not ok and container in CRITICAL_LOG_CONTAINERS:
                health["critical_missing"].append(f"log:{container}")

    for pcap_path in pcaps_dir.glob("*.pcap"):
        size = pcap_path.stat().st_size
        health["pcaps"][pcap_path.name] = {
            "status": "ok" if size > 0 else "empty",
            "bytes": size,
        }

    if health["critical_missing"]:
        health["status"] = "capture_failed"

    return health


# ---------------------------------------------------------------------------
# Action execution
# ---------------------------------------------------------------------------

def execute_actions(actions: List[Dict], project_root: pathlib.Path, duration_seconds: int, dry_run: bool) -> List[Dict]:
    timeline = sorted(actions, key=lambda a: int(a.get("at_second", 0)))
    action_log: List[Dict] = []
    if dry_run:
        for action in timeline:
            command = action["command"]
            cp = run_cmd(command, cwd=project_root, check=False, dry_run=True)
            action_log.append(
                {
                    "at_second": int(action.get("at_second", 0)),
                    "scheduled_second": int(action.get("at_second", 0)),
                    "command": command,
                    "returncode": cp.returncode,
                    "stdout": cp.stdout[-1000:],
                    "stderr": cp.stderr[-1000:],
                }
            )
        return action_log

    start = time.time()
    next_idx = 0

    while True:
        elapsed = int(time.time() - start)
        if elapsed >= duration_seconds:
            break
        while next_idx < len(timeline) and elapsed >= int(timeline[next_idx]["at_second"]):
            command = timeline[next_idx]["command"]
            cp = run_cmd(command, cwd=project_root, check=False, dry_run=dry_run)
            action_log.append(
                {
                    "at_second": elapsed,
                    "scheduled_second": int(timeline[next_idx]["at_second"]),
                    "command": command,
                    "returncode": cp.returncode,
                    "stdout": cp.stdout[-1000:],
                    "stderr": cp.stderr[-1000:],
                }
            )
            next_idx += 1
        time.sleep(1)
    return action_log


def write_json(path: pathlib.Path, payload: Dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one NetSAM necessity scenario repetition.")
    parser.add_argument("--scenario", required=True, help="Path to scenario JSON.")
    parser.add_argument("--repetition", type=int, required=True, help="Repetition index (1..N).")
    parser.add_argument("--project-root", default=str(DEFAULT_PROJECT_ROOT), help="free5gc-compose root path.")
    parser.add_argument("--dry-run", action="store_true", help="Do not execute docker/host actions.")
    args = parser.parse_args()

    project_root = pathlib.Path(args.project_root).resolve()
    scenario_path = pathlib.Path(args.scenario).resolve()
    if not scenario_path.exists():
        print(f"Scenario not found: {scenario_path}", file=sys.stderr)
        return 2

    scenario = load_scenario(scenario_path)
    run_id = make_run_id(scenario["scenario_id"], args.repetition)
    run_root = project_root / "experiments" / "runs" / run_id
    dirs = ensure_dirs(run_root)

    print(f"[run] run_id={run_id}")
    print(f"[run] scenario={scenario['scenario_id']} dry_run={args.dry_run}")

    # Collect environment metadata
    environment = collect_environment_metadata(project_root=project_root, dry_run=args.dry_run)
    preflight_result = preflight(project_root=project_root, dry_run=args.dry_run)

    # Pre-capture: verify tcpdump availability
    pcap_targets = scenario.get("capture", {}).get("pcap_targets", [])
    tcpdump_check = check_tcpdump_available(pcap_targets, project_root, args.dry_run)
    if not tcpdump_check["all_ok"] and not args.dry_run:
        print("[WARN] tcpdump missing in some containers; pcap capture may fail")

    started_at = now_utc_iso()

    log_containers = scenario.get("capture", {}).get("containers_for_logs", [])
    log_captures = start_log_captures(
        containers=log_containers,
        logs_dir=dirs["logs"],
        project_root=project_root,
        dry_run=args.dry_run,
    )
    pcap_captures = start_pcap_captures(
        pcap_targets=pcap_targets,
        project_root=project_root,
        dry_run=args.dry_run,
    )

    action_log: List[Dict] = []
    local_pcaps: List[str] = []
    status = "success"
    error: Optional[str] = None

    try:
        action_log = execute_actions(
            actions=scenario.get("actions", []),
            project_root=project_root,
            duration_seconds=int(scenario["duration_seconds"]),
            dry_run=args.dry_run,
        )
    except Exception as exc:
        status = "failed"
        error = str(exc)
    finally:
        stop_log_captures(log_captures, dry_run=args.dry_run)
        local_pcaps = stop_and_collect_pcaps(
            started_pcaps=pcap_captures,
            pcaps_dir=dirs["pcaps"],
            project_root=project_root,
            dry_run=args.dry_run,
        )

    # Post-capture: verify artifact integrity
    capture_health = verify_capture_health(
        logs_dir=dirs["logs"],
        pcaps_dir=dirs["pcaps"],
        expected_log_containers=log_containers,
        dry_run=args.dry_run,
    )
    if capture_health["status"] == "capture_failed":
        status = "capture_failed"
        print(f"[FAIL] Critical captures missing: {capture_health['critical_missing']}")

    ended_at = now_utc_iso()
    metadata = {
        "run_id": run_id,
        "scenario_path": str(scenario_path),
        "scenario": scenario,
        "status": status,
        "error": error,
        "started_at": started_at,
        "ended_at": ended_at,
        "environment": environment,
        "preflight": preflight_result,
        "tcpdump_check": tcpdump_check,
        "capture_health": capture_health,
        "captured_pcaps": local_pcaps,
        "actions_executed": action_log,
        "notes": "Use normalize_events.py then baselines.py then analysis/evaluate.py.",
    }
    write_json(dirs["run_root"] / "run_metadata.json", metadata)
    print(f"[run] metadata written to {dirs['run_root'] / 'run_metadata.json'}")
    print(f"[run] status={status}")
    return 0 if status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
