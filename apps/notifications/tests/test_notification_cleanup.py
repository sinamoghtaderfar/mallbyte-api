from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.notifications.models import Notification
from apps.notifications.services import delete_old_read_notifications


class NotificationCleanupTests(TestCase):
    def create_test_user(
        self,
        *,
        phone,
        email,
        full_name,
        password="testpass123",
    ):
        user = User(
            phone=phone,
            email=email,
            full_name=full_name,
            is_active=True,
        )
        user.set_password(password)
        user.save()
        return user

    def setUp(self):
        self.user = self.create_test_user(
            phone="+989800000001",
            email="notification_cleanup_user@example.com",
            full_name="Notification Cleanup User",
        )

        self.other_user = self.create_test_user(
            phone="+989800000002",
            email="other_notification_cleanup_user@example.com",
            full_name="Other Notification Cleanup User",
        )

    def create_notification(self, *, user, title, is_read, days_old):
        notification = Notification.objects.create(
            user=user,
            title=title,
            message="Cleanup test message",
            notification_type=Notification.NotificationType.SYSTEM,
            priority=Notification.Priority.NORMAL,
            is_read=is_read,
        )

        old_created_at = timezone.now() - timedelta(days=days_old)

        Notification.objects.filter(pk=notification.pk).update(
            created_at=old_created_at,
        )

        notification.refresh_from_db()

        return notification

    def test_delete_old_read_notifications_deletes_only_old_read_notifications(self):
        old_read_notification = self.create_notification(
            user=self.user,
            title="Old read notification",
            is_read=True,
            days_old=40,
        )

        old_unread_notification = self.create_notification(
            user=self.user,
            title="Old unread notification",
            is_read=False,
            days_old=40,
        )

        recent_read_notification = self.create_notification(
            user=self.user,
            title="Recent read notification",
            is_read=True,
            days_old=5,
        )

        deleted_count = delete_old_read_notifications(days=30)

        self.assertEqual(deleted_count, 1)

        self.assertFalse(
            Notification.objects.filter(pk=old_read_notification.pk).exists()
        )

        self.assertTrue(
            Notification.objects.filter(pk=old_unread_notification.pk).exists()
        )

        self.assertTrue(
            Notification.objects.filter(pk=recent_read_notification.pk).exists()
        )

    def test_delete_old_read_notifications_can_filter_by_user(self):
        user_old_read_notification = self.create_notification(
            user=self.user,
            title="User old read notification",
            is_read=True,
            days_old=40,
        )

        other_user_old_read_notification = self.create_notification(
            user=self.other_user,
            title="Other user old read notification",
            is_read=True,
            days_old=40,
        )

        deleted_count = delete_old_read_notifications(
            days=30,
            user=self.user,
        )

        self.assertEqual(deleted_count, 1)

        self.assertFalse(
            Notification.objects.filter(pk=user_old_read_notification.pk).exists()
        )

        self.assertTrue(
            Notification.objects.filter(pk=other_user_old_read_notification.pk).exists()
        )

    def test_delete_old_read_notifications_rejects_invalid_days(self):
        with self.assertRaises(ValueError):
            delete_old_read_notifications(days=0)

        with self.assertRaises(ValueError):
            delete_old_read_notifications(days=-1)
