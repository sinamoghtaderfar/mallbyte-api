from django.apps import AppConfig


class RbacConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.rbac"
    verbose_name = "Role-Based Access Control (RBAC)"

    def ready(self):
        from apps.rbac import signals  # noqa: F401
