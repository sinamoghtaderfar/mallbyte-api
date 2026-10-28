"""Data-only bridge for the trusted host runner. Never invokes Docker or a shell."""
import hashlib
import hmac
import json
import secrets
import sys
import uuid
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.observability.models import AuditLog
from apps.observability.services import create_audit_log
from apps.observability.workflow_models import InfrastructureOperation as Operation

# Host runner contains its own hardcoded allowlist as an independent control.
SAFE_TARGETS = (Operation.Target.CELERY_WORKER, Operation.Target.CELERY_BEAT)


class Command(BaseCommand):
    help = "Database-only claim/complete transport for separately approved restarts."

    def add_arguments(self, parser):
        parser.add_argument("verb", choices=["claim", "complete", "peek"])
        parser.add_argument("--operation-id", default="")
        parser.add_argument("--outcome", choices=["succeeded", "failed"])
        parser.add_argument("--message", default="")
        parser.add_argument("--token-stdin", action="store_true")

    def handle(self, *args, **opts):
        if opts["verb"] == "peek":
            # Read-only audit preview for host startup checks. No tokens.
            jobs = list(Operation.objects.filter(status=Operation.Status.APPROVED,
                approved_by__isnull=False, requested_by__isnull=False,
                expires_at__gt=timezone.now(), approved_at__isnull=False, target__in=SAFE_TARGETS)
                .exclude(approved_by_id=F("requested_by_id"))
                .order_by("created_at").values("id", "target")[:5])
            self.stdout.write(json.dumps({"pending": [{"id": str(j["id"]), "target": j["target"]} for j in jobs]}))
            return
        if opts["verb"] == "claim":
            with transaction.atomic():
                now = timezone.now()
                # Defer target if another host operation for it is currently running.
                running = set(Operation.objects.filter(status=Operation.Status.RUNNING,
                    target__in=SAFE_TARGETS).values_list("target", flat=True))
                job = (Operation.objects.select_for_update(skip_locked=True)
                    .filter(status=Operation.Status.APPROVED,
                        approved_by__isnull=False, requested_by__isnull=False,
                        expires_at__gt=now, approved_at__isnull=False,
                        target__in=[t for t in SAFE_TARGETS if t not in running])
                    .exclude(approved_by_id=F("requested_by_id"))
                    .order_by("created_at").first())
                if job is None:
                    self.stdout.write(json.dumps({"operation": None}))
                    return
                token = secrets.token_urlsafe(32)
                job.status = Operation.Status.RUNNING
                job.started_at = now
                job.execution_token_hash = hashlib.sha256(token.encode()).hexdigest()
                job.save(update_fields=["status", "started_at", "execution_token_hash"])
                create_audit_log(action=AuditLog.ActionChoices.SYSTEM,
                    description="Trusted host runner claimed approved operation",
                    object_type="InfrastructureOperation", object_id=str(job.pk),
                    metadata={"target": job.target})
                result = {"operation": {"id": str(job.id), "target": job.target}, "token": token}
            self.stdout.write(json.dumps(result))
            return
        if not opts["token_stdin"] or not opts["operation_id"] or not opts["outcome"]:
            raise CommandError("Completion requires operation ID, outcome and --token-stdin")
        try:
            pk = uuid.UUID(opts["operation_id"])
        except ValueError as exc:
            raise CommandError("Invalid UUID") from exc
        token = sys.stdin.readline().strip()
        if not token or len(token) > 200:
            raise CommandError("Missing execution token")
        with transaction.atomic():
            op = Operation.objects.select_for_update().filter(pk=pk).first()
            if not op or op.status != Operation.Status.RUNNING or not op.execution_token_hash:
                raise CommandError("Operation is not running")
            if not hmac.compare_digest(op.execution_token_hash, hashlib.sha256(token.encode()).hexdigest()):
                raise CommandError("Execution token rejected")
            op.status = (Operation.Status.SUCCEEDED if opts["outcome"] == "succeeded"
                         else Operation.Status.FAILED)
            op.completed_at = timezone.now()
            # Only structured, bounded completion messages supplied by host runner.
            op.result_message = str(opts["message"])[:200]
            op.execution_token_hash = ""
            op.save(update_fields=["status", "completed_at", "result_message", "execution_token_hash"])
            create_audit_log(action=AuditLog.ActionChoices.SYSTEM,
                description="Trusted host runner finished infrastructure operation",
                object_type="InfrastructureOperation", object_id=str(op.pk),
                metadata={"target": op.target, "status": op.status})
        self.stdout.write(json.dumps({"status": op.status, "id": str(op.pk)}))
