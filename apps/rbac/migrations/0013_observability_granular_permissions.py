"""Break broad observability privileges into auditable scoped permissions."""
from django.db import migrations

NEW = (
    ("view_observability_audit_logs", "View Audit Logs", "Read sensitive audit trails."),
    ("view_observability_error_details", "View Sensitive Error Details", "Read detailed request and error log fields."),
    ("view_observability_incidents", "View Incidents", "View internal incidents and history."),
    ("create_observability_incidents", "Create Incidents", "Create internal incidents."),
    ("assign_observability_incidents", "Assign Incidents", "Assign incidents to eligible staff."),
    ("manage_observability_incidents", "Manage Incidents", "Comment and transition incident lifecycle."),
    ("request_observability_ai_diagnosis", "Request AI Diagnosis", "Use optional external AI diagnosis."),
    ("view_observability_operations", "View Infrastructure Operations", "Read operation requests and results."),
    ("request_observability_operations", "Request Infrastructure Operations", "Request allowlisted infrastructure restarts."),
    ("approve_observability_operations", "Approve Infrastructure Operations", "Second-person approval of allowlisted restarts."),
)


def forward(apps, schema_editor):
    Permission = apps.get_model("rbac", "Permission")
    Role = apps.get_model("rbac", "Role")
    RolePermission = apps.get_model("rbac", "RolePermission")
    db = schema_editor.connection.alias
    for code, name, description in NEW:
        Permission.objects.using(db).update_or_create(
            codename=code, defaults={"name": name, "description": description, "module": "observability"}
        )

    codes = {
        "observability_viewer": {"view_observability", "view_observability_incidents"},
        "observability_operator": {
            "view_observability", "view_observability_logs", "manage_observability_alerts",
            "view_observability_incidents", "create_observability_incidents",
            "assign_observability_incidents", "manage_observability_incidents",
            "request_observability_ai_diagnosis", "view_observability_operations",
            "request_observability_operations",
        },
        "observability_admin": {
            "view_observability", "view_observability_logs", "manage_observability_alerts",
            "resolve_observability_errors", *[c for c, _, _ in NEW],
        },
        "super_admin": {
            "view_observability", "view_observability_logs", "manage_observability_alerts",
            "resolve_observability_errors", *[c for c, _, _ in NEW],
        },
    }
    for role_name, grants in codes.items():
        role = Role.objects.using(db).filter(name=role_name).first()
        if not role:
            continue
        # On these three system roles only, explicitly remove old broad observability grants.
        if role_name != "super_admin":
            RolePermission.objects.using(db).filter(role_id=role.pk, permission__module="observability").exclude(
                permission__codename__in=grants
            ).delete()
        for perm in Permission.objects.using(db).filter(codename__in=grants):
            RolePermission.objects.using(db).get_or_create(role_id=role.pk, permission_id=perm.pk)


class Migration(migrations.Migration):
    dependencies = [("rbac", "0012_observability_rbac")]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
