from django.db import migrations


def make_supervisor_readonly(apps, schema_editor):
    RolePermission = apps.get_model("rbac", "RolePermission")

    RolePermission.objects.using(schema_editor.connection.alias).filter(
        role__name="inventory_supervisor",
        permission__codename="manage_inventory",
    ).delete()


def restore_supervisor_permission(apps, schema_editor):
    Role = apps.get_model("rbac", "Role")
    Permission = apps.get_model("rbac", "Permission")
    RolePermission = apps.get_model("rbac", "RolePermission")

    db = schema_editor.connection.alias

    role = Role.objects.using(db).filter(name="inventory_supervisor").first()

    permission = (
        Permission.objects.using(db).filter(codename="manage_inventory").first()
    )

    if role and permission:
        RolePermission.objects.using(db).get_or_create(
            role=role,
            permission=permission,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("rbac", "0006_stock_transfer_operations"),
    ]

    operations = [
        migrations.RunPython(
            make_supervisor_readonly,
            restore_supervisor_permission,
        ),
    ]
