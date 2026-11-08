from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts.models import Seller
from apps.rbac.models import Permission, Role, RolePermission, UserRole
from apps.rbac.utils import get_permissions_cache_key, get_user_permissions, has_permission

User = get_user_model()


class AccountAuthorizationTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email="admin@example.com", password="admin-password")
        self.staff = User.objects.create_user(email="moderator@example.com", is_staff=True)
        self.owner = User.objects.create_user(email="owner@example.com")
        self.seller = Seller.objects.create(user=self.owner, store_name="Pending shop", business_email="shop@example.com", business_phone="09123456789")
        self.role = Role.objects.create(name="security_test")

    def grant(self, user, codename):
        permission, _ = Permission.objects.get_or_create(codename=codename, defaults={"name": codename, "module": "accounts"})
        RolePermission.objects.get_or_create(role=self.role, permission=permission)
        UserRole.objects.get_or_create(user=user, role=self.role)
        return permission

    def test_staff_flag_alone_cannot_access_sellers_or_delete_users(self):
        self.client.force_authenticate(self.staff)
        for url in ("/api/auth/admin/sellers/", "/api/auth/admin/sellers/pending/", f"/api/auth/admin/sellers/{self.seller.pk}/"):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        for action in ("verify", "reject"):
            self.assertEqual(self.client.post(f"/api/auth/admin/sellers/{self.seller.pk}/{action}/", {"reason": "Not eligible"}).status_code, 403)
        self.assertEqual(self.client.delete(f"/api/auth/admin/users/{self.owner.pk}/delete/").status_code, 403)
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.is_deleted)

    def test_explicit_seller_capabilities_do_not_require_staff(self):
        self.grant(self.owner, "view_sellers")
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.get("/api/auth/admin/sellers/").status_code, 200)
        self.assertEqual(self.client.post(f"/api/auth/admin/sellers/{self.seller.pk}/verify/").status_code, 403)

    def test_approval_rolls_back_if_role_assignment_fails(self):
        Role.objects.get_or_create(name="vendor")
        with patch("apps.rbac.utils.assign_role", side_effect=RuntimeError("assignment failed")):
            with self.assertRaises(RuntimeError):
                self.seller.approve(self.admin)
        self.seller.refresh_from_db()
        self.owner.refresh_from_db()
        self.assertEqual(self.seller.status, Seller.StatusChoices.PENDING)
        self.assertFalse(self.owner.is_seller)
        self.assertFalse(UserRole.objects.filter(user=self.owner).exists())

    def test_missing_vendor_role_cannot_silently_approve(self):
        Role.objects.filter(name="vendor").delete()
        self.client.force_authenticate(self.admin)
        result = self.client.post(f"/api/auth/admin/sellers/{self.seller.pk}/verify/")
        self.assertEqual(result.status_code, 400, result.data)
        self.seller.refresh_from_db()
        self.assertEqual(self.seller.status, Seller.StatusChoices.PENDING)

    def test_approval_and_rejection_cannot_override_decided_application(self):
        Role.objects.get_or_create(name="vendor")
        self.seller.approve(self.admin)
        with self.assertRaises(ValidationError):
            self.seller.reject(self.admin, "Changed decision")
        self.seller.refresh_from_db()
        self.owner.refresh_from_db()
        self.assertEqual(self.seller.status, Seller.StatusChoices.APPROVED)
        self.assertTrue(self.owner.is_seller)
        self.assertTrue(UserRole.objects.filter(user=self.owner, role__name="vendor", is_active=True).exists())

    def test_rejection_reason_is_validated_in_api(self):
        self.client.force_authenticate(self.admin)
        for reason in ("", "  ", {"secret": "invalid"}, "a" * 2001):
            result = self.client.post(f"/api/auth/admin/sellers/{self.seller.pk}/reject/", {"reason": reason}, format="json")
            self.assertEqual(result.status_code, 400, result.data)

    def test_delegated_delete_cannot_delete_privileged_accounts(self):
        self.grant(self.owner, "delete_user")
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.delete(f"/api/auth/admin/users/{self.staff.pk}/delete/").status_code, 400)
        self.staff.refresh_from_db()
        self.assertFalse(self.staff.is_deleted)

    def test_old_shared_cache_grant_is_never_authoritative(self):
        cache.set(get_permissions_cache_key(self.owner), ["delete_user"])
        self.assertFalse(has_permission(self.owner, "delete_user"))

    def test_rolled_back_grant_does_not_survive_a_permission_read(self):
        permission = Permission.objects.get(codename="delete_user")
        try:
            with transaction.atomic():
                RolePermission.objects.create(role=self.role, permission=permission)
                UserRole.objects.create(user=self.owner, role=self.role)
                self.assertTrue(has_permission(self.owner, "delete_user"))
                raise RuntimeError("rollback")
        except RuntimeError:
            pass
        self.assertFalse(has_permission(self.owner, "delete_user"))

    def test_permission_rename_and_assignment_retarget_take_effect_immediately(self):
        permission = self.grant(self.owner, "delete_user")
        self.assertTrue(has_permission(self.owner, "delete_user"))
        permission.codename = "renamed_delete_user"
        permission.save(update_fields=["codename"])
        self.assertFalse(has_permission(self.owner, "delete_user"))
        self.assertTrue(has_permission(self.owner, "renamed_delete_user"))
        assignment = UserRole.objects.get(user=self.owner, role=self.role)
        assignment.user = self.staff
        assignment.save(update_fields=["user"])
        self.assertFalse(has_permission(self.owner, "renamed_delete_user"))
        self.assertTrue(has_permission(self.staff, "renamed_delete_user"))

    def test_expired_or_inactive_accounts_have_no_permissions(self):
        self.grant(self.owner, "delete_user")
        UserRole.objects.filter(user=self.owner).update(expires_at=timezone.now())
        # Another unexpired user's assignment to this role must not satisfy the
        # expiry predicate for the target user's expired join row.
        UserRole.objects.create(user=self.staff, role=self.role)
        self.assertFalse(has_permission(self.owner, "delete_user"))
        self.admin.is_active = False
        self.assertFalse(has_permission(self.admin, "delete_user"))
        self.assertEqual(get_user_permissions(self.admin), [])

    def test_authorization_uses_one_query_regardless_of_role_count(self):
        self.grant(self.owner, "delete_user")
        for index in range(4):
            role = Role.objects.create(name=f"other-{index}")
            UserRole.objects.create(user=self.owner, role=role)
        with self.assertNumQueries(1):
            self.assertEqual(get_user_permissions(self.owner), ["delete_user"])

    def test_system_role_permission_policy_matches_console(self):
        role = Role.objects.create(name="protected-role", is_system_role=True)
        permission = Permission.objects.get(codename="delete_user")
        self.client.force_authenticate(self.admin)
        response = self.client.post(f"/api/rbac/roles/{role.pk}/add_permission/", {"permission_id": permission.pk})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(RolePermission.objects.filter(role=role).exists())


@skipUnless(connection.vendor == "postgresql", "PostgreSQL row-lock semantics required")
class SellerDecisionConcurrencyTests(TransactionTestCase):
    def test_simultaneous_approval_and_rejection_leave_one_consistent_decision(self):
        admin = User.objects.create_superuser(email="admin@example.com", password="admin-password")
        owner = User.objects.create_user(email="owner@example.com")
        seller = Seller.objects.create(user=owner, store_name="Racing shop", business_email="shop@example.com", business_phone="09123456789")
        Role.objects.get_or_create(name="vendor")
        barrier = Barrier(2)

        def decide(approve):
            close_old_connections()
            try:
                item = Seller.objects.get(pk=seller.pk)
                actor = User.objects.get(pk=admin.pk)
                barrier.wait(timeout=10)
                try:
                    if approve:
                        item.approve(actor)
                    else:
                        item.reject(actor, "Application rejected")
                    return "decided"
                except ValidationError:
                    return "already-decided"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(decide, decision) for decision in (True, False)]
            self.assertEqual(sorted(f.result(timeout=15) for f in futures), ["already-decided", "decided"])
        seller.refresh_from_db()
        owner.refresh_from_db()
        approved = seller.status == Seller.StatusChoices.APPROVED
        self.assertEqual(owner.is_seller, approved)
        self.assertEqual(UserRole.objects.filter(user=owner, role__name="vendor", is_active=True).exists(), approved)
