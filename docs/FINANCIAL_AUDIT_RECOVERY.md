# Recoverable financial audit jobs

Audit jobs only inspect reconciliation state and write audit metadata; they never
capture, settle or refund money. Migration `settlements.0003` adds attempt counts,
the input sample limit and an execution lease with a fencing token. An expired
worker cannot overwrite the result produced by its replacement.

Run `install_financial_audit_schedule` after deploying migrations to install both
the daily audit and five-minute recovery schedule. Re-running it is idempotent;
`--disable` disables both schedules. Run one Celery Beat scheduler and workers
that import `apps.settlements.tasks`.

Failed and abandoned runs reuse their original key and inputs. The default lease
is 1800 seconds (`FINANCIAL_AUDIT_LEASE_SECONDS`, minimum 60). Transient failures
retry with bounded backoff; at most four executions are allowed by default
(`FINANCIAL_AUDIT_MAX_ATTEMPTS`). Daily retries retain the original daily key even
when a retry happens after midnight. Recovery dispatch is bounded to 50 runs per
tick, and the database claim makes duplicate deliveries harmless.

Inspect failed/exhausted audit runs through the existing authorized monitoring
API. After investigating a permanent failure, an authorized operator can request
a new manual audit; exhausted historical runs remain immutable audit evidence.
Choose a lease longer than the measured worst-case reconciliation duration to
avoid redundant expensive work. Validate broker/worker/Beat recovery in staging;
unit tests use an isolated broker and database, without production data.
