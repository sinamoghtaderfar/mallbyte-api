from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.accounts.views import ThrottledTokenObtainPairView, CookieTokenRefreshView
from config.views import api_home

urlpatterns = [
    path("", api_home, name="api_home"),
    
    path("admin/", admin.site.urls),

    path(
        "api/auth/token/",
        ThrottledTokenObtainPairView.as_view(),
        name="token_obtain_pair",
    ),
    path(
        "api/auth/token/refresh/",
        CookieTokenRefreshView.as_view(),
        name="token_refresh",
    ),

    path("api/auth/", include("apps.accounts.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "swagger/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path("api/rbac/", include("apps.rbac.urls")),
    path("api/products/", include("apps.products.urls")),
    path("api/inventory/", include("apps.inventory.urls")),
    path("api/orders/", include("apps.orders.urls")),
    path("api/payments/", include("apps.payments.urls")),
    path("api/shipping/", include("apps.shipping.urls")),
    path("api/discounts/", include("apps.discounts.urls")),
    path("api/returns/", include("apps.returns.urls")),
    path("api/notifications/", include("apps.notifications.urls")),
    path("api/reviews/", include("apps.reviews.urls")),
    path("api/support/", include("apps.support.urls")),
    path("api/content/", include("apps.content.urls")),
    path("api/analytics/", include("apps.analytics.urls")),
    path("api/observability/", include("apps.observability.urls")),
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)