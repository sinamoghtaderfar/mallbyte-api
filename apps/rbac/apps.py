from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.rbac"
    verbose_name = "Role-Based Access Control (RBAC)"
    
    def ready(self):
        # Import signals if needed
        pass