from django.db import migrations, models

SUPPORT_PERMISSIONS = [
    {
        "name": "View All Support Tickets",
        "codename": "view_all_support_tickets",
        "description": "Can view support tickets from all customers",
    },
    {
        "name": "Reply To Support Tickets",
        "codename": "reply_support_tickets",
        "description": "Can send public replies to customer support tickets",
    },
    {
        "name": "View Support Internal Notes",
        "codename": "view_support_internal_notes",
        "description": "Can view internal notes on support tickets",
    },
    {
        "name": "Add Support Internal Note",
        "codename": "add_support_internal_note",
        "description": "Can create internal notes on support tickets",
    },
    {
        "name": "Assign Support Tickets",
        "codename": "assign_support_tickets",
        "description": "Can assign support tickets to support users",
    },
    {
        "name": "Manage Support Tags",
        "codename": "manage_support_tags",
        "description": "Can create, update, delete, add, and remove support tags",
    },
    {
        "name": "Change Support Priority",
        "codename": "change_support_priority",
        "description": "Can change support ticket priority",
    },
    {
        "name": "Resolve Support Tickets",
        "codename": "resolve_support_tickets",
        "description": "Can mark support tickets as resolved",
    },
    {
        "name": "Close Support Tickets",
        "codename": "close_support_tickets",
        "description": "Can close support tickets",
    },
    {
        "name": "Reopen Support Tickets",
        "codename": "reopen_support_tickets",
        "description": "Can reopen closed or resolved support tickets",
    },
    {
        "name": "View Support Audit Logs",
        "codename": "view_support_audit_logs",
        "description": "Can view support ticket audit logs",
    },
]


SUPPORT_AGENT_PERMISSIONS = {
    "view_all_support_tickets",
    "reply_support_tickets",
    "view_support_internal_notes",
    "add_support_internal_note",
    "resolve_support_tickets",
}


SUPPORT_MANAGER_PERMISSIONS = {
    permission["codename"] for permission in SUPPORT_PERMISSIONS
}


def create_support_rbac(apps, schema_editor):
    Role = apps.get_model("rbac", "Role")
    Permission = apps.get_model("rbac", "Permission")
    RolePermission = apps.get_model(
        "rbac",
        "RolePermission",
    )

    support_agent, _ = Role.objects.update_or_create(
        name="support_agent",
        defaults={
            "description": (
                "Support Agent - Can handle customer conversations "
                "and resolve support tickets"
            ),
            "level": 60,
            "is_system_role": True,
        },
    )

    support_manager, _ = Role.objects.update_or_create(
        name="support_manager",
        defaults={
            "description": ("Support Manager - Full support ticket management access"),
            "level": 70,
            "is_system_role": True,
        },
    )

    permissions_by_codename = {}

    for permission_data in SUPPORT_PERMISSIONS:
        permission, _ = Permission.objects.update_or_create(
            codename=permission_data["codename"],
            defaults={
                "name": permission_data["name"],
                "module": "support",
                "description": permission_data["description"],
            },
        )

        permissions_by_codename[permission_data["codename"]] = permission

    for codename in SUPPORT_AGENT_PERMISSIONS:
        RolePermission.objects.get_or_create(
            role=support_agent,
            permission=permissions_by_codename[codename],
        )

    for codename in SUPPORT_MANAGER_PERMISSIONS:
        RolePermission.objects.get_or_create(
            role=support_manager,
            permission=permissions_by_codename[codename],
        )

    super_admin = Role.objects.filter(name="super_admin").first()

    if super_admin:
        for permission in permissions_by_codename.values():
            RolePermission.objects.get_or_create(
                role=super_admin,
                permission=permission,
            )


class Migration(migrations.Migration):
    dependencies = [
        ("rbac", "0007_supervisor_readonly_inventory"),
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
                    ("support", "Support"),
                    ("rbac", "RBAC"),
                ],
                max_length=50,
                verbose_name="Module",
            ),
        ),
        migrations.RunPython(
            create_support_rbac,
            migrations.RunPython.noop,
        ),
    ]
