from typing import cast

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.notifications.models import Notification
from apps.notifications.services import create_notification


class NotificationPaginationTests(APITestCase):
    def setUp(self):
        self.user = User(
            phone="+989300000010",
            email="notification_pagination@example.com",
            full_name="Notification Pagination User",
            is_active=True,
        )
        self.user.set_password("testpass123")
        self.user.save()

        for index in range(5):
            create_notification(
                user=self.user,
                title=f"Notification {index}",
                message=f"Message {index}",
                notification_type=Notification.NotificationType.SYSTEM,
            )

        self.get_api_client().force_authenticate(user=self.user)

    def get_api_client(self) -> APIClient:
        return cast(APIClient, self.client)

    def test_notification_list_respects_page_size_query_param(self):
        response = self.client.get(
            reverse("notification-list"),
            {"page_size": 2},
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        data = response.json()

        self.assertEqual(data["count"], 5)
        self.assertEqual(len(data["results"]), 2)
        self.assertIsNotNone(data["next"])

    def test_notification_list_uses_default_page_size(self):
        for index in range(20):
            create_notification(
                user=self.user,
                title=f"Extra notification {index}",
                message=f"Extra message {index}",
                notification_type=Notification.NotificationType.SYSTEM,
            )

        response = self.client.get(
            reverse("notification-list"),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        data = response.json()

        self.assertEqual(data["count"], 25)
        self.assertEqual(len(data["results"]), 20)
        self.assertIsNotNone(data["next"])
