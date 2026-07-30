from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.notifications.models import Notification, NotificationPreference
from apps.notifications.services import create_notification


class NotificationFullWorkflowTests(APITestCase):
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
            phone="+989880000001",
            email="notification_full_workflow_user@example.com",
            full_name="Notification Full Workflow User",
        )

        self.other_user = self.create_test_user(
            phone="+989880000002",
            email="other_notification_full_workflow_user@example.com",
            full_name="Other Notification Full Workflow User",
        )

    def authenticate_user(self):
        self.client.force_authenticate(user=self.user)

    def test_full_notification_workflow(self):
        order_notification = create_notification(
            user=self.user,
            title="Order created",
            message="Your order has been created.",
            notification_type=Notification.NotificationType.ORDER,
            priority=Notification.Priority.NORMAL,
        )

        payment_notification = create_notification(
            user=self.user,
            title="Payment failed",
            message="Your payment failed.",
            notification_type=Notification.NotificationType.PAYMENT,
            priority=Notification.Priority.HIGH,
        )

        read_system_notification = create_notification(
            user=self.user,
            title="System message",
            message="System message for user.",
            notification_type=Notification.NotificationType.SYSTEM,
            priority=Notification.Priority.LOW,
        )
        read_system_notification.mark_as_read()

        other_user_notification = create_notification(
            user=self.other_user,
            title="Other user notification",
            message="This belongs to another user.",
            notification_type=Notification.NotificationType.SYSTEM,
            priority=Notification.Priority.NORMAL,
        )

        self.authenticate_user()

        unread_count_url = reverse("notification-unread-count")

        unread_count_response = self.client.get(unread_count_url)

        self.assertEqual(unread_count_response.status_code, status.HTTP_200_OK)
        self.assertEqual(unread_count_response.json()["unread_count"], 2)

        summary_url = reverse("notification-summary")

        summary_response = self.client.get(summary_url)

        self.assertEqual(summary_response.status_code, status.HTTP_200_OK)

        summary_data = summary_response.json()

        self.assertEqual(summary_data["total_count"], 3)
        self.assertEqual(summary_data["unread_count"], 2)
        self.assertEqual(summary_data["read_count"], 1)

        self.assertEqual(
            summary_data["by_type"][Notification.NotificationType.ORDER], 1
        )
        self.assertEqual(
            summary_data["by_type"][Notification.NotificationType.PAYMENT], 1
        )
        self.assertEqual(
            summary_data["by_type"][Notification.NotificationType.SYSTEM], 1
        )

        self.assertEqual(summary_data["by_priority"][Notification.Priority.NORMAL], 1)
        self.assertEqual(summary_data["by_priority"][Notification.Priority.HIGH], 1)
        self.assertEqual(summary_data["by_priority"][Notification.Priority.LOW], 1)

        mark_all_read_url = reverse("notification-mark-all-read")

        mark_all_read_response = self.client.post(
            mark_all_read_url,
            data={},
            format="json",
        )

        self.assertEqual(mark_all_read_response.status_code, status.HTTP_200_OK)
        self.assertEqual(mark_all_read_response.json()["marked_count"], 2)

        order_notification.refresh_from_db()
        payment_notification.refresh_from_db()
        read_system_notification.refresh_from_db()
        other_user_notification.refresh_from_db()

        self.assertTrue(order_notification.is_read)
        self.assertTrue(payment_notification.is_read)
        self.assertTrue(read_system_notification.is_read)

        self.assertFalse(other_user_notification.is_read)

        clear_read_url = reverse("notification-clear-read")

        clear_read_response = self.client.delete(clear_read_url)

        self.assertEqual(clear_read_response.status_code, status.HTTP_200_OK)
        self.assertEqual(clear_read_response.json()["deleted_count"], 3)

        self.assertFalse(Notification.objects.filter(pk=order_notification.pk).exists())
        self.assertFalse(
            Notification.objects.filter(pk=payment_notification.pk).exists()
        )
        self.assertFalse(
            Notification.objects.filter(pk=read_system_notification.pk).exists()
        )

        self.assertTrue(
            Notification.objects.filter(pk=other_user_notification.pk).exists()
        )

        preference, _ = NotificationPreference.objects.get_or_create(
            user=self.user,
        )
        preference.muted_notification_types = [
            Notification.NotificationType.SYSTEM,
        ]
        preference.save(update_fields=["muted_notification_types", "updated_at"])

        blocked_notification = create_notification(
            user=self.user,
            title="Blocked system notification",
            message="This notification should be blocked.",
            notification_type=Notification.NotificationType.SYSTEM,
            priority=Notification.Priority.NORMAL,
        )

        self.assertIsNone(blocked_notification)

        self.assertFalse(
            Notification.objects.filter(
                user=self.user,
                title="Blocked system notification",
            ).exists()
        )
