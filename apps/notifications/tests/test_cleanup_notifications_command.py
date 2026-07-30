from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.notifications.models import Notification


class CleanupNotificationsCommandTests(TestCase):
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
            phone="+989810000001",
            email="cleanup_command_user@example.com",
            full_name="Cleanup Command User",
        )

    def create_notification(self, *, user, title, is_read, days_old):
        notification = Notification.objects.create(
            user=user,
            title=title,
            message="Cleanup command test message",
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

    def test_cleanup_notifications_command_deletes_old_read_notifications(self):
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

        output = StringIO()

        call_command(
            "cleanup_notifications",
            "--days",
            "30",
            stdout=output,
        )

        self.assertIn(
            "Deleted 1 old read notifications.",
            output.getvalue(),
        )

        self.assertFalse(
            Notification.objects.filter(pk=old_read_notification.pk).exists()
        )

        self.assertTrue(
            Notification.objects.filter(pk=old_unread_notification.pk).exists()
        )

    def test_cleanup_notifications_command_can_filter_by_user_id(self):
        other_user = self.create_test_user(
            phone="+989810000002",
            email="other_cleanup_command_user@example.com",
            full_name="Other Cleanup Command User",
        )

        user_notification = self.create_notification(
            user=self.user,
            title="User old read notification",
            is_read=True,
            days_old=40,
        )

        other_user_notification = self.create_notification(
            user=other_user,
            title="Other user old read notification",
            is_read=True,
            days_old=40,
        )

        output = StringIO()

        call_command(
            "cleanup_notifications",
            "--days",
            "30",
            "--user-id",
            str(self.user.pk),
            stdout=output,
        )

        self.assertIn(
            f"Deleted 1 old read notifications for user {self.user.pk}.",
            output.getvalue(),
        )

        self.assertFalse(Notification.objects.filter(pk=user_notification.pk).exists())

        self.assertTrue(
            Notification.objects.filter(pk=other_user_notification.pk).exists()
        )

    def test_cleanup_notifications_command_rejects_invalid_days(self):
        with self.assertRaises(CommandError):
            call_command(
                "cleanup_notifications",
                "--days",
                "0",
            )

    def test_cleanup_notifications_command_rejects_missing_user(self):
        with self.assertRaises(CommandError):
            call_command(
                "cleanup_notifications",
                "--user-id",
                "999999",
            )
