from django.http import JsonResponse
from django.utils import timezone


def api_home(request):
    return JsonResponse(
        {
            "name": "MallByte API",
            "status": "running",
            "message": "Welcome to the MallByte backend API.",
            "version": "1.0.0",
            "timestamp": timezone.now().isoformat(),
            "links": {
                "admin": "/admin/",
                "auth": "/api/auth/",
                "products": "/api/products/",
                "health": "/api/observability/health/",
                "schema": "/api/schema/",
                "docs": "/api/docs/",
            },
        }
    )
