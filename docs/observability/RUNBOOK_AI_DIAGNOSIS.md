# MallByte — AI Diagnosis Runbook

## Purpose
A human operator starts a provider-backed **advisory analysis** of a technical incident. AI must never automatically fix Django code, execute commands, merge pull requests, change infrastructure or deploy anything.

## Requirements & configuration

- Install migrations and ensure `celery_worker` is running.
- Put the OpenAI API key in **backend-only** `.env.docker`, never git, never `NEXT_PUBLIC_*` or a browser:

  ```dotenv
  OBSERVABILITY_AI_API_KEY=REPLACE_WITH_REAL_PROVIDER_KEY
  OBSERVABILITY_AI_ENABLED=auto
  OBSERVABILITY_AI_MODEL=gpt-5-mini
  OBSERVABILITY_AI_RATE=10/day
  ```

- Restart both backend web and worker from trusted host:

  ```bash
  docker compose -f compose.yaml -f compose.dev.yaml --profile celery up -d --force-recreate web celery_worker
  ```

- The `auto` mode enables the feature **only when a nonblank API key exists**. Emergency stop: `OBSERVABILITY_AI_ENABLED=false` on **both web and worker** followed by their restart. Existing queued AI jobs will then fail safely.
- Each diagnosis must have `consent_to_external_processing=true`; the UI requires an opt-in checkbox. Incident text is excluded by default; separately opting in can send scrubbed title/description. Redaction is not a guarantee against PII leakage; **do not provide customer details or secrets**.
- Technical metadata (exception type, route template, severity/status) can still be operationally sensitive; approve provider data processing policy before enabling outside development.

## Test without spending API credits

1. Run tests: `python manage.py test apps.observability.tests_workflows --noinput` in web container.
2. Create an incident from UI, select it, tick external processing consent, request diagnosis.
3. Expect `queued` then `running` then `succeeded` (or `failed`) in diagnosis list after Refresh.
4. Check worker logs; never paste a provider key or raw HTTP body in tickets.
5. With empty key expect HTTP 503 instead of an unexpected external call.

## Handling failure

- `queued` for several minutes: check `docker compose ... logs celery_worker`, Redis connectivity and task registration `apps.observability.tasks.run_observability_ai_diagnosis`.
- `failed`: verify provider key/model, API billing, network egress, no secrets in logs. A new attempt is allowed after a 10-minute incident cooldown and daily quota permits.
- `running` stuck: investigate worker crash/time limits. Do not blindly retrigger expensive jobs; reconcile state before retrying.
- Reports can be wrong. Validate against actual logs/DB metrics before a production code change.

## Cost control

Backend has a database-enforced maximum **10 diagnoses per user in a rolling 24-hour period**, plus a 10-minute cooldown per incident and the DRF throttle. Provider billing limits should also be configured in the provider account; server-side quota is not a hard monetary cost cap.
