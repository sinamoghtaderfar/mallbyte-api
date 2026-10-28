"""Manually mark an abandoned RUNNING operation failed after independent host checks.

Never runs Docker, shell commands or automatic retries. The operator must verify
that no host runner is currently restarting the relevant service before use.
"""
from datetime import timedelta
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.observability.models import AuditLog
from apps.observability.services import create_audit_log
from apps.observability.workflow_models import InfrastructureOperation


class Command(BaseCommand):
    help = "Inspect or manually fail a stale running restart operation (no Docker actions)."

    def add_arguments(self, parser):
        parser.add_argument("--operation-id", required=True)
        parser.add_argument("--confirm-failed", action="store_true")
        parser.add_argument("--reason", default="")
        parser.add_argument("--min-age-minutes", type=int, default=10)

    def handle(self, *args, **options):
        try:
            operation_id = UUID(options["operation_id"])
        except (ValueError, TypeError) as exc:
            raise CommandError("Invalid operation ID") from exc
        min_age = options["min_age_minutes"]
        if min_age < 10:
            raise CommandError("Minimum stale age must be at least ten minutes")
        with transaction.atomic():
            op = InfrastructureOperation.objects.select_for_update().filter(pk=operation_id).first()
            if op is None:
                raise CommandError("Operation does not exist")
            self.stdout.write(
                f"Operation {op.pk}: target={op.target} status={op.status} "
                f"started_at={op.started_at}"
            )
            if not options["confirm_failed"]:
                self.stdout.write("Read-only inspection. No changes made.")
                return
            if op.status != InfrastructureOperation.Status.RUNNING or op.started_at is None:
                raise CommandError("Only RUNNING operations with a start timestamp can be reconciled")
            if op.started_at > timezone.now() - timedelta(minutes=min_age):
                raise CommandError("Operation is not old enough to reconcile")
            reason = options["reason"].strip()
            if len(reason) < 20 or len(reason) > 400:
                raise CommandError("Provide a specific reason between 20 and 400 characters")
            op.status = InfrastructureOperation.Status.FAILED
            op.completed_at = timezone.now()
            op.result_message = "Manually reconciled after host verification."
            op.execution_token_hash = ""
            op.save(update_fields=["status", "completed_at", "result_message", "execution_token_hash"])
            create_audit_log(
                action=AuditLog.ActionChoices.SYSTEM,
                object_type="InfrastructureOperation",
                object_id=str(op.pk),
                description="Manual reconciliation of stale RUNNING infrastructure operation",
                metadata={"target": op.target, "reason": reason[:400]},
            )
            self.stdout.write("Operation marked failed; no restart was triggered.")
