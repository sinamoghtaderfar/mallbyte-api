from datetime import timedelta
from typing import Any, cast

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.notifications.models import Notification


class NotificationFiltersAndOrderingTests(APITestCase):
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
            phone="+989870000001",
            email="notification_filter_user@example.com",
            full_name="Notification Filter User",
        )

        self.other_user = self.create_test_user(
            phone="+989870000002",
            email="other_notification_filter_user@example.com",
            full_name="Other Notification Filter User",
        )

    def get_api_client(self) -> APIClient:
        return cast(APIClient, self.client)

    def authenticate_user(self):
        self.get_api_client().force_authenticate(user=self.user)

    def get_response_items(self, response) -> list[dict[str, Any]]:
        data = response.json()

        if isinstance(data, dict) and "results" in data:
            results = data["results"]

            if isinstance(results, list):
                return results

            return []

        if isinstance(data, list):
            return data

        return []

    def create_notification(
        self,
        *,
        user,
        title,
        notification_type=Notification.NotificationType.SYSTEM,
        channel=Notification.Channel.IN_APP,
        priority=Notification.Priority.NORMAL,
        is_read=False,
        created_at=None,
    ):
        notification = Notification.objects.create(
            user=user,
            title=title,
            message=f"{title} message",
            notification_type=notification_type,
            channel=channel,
            priority=priority,
            is_read=is_read,
        )

        if created_at is not None:
            Notification.objects.filter(pk=notification.pk).update(
                created_at=created_at,
            )
            notification.refresh_from_db()

        return notification

    def test_user_can_filter_notifications_by_notification_type(self):
        product_notification = self.create_notification(
            user=self.user,
            title="Product notification",
            notification_type=Notification.NotificationType.PRODUCT,
        )

        order_notification = self.create_notification(
            user=self.user,
            title="Order notification",
            notification_type=Notification.NotificationType.ORDER,
        )

        other_user_product_notification = self.create_notification(
            user=self.other_user,
            title="Other user product notification",
            notification_type=Notification.NotificationType.PRODUCT,
        )

        self.authenticate_user()

        url = reverse("notification-list")

        response = self.client.get(
            url,
            {
                "notification_type": Notification.NotificationType.PRODUCT,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        items = self.get_response_items(response)
        ids = [item["id"] for item in items]

        self.assertIn(product_notification.pk, ids)
        self.assertNotIn(order_notification.pk, ids)
        self.assertNotIn(other_user_product_notification.pk, ids)

    def test_user_can_filter_notifications_by_channel(self):
        in_app_notification = self.create_notification(
            user=self.user,
            title="In app notification",
            channel=Notification.Channel.IN_APP,
        )

        email_notification = self.create_notification(
            user=self.user,
            title="Email notification",
            channel=Notification.Channel.EMAIL,
        )

        self.authenticate_user()

        url = reverse("notification-list")

        response = self.client.get(
            url,
            {
                "channel": Notification.Channel.IN_APP,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        items = self.get_response_items(response)
        ids = [item["id"] for item in items]

        self.assertIn(in_app_notification.pk, ids)
        self.assertNotIn(email_notification.pk, ids)

    def test_user_can_filter_notifications_by_priority(self):
        high_notification = self.create_notification(
            user=self.user,
            title="High notification",
            priority=Notification.Priority.HIGH,
        )

        normal_notification = self.create_notification(
            user=self.user,
            title="Normal notification",
            priority=Notification.Priority.NORMAL,
        )

        self.authenticate_user()

        url = reverse("notification-list")

        response = self.client.get(
            url,
            {
                "priority": Notification.Priority.HIGH,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        items = self.get_response_items(response)
        ids = [item["id"] for item in items]

        self.assertIn(high_notification.pk, ids)
        self.assertNotIn(normal_notification.pk, ids)

    def test_user_can_filter_notifications_by_is_read_true(self):
        read_notification = self.create_notification(
            user=self.user,
            title="Read notification",
            is_read=True,
        )

        unread_notification = self.create_notification(
            user=self.user,
            title="Unread notification",
            is_read=False,
        )

        self.authenticate_user()

        url = reverse("notification-list")

        response = self.client.get(
            url,
            {
                "is_read": "true",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        items = self.get_response_items(response)
        ids = [item["id"] for item in items]

        self.assertIn(read_notification.pk, ids)
        self.assertNotIn(unread_notification.pk, ids)

    def test_user_can_filter_notifications_by_is_read_false(self):
        read_notification = self.create_notification(
            user=self.user,
            title="Read notification",
            is_read=True,
        )

        unread_notification = self.create_notification(
            user=self.user,
            title="Unread notification",
            is_read=False,
        )

        self.authenticate_user()

        url = reverse("notification-list")

        response = self.client.get(
            url,
            {
                "is_read": "false",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        items = self.get_response_items(response)
        ids = [item["id"] for item in items]

        self.assertIn(unread_notification.pk, ids)
        self.assertNotIn(read_notification.pk, ids)

    def test_notifications_are_ordered_by_newest_first(self):
        now = timezone.now()

        old_notification = self.create_notification(
            user=self.user,
            title="Old notification",
            created_at=now - timedelta(days=3),
        )

        middle_notification = self.create_notification(
            user=self.user,
            title="Middle notification",
            created_at=now - timedelta(days=2),
        )

        newest_notification = self.create_notification(
            user=self.user,
            title="Newest notification",
            created_at=now - timedelta(days=1),
        )

        self.authenticate_user()

        url = reverse("notification-list")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        items = self.get_response_items(response)
        ids = [item["id"] for item in items]

        self.assertEqual(
            ids[:3],
            [
                newest_notification.pk,
                middle_notification.pk,
                old_notification.pk,
            ],
        )
