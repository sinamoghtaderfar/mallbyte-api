# apps/orders/views.py

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.orders.models import (
    Cart,
    CartItem,
    Order,
    OrderStatusHistory,
    SellerOrderFulfillment,
    SellerOrderFulfillmentHistory,
)
from apps.orders.serializers import (
    AddToCartSerializer,
    CartSerializer,
    CheckoutSerializer,
    OrderDetailSerializer,
    OrderListSerializer,
    OrderStatusUpdateSerializer,
    SellerOrderDetailSerializer,
    SellerOrderListSerializer,
    SellerOrderStatusUpdateSerializer,
    UpdateCartItemSerializer,
)
from apps.orders.services import create_order_notification
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

        if self.action == "seller_orders":
            return SellerOrderListSerializer

        if self.action == "seller_detail":
            return SellerOrderDetailSerializer

        if self.action == "seller_status":
            return SellerOrderStatusUpdateSerializer

        if self.action == "update_status":
            return OrderStatusUpdateSerializer

        return OrderDetailSerializer

    def _require_seller(self, user):
        """
        Ensure current user is a seller.
        """
        if not getattr(user, "is_seller", False):
            raise PermissionDenied("Only sellers can access seller orders.")

    def _get_seller_queryset(self, user):
        """
        Orders that contain at least one product owned by this seller.
        """
        self._require_seller(user)

        return (
            Order.objects.select_related("user")
            .prefetch_related(
                "items__product",
                "status_history",
            )
            .filter(items__product__seller=user)
            .distinct()
        )

    def _get_seller_order_or_404(self, user, pk):
        """
        Retrieve one seller-visible order.
        """
        return get_object_or_404(self._get_seller_queryset(user), pk=pk)

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
            order.cancel(user=request.user)
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
        create_order_notification(
            order=order,
            template_key="order_cancelled",
            order_id=order.order_number,
        )
        order.refresh_from_db()
        response_serializer = OrderDetailSerializer(order)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="seller")
    def seller_orders(self, request):
        """
        List orders that contain this seller's products.

        Endpoint:
        GET /api/orders/orders/seller/
        """
        orders = self._get_seller_queryset(request.user)

        serializer = SellerOrderListSerializer(
            orders,
            many=True,
            context={"request": request},
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"], url_path="seller-detail")
    def seller_detail(self, request, pk=None):
        """
        Show one seller-visible order.

        Endpoint:
        GET /api/orders/orders/{id}/seller-detail/
        """
        order = self._get_seller_order_or_404(request.user, pk)

        serializer = SellerOrderDetailSerializer(
            order,
            context={"request": request},
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["post"],
        url_path="seller-status",
    )
    def seller_status(self, request, pk=None):
        """Update only the authenticated seller's fulfillment state."""
        visible_order = self._get_seller_order_or_404(request.user, pk)

        # Keep validation, state changes, and history in the same transaction.
        # Payment completion locks the order before changing fulfillment.
        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=visible_order.pk)

            (
                fulfillment,
                _created,
            ) = SellerOrderFulfillment.objects.select_for_update().get_or_create(
                order=order,
                seller=request.user,
                defaults={
                    "status": (
                        order.status
                        if order.payment_status == Order.PaymentStatusChoices.PAID
                        else Order.StatusChoices.PENDING_PAYMENT
                    ),
                },
            )

            serializer = SellerOrderStatusUpdateSerializer(
                data=request.data,
                context={
                    "order": order,
                    "fulfillment": fulfillment,
                },
            )
            serializer.is_valid(raise_exception=True)

            old_status = fulfillment.status
            new_status = serializer.validated_data["status"]
            note = serializer.validated_data.get("note", "")

            fulfillment.status = new_status
            fulfillment.save(update_fields=["status", "updated_at"])

            SellerOrderFulfillmentHistory.objects.create(
                fulfillment=fulfillment,
                old_status=old_status,
                new_status=new_status,
                changed_by=request.user,
                note=note,
            )

        # Never modify the marketplace-wide Order.status here.
        response_serializer = SellerOrderDetailSerializer(
            order,
            context={"request": request},
        )
        return Response(
            response_serializer.data,
            status=status.HTTP_200_OK,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="update-status",
        permission_classes=[IsAuthenticated, IsProductAdmin],
    )
    def update_status(self, request, pk=None):
        """Move an already-paid order to processing as an administrator."""
        visible_order = self.get_object()

        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=visible_order.pk)

            # Validate after acquiring the lock; don't trust stale status.
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
                note=note or "Order preparation started.",
            )

            create_order_notification(
                order=order,
                template_key="order_status_updated",
                order_id=order.order_number,
                status_display=order.get_status_display(),
                metadata={"status": order.status},
            )

        response_serializer = OrderDetailSerializer(order)
        return Response(
            response_serializer.data,
            status=status.HTTP_200_OK,
        )
