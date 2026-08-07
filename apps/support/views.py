from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.support.models import (
    SupportTag,
    SupportTicket,
    TicketAttachment,
    TicketAuditLog,
    TicketMessage,
)
from apps.support.notifications import create_support_notification
from apps.support.permissions import (
    IsSupportStaff,
    IsTicketParticipantOrSupportStaff,
)
from apps.support.serializers import (
    SupportTagSerializer,
    SupportTicketSerializer,
    TicketAssignSerializer,
    TicketAttachmentSerializer,
    TicketAuditLogSerializer,
    TicketReplySerializer,
    TicketTagSerializer,
)


class SupportTagViewSet(viewsets.ModelViewSet):
    serializer_class = SupportTagSerializer
    queryset = SupportTag.objects.all().order_by("name")

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [IsAuthenticated()]

        return [IsAuthenticated(), IsSupportStaff()]

class SupportTicketViewSet(viewsets.ModelViewSet):
    serializer_class = SupportTicketSerializer
    permission_classes = [IsAuthenticated, IsTicketParticipantOrSupportStaff]
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

    def get_queryset(self):
        user = self.request.user

        queryset = (
            SupportTicket.objects.select_related(
                "customer",
                "assigned_to",
                "order",
                "product",
                "return_request",
            )
            .prefetch_related("messages")
            .all()
        )

        if not (user.is_staff or user.is_superuser):
            queryset = queryset.filter(customer=user)

        status_filter = self.request.query_params.get("status")
        priority = self.request.query_params.get("priority")
        category = self.request.query_params.get("category")
        assigned_to = self.request.query_params.get("assigned_to")
        customer = self.request.query_params.get("customer")
        order = self.request.query_params.get("order")
        product = self.request.query_params.get("product")
        ordering = self.request.query_params.get("ordering")

        if status_filter:
            queryset = queryset.filter(status=status_filter)

        if priority:
            queryset = queryset.filter(priority=priority)

        if category:
            queryset = queryset.filter(category=category)

        if order:
            queryset = queryset.filter(order_id=order)

        if product:
            queryset = queryset.filter(product_id=product)

        if assigned_to:
            if assigned_to == "me":
                queryset = queryset.filter(assigned_to=user)
            elif user.is_staff or user.is_superuser:
                queryset = queryset.filter(assigned_to_id=assigned_to)

        if customer and (user.is_staff or user.is_superuser):
            queryset = queryset.filter(customer_id=customer)

        allowed_ordering_fields = {
            "created_at",
            "-created_at",
            "updated_at",
            "-updated_at",
            "last_message_at",
            "-last_message_at",
            "status",
            "-status",
            "priority",
            "-priority",
        }

        if ordering in allowed_ordering_fields:
            queryset = queryset.order_by(ordering)

        return queryset

    def get_permissions(self):
        if self.action in ["assign", "resolve", "close", "reopen"]:
            return [IsAuthenticated(), IsSupportStaff()]

        return super().get_permissions()
    
    @action(
        detail=False,
        methods=["get"],
        url_path="summary",
        permission_classes=[IsAuthenticated],
    )
    def summary(self, request):
        queryset = self.get_queryset()

        status_summary = queryset.aggregate(
            total=Count("id"),
            open=Count(
                "id",
                filter=Q(status=SupportTicket.StatusChoices.OPEN),
            ),
            pending=Count(
                "id",
                filter=Q(status=SupportTicket.StatusChoices.PENDING),
            ),
            resolved=Count(
                "id",
                filter=Q(status=SupportTicket.StatusChoices.RESOLVED),
            ),
            closed=Count(
                "id",
                filter=Q(status=SupportTicket.StatusChoices.CLOSED),
            ),
        )

        priority_summary = queryset.aggregate(
            low=Count(
                "id",
                filter=Q(priority=SupportTicket.PriorityChoices.LOW),
            ),
            normal=Count(
                "id",
                filter=Q(priority=SupportTicket.PriorityChoices.NORMAL),
            ),
            high=Count(
                "id",
                filter=Q(priority=SupportTicket.PriorityChoices.HIGH),
            ),
            urgent=Count(
                "id",
                filter=Q(priority=SupportTicket.PriorityChoices.URGENT),
            ),
        )

        category_summary = queryset.aggregate(
            order=Count(
                "id",
                filter=Q(category=SupportTicket.CategoryChoices.ORDER),
            ),
            payment=Count(
                "id",
                filter=Q(category=SupportTicket.CategoryChoices.PAYMENT),
            ),
            shipping=Count(
                "id",
                filter=Q(category=SupportTicket.CategoryChoices.SHIPPING),
            ),
            return_ticket=Count(
                "id",
                filter=Q(category=SupportTicket.CategoryChoices.RETURN),
            ),
            product=Count(
                "id",
                filter=Q(category=SupportTicket.CategoryChoices.PRODUCT),
            ),
            account=Count(
                "id",
                filter=Q(category=SupportTicket.CategoryChoices.ACCOUNT),
            ),
            other=Count(
                "id",
                filter=Q(category=SupportTicket.CategoryChoices.OTHER),
            ),
        )

        assigned_to_me_count = queryset.filter(
            assigned_to=request.user,
        ).count()

        unassigned_count = queryset.filter(
            assigned_to__isnull=True,
        ).count()

        return Response(
            {
                "status": status_summary,
                "priority": priority_summary,
                "category": category_summary,
                "assigned_to_me": assigned_to_me_count,
                "unassigned": unassigned_count,
            },
            status=status.HTTP_200_OK,
        )
        
    @action(
        detail=True,
        methods=["get", "post"],
        url_path="attachments",
        permission_classes=[IsAuthenticated, IsTicketParticipantOrSupportStaff],
        parser_classes=[MultiPartParser, FormParser],
    )
    def attachments(self, request, pk=None):
        ticket = self.get_object()

        if request.method == "GET":
            serializer = TicketAttachmentSerializer(
                ticket.attachments.all(),
                many=True,
                context={"request": request},
            )
            return Response(serializer.data, status=status.HTTP_200_OK)

        serializer = TicketAttachmentSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        uploaded_file = serializer.validated_data["file"]

        attachment = TicketAttachment.objects.create(
            ticket=ticket,
            uploaded_by=request.user,
            file=uploaded_file,
            original_filename=getattr(uploaded_file, "name", ""),
            content_type=getattr(uploaded_file, "content_type", ""),
            size=getattr(uploaded_file, "size", 0) or 0,
        )

        TicketAuditLog.log(
            ticket=ticket,
            actor=request.user,
            action=TicketAuditLog.ActionChoices.ATTACHMENT_ADDED,
            description="Attachment uploaded.",
            metadata={
                "attachment_id": attachment.pk,
                "filename": attachment.original_filename,
                "size": attachment.size,
            },
        )

        response_serializer = TicketAttachmentSerializer(
            attachment,
            context={"request": request},
        )

        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @action(
        detail=True,
        methods=["post"],
        url_path="add-tag",
        permission_classes=[IsAuthenticated, IsSupportStaff],
    )
    def add_tag(self, request, pk=None):
        ticket = self.get_object()

        serializer = TicketTagSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tag = serializer.validated_data["tag"]
        ticket.tags.add(tag)

        TicketAuditLog.log(
            ticket=ticket,
            actor=request.user,
            action=TicketAuditLog.ActionChoices.TAG_ADDED,
            description=f"Tag '{tag.name}' added.",
            metadata={
                "tag_id": tag.pk,
                "tag_name": tag.name,
            },
        )

        response_serializer = self.get_serializer(ticket)

        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["post"],
        url_path="remove-tag",
        permission_classes=[IsAuthenticated, IsSupportStaff],
    )
    def remove_tag(self, request, pk=None):
        ticket = self.get_object()

        serializer = TicketTagSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tag = serializer.validated_data["tag"]
        ticket.tags.remove(tag)

        TicketAuditLog.log(
            ticket=ticket,
            actor=request.user,
            action=TicketAuditLog.ActionChoices.TAG_REMOVED,
            description=f"Tag '{tag.name}' removed.",
            metadata={
                "tag_id": tag.pk,
                "tag_name": tag.name,
            },
        )

        response_serializer = self.get_serializer(ticket)

        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["get"],
        url_path="audit-logs",
        permission_classes=[IsAuthenticated, IsSupportStaff],
    )
    def audit_logs(self, request, pk=None):
        ticket = self.get_object()

        serializer = TicketAuditLogSerializer(
            ticket.audit_logs.all(),
            many=True,
        )

        return Response(serializer.data, status=status.HTTP_200_OK)
    @action(
        detail=True,
        methods=["post"],
        url_path="reply",
        permission_classes=[IsAuthenticated, IsTicketParticipantOrSupportStaff],
    )
    def reply(self, request, pk=None):
        ticket = self.get_object()

        if ticket.status == SupportTicket.StatusChoices.CLOSED:
            return Response(
                {"detail": "Cannot reply to a closed ticket. Reopen it first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = TicketReplySerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        is_internal_note = serializer.validated_data.get("is_internal_note", False)

        message = TicketMessage.objects.create(
            ticket=ticket,
            sender=request.user,
            message=serializer.validated_data["message"],
            is_internal_note=is_internal_note,
        )

        TicketAuditLog.log(
            ticket=ticket,
            actor=request.user,
            action=(
                TicketAuditLog.ActionChoices.INTERNAL_NOTE_CREATED
                if is_internal_note
                else TicketAuditLog.ActionChoices.REPLIED
            ),
            description=(
                "Internal note created."
                if is_internal_note
                else "Ticket reply added."
            ),
            metadata={
                "message_id": message.pk,
            },
        )

        update_fields = ["updated_at"]

        if not is_internal_note:
            ticket.last_message_at = timezone.now()
            update_fields.append("last_message_at")

            if request.user.is_staff or request.user.is_superuser:
                ticket.status = SupportTicket.StatusChoices.PENDING
            else:
                ticket.status = SupportTicket.StatusChoices.OPEN

            update_fields.append("status")

        ticket.save(update_fields=update_fields)
        
        if not is_internal_note:
            if request.user.is_staff or request.user.is_superuser:
                create_support_notification(
                    user=ticket.customer,
                    ticket=ticket,
                    template_key="support_ticket_staff_replied",
                    ticket_number=ticket.ticket_number,
                )
            elif ticket.assigned_to:
                create_support_notification(
                    user=ticket.assigned_to,
                    ticket=ticket,
                    template_key="support_ticket_customer_replied",
                    ticket_number=ticket.ticket_number,
                )

        response_serializer = self.get_serializer(ticket)

        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @action(
        detail=True,
        methods=["post"],
        url_path="assign",
        permission_classes=[IsAuthenticated, IsSupportStaff],
    )
    def assign(self, request, pk=None):
        ticket = self.get_object()

        serializer = TicketAssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ticket.assigned_to = serializer.validated_data["assigned_to"]
        ticket.save(update_fields=["assigned_to", "updated_at"])
        
        TicketAuditLog.log(
            ticket=ticket,
            actor=request.user,
            action=TicketAuditLog.ActionChoices.ASSIGNED,
            description=f"Ticket assigned to {ticket.assigned_to}.",
            metadata={
                "assigned_to_id": ticket.assigned_to_id,
            },
        )
        
        create_support_notification(
            user=ticket.assigned_to,
            ticket=ticket,
            template_key="support_ticket_assigned",
            ticket_number=ticket.ticket_number,
        )

        response_serializer = self.get_serializer(ticket)

        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["post"],
        url_path="resolve",
        permission_classes=[IsAuthenticated, IsSupportStaff],
    )
    def resolve(self, request, pk=None):
        ticket = self.get_object()
        ticket.mark_resolved()
        
        TicketAuditLog.log(
            ticket=ticket,
            actor=request.user,
            action=TicketAuditLog.ActionChoices.RESOLVED,
            description="Ticket resolved.",
        )
        
        create_support_notification(
            user=ticket.customer,
            ticket=ticket,
            template_key="support_ticket_resolved",
            ticket_number=ticket.ticket_number,
        )

        serializer = self.get_serializer(ticket)

        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["post"],
        url_path="close",
        permission_classes=[IsAuthenticated, IsSupportStaff],
    )
    def close(self, request, pk=None):
        ticket = self.get_object()
        ticket.close()
        TicketAuditLog.log(
            ticket=ticket,
            actor=request.user,
            action=TicketAuditLog.ActionChoices.CLOSED,
            description="Ticket closed.",
        )
        create_support_notification(
            user=ticket.customer,
            ticket=ticket,
            template_key="support_ticket_closed",
            ticket_number=ticket.ticket_number,
        )

        serializer = self.get_serializer(ticket)

        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["post"],
        url_path="reopen",
        permission_classes=[IsAuthenticated, IsSupportStaff],
    )
    def reopen(self, request, pk=None):
        ticket = self.get_object()
        ticket.reopen()
        
        TicketAuditLog.log(
            ticket=ticket,
            actor=request.user,
            action=TicketAuditLog.ActionChoices.REOPENED,
            description="Ticket reopened.",
        )
        
        create_support_notification(
            user=ticket.customer,
            ticket=ticket,
            template_key="support_ticket_reopened",
            ticket_number=ticket.ticket_number,
        )

        serializer = self.get_serializer(ticket)

        return Response(serializer.data, status=status.HTTP_200_OK)