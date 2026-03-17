from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .views import (
    RegisterView, ProfileView, AddressViewSet,
    OTPRequestView, OTPVerifyView,
    SellerApplyView, SellerStatusView, SellerDashboardView,
    SellerStoreView, AdminSellersListView, AdminSellerDetailView,
    AdminSellerVerifyView, AdminSellerRejectView,
    AdminPendingSellersView, AdminVerifySellerView,
    PasswordResetRequestView, PasswordResetVerifyView, ChangePasswordView,
)

# Create a router for viewsets
router = DefaultRouter()
router.register("addresses", AddressViewSet, basename="address")  

urlpatterns = [
    # JWT endpoints
    path("token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    
    # OTP endpoints
    path('otp/request/', OTPRequestView.as_view(), name='otp_request'),
    path('otp/verify/', OTPVerifyView.as_view(), name='otp_verify'),
    
    # User endpoints
    path("register/", RegisterView.as_view(), name="register"),
    path("profile/", ProfileView.as_view(), name="profile"),
    
    # Seller endpoints
    path('seller/apply/', SellerApplyView.as_view(), name='seller_apply'),
    path('seller/status/', SellerStatusView.as_view(), name='seller_status'),
    path('seller/dashboard/', SellerDashboardView.as_view(), name='seller_dashboard'),
    path('seller/store/', SellerStoreView.as_view(), name='seller_store'),
    
    # Admin endpoints
    path('admin/sellers/', AdminSellersListView.as_view(), name='admin_sellers_list'),
    path('admin/sellers/<int:pk>/', AdminSellerDetailView.as_view(), name='admin_seller_detail'),
    path('admin/sellers/<int:pk>/verify/', AdminSellerVerifyView.as_view(), name='admin_seller_verify'),
    path('admin/sellers/<int:pk>/reject/', AdminSellerRejectView.as_view(), name='admin_seller_reject'),
    
    # Admin seller management
    path('admin/sellers/pending/', AdminPendingSellersView.as_view(), name='admin_pending_sellers'),
    path('admin/sellers/<int:seller_id>/verify/', AdminVerifySellerView.as_view(), name='admin_verify_seller'),
    
    # Password reset
    path('password-reset/request/', PasswordResetRequestView.as_view(), name='password_reset_request'),
    path('password-reset/verify/', PasswordResetVerifyView.as_view(), name='password_reset_verify'),
    
    # Change password
    path('change-password/', ChangePasswordView.as_view(), name='change_password'),
    
    
    # Include router URLs
    path("", include(router.urls)),
]
