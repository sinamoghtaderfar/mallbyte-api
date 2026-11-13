from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"

    def ready(self):
        # Register documentation extensions after Django has loaded all models.
        # These extensions replace views only inside the OpenAPI generator.
        from importlib import import_module

        import_module("config.openapi")
