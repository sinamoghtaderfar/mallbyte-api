# Staging Load Test and Production Launch Gates

## Scope

The k6 smoke scenario checks **public** catalog browsing and the minimal health endpoint.
No orders, email, payments, private data or privileged sessions are mutated.

This script is not a benchmark result. Performance depends on the real
infrastructure, dataset, network conditions and realistic traffic mix.

## Run against isolated staging

Install k6 locally or use a pinned k6 Docker image. Deploy staging with
a realistically populated catalog and working external PostgreSQL + Redis.

```sh
BASE_URL=https://staging-api.example.com VUS=3 DURATION=20s \
  k6 run ops/loadtest/catalog-smoke.js
```

The script refuses unfamiliar hostnames by default. Non-staging
environments require an explicit opt-in; do not use it on production
without an approved and scheduled load test.

### Initial smoke gates

- Catalog HTTP errors below 1% (including failed response assertions)
- Catalog p95 request time below 1200 ms for a small staging smoke load
- No queue backlog growth, elevated CPU/memory or Redis instability
- Error monitoring shows no unanticipated 500s
- No accidental real payment or transactional side effects

These are **initial thresholds**, not a proven SLO. Validate them with
product-specific traffic, hardware and a representative dataset.

## Release checklist

| Gate | Evidence required |
| --- | --- |
| Backend and Frontend CI | Green on exact release commits |
| Browser E2E | Green and staged API integration manually verified |
| MFA | New enrollment, second login, recovery code, replay and legacy token tests |
| Security | Production dependency audit, API permission regression tests, verified TLS |
| Databases | Migrations, backups, staging restore drill, RPO/RTO documented |
| Workers | Celery worker/beat logs and task execution verified |
| Assets | Static files and private support attachments served safely |
| External integrations | SMTP sandbox, verified payment callbacks, retry safety |
| Performance | k6 results from staging + latency/error dashboards |
| Operations | Runbook, rollback plan, domain, DNS, on-call and incident alerts |

## Safe rollout

1. Record release Git commit SHA for each service and database migration plan.
2. Make a tested and encrypted off-site backup (DB and media), then restore on staging.
3. Provision HTTPS, strict origins, secrets and external dependencies.
4. Validate `manage.py check --deploy`, migrate and collectstatic on staging.
5. Run API integration tests, browser E2E with a real staging API, MFA enrollment and the load smoke test.
6. Ship during an approved maintenance window; monitor for rollback signals.
7. Verify login, catalog, orders, Celery and observability after launch.

**No production deployment can be claimed without access to a real host,
DNS/TLS configuration, secret store, and verified restore and monitoring.**
