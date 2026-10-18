from django.db import migrations, models

ANALYTICS_PERMISSIONS = [
    {
        "codename": "view_platform_analytics",
        "name": "View Platform Analytics",
        "description": (
            "Can view platform-wide analytics, "
            "dashboards, trends, breakdowns and alerts."
        ),
    },
    {
        "codename": "export_analytics",
        "name": "Export Analytics",
        "description": ("Can export platform-wide analytics data."),
    },
    {
        "codename": "manage_analytics_reports",
        "name": "Manage Analytics Reports",
        "description": (
            "Can generate, inspect and download " "generated analytics reports."
        ),
    },
    {
        "codename": "manage_analytics_schedules",
        "name": "Manage Analytics Schedules",
        "description": (
            "Can create, edit, delete and execute " "scheduled analytics reports."
        ),
    },
]


def create_analytics_rbac(apps, schema_editor):
    Role = apps.get_model("rbac", "Role")
    Permission = apps.get_model("rbac", "Permission")
    RolePermission = apps.get_model(
        "rbac",
        "RolePermission",
    )

    viewer, _ = Role.objects.update_or_create(
        name="analytics_viewer",
        defaults={
            "description": (
                "Read-only access to platform analytics "
                "dashboards and aggregated metrics."
            ),
            "level": 65,
            "is_system_role": True,
        },
    )

    manager, _ = Role.objects.update_or_create(
        name="analytics_manager",
        defaults={
            "description": (
                "Full access to platform analytics, " "exports, reports and schedules."
            ),
            "level": 80,
            "is_system_role": True,
        },
    )

    permission_map = {}

    for data in ANALYTICS_PERMISSIONS:
        permission, _ = Permission.objects.update_or_create(
            codename=data["codename"],
            defaults={
                "name": data["name"],
                "module": "analytics",
                "description": data["description"],
            },
        )
        permission_map[data["codename"]] = permission

    RolePermission.objects.get_or_create(
        role=viewer,
        permission=permission_map["view_platform_analytics"],
    )

    for permission in permission_map.values():
        RolePermission.objects.get_or_create(
            role=manager,
            permission=permission,
        )

    super_admin = Role.objects.filter(
        name="super_admin",
    ).first()

    if super_admin:
        for permission in permission_map.values():
            RolePermission.objects.get_or_create(
                role=super_admin,
                permission=permission,
            )


class Migration(migrations.Migration):
    dependencies = [
        ("rbac", "0008_support_rbac"),
    ]

    operations = [
        migrations.AlterField(
            model_name="permission",
            name="module",
            field=models.CharField(
                max_length=50,
                verbose_name="Module",
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
                    ("support", "Support"),
                    ("analytics", "Analytics"),
                    ("rbac", "RBAC"),
                ],
            ),
        ),
        migrations.RunPython(
            create_analytics_rbac,
            migrations.RunPython.noop,
        ),
    ]
