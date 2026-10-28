# MallByte — Redis Emergency Runbook (Manual Only)

**Redis is the broker for Celery** and may also hold cache/session/retry state. A wrong restart can interrupt queued jobs, discard transient data and create duplicate financial/order side effects. For this reason Redis is intentionally **not** part of the automatic host runner.

## Before any restart

1. Confirm a genuine problem: Redis ping/health, container logs, resource pressure, connection errors, current alerts.
2. Identify the Redis use cases and persistence mode (`redis.conf`, AOF/RDB), available backups and recovery point; do not assume all queues survive restart.
3. Inspect Celery `active`, `reserved`, `scheduled` and stalled tasks (and avoid re-running non-idempotent settlement/payment tasks).
4. If production: announce maintenance, obtain approval/change ticket, freeze sensitive financial operations, and plan recovery/rollback.
5. Consider the safer remediation first (network/DNS/connection settings, client reconnect, resource constraints) rather than restart.

## Last resort on the trusted Docker host

Only after verifying the above and following team change control:

```bash
cd ~/projects/mallbyte-api
docker compose -f compose.yaml -f compose.dev.yaml ps redis
docker compose -f compose.yaml -f compose.dev.yaml logs --tail=100 redis
# DANGEROUS, MANUAL ONLY, AFTER EXPLICIT HUMAN CHANGE APPROVAL:
docker compose -f compose.yaml -f compose.dev.yaml restart redis
```

There is no `--force`, data-volume deletion or `docker compose down -v` in this runbook. Redis data deletion is not part of normal recovery.

## Afterward

1. Verify Redis ping and both Celery Worker and Beat broker connectivity.
2. Check queued and failed tasks; verify no duplicate settlements/refunds/orders were processed.
3. Generate a new Observability health snapshot and verify error rates.
4. Document incident timeline, impact, cause, exact action and owner.

Do **not** turn the Redis restart into a single-click admin operation merely for convenience. In a future production setup use a proper orchestrator/HA Redis deployment with tested failover, data backup and operational policies.
