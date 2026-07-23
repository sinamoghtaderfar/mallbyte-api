from typing import cast

from django.contrib.auth.models import AnonymousUser
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.notifications.models import Notification
from apps.notifications.serializers import NotificationSerializer
from apps.notifications.services import (
    delete_all_notifications,
    delete_read_notifications,
    delete_selected_notifications,
    get_notification_summary,
    get_unread_notification_count,
    mark_all_notifications_as_read,
    mark_notification_as_read,
    mark_notification_as_unread,
    mark_selected_notifications_as_read,
    mark_selected_notifications_as_unread,
)


class NotificationViewSet(viewsets.ModelViewSet):
    """
    Notification API.

    Users can:
    - list own notifications
    - retrieve own notification
    - mark one notification as read
    - mark one notification as unread
    - mark all notifications as read
    - get unread count

    Admins can see all notifications.
    """

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        queryset = Notification.objects.select_related("user").all()
        user = self.request.user

        if isinstance(user, AnonymousUser):
            return queryset.none()

        if not (
            getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)
        ):
            queryset = queryset.filter(user=user)

        request = cast(Request, self.request)

        notification_type = request.query_params.get("notification_type")
        channel = request.query_params.get("channel")
        priority = request.query_params.get("priority")
        is_read = request.query_params.get("is_read")

        if notification_type:
            queryset = queryset.filter(notification_type=notification_type)

        if channel:
            queryset = queryset.filter(channel=channel)

        if priority:
            queryset = queryset.filter(priority=priority)

        if is_read is not None:
            if is_read.lower() == "true":
                queryset = queryset.filter(is_read=True)
            elif is_read.lower() == "false":
                queryset = queryset.filter(is_read=False)

        return queryset

    def create(self, request, *args, **kwargs):
        return Response(
            {"detail": "Creating notifications directly is not allowed."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        count = get_unread_notification_count(user=request.user)

        return Response(
            {
                "unread_count": count,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        summary_data = get_notification_summary(user=request.user)

        return Response(summary_data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="mark-read")
    def mark_read(self, request, pk=None):
        notification = self.get_object()

        try:
            mark_notification_as_read(
                notification=notification,
                user=request.user,
            )
        except PermissionError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = self.get_serializer(notification)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="mark-unread")
    def mark_unread(self, request, pk=None):
        notification = self.get_object()

        try:
            mark_notification_as_unread(
                notification=notification,
                user=request.user,
            )
        except PermissionError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = self.get_serializer(notification)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="mark-all-read")
    def mark_all_read(self, request):
        marked_count = mark_all_notifications_as_read(user=request.user)

        return Response(
            {
                "marked_count": marked_count,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["post"], url_path="mark-selected-read")
    def mark_selected_read(self, request):
        notification_ids = request.data.get("ids", [])

        if not isinstance(notification_ids, list):
            return Response(
                {"detail": "ids must be a list."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        marked_count = mark_selected_notifications_as_read(
            user=request.user,
            notification_ids=notification_ids,
        )

        return Response(
            {"marked_count": marked_count},
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["post"], url_path="mark-selected-unread")
    def mark_selected_unread(self, request):
        notification_ids = request.data.get("ids", [])

        if not isinstance(notification_ids, list):
            return Response(
                {"detail": "ids must be a list."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        marked_count = mark_selected_notifications_as_unread(
            user=request.user,
            notification_ids=notification_ids,
        )

        return Response(
            {"marked_count": marked_count},
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["post"], url_path="delete-selected")
    def delete_selected(self, request):
        notification_ids = request.data.get("ids", [])

        if not isinstance(notification_ids, list):
            return Response(
                {"detail": "ids must be a list."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        deleted_count = delete_selected_notifications(
            user=request.user,
            notification_ids=notification_ids,
        )

        return Response(
            {"deleted_count": deleted_count},
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["delete"], url_path="clear-read")
    def clear_read(self, request):
        deleted_count = delete_read_notifications(user=request.user)

        return Response(
            {"deleted_count": deleted_count},
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["delete"], url_path="clear-all")
    def clear_all(self, request):
        deleted_count = delete_all_notifications(user=request.user)

        return Response(
            {"deleted_count": deleted_count},
            status=status.HTTP_200_OK,
        )
