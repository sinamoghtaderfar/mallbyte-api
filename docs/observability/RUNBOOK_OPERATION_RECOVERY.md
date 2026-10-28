# Approved Celery restart — recovery and verification runbook

`systemd --user` starts the host runner; the runner does not execute Redis restarts. The Django bridge does not get Docker access. Two distinct real users are required for request and approval.

## Routine validation (safe; no restart)

```bash
systemctl --user status mallbyte-observability-ops.timer --no-pager
systemctl --user status mallbyte-observability-ops.service --no-pager
journalctl --user -u mallbyte-observability-ops.service -n 60 --no-pager
python3 deploy/observability_ops/host_runner.py --dry-run
```

The timer being `active (waiting)` and its one-shot service being `inactive (dead)` with `0/SUCCESS` is expected. Dry-run only lists *eligible* approvals.

## Real restart (staging/development only, during maintenance window)
1. Verify no live financial reconciliation or other sensitive Celery task is in progress.
2. Operator creates a narrowly scoped request for `celery_worker` or `celery_beat`; include reason.
3. A separate `observability_admin` reviews and approves it. The same account may not self-approve.
4. Host runner automatically picks up the approved request through timer; **never** mount `/var/run/docker.sock` in the web or worker container.
5. Inspect operation status and timestamps. `succeeded` only means Compose reported success and container running, not that application health is guaranteed.
6. Check Redis/PostgreSQL/Celery health and queue activity again. Audit the whole timeline.

## Stale `running` operation: manual recovery ONLY

If `running` remains after an interrupted host runner, **do not simply reissue a restart**. On the Docker host, first verify no runner is active, no Compose restart is in progress, service is healthy or identify the actual condition, and gather logs:

```bash
systemctl --user status mallbyte-observability-ops.service --no-pager
journalctl --user -u mallbyte-observability-ops.service -n 100 --no-pager
docker compose -f compose.yaml -f compose.dev.yaml --profile celery ps
```

Then inspect the stale operation (no write):

```bash
docker compose -f compose.yaml -f compose.dev.yaml exec web \
  python manage.py observability_ops_reconcile --operation-id UUID_HERE
```

If it has been `running` for **at least 10 minutes** and you independently established there is no active host restart, explicitly mark it failed:

```bash
docker compose -f compose.yaml -f compose.dev.yaml exec web \
  python manage.py observability_ops_reconcile --operation-id UUID_HERE \
  --confirm-failed --reason "Verified that no host runner is active and inspected current container health"
```

This writes an Audit Log, clears its one-time token, and does **not** execute or retry any restart. It cannot change recent or already completed operations.

## Timer unit timeout
V3 sets `TimeoutStartSec=300` (seconds) because Compose restart + container checks can exceed systemd's default startup timeout. After applying v3, re-run:

```bash
python3 deploy/observability_ops/install_timer.py --install
systemctl --user cat mallbyte-observability-ops.service
```

Only reconfigure the timer after validating the deployment scripts. It keeps a user-scoped service; permanent unattended production operations require a dedicated host account, least-privilege host policy, and approval architecture review.

Redis must be handled manually according to `RUNBOOK_REDIS.md`; it is never in the runner's hardcoded allowlist.
