from typing import Any, cast

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.notifications.models import Notification
from apps.notifications.services import create_notification


class NotificationAPITests(APITestCase):
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
            phone="+989300000001",
            email="notification_user@example.com",
            full_name="Notification User",
        )

        self.other_user = self.create_test_user(
            phone="+989300000002",
            email="other_notification_user@example.com",
            full_name="Other Notification User",
        )

        self.admin_user = self.create_test_user(
            phone="+989300000003",
            email="notification_admin@example.com",
            full_name="Notification Admin",
            is_staff=True,
            is_superuser=True,
        )

        self.notification = create_notification(
            user=self.user,
            title="Order created",
            message="Your order has been created.",
            notification_type=Notification.NotificationType.ORDER,
            priority=Notification.Priority.NORMAL,
            related_object_type="order",
            related_object_id="1",
            action_url="/orders/1/",
        )

        self.read_notification = create_notification(
            user=self.user,
            title="Payment successful",
            message="Your payment was successful.",
            notification_type=Notification.NotificationType.PAYMENT,
            priority=Notification.Priority.HIGH,
            related_object_type="payment",
            related_object_id="1",
        )
        self.read_notification.mark_as_read()

        self.other_notification = create_notification(
            user=self.other_user,
            title="Other user notification",
            message="This notification belongs to another user.",
            notification_type=Notification.NotificationType.PRODUCT,
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

    def test_user_can_list_only_own_notifications(self):
        self.authenticate_user()

        url = reverse("notification-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        items = self.get_response_items(response)
        ids = [item["id"] for item in items]

        self.assertIn(self.notification.pk, ids)
        self.assertIn(self.read_notification.pk, ids)
        self.assertNotIn(self.other_notification.pk, ids)

    def test_user_can_retrieve_own_notification(self):
        self.authenticate_user()

        url = reverse("notification-detail", args=[self.notification.pk])
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertEqual(data["id"], self.notification.pk)
        self.assertEqual(data["title"], "Order created")
        self.assertEqual(data["message"], "Your order has been created.")
        self.assertEqual(data["notification_type"], Notification.NotificationType.ORDER)
        self.assertEqual(data["priority"], Notification.Priority.NORMAL)
        self.assertEqual(data["is_read"], False)

    def test_user_cannot_retrieve_other_user_notification(self):
        self.authenticate_user()

        url = reverse("notification-detail", args=[self.other_notification.pk])
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_unread_count_returns_only_current_user_unread_notifications(self):
        self.authenticate_user()

        url = reverse("notification-unread-count")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertEqual(data["unread_count"], 1)

    def test_user_can_mark_notification_as_read(self):
        self.authenticate_user()

        url = reverse("notification-mark-read", args=[self.notification.pk])
        response = self.client.post(url, data={}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.notification.refresh_from_db()

        data = response.json()

        self.assertTrue(self.notification.is_read)
        self.assertIsNotNone(self.notification.read_at)
        self.assertEqual(data["is_read"], True)

    def test_user_can_mark_notification_as_unread(self):
        self.authenticate_user()

        self.assertTrue(self.read_notification.is_read)

        url = reverse("notification-mark-unread", args=[self.read_notification.pk])
        response = self.client.post(url, data={}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.read_notification.refresh_from_db()

        data = response.json()

        self.assertFalse(self.read_notification.is_read)
        self.assertIsNone(self.read_notification.read_at)
        self.assertEqual(data["is_read"], False)

    def test_user_can_mark_all_own_notifications_as_read(self):
        self.authenticate_user()

        second_unread = create_notification(
            user=self.user,
            title="Shipping update",
            message="Your order has been shipped.",
            notification_type=Notification.NotificationType.SHIPPING,
        )

        url = reverse("notification-mark-all-read")
        response = self.client.post(url, data={}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertEqual(data["marked_count"], 2)

        self.notification.refresh_from_db()
        second_unread.refresh_from_db()
        self.other_notification.refresh_from_db()

        self.assertTrue(self.notification.is_read)
        self.assertTrue(second_unread.is_read)

        # Other user's notification must not be changed.
        self.assertFalse(self.other_notification.is_read)

    def test_admin_can_list_all_notifications(self):
        self.authenticate_admin()

        url = reverse("notification-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        items = self.get_response_items(response)
        ids = [item["id"] for item in items]

        self.assertIn(self.notification.pk, ids)
        self.assertIn(self.read_notification.pk, ids)
        self.assertIn(self.other_notification.pk, ids)

    def test_user_can_filter_notifications_by_is_read_false(self):
        unread_notification = Notification.objects.create(
            user=self.user,
            title="Unread notification",
            message="Unread message",
            notification_type=Notification.NotificationType.ORDER,
            priority=Notification.Priority.NORMAL,
            is_read=False,
        )

        read_notification = Notification.objects.create(
            user=self.user,
            title="Read notification",
            message="Read message",
            notification_type=Notification.NotificationType.ORDER,
            priority=Notification.Priority.NORMAL,
            is_read=True,
        )

        self.get_api_client().force_authenticate(user=self.user)

        url = reverse("notification-list")

        response = self.client.get(url, {"is_read": "false"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        items = self.get_response_items(response)
        titles = [item["title"] for item in items]

        self.assertIn(unread_notification.title, titles)
        self.assertNotIn(read_notification.title, titles)

    def test_user_can_filter_notifications_by_is_read_true(self):
        unread_notification = Notification.objects.create(
            user=self.user,
            title="Unread notification",
            message="Unread message",
            notification_type=Notification.NotificationType.ORDER,
            priority=Notification.Priority.NORMAL,
            is_read=False,
        )

        read_notification = Notification.objects.create(
            user=self.user,
            title="Read notification",
            message="Read message",
            notification_type=Notification.NotificationType.ORDER,
            priority=Notification.Priority.NORMAL,
            is_read=True,
        )

        self.get_api_client().force_authenticate(user=self.user)

        url = reverse("notification-list")

        response = self.client.get(url, {"is_read": "true"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        items = self.get_response_items(response)
        titles = [item["title"] for item in items]

        self.assertIn(read_notification.title, titles)
        self.assertNotIn(unread_notification.title, titles)

    def test_user_can_filter_notifications_by_notification_type(self):
        product_notification = Notification.objects.create(
            user=self.user,
            title="Product notification",
            message="Product message",
            notification_type=Notification.NotificationType.PRODUCT,
            priority=Notification.Priority.NORMAL,
        )

        order_notification = Notification.objects.create(
            user=self.user,
            title="Order notification",
            message="Order message",
            notification_type=Notification.NotificationType.ORDER,
            priority=Notification.Priority.NORMAL,
        )

        self.get_api_client().force_authenticate(user=self.user)

        url = reverse("notification-list")

        response = self.client.get(
            url,
            {"notification_type": Notification.NotificationType.PRODUCT},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        items = self.get_response_items(response)
        titles = [item["title"] for item in items]

        self.assertIn(product_notification.title, titles)
        self.assertNotIn(order_notification.title, titles)

    def test_user_can_filter_notifications_by_priority(self):
        high_notification = Notification.objects.create(
            user=self.user,
            title="High priority notification",
            message="High priority message",
            notification_type=Notification.NotificationType.ORDER,
            priority=Notification.Priority.HIGH,
        )

        normal_notification = Notification.objects.create(
            user=self.user,
            title="Normal priority notification",
            message="Normal priority message",
            notification_type=Notification.NotificationType.ORDER,
            priority=Notification.Priority.NORMAL,
        )

        self.get_api_client().force_authenticate(user=self.user)

        url = reverse("notification-list")

        response = self.client.get(
            url,
            {"priority": Notification.Priority.HIGH},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        items = self.get_response_items(response)
        titles = [item["title"] for item in items]

        self.assertIn(high_notification.title, titles)
        self.assertNotIn(normal_notification.title, titles)
