from django.db import transaction
from django.db.models import Count

from apps.notifications.models import Notification


def create_notification(
    *,
    user,
    title,
    message,
    notification_type=Notification.NotificationType.SYSTEM,
    channel=Notification.Channel.IN_APP,
    priority=Notification.Priority.NORMAL,
    related_object_type="",
    related_object_id="",
    action_url="",
    metadata=None,
):
    """
    Create a notification for a user.

    MVP:
    - only creates in-app notification
    - later we can add email / sms / push here
    """

    if metadata is None:
        metadata = {}

    return Notification.objects.create(
        user=user,
        title=title,
        message=message,
        notification_type=notification_type,
        channel=channel,
        priority=priority,
        related_object_type=related_object_type or "",
        related_object_id=str(related_object_id) if related_object_id else "",
        action_url=action_url or "",
        metadata=metadata,
    )


def mark_notification_as_read(*, notification, user):
    """
    Mark one notification as read.
    Normal user can only mark own notifications.
    """

    if notification.user_id != user.id and not (user.is_staff or user.is_superuser):
        raise PermissionError("You cannot update this notification.")

    notification.mark_as_read()
    return notification


def mark_notification_as_unread(*, notification, user):
    """
    Mark one notification as unread.
    Normal user can only mark own notifications.
    """

    if notification.user_id != user.id and not (user.is_staff or user.is_superuser):
        raise PermissionError("You cannot update this notification.")

    notification.mark_as_unread()
    return notification


@transaction.atomic
def mark_all_notifications_as_read(*, user):
    """
    Mark all unread notifications of current user as read.
    """

    unread_notifications = Notification.objects.select_for_update().filter(
        user=user,
        is_read=False,
    )

    count = unread_notifications.count()

    for notification in unread_notifications:
        notification.mark_as_read()

    return count


def get_unread_notification_count(*, user):
    """
    Count unread notifications of current user.
    """

    return Notification.objects.filter(
        user=user,
        is_read=False,
    ).count()


def delete_read_notifications(*, user):
    read_notifications = Notification.objects.filter(
        user=user,
        is_read=True,
    )

    count = read_notifications.count()
    read_notifications.delete()

    return count


def delete_all_notifications(*, user):
    notifications = Notification.objects.filter(user=user)

    count = notifications.count()
    notifications.delete()

    return count


def get_notification_summary(*, user):
    notifications = Notification.objects.filter(user=user)

    by_type = {
        item["notification_type"]: item["count"]
        for item in notifications.values("notification_type").annotate(
            count=Count("id")
        )
    }

    by_priority = {
        item["priority"]: item["count"]
        for item in notifications.values("priority").annotate(count=Count("id"))
    }

    total_count = notifications.count()
    unread_count = notifications.filter(is_read=False).count()
    read_count = notifications.filter(is_read=True).count()

    return {
        "total_count": total_count,
        "unread_count": unread_count,
        "read_count": read_count,
        "by_type": by_type,
        "by_priority": by_priority,
    }


def mark_selected_notifications_as_read(*, user, notification_ids):
    notifications = Notification.objects.filter(
        user=user,
        id__in=notification_ids,
        is_read=False,
    )

    count = notifications.count()

    for notification in notifications:
        notification.mark_as_read()

    return count


def delete_selected_notifications(*, user, notification_ids):
    notifications = Notification.objects.filter(
        user=user,
        id__in=notification_ids,
    )

    count = notifications.count()
    notifications.delete()

    return count


def mark_selected_notifications_as_unread(*, user, notification_ids):
    notifications = Notification.objects.filter(
        user=user,
        id__in=notification_ids,
        is_read=True,
    )

    count = notifications.count()

    for notification in notifications:
        notification.mark_as_unread()

    return count
