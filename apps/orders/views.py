# apps/orders/views.py

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404

from requests import request
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.orders.models import Cart, CartItem, Order, OrderStatusHistory
from apps.orders.serializers import (
    AddToCartSerializer,
    CartItemSerializer,
    CartSerializer,
    CheckoutSerializer,
    OrderDetailSerializer,
    OrderListSerializer,
    OrderStatusUpdateSerializer,
    UpdateCartItemSerializer,
)
from apps.rbac.permissions import IsProductAdmin


# ============================================================
# Cart ViewSet
# ============================================================

class CartViewSet(viewsets.GenericViewSet):
    """
    Cart API for the logged-in user.

    Main endpoints:
    - GET    /api/orders/cart/
    - POST   /api/orders/cart/add/
    - PATCH  /api/orders/cart/items/{item_id}/
    - DELETE /api/orders/cart/items/{item_id}/
    - DELETE /api/orders/cart/clear/
    """

    permission_classes = [IsAuthenticated]

    def get_cart(self):
        """
        Get or create cart for current user.
        """
        cart, created = Cart.objects.get_or_create(user=self.request.user)
        return cart

    def list(self, request):
        """
        Show current user's cart.

        Endpoint:
        GET /api/orders/cart/
        """
        cart = self.get_cart()
        serializer = CartSerializer(cart)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="add")
    def add_item(self, request):
        """
        Add product to cart.

        If product already exists in cart:
        - increase quantity
        """
        serializer = AddToCartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        product = serializer.validated_data["product"]
        quantity = serializer.validated_data["quantity"]

        cart = self.get_cart()

        with transaction.atomic():
            cart_item, created = CartItem.objects.get_or_create(
                cart=cart,
                product=product,
                defaults={
                    "quantity": quantity,
                    "unit_price": product.final_price,
                },
            )

            if not created:
                new_quantity = cart_item.quantity + quantity

                if product.available_stock < new_quantity:
                    return Response(
                        {"quantity": "Not enough available stock."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                cart_item.quantity = new_quantity
                cart_item.unit_price = product.final_price
                cart_item.save()

        response_serializer = CartSerializer(cart)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(
    detail=False,
    methods=["patch", "delete"],
    url_path=r"items/(?P<item_id>[^/.]+)",
)
    def item_detail(self, request, item_id=None):
        """
        Update or remove one cart item.

        PATCH:
        /api/orders/cart/items/{item_id}/

        DELETE:
        /api/orders/cart/items/{item_id}/
        """
        cart = self.get_cart()
        cart_item = get_object_or_404(CartItem, id=item_id, cart=cart)

        if request.method == "PATCH":
            serializer = UpdateCartItemSerializer(
                data=request.data,
                context={"cart_item": cart_item},
            )
            serializer.is_valid(raise_exception=True)

            cart_item.quantity = serializer.validated_data["quantity"]
            cart_item.unit_price = cart_item.product.final_price
            cart_item.save()

            response_serializer = CartSerializer(cart)
            return Response(response_serializer.data, status=status.HTTP_200_OK)

        if request.method == "DELETE":
            cart_item.delete()

        response_serializer = CartSerializer(cart)
        return Response(response_serializer.data, status=status.HTTP_200_OK)
    
    @action(detail=False, methods=["delete"], url_path="clear")
    def clear_cart(self, request):
        """
        Remove all items from cart.
        """
        cart = self.get_cart()
        cart.clear()

        return Response(
            {"message": "Cart cleared successfully."},
            status=status.HTTP_200_OK,
        )


# ============================================================
# Order ViewSet
# ============================================================

class OrderViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Order API.

    Users can:
    - list their own orders
    - retrieve their own order details
    - checkout from cart
    - cancel their own pending order

    Admins can:
    - see all orders
    - update order status
    """

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """
        Normal users see only their own orders.
        Staff/superuser see all orders.
        """
        user = self.request.user

        queryset = Order.objects.select_related("user").prefetch_related(
            "items",
            "status_history",
        )

        if user.is_staff or user.is_superuser:
            return queryset.all()

        return queryset.filter(user=user)

    def get_serializer_class(self):
        """
        Use small serializer for list.
        Use detailed serializer for retrieve.
        """
        if self.action == "list":
            return OrderListSerializer

        if self.action == "checkout":
            return CheckoutSerializer

        if self.action == "update_status":
            return OrderStatusUpdateSerializer

        return OrderDetailSerializer

    @action(detail=False, methods=["post"], url_path="checkout")
    def checkout(self, request):
        """
        Create order from current user's cart.

        Checkout will:
        - create Order
        - create OrderItems
        - reserve stock
        - clear cart
        """
        serializer = CheckoutSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        order = serializer.save()

        response_serializer = OrderDetailSerializer(order)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        """
        Cancel order.

        User can cancel only own pending_payment order.
        Admin can cancel allowed orders.
        """
        order = self.get_object()

        if not (request.user.is_staff or request.user.is_superuser):
            if order.user != request.user:
                return Response(
                    {"detail": "You cannot cancel this order."},
                    status=status.HTTP_403_FORBIDDEN,
                )

            if order.status != Order.StatusChoices.PENDING_PAYMENT:
                return Response(
                    {"detail": "Only pending payment orders can be cancelled."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        old_status = order.status

        try:
            order.cancel()
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages if hasattr(exc, "messages") else str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        OrderStatusHistory.objects.create(
            order=order,
            old_status=old_status,
            new_status=order.status,
            changed_by=request.user,
            note="Order cancelled.",
        )

        order.refresh_from_db()
        response_serializer = OrderDetailSerializer(order)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["post"],
        url_path="update-status",
        permission_classes=[IsAuthenticated, IsProductAdmin],
    )
    def update_status(self, request, pk=None):
        """
        Admin action for changing order status.
        """
        order = self.get_object()

        serializer = OrderStatusUpdateSerializer(
            data=request.data,
            context={"order": order},
        )
        serializer.is_valid(raise_exception=True)

        old_status = order.status
        new_status = serializer.validated_data["status"]
        note = serializer.validated_data.get("note", "")

        order.status = new_status
        order.save(update_fields=["status", "total_amount", "updated_at"])

        OrderStatusHistory.objects.create(
            order=order,
            old_status=old_status,
            new_status=new_status,
            changed_by=request.user,
            note=note,
        )

        order.refresh_from_db()
        response_serializer = OrderDetailSerializer(order)
        return Response(response_serializer.data, status=status.HTTP_200_OK)