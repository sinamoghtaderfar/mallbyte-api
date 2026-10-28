# MallByte — Incident Handling Runbook

1. **Detect:** use health, latency, errors and Alerts to validate scope. Link ErrorLog/Alert UUID to a new incident when authorized.
2. **Triage:** choose severity according to real user impact, not exception appearance. Avoid credentials, customer PII and raw sensitive payloads in descriptions.
3. **Assign:** choose an active technical account with permission to view incidents. Keep the timeline current.
4. **Investigate:** check correlation IDs, sanitized logs, recent deploys, DB queries, Redis/Celery. Optional AI suggestions are advisory; verify independently.
5. **Mitigate:** use a safe fix/deploy procedure or approved infrastructure operation. No autonomous code modification from the AI panel.
6. **Verify:** check same transaction path end to end, watch error trends, test critical finance/payment invariants, write a clear resolution note.
7. **Close:** document contributing conditions, follow-ups and preventive actions.

## Access model

- Viewer: health/metrics and minimal incident summaries, no human-generated notes or sensitive log/audit data.
- Operator: manage workflow, request limited AI diagnosis and infrastructure operations.
- Admin: sensitive logs/audit and independent infrastructure approvals, but no approval of own request.
- Role assignment is controlled by the existing RBAC app, not by incidental `is_staff` alone.
