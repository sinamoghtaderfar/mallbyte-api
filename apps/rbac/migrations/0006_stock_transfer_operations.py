from django.db import migrations

NEW_PERMISSIONS = [
    {
        "name": "Create Stock Transfers",
        "codename": "create_stock_transfers",
        "description": "Can create stock transfer requests.",
    },
    {
        "name": "Ship Stock Transfers",
        "codename": "ship_stock_transfers",
        "description": (
            "Can ship approved transfers from an assigned source warehouse."
        ),
    },
    {
        "name": "Receive Stock Transfers",
        "codename": "receive_stock_transfers",
        "description": (
            "Can receive in-transit transfers into an assigned destination warehouse."
        ),
    },
]


def create_transfer_operation_permissions(apps, schema_editor):
    Role = apps.get_model("rbac", "Role")
    Permission = apps.get_model("rbac", "Permission")
    RolePermission = apps.get_model(
        "rbac",
        "RolePermission",
    )

    permissions = {}

    for permission_data in NEW_PERMISSIONS:
        permission, _ = Permission.objects.update_or_create(
            codename=permission_data["codename"],
            defaults={
                "name": permission_data["name"],
                "module": "inventory",
                "description": permission_data["description"],
            },
        )

        permissions[permission.codename] = permission

    inventory_manager = Role.objects.get(
        name="inventory_manager",
    )

    inventory_supervisor = Role.objects.get(
        name="inventory_supervisor",
    )

    warehouse_operator, _ = Role.objects.update_or_create(
        name="warehouse_operator",
        defaults={
            "description": (
                "Warehouse Operator - Ships and receives "
                "stock transfers for assigned warehouses"
            ),
            "level": 60,
            "is_system_role": True,
        },
    )

    # Legacy broad transfer permission is no longer used
    # by manager or supervisor.
    RolePermission.objects.filter(
        role__in=[
            inventory_manager,
            inventory_supervisor,
        ],
        permission__codename="manage_stock_transfers",
    ).delete()

    RolePermission.objects.get_or_create(
        role=inventory_manager,
        permission=permissions["create_stock_transfers"],
    )

    approve_permission = Permission.objects.get(
        codename="approve_stock_transfers",
    )

    RolePermission.objects.get_or_create(
        role=inventory_supervisor,
        permission=approve_permission,
    )

    view_permission = Permission.objects.get(
        codename="view_inventory",
    )

    RolePermission.objects.get_or_create(
        role=warehouse_operator,
        permission=view_permission,
    )

    RolePermission.objects.get_or_create(
        role=warehouse_operator,
        permission=permissions["ship_stock_transfers"],
    )

    RolePermission.objects.get_or_create(
        role=warehouse_operator,
        permission=permissions["receive_stock_transfers"],
    )

    super_admin = Role.objects.filter(
        name="super_admin",
    ).first()

    if super_admin:
        for permission in permissions.values():
            RolePermission.objects.get_or_create(
                role=super_admin,
                permission=permission,
            )


def reverse_transfer_operation_permissions(apps, schema_editor):
    Role = apps.get_model("rbac", "Role")
    Permission = apps.get_model("rbac", "Permission")
    RolePermission = apps.get_model(
        "rbac",
        "RolePermission",
    )

    manager = Role.objects.filter(
        name="inventory_manager",
    ).first()

    supervisor = Role.objects.filter(
        name="inventory_supervisor",
    ).first()

    legacy_permission = Permission.objects.filter(
        codename="manage_stock_transfers",
    ).first()

    if legacy_permission:
        for role in [manager, supervisor]:
            if role:
                RolePermission.objects.get_or_create(
                    role=role,
                    permission=legacy_permission,
                )

    Role.objects.filter(
        name="warehouse_operator",
    ).delete()

    Permission.objects.filter(
        codename__in=[
            "create_stock_transfers",
            "ship_stock_transfers",
            "receive_stock_transfers",
        ]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("rbac", "0005_stock_transfer_approval"),
    ]

    operations = [
        migrations.RunPython(
            create_transfer_operation_permissions,
            reverse_transfer_operation_permissions,
        ),
    ]
