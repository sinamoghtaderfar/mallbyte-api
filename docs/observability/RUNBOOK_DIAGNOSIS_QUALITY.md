# AI Diagnosis — Evidence-first runbook (MallByte v3)

## Purpose
AI analysis assists triage; it does not fix Django code, prove root cause, change infrastructure, or process real customer secrets. Groq Responses API is supported without the `store` parameter; OpenAI Responses API is supported with `store=false`. Only the two pinned HTTPS endpoints are eligible.

## Preconditions
- Operator has `request_observability_ai_diagnosis` and explicitly consents to external processing.
- API key is in the ignored `.env.docker` file on BOTH web and Celery worker.
- Groq and OpenAI keys must NEVER be copied into logs, incidents, Git or tickets.
- At least one actual observation is required: a linked Error Log (with status, exception type, or redacted route template), OR useful title/description explicitly opted into external processing. `severity` and `status` alone are not diagnostic evidence.

## What is sent
- Case severity and status (administrative metadata)
- Only actually observed exception type, HTTP status, privacy-minimized static route template
- Optional, consented title and description through best-effort scrubbing (not guaranteed PII removal)
- Explicit list of unavailable fields

No traceback, raw exception message, query string, IP, emails, identity, credentials, raw HTTP body, or environment variable dump should be sent. **Before opting in to send description, manually inspect the text for identifying information, secrets or business-sensitive details.** Avoid real customer information even with automatic scrubbing.

## Procedure
1. Confirm actual log record or a specific privacy-reviewed description exists.
2. In Incident, choose **Diagnose**, explicitly consent; `include_description` only after review.
3. Check task: `queued` → `running` → `succeeded` / `failed`.
4. Read report as *hypotheses*, compare to actual logs/metrics; independently verify before mitigation.
5. Do not paste the complete traceback, authorization header, environment values or customer data into an Incident to improve the report.

## 400 'Insufficient diagnostic evidence'
Link a real Error Log with nonempty diagnostic fields, OR provide a meaningful, sanitized incident description and explicitly opt in to its external processing. No external request is made for evidence-free cases.

## Provider problems
- `401`: invalid/revoked key; rotate and verify config, do not print key.
- `403`: account, policy or network restriction; inspect provider control plane. Never attempt circumvention.
- `429`: rate or free-tier limit; use native rate controls and wait for reset.
- Network/timeout: verify worker connectivity. No raw upstream bodies in logs.
- Emergency stop: set `OBSERVABILITY_AI_ENABLED=false` in `.env.docker`, recreate `web` and `celery_worker`.

## Validation
Run: `python manage.py test apps.observability.tests_workflows --noinput`. The test suite uses mocks and never spends provider credits.
