from django.apps import AppConfig

class ProductsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.products'  # این مهمه - باید apps.products باشه
    verbose_name = 'Products Management'