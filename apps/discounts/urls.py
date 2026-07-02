from django.urls import path

from apps.discounts.views import ValidateDiscountView

app_name = "discounts"

urlpatterns = [
    path("validate/", ValidateDiscountView.as_view(), name="validate-discount"),
]