"""CMS permission seed, with no automatic staff access and no destructive reverse."""
from django.db import migrations

PERMISSIONS = {
    "view_content_drafts": "View unpublished CMS entries",
    "manage_content": "Create, edit and remove draft CMS entries",
    "publish_content": "Publish, archive and modify published CMS entries",
}
ROLES = {
    "content_viewer": (45, ("view_content_drafts",)),
    "content_editor": (50, ("view_content_drafts", "manage_content")),
    "content_publisher": (55, ("view_content_drafts", "publish_content")),
    "content_manager": (60, tuple(PERMISSIONS)),
}


def seed_cms_roles(apps, schema_editor):
    Permission = apps.get_model("rbac", "Permission")
    Role = apps.get_model("rbac", "Role")
    RolePermission = apps.get_model("rbac", "RolePermission")

    perms = {}
    for code, description in PERMISSIONS.items():
        obj, _ = Permission.objects.update_or_create(
            codename=code,
            defaults={"name": code.replace("_", " ").title(),
                      "module": "content", "description": description},
        )
        perms[code] = obj

    for name, (level, codes) in ROLES.items():
        role, _ = Role.objects.update_or_create(
            name=name,
            defaults={"description": "Content management: " + name,
                      "level": level, "is_system_role": True},
        )
        for code in codes:
            RolePermission.objects.get_or_create(role=role, permission=perms[code])

    # Existing content_admin role retains its abilities if it exists.
    for name in ("content_admin", "super_admin"):
        role = Role.objects.filter(name=name).first()
        if role:
            for obj in perms.values():
                RolePermission.objects.get_or_create(role=role, permission=obj)


class Migration(migrations.Migration):
    dependencies = [("rbac", "0010_seller_analytics_rbac")]
    operations = [migrations.RunPython(seed_cms_roles, migrations.RunPython.noop)]
