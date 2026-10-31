from django.contrib.auth import get_user_model
from django.http import FileResponse, Http404
from django.utils.http import content_disposition_header
from apps.support.attachment_validation import SUPPORT_ATTACHMENT_MIME_TYPES
from pathlib import Path
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import (
    FormParser,
    MultiPartParser,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.support.models import (
    SupportTag,
    SupportTicket,
    TicketAttachment,
    TicketAuditLog,
    TicketMessage,
)
from apps.support.notifications import (
    create_support_notification,
)
from apps.support.permissions import (
    CanAccessSupportAttachments,
    CanAssignSupportTickets,
    CanChangeSupportPriority,
    CanCloseSupportTickets,
    CanManageSupportTags,
    CanReopenSupportTickets,
    CanResolveSupportTickets,
    CanRespondToSupportTicket,
    CanViewSupportAuditLogs,
    IsTicketParticipantOrSupportStaff,
    can_be_assigned_support_ticket,
    is_support_staff,
)
from apps.support.serializers import (
    SupportTagSerializer,
    SupportTicketSerializer,
    TicketAssignSerializer,
    TicketAttachmentSerializer,
    TicketAuditLogSerializer,
    TicketPrioritySerializer,
    TicketReplySerializer,
    TicketTagSerializer,
)

User = get_user_model()


class SupportTagViewSet(viewsets.ModelViewSet):
    serializer_class = SupportTagSerializer
    queryset = SupportTag.objects.all().order_by("name")

    def get_permissions(self):
        if self.action in [
            "list",
            "retrieve",
        ]:
            permission_classes = [
                IsAuthenticated,
            ]
        else:
            permission_classes = [
                IsAuthenticated,
                CanManageSupportTags,
            ]

        return [permission() for permission in permission_classes]


class SupportTicketViewSet(viewsets.ModelViewSet):
    serializer_class = SupportTicketSerializer

    permission_classes = [
        IsAuthenticated,
        IsTicketParticipantOrSupportStaff,
    ]

    http_method_names = [
        "get",
        "post",
        "head",
        "options",
    ]

    action_permission_classes = {
        "attachments": [
            IsAuthenticated,
            CanAccessSupportAttachments,
        ],
        "download_attachment": [
            IsAuthenticated,
            CanAccessSupportAttachments,
        ],
        "reply": [
            IsAuthenticated,
            CanRespondToSupportTicket,
        ],
        "agents": [
            IsAuthenticated,
            CanAssignSupportTickets,
        ],
        "assign": [
            IsAuthenticated,
            CanAssignSupportTickets,
        ],
        "add_tag": [
            IsAuthenticated,
            CanManageSupportTags,
        ],
        "remove_tag": [
            IsAuthenticated,
            CanManageSupportTags,
        ],
        "priority": [
            IsAuthenticated,
            CanChangeSupportPriority,
        ],
        "resolve": [
            IsAuthenticated,
            CanResolveSupportTickets,
        ],
        "close": [
            IsAuthenticated,
            CanCloseSupportTickets,
        ],
        "reopen": [
            IsAuthenticated,
            CanReopenSupportTickets,
        ],
        "audit_logs": [
            IsAuthenticated,
            CanViewSupportAuditLogs,
        ],
    }

    def get_permissions(self):
        permission_classes = self.action_permission_classes.get(self.action)

        if permission_classes is None:
            return super().get_permissions()

        return [permission() for permission in permission_classes]

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

        if not is_support_staff(user):
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
            elif is_support_staff(user):
                queryset = queryset.filter(assigned_to_id=assigned_to)

        if customer and is_support_staff(user):
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

    @action(
        detail=False,
        methods=["get"],
        url_path="summary",
    )
    def summary(self, request):
        queryset = self.get_queryset()

        status_summary = queryset.aggregate(
            total=Count("id"),
            open=Count(
                "id",
                filter=Q(status=(SupportTicket.StatusChoices.OPEN)),
            ),
            pending=Count(
                "id",
                filter=Q(status=(SupportTicket.StatusChoices.PENDING)),
            ),
            resolved=Count(
                "id",
                filter=Q(status=(SupportTicket.StatusChoices.RESOLVED)),
            ),
            closed=Count(
                "id",
                filter=Q(status=(SupportTicket.StatusChoices.CLOSED)),
            ),
        )

        priority_summary = queryset.aggregate(
            low=Count(
                "id",
                filter=Q(priority=(SupportTicket.PriorityChoices.LOW)),
            ),
            normal=Count(
                "id",
                filter=Q(priority=(SupportTicket.PriorityChoices.NORMAL)),
            ),
            high=Count(
                "id",
                filter=Q(priority=(SupportTicket.PriorityChoices.HIGH)),
            ),
            urgent=Count(
                "id",
                filter=Q(priority=(SupportTicket.PriorityChoices.URGENT)),
            ),
        )

        category_summary = queryset.aggregate(
            order=Count(
                "id",
                filter=Q(category=(SupportTicket.CategoryChoices.ORDER)),
            ),
            payment=Count(
                "id",
                filter=Q(category=(SupportTicket.CategoryChoices.PAYMENT)),
            ),
            shipping=Count(
                "id",
                filter=Q(category=(SupportTicket.CategoryChoices.SHIPPING)),
            ),
            return_ticket=Count(
                "id",
                filter=Q(category=(SupportTicket.CategoryChoices.RETURN)),
            ),
            product=Count(
                "id",
                filter=Q(category=(SupportTicket.CategoryChoices.PRODUCT)),
            ),
            account=Count(
                "id",
                filter=Q(category=(SupportTicket.CategoryChoices.ACCOUNT)),
            ),
            other=Count(
                "id",
                filter=Q(category=(SupportTicket.CategoryChoices.OTHER)),
            ),
        )

        assigned_to_me_count = queryset.filter(assigned_to=request.user).count()

        unassigned_count = queryset.filter(assigned_to__isnull=True).count()

        return Response(
            {
                "status": status_summary,
                "priority": priority_summary,
                "category": category_summary,
                "assigned_to_me": (assigned_to_me_count),
                "unassigned": (unassigned_count),
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get"], url_path=r"attachments/(?P<attachment_id>[0-9]+)/download")
    def download_attachment(self, request, pk=None, attachment_id=None):
        ticket = self.get_object()
        attachment = ticket.attachments.filter(pk=attachment_id).first()
        if attachment is None:
            raise Http404

        try:
            stream = attachment.file.open("rb")
        except (FileNotFoundError, OSError, ValueError):
            raise Http404

        name = Path(attachment.original_filename).name or "attachment"
        extension = Path(name).suffix.lower()
        response = FileResponse(
            stream,
            content_type=SUPPORT_ATTACHMENT_MIME_TYPES.get(extension, "application/octet-stream"),
        )
        response["Content-Disposition"] = content_disposition_header(True, name)
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    @action(
        detail=True,
        methods=["get", "post"],
        url_path="attachments",
        parser_classes=[
            MultiPartParser,
            FormParser,
        ],
    )
    def attachments(
        self,
        request,
        pk=None,
    ):
        ticket = self.get_object()

        if request.method == "GET":
            serializer = TicketAttachmentSerializer(
                ticket.attachments.all(),
                many=True,
                context={
                    "request": request,
                },
            )

            return Response(
                serializer.data,
                status=status.HTTP_200_OK,
            )

        if ticket.status == SupportTicket.StatusChoices.CLOSED:
            return Response(
                {
                    "detail": (
                        "Cannot upload attachments to a closed "
                        "ticket. Reopen it first."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = TicketAttachmentSerializer(
            data=request.data,
            context={
                "request": request,
            },
        )

        serializer.is_valid(raise_exception=True)

        uploaded_file = serializer.validated_data["file"]

        attachment = TicketAttachment.objects.create(
            ticket=ticket,
            uploaded_by=request.user,
            file=uploaded_file,
            original_filename=getattr(
                uploaded_file,
                "name",
                "",
            ),
            content_type=SUPPORT_ATTACHMENT_MIME_TYPES[Path(uploaded_file.name).suffix.lower()],
            size=(
                getattr(
                    uploaded_file,
                    "size",
                    0,
                )
                or 0
            ),
        )

        TicketAuditLog.log(
            ticket=ticket,
            actor=request.user,
            action=(TicketAuditLog.ActionChoices.ATTACHMENT_ADDED),
            description="Attachment uploaded.",
            metadata={
                "attachment_id": (attachment.pk),
                "filename": (attachment.original_filename),
                "size": attachment.size,
            },
        )

        response_serializer = TicketAttachmentSerializer(
            attachment,
            context={
                "request": request,
            },
        )

        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="add-tag",
    )
    def add_tag(
        self,
        request,
        pk=None,
    ):
        ticket = self.get_object()

        serializer = TicketTagSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tag = serializer.validated_data["tag"]

        ticket.tags.add(tag)

        TicketAuditLog.log(
            ticket=ticket,
            actor=request.user,
            action=(TicketAuditLog.ActionChoices.TAG_ADDED),
            description=(f"Tag '{tag.name}' added."),
            metadata={
                "tag_id": tag.pk,
                "tag_name": tag.name,
            },
        )

        return Response(
            self.get_serializer(ticket).data,
            status=status.HTTP_200_OK,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="remove-tag",
    )
    def remove_tag(
        self,
        request,
        pk=None,
    ):
        ticket = self.get_object()

        serializer = TicketTagSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tag = serializer.validated_data["tag"]

        ticket.tags.remove(tag)

        TicketAuditLog.log(
            ticket=ticket,
            actor=request.user,
            action=(TicketAuditLog.ActionChoices.TAG_REMOVED),
            description=(f"Tag '{tag.name}' removed."),
            metadata={
                "tag_id": tag.pk,
                "tag_name": tag.name,
            },
        )

        return Response(
            self.get_serializer(ticket).data,
            status=status.HTTP_200_OK,
        )

    @action(
        detail=True,
        methods=["get"],
        url_path="audit-logs",
    )
    def audit_logs(
        self,
        request,
        pk=None,
    ):
        ticket = self.get_object()

        serializer = TicketAuditLogSerializer(
            ticket.audit_logs.all(),
            many=True,
        )

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="reply",
    )
    def reply(
        self,
        request,
        pk=None,
    ):
        ticket = self.get_object()

        if ticket.status == SupportTicket.StatusChoices.CLOSED:
            return Response(
                {"detail": ("Cannot reply to a closed " "ticket. Reopen it first.")},
                status=(status.HTTP_400_BAD_REQUEST),
            )

        serializer = TicketReplySerializer(
            data=request.data,
            context={
                "request": request,
                "ticket": ticket,
            },
        )

        serializer.is_valid(raise_exception=True)

        is_internal_note = serializer.validated_data.get(
            "is_internal_note",
            False,
        )

        message = TicketMessage.objects.create(
            ticket=ticket,
            sender=request.user,
            message=(serializer.validated_data["message"]),
            is_internal_note=(is_internal_note),
        )

        TicketAuditLog.log(
            ticket=ticket,
            actor=request.user,
            action=(
                TicketAuditLog.ActionChoices.INTERNAL_NOTE_CREATED
                if is_internal_note
                else (TicketAuditLog.ActionChoices.REPLIED)
            ),
            description=(
                "Internal note created." if is_internal_note else "Ticket reply added."
            ),
            metadata={
                "message_id": message.pk,
            },
        )

        update_fields = ["updated_at"]

        is_customer_reply = ticket.customer_id == request.user.id

        if not is_internal_note:
            ticket.last_message_at = timezone.now()

            update_fields.append("last_message_at")

            if is_customer_reply:
                ticket.status = SupportTicket.StatusChoices.OPEN
            else:
                ticket.status = SupportTicket.StatusChoices.PENDING

            update_fields.append("status")

        ticket.save(update_fields=update_fields)

        if not is_internal_note:
            if is_customer_reply:
                if ticket.assigned_to:
                    create_support_notification(
                        user=ticket.assigned_to,
                        ticket=ticket,
                        template_key=("support_ticket_" "customer_replied"),
                        ticket_number=(ticket.ticket_number),
                    )
            else:
                create_support_notification(
                    user=ticket.customer,
                    ticket=ticket,
                    template_key=("support_ticket_" "staff_replied"),
                    ticket_number=(ticket.ticket_number),
                )

        return Response(
            self.get_serializer(ticket).data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=False,
        methods=["get"],
        url_path="agents",
    )
    def agents(self, request):
        users = (
            User.objects.filter(is_active=True)
            .only(
                "id",
                "email",
                "full_name",
                "is_superuser",
            )
            .order_by(
                "full_name",
                "email",
            )
        )

        data = [
            {
                "id": user.id,
                "email": user.email,
                "full_name": user.full_name,
            }
            for user in users
            if can_be_assigned_support_ticket(user)
        ]

        return Response(
            data,
            status=status.HTTP_200_OK,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="assign",
    )
    def assign(
        self,
        request,
        pk=None,
    ):
        ticket = self.get_object()

        serializer = TicketAssignSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)

        ticket.assigned_to = serializer.validated_data["assigned_to"]

        ticket.save(
            update_fields=[
                "assigned_to",
                "updated_at",
            ]
        )

        TicketAuditLog.log(
            ticket=ticket,
            actor=request.user,
            action=(TicketAuditLog.ActionChoices.ASSIGNED),
            description=(f"Ticket assigned to " f"{ticket.assigned_to}."),
            metadata={
                "assigned_to_id": (ticket.assigned_to_id),
            },
        )

        create_support_notification(
            user=ticket.assigned_to,
            ticket=ticket,
            template_key=("support_ticket_assigned"),
            ticket_number=(ticket.ticket_number),
        )

        return Response(
            self.get_serializer(ticket).data,
            status=status.HTTP_200_OK,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="priority",
    )
    def priority(
        self,
        request,
        pk=None,
    ):
        ticket = self.get_object()

        serializer = TicketPrioritySerializer(data=request.data)

        serializer.is_valid(raise_exception=True)

        old_priority = ticket.priority

        ticket.priority = serializer.validated_data["priority"]

        ticket.save(
            update_fields=[
                "priority",
                "updated_at",
            ]
        )

        TicketAuditLog.log(
            ticket=ticket,
            actor=request.user,
            action=(TicketAuditLog.ActionChoices.PRIORITY_CHANGED),
            description=(
                "Ticket priority changed "
                f"from {old_priority} "
                f"to {ticket.priority}."
            ),
            metadata={
                "old_priority": old_priority,
                "new_priority": (ticket.priority),
            },
        )

        return Response(
            self.get_serializer(ticket).data,
            status=status.HTTP_200_OK,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="resolve",
    )
    def resolve(
        self,
        request,
        pk=None,
    ):
        ticket = self.get_object()

        ticket.mark_resolved()

        TicketAuditLog.log(
            ticket=ticket,
            actor=request.user,
            action=(TicketAuditLog.ActionChoices.RESOLVED),
            description="Ticket resolved.",
        )

        create_support_notification(
            user=ticket.customer,
            ticket=ticket,
            template_key=("support_ticket_resolved"),
            ticket_number=(ticket.ticket_number),
        )

        return Response(
            self.get_serializer(ticket).data,
            status=status.HTTP_200_OK,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="close",
    )
    def close(
        self,
        request,
        pk=None,
    ):
        ticket = self.get_object()

        ticket.close()

        TicketAuditLog.log(
            ticket=ticket,
            actor=request.user,
            action=(TicketAuditLog.ActionChoices.CLOSED),
            description="Ticket closed.",
        )

        create_support_notification(
            user=ticket.customer,
            ticket=ticket,
            template_key=("support_ticket_closed"),
            ticket_number=(ticket.ticket_number),
        )

        return Response(
            self.get_serializer(ticket).data,
            status=status.HTTP_200_OK,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="reopen",
    )
    def reopen(
        self,
        request,
        pk=None,
    ):
        ticket = self.get_object()

        ticket.reopen()

        TicketAuditLog.log(
            ticket=ticket,
            actor=request.user,
            action=(TicketAuditLog.ActionChoices.REOPENED),
            description="Ticket reopened.",
        )

        create_support_notification(
            user=ticket.customer,
            ticket=ticket,
            template_key=("support_ticket_reopened"),
            ticket_number=(ticket.ticket_number),
        )

        return Response(
            self.get_serializer(ticket).data,
            status=status.HTTP_200_OK,
        )
