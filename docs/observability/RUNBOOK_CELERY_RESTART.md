# MallByte — Controlled Celery Restarts Runbook

## Why a separate control plane

The Django web process can request/approve an operation, but **cannot** call Docker, spawn a shell, mount `/var/run/docker.sock` or execute a restart. A separate **host-only** `deploy/observability_ops/host_runner.py` claims already approved requests from the DB, performs a hard-allowlisted Docker Compose restart and sends outcome back. Never put the host runner in a web/Celery entrypoint.

## Initial host setup (after Backend tests and migration)

```bash
cd ~/projects/mallbyte-api
python3 deploy/observability_ops/host_runner.py --dry-run
# Only after reviewing runbook and confirming Docker Compose works on the host:
python3 deploy/observability_ops/install_timer.py --install
systemctl --user status mallbyte-observability-ops.timer
systemctl --user list-timers --all | grep mallbyte-observability
```

The `systemd --user` timer checks one approved request per minute. It uses the current host user's Docker permissions: membership in the Docker group is effectively privileged. Run it only on your trusted host, under an operationally managed account. Host user managers may stop after logout; for dedicated unattended environments, deliberately configure an appropriate service/linger policy. This template targets the repo's **dev Compose files** (`compose.yaml` and `compose.dev.yaml`), **not production Kubernetes or remote Docker contexts**.

## What can be restarted

- `celery_worker`: only an **already running** service, after different authorized operator requests and admin approves.
- `celery_beat`: same, but first make sure **exactly one Beat** process exists, otherwise tasks may dispatch twice.
- `redis`: blocked by the host runner, including if someone changes a Django setting. Use the Redis-specific runbook, and do not enable one-click Redis restart.
- The runner never starts a missing service and never accepts shell commands/paths/target names from the HTTP request.

## Live execution procedure

1. Diagnose the service: check `/api/observability/health/`, worker/Beat logs, Redis and DB health.
2. Open `/admin/observability`, create a request with a meaningful reason and choose only Worker or Beat.
3. A **different** admin account approves it before its 30-minute expiry. Self-approval is forbidden even for superusers.
4. On the host, the active timer claims it, performs one restart, checks container running state, records `succeeded` or `failed` and audits the action. Status `succeeded` means Docker restart + container running; it **does not prove tasks processed correctly**, so perform follow-up health and queue checks.
5. Check result in the UI, logs, and the new health snapshot. For a failure, investigate and resolve manually; do not repeatedly approve restarts.

## Manual host-only smoke test

```bash
cd ~/projects/mallbyte-api
python3 deploy/observability_ops/host_runner.py --dry-run
# Only after a different admin has approved a genuine operation:
python3 deploy/observability_ops/host_runner.py
```

The real runner processes **one** approved operation per invocation. Do not test live restart on an important task queue without a maintenance window.

## Shut down automation

```bash
systemctl --user disable --now mallbyte-observability-ops.timer
# Or remove its managed service/timer files:
python3 deploy/observability_ops/install_timer.py --uninstall
```

Disabling the timer does **not** revoke approved DB requests; review/cancel outstanding approvals before re-enabling. Approval expiry is enforced at claim.

## Failure handling

- If `approved` remains: check timer status and journal `journalctl --user -u mallbyte-observability-ops.service -n 80`; verify web container running and Docker permissions.
- If `failed`: check Compose service health/exit status and preserve task logs, assess whether restart caused in-flight task retries. No automatic retry of host restart.
- If `running` is stuck: the host runner may have died after claim. **Never blindly set it back to approved**; check Docker events/timestamps and audit trail, then reconcile under change control. A finished operation uses a one-time token that is never exposed over HTTP.
- Celery tasks must be idempotent where possible; Worker restart can interrupt tasks or cause redelivery. Verify financial tasks carefully before retrying anything.

## Security boundary

No Docker socket in `web` or `celery_worker`, no unrestricted user-defined Compose args, no direct restarts on GET/POST, no supervisor privilege via Django user roles. This host runner itself has high OS privilege and requires normal host change-management/audit controls.
