from django.test import TestCase

from apps.accounts.models import User
from apps.notifications.models import Notification, NotificationPreference
from apps.notifications.services import create_notification


class NotificationPreferenceTests(TestCase):
    def create_test_user(
        self,
        *,
        phone,
        email,
        full_name,
        password="testpass123",
        is_staff=False,
        is_superuser=False,
    ):
        user = User(
            phone=phone,
            email=email,
            full_name=full_name,
            is_active=True,
            is_staff=is_staff,
            is_superuser=is_superuser,
        )
        user.set_password(password)
        user.save()
        return user

    def setUp(self):
        self.user = self.create_test_user(
            phone="+989700000001",
            email="notification_pref_user@example.com",
            full_name="Notification Preference User",
        )

    def test_create_notification_creates_default_preference_when_allowed(self):
        self.assertFalse(NotificationPreference.objects.filter(user=self.user).exists())

        notification = create_notification(
            user=self.user,
            title="Allowed notification",
            message="This notification should be created.",
            notification_type=Notification.NotificationType.ORDER,
            channel=Notification.Channel.IN_APP,
            priority=Notification.Priority.NORMAL,
        )

        self.assertIsNotNone(notification)

        self.assertTrue(NotificationPreference.objects.filter(user=self.user).exists())

        self.assertTrue(
            Notification.objects.filter(
                user=self.user,
                title="Allowed notification",
                notification_type=Notification.NotificationType.ORDER,
                channel=Notification.Channel.IN_APP,
            ).exists()
        )

    def test_muted_notification_type_blocks_notification_creation(self):
        NotificationPreference.objects.create(
            user=self.user,
            muted_notification_types=[
                Notification.NotificationType.ORDER,
            ],
        )

        notification = create_notification(
            user=self.user,
            title="Muted order notification",
            message="This notification should not be created.",
            notification_type=Notification.NotificationType.ORDER,
            channel=Notification.Channel.IN_APP,
            priority=Notification.Priority.NORMAL,
        )

        self.assertIsNone(notification)

        self.assertFalse(
            Notification.objects.filter(
                user=self.user,
                title="Muted order notification",
            ).exists()
        )

    def test_muted_channel_blocks_notification_creation(self):
        NotificationPreference.objects.create(
            user=self.user,
            muted_channels=[
                Notification.Channel.IN_APP,
            ],
        )

        notification = create_notification(
            user=self.user,
            title="Muted channel notification",
            message="This notification should not be created.",
            notification_type=Notification.NotificationType.SYSTEM,
            channel=Notification.Channel.IN_APP,
            priority=Notification.Priority.NORMAL,
        )

        self.assertIsNone(notification)

        self.assertFalse(
            Notification.objects.filter(
                user=self.user,
                title="Muted channel notification",
            ).exists()
        )

    def test_disabled_email_channel_blocks_email_notification(self):
        NotificationPreference.objects.create(
            user=self.user,
            email_enabled=False,
        )

        notification = create_notification(
            user=self.user,
            title="Email notification",
            message="This email notification should not be created.",
            notification_type=Notification.NotificationType.SYSTEM,
            channel=Notification.Channel.EMAIL,
            priority=Notification.Priority.NORMAL,
        )

        self.assertIsNone(notification)

        self.assertFalse(
            Notification.objects.filter(
                user=self.user,
                title="Email notification",
                channel=Notification.Channel.EMAIL,
            ).exists()
        )

    def test_disabled_in_app_channel_blocks_in_app_notification(self):
        NotificationPreference.objects.create(
            user=self.user,
            in_app_enabled=False,
        )

        notification = create_notification(
            user=self.user,
            title="In-app notification",
            message="This in-app notification should not be created.",
            notification_type=Notification.NotificationType.SYSTEM,
            channel=Notification.Channel.IN_APP,
            priority=Notification.Priority.NORMAL,
        )

        self.assertIsNone(notification)

        self.assertFalse(
            Notification.objects.filter(
                user=self.user,
                title="In-app notification",
                channel=Notification.Channel.IN_APP,
            ).exists()
        )
