from unittest.mock import Mock

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase

from apps.accounts.admin import UserAdmin
from apps.reviews.admin_roles import REVIEW_MODERATORS_GROUP_NAME

User = get_user_model()


class UserAdminReviewModeratorActionTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.admin_site = AdminSite()
        self.user_admin = UserAdmin(User, self.admin_site)
        self.user_admin.message_user = Mock()

        self.superuser = User.objects.create_superuser(
            email="admin@example.com",
            full_name="Super Admin",
            password="password",
        )
        self.staff_user = User.objects.create_user(
            email="staff@example.com",
            full_name="Staff User",
            password="password",
            is_staff=True,
        )
        self.user = User.objects.create_user(
            email="moderator@example.com",
            full_name="Moderator User",
            password="password",
        )

    def make_request(self, user):
        request = self.factory.post("/admin/accounts/user/")
        request.user = user
        return request

    def test_superuser_can_make_selected_users_review_moderators_from_admin(self):
        request = self.make_request(self.superuser)

        self.user_admin.make_review_moderators(
            request,
            User.objects.filter(pk=self.user.pk),
        )

        self.user.refresh_from_db()

        self.assertTrue(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)
        self.assertTrue(self.user.is_active)
        self.assertTrue(
            self.user.groups.filter(name=REVIEW_MODERATORS_GROUP_NAME).exists()
        )

        group = Group.objects.get(name=REVIEW_MODERATORS_GROUP_NAME)
        permissions = set(group.permissions.values_list("codename", flat=True))

        self.assertIn("view_productreview", permissions)
        self.assertIn("change_productreview", permissions)
        self.assertIn("view_productreviewvote", permissions)
        self.assertNotIn("add_productreview", permissions)
        self.assertNotIn("delete_productreview", permissions)

    def test_superuser_can_remove_review_moderator_role_from_admin(self):
        request = self.make_request(self.superuser)

        self.user_admin.make_review_moderators(
            request,
            User.objects.filter(pk=self.user.pk),
        )

        self.user_admin.remove_review_moderator_role(
            request,
            User.objects.filter(pk=self.user.pk),
        )

        self.user.refresh_from_db()

        self.assertFalse(
            self.user.groups.filter(name=REVIEW_MODERATORS_GROUP_NAME).exists()
        )

    def test_non_superuser_cannot_assign_review_moderator_access(self):
        request = self.make_request(self.staff_user)

        self.user_admin.make_review_moderators(
            request,
            User.objects.filter(pk=self.user.pk),
        )

        self.user.refresh_from_db()

        self.assertFalse(self.user.is_staff)
        self.assertFalse(
            self.user.groups.filter(name=REVIEW_MODERATORS_GROUP_NAME).exists()
        )

    def test_review_moderator_column_detects_group_membership(self):
        request = self.make_request(self.superuser)

        self.user_admin.make_review_moderators(
            request,
            User.objects.filter(pk=self.user.pk),
        )

        self.user.refresh_from_db()

        self.assertTrue(self.user_admin.is_review_moderator(self.user))
