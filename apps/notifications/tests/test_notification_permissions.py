from typing import Any, cast

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.notifications.models import Notification


class NotificationPermissionTests(APITestCase):
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
            phone="+989860000001",
            email="notification_permission_user@example.com",
            full_name="Notification Permission User",
        )

        self.other_user = self.create_test_user(
            phone="+989860000002",
            email="other_notification_permission_user@example.com",
            full_name="Other Notification Permission User",
        )

        self.admin_user = self.create_test_user(
            phone="+989860000003",
            email="admin_notification_permission@example.com",
            full_name="Notification Permission Admin",
            is_staff=True,
            is_superuser=True,
        )

        self.user_notification = Notification.objects.create(
            user=self.user,
            title="User notification",
            message="This belongs to the main user.",
            notification_type=Notification.NotificationType.ORDER,
            priority=Notification.Priority.NORMAL,
            is_read=False,
        )

        self.user_read_notification = Notification.objects.create(
            user=self.user,
            title="User read notification",
            message="This belongs to the main user and is read.",
            notification_type=Notification.NotificationType.PAYMENT,
            priority=Notification.Priority.HIGH,
            is_read=True,
        )

        self.other_notification = Notification.objects.create(
            user=self.other_user,
            title="Other user notification",
            message="This belongs to another user.",
            notification_type=Notification.NotificationType.SYSTEM,
            priority=Notification.Priority.NORMAL,
            is_read=False,
        )

    def get_api_client(self) -> APIClient:
        return cast(APIClient, self.client)

    def authenticate_user(self):
        self.get_api_client().force_authenticate(user=self.user)

    def authenticate_admin(self):
        self.get_api_client().force_authenticate(user=self.admin_user)

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

    def test_user_cannot_retrieve_other_user_notification(self):
        self.authenticate_user()

        url = reverse("notification-detail", args=[self.other_notification.pk])

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_user_cannot_mark_other_user_notification_as_read(self):
        self.authenticate_user()

        url = reverse("notification-mark-read", args=[self.other_notification.pk])

        response = self.client.post(url, data={}, format="json")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        self.other_notification.refresh_from_db()

        self.assertFalse(self.other_notification.is_read)

    def test_user_cannot_mark_other_user_notification_as_unread(self):
        self.other_notification.mark_as_read()
        self.other_notification.refresh_from_db()

        self.assertTrue(self.other_notification.is_read)

        self.authenticate_user()

        url = reverse("notification-mark-unread", args=[self.other_notification.pk])

        response = self.client.post(url, data={}, format="json")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        self.other_notification.refresh_from_db()

        self.assertTrue(self.other_notification.is_read)

    def test_user_cannot_delete_other_user_notification(self):
        self.authenticate_user()

        url = reverse("notification-detail", args=[self.other_notification.pk])

        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        self.assertTrue(
            Notification.objects.filter(pk=self.other_notification.pk).exists()
        )

    def test_staff_can_list_all_notifications(self):
        self.authenticate_admin()

        url = reverse("notification-list")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        items = self.get_response_items(response)
        ids = [item["id"] for item in items]

        self.assertIn(self.user_notification.pk, ids)
        self.assertIn(self.user_read_notification.pk, ids)
        self.assertIn(self.other_notification.pk, ids)

    def test_staff_can_retrieve_other_user_notification(self):
        self.authenticate_admin()

        url = reverse("notification-detail", args=[self.other_notification.pk])

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertEqual(data["id"], self.other_notification.pk)

    def test_direct_notification_create_is_not_allowed(self):
        self.authenticate_user()

        before_count = Notification.objects.count()

        url = reverse("notification-list")

        response = self.client.post(
            url,
            data={
                "title": "Fake notification",
                "message": "This should not be created directly.",
                "notification_type": Notification.NotificationType.SYSTEM,
                "priority": Notification.Priority.NORMAL,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        data = response.json()

        self.assertEqual(
            data["detail"],
            "Creating notifications directly is not allowed.",
        )

        self.assertEqual(Notification.objects.count(), before_count)
