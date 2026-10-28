#!/usr/bin/env python3
"""HOST-ONLY runner. No Django, database password or Docker socket inside web/Celery.

One invocation processes at most one approved, independently authorized operation.
Run via a dedicated systemd --user timer. Never add this script to web startup.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

SAFE_TARGETS = frozenset({"celery_worker", "celery_beat"})
ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ["docker", "compose", "-f", "compose.yaml", "-f", "compose.dev.yaml", "--profile", "celery"]
BRIDGE = [*COMPOSE, "exec", "-T", "web", "python", "manage.py", "observability_ops_bridge"]
LOCK_DIR = Path.home() / ".cache" / "mallbyte"
LOCK = LOCK_DIR / "observability-host-runner.lock"


def call(command, *, timeout=60, input=None):
    return subprocess.run(command, cwd=str(ROOT), input=input, capture_output=True,
                          text=True, timeout=timeout, check=False)


def bridge(*args, input=None):
    response = call([*BRIDGE, *args], timeout=45, input=input)
    if response.returncode:
        raise RuntimeError("Database bridge failed (check Django container logs and permissions)")
    try:
        return json.loads(response.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Database bridge produced an unexpected response") from exc


def main():
    parser = argparse.ArgumentParser(description="Poll and execute one independently approved Celery restart")
    parser.add_argument("--dry-run", action="store_true", help="Read eligible operations; make no changes")
    args = parser.parse_args()
    if Path('/.dockerenv').exists():
        raise SystemExit("Refusing to run in a Docker container. Use the trusted Docker HOST only.")
    if not shutil.which('docker') or not (ROOT/'manage.py').is_file():
        raise SystemExit("Requires Docker Compose and repo-root manage.py on the host")
    if args.dry_run:
        jobs = bridge("peek")
        print("Eligible approvals:", jobs.get("pending", []))
        return
    # Only one runner on this host; DB row-lock prevents duplicate claim across hosts.
    LOCK_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    with LOCK.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Runner already active; exiting")
            return
        claim = bridge("claim")
        item = claim.get("operation")
        if not item:
            print("No approved Celery restart requests")
            return
        op_id = item["id"]
        target = item["target"]
        token = claim.get("token", "")
        outcome = "failed"
        message = "Runner did not complete"
        try:
            if target not in SAFE_TARGETS:
                raise RuntimeError("Target blocked by independent host allowlist")
            # Don't implicitly START or CREATE services. Only restart already running containers.
            ps = call([*COMPOSE, "ps", "-q", target], timeout=25)
            ids = ps.stdout.strip().splitlines() if ps.returncode == 0 else []
            if len(ids) != 1:
                message = "Target is not a single running service; restart refused"
            else:
                inspect = call(["docker", "inspect", "-f", "{{.State.Running}}", ids[0]], timeout=20)
                if inspect.returncode or inspect.stdout.strip() != "true":
                    message = "Target container is not running; restart refused"
                else:
                    result = call([*COMPOSE, "restart", target], timeout=150)
                    if result.returncode:
                        message = f"Docker Compose restart exited {result.returncode}"
                    else:
                        verify = call(["docker", "inspect", "-f", "{{.State.Running}}", ids[0]], timeout=20)
                        if verify.returncode == 0 and verify.stdout.strip() == "true":
                            outcome, message = "succeeded", "Restart returned success; container running (check service health)"
                        else:
                            # Compose may have replaced the container ID; re-query once.
                            after = call([*COMPOSE, "ps", "-q", target], timeout=25)
                            if after.returncode == 0 and after.stdout.strip():
                                state = call(["docker", "inspect", "-f", "{{.State.Running}}", after.stdout.strip().splitlines()[0]], timeout=20)
                                if state.returncode == 0 and state.stdout.strip() == "true":
                                    outcome, message = "succeeded", "Restart returned success; container running (check service health)"
                                else:
                                    message = "Post-restart health check failed"
                            else:
                                message = "Post-restart container not found"
        except (RuntimeError, OSError, subprocess.TimeoutExpired):
            message = "Runner could not execute or verify restart"
        # Pass ephemeral token via stdin, not process command-line arguments.
        try:
            report = bridge("complete", "--operation-id", op_id, "--outcome", outcome,
                            "--message", message, "--token-stdin", input=token + "\n")
        except Exception:
            print("CRITICAL: DB completion failed; manually reconcile operation", op_id, file=sys.stderr)
            raise
        print(f"Operation {op_id}: {report['status']}: {message}")
        if outcome != "succeeded":
            raise SystemExit(1)


if __name__ == '__main__':
    main()
