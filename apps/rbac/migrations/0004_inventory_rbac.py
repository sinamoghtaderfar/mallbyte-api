from django.db import migrations, models

INVENTORY_PERMISSIONS = [
    {
        "name": "View Inventory",
        "codename": "view_inventory",
        "module": "inventory",
        "description": (
            "Can view warehouses, stock levels, " "stock movements, and stock transfers"
        ),
    },
    {
        "name": "Manage Inventory",
        "codename": "manage_inventory",
        "module": "inventory",
        "description": (
            "Can create and update warehouses, stock records, "
            "reservations, and stock movements"
        ),
    },
    {
        "name": "Manage Stock Transfers",
        "codename": "manage_stock_transfers",
        "module": "inventory",
        "description": ("Can create and manage stock transfers " "between warehouses"),
    },
]


def create_inventory_rbac(apps, schema_editor):
    Role = apps.get_model("rbac", "Role")
    Permission = apps.get_model("rbac", "Permission")
    RolePermission = apps.get_model(
        "rbac",
        "RolePermission",
    )

    inventory_manager, _ = Role.objects.get_or_create(
        name="inventory_manager",
        defaults={
            "description": (
                "Inventory Manager - Can manage warehouses, "
                "stock, and stock transfers"
            ),
            "level": 70,
            "is_system_role": True,
        },
    )

    inventory_permissions = []

    for permission_data in INVENTORY_PERMISSIONS:
        permission, _ = Permission.objects.update_or_create(
            codename=permission_data["codename"],
            defaults={
                "name": permission_data["name"],
                "module": permission_data["module"],
                "description": permission_data["description"],
            },
        )

        inventory_permissions.append(permission)

        RolePermission.objects.get_or_create(
            role=inventory_manager,
            permission=permission,
        )

    try:
        super_admin = Role.objects.get(
            name="super_admin",
        )
    except Role.DoesNotExist:
        super_admin = None

    if super_admin:
        for permission in inventory_permissions:
            RolePermission.objects.get_or_create(
                role=super_admin,
                permission=permission,
            )


def remove_inventory_rbac(apps, schema_editor):
    Role = apps.get_model("rbac", "Role")
    Permission = apps.get_model("rbac", "Permission")

    Role.objects.filter(
        name="inventory_manager",
    ).delete()

    Permission.objects.filter(
        codename__in=[
            "view_inventory",
            "manage_inventory",
            "manage_stock_transfers",
        ],
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("rbac", "0003_alter_adminlog_action"),
    ]

    operations = [
        migrations.AlterField(
            model_name="permission",
            name="module",
            field=models.CharField(
                choices=[
                    ("accounts", "Accounts"),
                    ("products", "Products"),
                    ("inventory", "Inventory"),
                    ("orders", "Orders"),
                    ("payments", "Payments"),
                    ("discounts", "Discounts"),
                    ("reviews", "Reviews"),
                    ("shipping", "Shipping"),
                    ("content", "Content"),
                    ("rbac", "RBAC"),
                ],
                max_length=50,
                verbose_name="Module",
            ),
        ),
        migrations.RunPython(
            create_inventory_rbac,
            remove_inventory_rbac,
        ),
    ]
