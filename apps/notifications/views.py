from django.contrib.auth.models import AnonymousUser
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.notifications.models import Notification
from apps.notifications.serializers import NotificationSerializer
from apps.notifications.services import (
    get_unread_notification_count,
    mark_all_notifications_as_read,
    mark_notification_as_read,
    mark_notification_as_unread,
)


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
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

    def get_queryset(self):
        queryset = Notification.objects.select_related("user").all()

        user = self.request.user

        if isinstance(user, AnonymousUser):
            return queryset.none()

        if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
            return queryset

        return queryset.filter(user=user)

    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        count = get_unread_notification_count(user=request.user)

        return Response(
            {
                "unread_count": count,
            },
            status=status.HTTP_200_OK,
        )

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
