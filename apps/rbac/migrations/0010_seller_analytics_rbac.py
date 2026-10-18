from django.db import migrations


def seed_seller_analytics_permission(apps, schema_editor):
    Role = apps.get_model("rbac", "Role")
    Permission = apps.get_model("rbac", "Permission")
    RolePermission = apps.get_model("rbac", "RolePermission")

    permission, _ = Permission.objects.update_or_create(
        codename="view_seller_analytics",
        defaults={
            "name": "View Own Seller Analytics",
            "module": "analytics",
            "description": "View merchandise metrics for owned products only.",
        },
    )
    vendor, _ = Role.objects.get_or_create(
        name="vendor",
        defaults={
            "description": "Marketplace seller",
            "level": 30,
            "is_system_role": True,
        },
    )
    RolePermission.objects.get_or_create(role=vendor, permission=permission)
    super_admin = Role.objects.filter(name="super_admin").first()
    if super_admin:
        RolePermission.objects.get_or_create(
            role=super_admin,
            permission=permission,
        )


class Migration(migrations.Migration):
    dependencies = [("rbac", "0009_analytics_rbac")]
    operations = [
        migrations.RunPython(
            seed_seller_analytics_permission,
            migrations.RunPython.noop,
        ),
    ]
