from django.db import migrations


def create_stock_transfer_approval(apps, schema_editor):
    Role = apps.get_model("rbac", "Role")
    Permission = apps.get_model("rbac", "Permission")
    RolePermission = apps.get_model(
        "rbac",
        "RolePermission",
    )

    approve_permission, _ = Permission.objects.update_or_create(
        codename="approve_stock_transfers",
        defaults={
            "name": "Approve Stock Transfers",
            "module": "inventory",
            "description": (
                "Can approve or cancel stock transfer requests "
                "created by other inventory managers"
            ),
        },
    )

    supervisor, _ = Role.objects.update_or_create(
        name="inventory_supervisor",
        defaults={
            "description": (
                "Inventory Supervisor - Can manage inventory "
                "and approve stock transfers"
            ),
            "level": 80,
            "is_system_role": True,
        },
    )

    permission_codenames = [
        "view_inventory",
        "manage_inventory",
        "manage_stock_transfers",
        "approve_stock_transfers",
    ]

    permissions = Permission.objects.filter(
        codename__in=permission_codenames,
    )

    for permission in permissions:
        RolePermission.objects.get_or_create(
            role=supervisor,
            permission=permission,
        )

    try:
        super_admin = Role.objects.get(
            name="super_admin",
        )
    except Role.DoesNotExist:
        super_admin = None

    if super_admin:
        RolePermission.objects.get_or_create(
            role=super_admin,
            permission=approve_permission,
        )


def remove_stock_transfer_approval(apps, schema_editor):
    Role = apps.get_model("rbac", "Role")
    Permission = apps.get_model("rbac", "Permission")

    Role.objects.filter(
        name="inventory_supervisor",
    ).delete()

    Permission.objects.filter(
        codename="approve_stock_transfers",
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("rbac", "0004_inventory_rbac"),
    ]

    operations = [
        migrations.RunPython(
            create_stock_transfer_approval,
            remove_stock_transfer_approval,
        ),
    ]
