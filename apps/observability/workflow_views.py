"""DRF actions for internal incidents, optional diagnosis and approved operations."""
from django.contrib.auth import get_user_model
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from apps.observability.ai_diagnosis import ai_ready
from apps.observability.models import AuditLog
from apps.observability.permissions import allowed
from apps.observability.services import create_audit_log
from apps.observability.sanitization import scrub_text
from apps.observability.workflow_models import Incident, IncidentEvent, AIDiagnosis, InfrastructureOperation
from apps.observability.workflow_tasks import run_observability_ai_diagnosis
from apps.observability.workflow_permissions import (
    ViewIncidents, CreateIncidents, AssignIncidents, ManageIncidents, RequestAIDiagnosis,
    ViewOperations, RequestOperations, ApproveOperations,
)
from apps.observability.workflow_serializers import (
    IncidentSerializer, IncidentSummarySerializer, IncidentCreateSerializer, IncidentEventSerializer, AIDiagnosisSerializer,
    InfrastructureOperationSerializer, InfrastructureOperationRequestSerializer,
)


def audit(request, kind, obj, message):
    create_audit_log(actor=request.user, action=AuditLog.ActionChoices.UPDATE,
                     object_type=kind, object_id=str(obj.pk), description=message, request=request)


class AssignInput(serializers.Serializer):
    user_id = serializers.IntegerField(min_value=1)


class TransitionInput(serializers.Serializer):
    status = serializers.ChoiceField(choices=Incident.Status.choices)
    note = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class CommentInput(serializers.Serializer):
    note = serializers.CharField(min_length=2, max_length=2000, trim_whitespace=True)


class DiagnosisInput(serializers.Serializer):
    include_description = serializers.BooleanField(default=False)
    consent_to_external_processing = serializers.BooleanField(required=True)

    def validate_consent_to_external_processing(self, value):
        if not value:
            raise serializers.ValidationError("Explicit external processing consent is required.")
        return value


TRANSITIONS = {
    Incident.Status.OPEN: {Incident.Status.INVESTIGATING, Incident.Status.CLOSED},
    Incident.Status.INVESTIGATING: {Incident.Status.MITIGATED, Incident.Status.RESOLVED},
    Incident.Status.MITIGATED: {Incident.Status.INVESTIGATING, Incident.Status.RESOLVED},
    Incident.Status.RESOLVED: {Incident.Status.CLOSED, Incident.Status.INVESTIGATING},
    Incident.Status.CLOSED: {Incident.Status.INVESTIGATING},
}


class IncidentViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                      mixins.CreateModelMixin, viewsets.GenericViewSet):
    queryset = Incident.objects.select_related("created_by", "assigned_to", "source_error", "source_alert")
    serializer_class = IncidentSerializer
    throttle_scope = None  # DRF router compatibility
    http_method_names = ["get", "post", "head", "options"]

    def get_permissions(self):
        cls = {
            "list": ViewIncidents, "retrieve": ViewIncidents,
            "create": CreateIncidents, "events": ManageIncidents,
            "diagnoses": RequestAIDiagnosis, "assign": AssignIncidents,
            "transition": ManageIncidents, "comment": ManageIncidents,
            "diagnose": RequestAIDiagnosis,
        }.get(self.action)
        return [IsAuthenticated(), (cls or ViewIncidents)()]

    def get_serializer_class(self):
        if self.action == "create":
            return IncidentCreateSerializer
        if self.action in ("list", "retrieve") and not allowed(
            self.request.user, "manage_observability_incidents"
        ):
            return IncidentSummarySerializer
        return IncidentSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        state = self.request.query_params.get("status")
        severity = self.request.query_params.get("severity")
        if state in Incident.Status.values:
            qs = qs.filter(status=state)
        if severity in Incident.Severity.values:
            qs = qs.filter(severity=severity)
        return qs

    def create(self, request, *args, **kwargs):
        data = IncidentCreateSerializer(data=request.data, context={"request": request})
        data.is_valid(raise_exception=True)
        with transaction.atomic():
            instance = data.save(created_by=request.user)
            IncidentEvent.objects.create(incident=instance, actor=request.user,
                                         event_type=IncidentEvent.Type.CREATED, note="Incident created")
            audit(request, "Incident", instance, "Created internal incident")
        return Response(IncidentSerializer(instance).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def events(self, request, pk=None):
        incident = self.get_object()
        return Response(IncidentEventSerializer(incident.events.all()[:200], many=True).data)

    @action(detail=True, methods=["get"])
    def diagnoses(self, request, pk=None):
        incident = self.get_object()
        return Response(AIDiagnosisSerializer(incident.diagnoses.all()[:30], many=True).data)

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        data = AssignInput(data=request.data)
        data.is_valid(raise_exception=True)
        User = get_user_model()
        user = User.objects.filter(pk=data.validated_data["user_id"], is_active=True, is_deleted=False).first()
        if user is None or not allowed(user, "view_observability_incidents"):
            raise ValidationError({"user_id": "Assignee must be an active observability team member."})
        with transaction.atomic():
            obj = Incident.objects.select_for_update().get(pk=self.get_object().pk)
            before = str(obj.assigned_to_id or "")
            obj.assigned_to = user
            obj.save(update_fields=["assigned_to", "updated_at"])
            IncidentEvent.objects.create(incident=obj, actor=request.user, event_type=IncidentEvent.Type.ASSIGNED,
                                         from_value=before, to_value=str(user.pk), note="Assignee changed")
            audit(request, "Incident", obj, "Assigned incident to an observability team member")
        return Response(IncidentSerializer(obj).data)

    @action(detail=True, methods=["post"])
    def transition(self, request, pk=None):
        data = TransitionInput(data=request.data)
        data.is_valid(raise_exception=True)
        new = data.validated_data["status"]
        note = scrub_text(data.validated_data.get("note", ""), limit=2000)
        with transaction.atomic():
            obj = Incident.objects.select_for_update().get(pk=self.get_object().pk)
            if new not in TRANSITIONS.get(obj.status, set()):
                return Response({"detail": "Invalid incident status transition."}, status=409)
            if new == Incident.Status.RESOLVED and len(note.strip()) < 10:
                raise ValidationError({"note": "Resolution requires at least ten characters."})
            before = obj.status
            obj.status = new
            obj.resolved_at = timezone.now() if new in (Incident.Status.RESOLVED, Incident.Status.CLOSED) else None
            obj.save(update_fields=["status", "resolved_at", "updated_at"])
            IncidentEvent.objects.create(incident=obj, actor=request.user, event_type=IncidentEvent.Type.STATUS,
                                         from_value=before, to_value=new, note=note)
            audit(request, "Incident", obj, f"Changed incident status {before} -> {new}")
        return Response(IncidentSerializer(obj).data)

    @action(detail=True, methods=["post"])
    def comment(self, request, pk=None):
        data = CommentInput(data=request.data)
        data.is_valid(raise_exception=True)
        obj = self.get_object()
        event = IncidentEvent.objects.create(incident=obj, actor=request.user,
                                             event_type=IncidentEvent.Type.COMMENT,
                                             note=scrub_text(data.validated_data["note"], limit=2000))
        audit(request, "Incident", obj, "Added incident comment")
        return Response(IncidentEventSerializer(event).data, status=201)

    @action(detail=True, methods=["post"], throttle_classes=[ScopedRateThrottle],
            throttle_scope="observability_ai")
    def diagnose(self, request, pk=None):
        data = DiagnosisInput(data=request.data)
        data.is_valid(raise_exception=True)
        if not ai_ready():
            return Response({"detail": "Configure OBSERVABILITY_AI_API_KEY on web and Celery worker."}, status=503)
        obj = self.get_object()
        # Database row lock: cooldown remains valid even with per-process cache fallback.
        with transaction.atomic():
            obj = Incident.objects.select_for_update().get(pk=obj.pk)
            cutoff = timezone.now() - timedelta(minutes=10)
            if AIDiagnosis.objects.filter(incident=obj, created_at__gte=cutoff).exists():
                return Response({"detail": "One diagnosis per incident every ten minutes."}, status=429)
            # Durable daily budget protects external API costs across app processes.
            limit = 10
            if AIDiagnosis.objects.filter(requested_by=request.user,
                created_at__gte=timezone.now() - timedelta(days=1)).count() >= limit:
                return Response({"detail": "Daily AI diagnosis limit reached."}, status=429)
            item = AIDiagnosis.objects.create(
                incident=obj, requested_by=request.user,
                model_name="pending", response="",
                include_description=data.validated_data["include_description"],
            )
            IncidentEvent.objects.create(incident=obj, actor=request.user,
                event_type=IncidentEvent.Type.AI, note="Requested explicitly consented AI diagnosis")
            audit(request, "Incident", obj, "Queued opt-in AI diagnosis")
            # Queue only after commit; no provider I/O from an HTTP handler.
            def enqueue():
                try:
                    run_observability_ai_diagnosis.delay(str(item.pk))
                except Exception:
                    AIDiagnosis.objects.filter(pk=item.pk, status=AIDiagnosis.Status.QUEUED).update(
                        status=AIDiagnosis.Status.FAILED,
                        response="AI worker queue unavailable. No provider call was made."
                    )
            transaction.on_commit(enqueue)
        item.refresh_from_db()
        return Response(AIDiagnosisSerializer(item).data, status=202)



class InfrastructureOperationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                                     mixins.CreateModelMixin, viewsets.GenericViewSet):
    queryset = InfrastructureOperation.objects.select_related("requested_by", "approved_by")
    serializer_class = InfrastructureOperationSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_permissions(self):
        cls = {
            "list": ViewOperations, "retrieve": ViewOperations,
            "create": RequestOperations, "approve": ApproveOperations,
            "reject": ApproveOperations, "cancel": RequestOperations,
        }.get(self.action)
        return [IsAuthenticated(), (cls or ViewOperations)()]

    def get_serializer_class(self):
        if self.action == "create":
            return InfrastructureOperationRequestSerializer
        return InfrastructureOperationSerializer

    def get_throttles(self):
        if self.action == "create":
            self.throttle_scope = "observability_ops"
            return [ScopedRateThrottle()]
        return super().get_throttles()

    def create(self, request, *args, **kwargs):
        data = InfrastructureOperationRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        with transaction.atomic():
            op = InfrastructureOperation.objects.create(requested_by=request.user,
                                                          **data.validated_data)
            audit(request, "InfrastructureOperation", op, f"Requested restart: {op.target}")
        return Response(InfrastructureOperationSerializer(op).data, status=201)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        with transaction.atomic():
            op = InfrastructureOperation.objects.select_for_update().get(pk=self.get_object().pk)
            if op.status != InfrastructureOperation.Status.PENDING:
                return Response({"detail": "Only pending requests can be approved."}, status=409)
            if op.expires_at <= timezone.now():
                op.status = InfrastructureOperation.Status.EXPIRED
                op.save(update_fields=["status"])
                return Response({"detail": "This request has expired."}, status=409)
            if op.requested_by_id == request.user.pk:
                raise PermissionDenied("A second person must approve the operation.")
            op.status = InfrastructureOperation.Status.APPROVED
            op.approved_by = request.user
            op.approved_at = timezone.now()
            op.save(update_fields=["status", "approved_by", "approved_at"])
            audit(request, "InfrastructureOperation", op, "Approved restart request")
        return Response(InfrastructureOperationSerializer(op).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        with transaction.atomic():
            op = InfrastructureOperation.objects.select_for_update().get(pk=self.get_object().pk)
            if op.status != InfrastructureOperation.Status.PENDING:
                return Response({"detail": "Only pending requests can be rejected."}, status=409)
            op.status = InfrastructureOperation.Status.REJECTED
            op.save(update_fields=["status"])
            audit(request, "InfrastructureOperation", op, "Rejected restart request")
        return Response(InfrastructureOperationSerializer(op).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        with transaction.atomic():
            op = InfrastructureOperation.objects.select_for_update().get(pk=self.get_object().pk)
            if op.requested_by_id != request.user.pk and not allowed(
                request.user, "approve_observability_operations"
            ):
                raise PermissionDenied("Only the requester or an approver may cancel.")
            if op.status not in (InfrastructureOperation.Status.PENDING, InfrastructureOperation.Status.APPROVED):
                return Response({"detail": "Operation can no longer be cancelled."}, status=409)
            op.status = InfrastructureOperation.Status.CANCELLED
            op.save(update_fields=["status"])
            audit(request, "InfrastructureOperation", op, "Cancelled restart request")
        return Response(InfrastructureOperationSerializer(op).data)
