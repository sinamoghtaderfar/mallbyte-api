"""Provider I/O outside web workers; runs only after explicit consented API request."""
from celery import shared_task
from django.db import transaction
from apps.observability.ai_diagnosis import AIUnavailable, ask_ai_diagnosis
from apps.observability.workflow_models import AIDiagnosis


@shared_task(name="apps.observability.tasks.run_observability_ai_diagnosis", bind=True,
             max_retries=0, soft_time_limit=45, time_limit=55)
def run_observability_ai_diagnosis(self, diagnosis_id):
    with transaction.atomic():
        diagnosis = AIDiagnosis.objects.select_for_update().filter(pk=diagnosis_id).first()
        if not diagnosis or diagnosis.status != AIDiagnosis.Status.QUEUED:
            return {"status": "ignored"}
        diagnosis.status = AIDiagnosis.Status.RUNNING
        diagnosis.save(update_fields=["status", "updated_at"])
    try:
        model, report = ask_ai_diagnosis(
            diagnosis.incident, include_description=diagnosis.include_description
        )
    except AIUnavailable:
        # Never store provider request data, credentials or upstream response bodies.
        AIDiagnosis.objects.filter(pk=diagnosis_id, status=AIDiagnosis.Status.RUNNING).update(
            status=AIDiagnosis.Status.FAILED, response="Diagnosis unavailable. Check AI provider configuration and logs."
        )
        return {"status": "failed"}
    except Exception:
        AIDiagnosis.objects.filter(pk=diagnosis_id, status=AIDiagnosis.Status.RUNNING).update(
            status=AIDiagnosis.Status.FAILED, response="Diagnosis failed. No changes were made."
        )
        return {"status": "failed"}
    AIDiagnosis.objects.filter(pk=diagnosis_id, status=AIDiagnosis.Status.RUNNING).update(
        model_name=model[:100], response=report[:8000], status=AIDiagnosis.Status.SUCCEEDED
    )
    return {"status": "succeeded"}
