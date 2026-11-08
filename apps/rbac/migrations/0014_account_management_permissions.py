from django.db import migrations

ACCOUNT_PERMISSIONS = {
    "view_sellers": "View seller applications and private seller details",
    "approve_seller": "Approve pending seller applications",
    "reject_seller": "Reject pending seller applications",
    "delete_user": "Delete non-privileged user accounts",
    "view_all_orders": "View orders across customers",
    "manage_orders": "Manage orders across customers",
    "view_all_payments": "View payments across customers",
    "manage_payments": "Manage internal payment records",
    "view_all_shipments": "View shipments across customers",
    "manage_shipments": "Manage shipment operations",
    "view_all_returns": "View returns across customers",
    "manage_returns": "Manage return decisions and refunds",
}


def seed_account_permissions(apps, schema_editor):
    permission = apps.get_model("rbac", "Permission")
    role = apps.get_model("rbac", "Role")
    role_permission = apps.get_model("rbac", "RolePermission")
    alias = schema_editor.connection.alias
    for codename, description in ACCOUNT_PERMISSIONS.items():
        item, _ = permission.objects.using(alias).get_or_create(
            codename=codename,
            defaults={"name": description, "module": ("payments" if "payments" in codename else "shipping" if "shipments" in codename else "orders" if "orders" in codename or "returns" in codename else "accounts"), "description": description},
        )
        # Staff is not a business role. Preserve explicit grants; give only the
        # established vendor-manager role the three seller capabilities.
        if codename in {"view_sellers", "approve_seller", "reject_seller"}:
            for role_id in role.objects.using(alias).filter(name="vendor_manager").values_list("pk", flat=True):
                role_permission.objects.using(alias).get_or_create(role_id=role_id, permission_id=item.pk)


class Migration(migrations.Migration):
    dependencies = [("rbac", "0013_observability_granular_permissions")]
    operations = [migrations.RunPython(seed_account_permissions, migrations.RunPython.noop)]
