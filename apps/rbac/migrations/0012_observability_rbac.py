from django.db import migrations, models

PERMISSIONS = (
    ("view_observability", "View Observability", "Read system health and aggregated metrics."),
    ("view_observability_logs", "View Observability Logs", "Read operational request, error, audit and task logs."),
    ("manage_observability_alerts", "Manage Observability Alerts", "Acknowledge and resolve operational alerts."),
    ("resolve_observability_errors", "Resolve Observability Errors", "Mark error records as resolved."),
)


def create_roles(apps, schema_editor):
    Role = apps.get_model("rbac", "Role")
    Permission = apps.get_model("rbac", "Permission")
    RolePermission = apps.get_model("rbac", "RolePermission")
    objects = {}
    for codename, name, description in PERMISSIONS:
        permission, _ = Permission.objects.update_or_create(
            codename=codename,
            defaults={"name": name, "description": description, "module": "observability"},
        )
        objects[codename] = permission

    roles = {
        "observability_viewer": (65, ("view_observability",)),
        "observability_operator": (75, (
            "view_observability", "view_observability_logs", "manage_observability_alerts")),
        "observability_admin": (85, tuple(objects)),
    }
    for name, (level, codes) in roles.items():
        role, _ = Role.objects.update_or_create(
            name=name,
            defaults={"description": f"Scoped {name.replace('_', ' ')} role", "level": level, "is_system_role": True},
        )
        for code in codes:
            RolePermission.objects.get_or_create(role=role, permission=objects[code])
    super_admin = Role.objects.filter(name="super_admin").first()
    if super_admin:
        for permission in objects.values():
            RolePermission.objects.get_or_create(role=super_admin, permission=permission)


class Migration(migrations.Migration):
    dependencies = [("rbac", "0011_content_cms_rbac")]
    operations = [
        migrations.AlterField(
            model_name="permission", name="module",
            field=models.CharField(max_length=50, verbose_name="Module", choices=[
                ("accounts", "Accounts"), ("products", "Products"),
                ("inventory", "Inventory"), ("orders", "Orders"),
                ("payments", "Payments"), ("discounts", "Discounts"),
                ("reviews", "Reviews"), ("shipping", "Shipping"),
                ("content", "Content"), ("support", "Support"),
                ("analytics", "Analytics"), ("observability", "Observability"),
                ("rbac", "RBAC"),
            ]),
        ),
        migrations.RunPython(create_roles, migrations.RunPython.noop),
    ]
