#Cart → Checkout → Payment Success → Create Shipment → Ready → Shipped → Delivered

# scripts/test_shipping_flow.py

import os
import sys
from pathlib import Path

import django


# Add project root to Python path.
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")
django.setup()

from django.contrib.auth import get_user_model


from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.products.models import Category, Brand, Product
from apps.inventory.models import Warehouse, Stock
from apps.orders.models import Order
from apps.shipping.models import Shipment


User = get_user_model()


# ============================================================
# Helpers
# ============================================================

def print_step(message):
    print(f"\n--- {message} ---")


def get_token(user):
    refresh = RefreshToken.for_user(user)
    return str(refresh.access_token)


def auth_client(user):
    client = APIClient()
    token = get_token(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def assert_status(response, expected_status, message):
    if response.status_code != expected_status:
        print("FAILED:", message)
        print("Expected:", expected_status)
        print("Got:", response.status_code)

        if hasattr(response, "data"):
            print("Response:", response.data)
        else:
            print("Response:", response.content.decode(errors="ignore"))

        raise AssertionError(message)


def reset_test_data():
    """
    Remove only test data created by this script.
    """

    User.objects.filter(phone__in=[
        "+989111111111",
        "+989222222222",
    ]).delete()

    Product.objects.filter(sku="SHIP-TEST-001").delete()
    Category.objects.filter(slug="shipping-test-category").delete()
    Brand.objects.filter(slug="shipping-test-brand").delete()
    Warehouse.objects.filter(code="SHIP-WH-001").delete()


def create_users():
    """
    Create one staff user and one normal customer.
    """

    admin = User.objects.create_user(
        phone="+989111111111",
        password="AdminPass123!",
        email="shipping-admin@example.com",
        full_name="Shipping Admin",
    )
    admin.is_staff = True
    admin.is_superuser = True
    admin.save()

    customer = User.objects.create_user(
        phone="+989222222222",
        password="CustomerPass123!",
        email="shipping-customer@example.com",
        full_name="Shipping Customer",
    )

    return admin, customer


def create_product_and_stock(seller):
    """
    Create product and stock directly with ORM.
    The API flow will use this product.
    """

    category = Category.objects.create(
        name="Shipping Test Category",
        slug="shipping-test-category",
    )

    brand = Brand.objects.create(
        name="Shipping Test Brand",
        slug="shipping-test-brand",
    )

    product = Product.objects.create(
        name="Shipping Test Product",
        slug="shipping-test-product",
        sku="SHIP-TEST-001",
        seller=seller,
        category=category,
        brand=brand,
        description="Product used for shipping flow test.",
        price=100000,
        status="approved",
        is_active=True,
    )

    warehouse = Warehouse.objects.create(
        name="Shipping Test Warehouse",
        code="SHIP-WH-001",
        city="Tehran",
        address="Test warehouse address",
        is_active=True,
    )

    stock = Stock.objects.create(
        product=product,
        warehouse=warehouse,
        quantity=20,
        reserved_quantity=0,
        low_stock_threshold=5,
    )

    return product, warehouse, stock


# ============================================================
# Main Test Flow
# ============================================================

def main():
    print_step("Reset test data")
    reset_test_data()

    print_step("Create users")
    admin, customer = create_users()

    admin_client = auth_client(admin)
    customer_client = auth_client(customer)

    print("Admin:", admin.phone)
    print("Customer:", customer.phone)

    print_step("Create product and stock")
    product, warehouse, stock = create_product_and_stock(admin)

    print("Product:", product.name)
    print("Initial quantity:", stock.quantity)
    print("Initial reserved:", stock.reserved_quantity)

    # --------------------------------------------------------
    # 1. Add product to cart
    # --------------------------------------------------------

    print_step("Add product to cart")

    response = customer_client.post(
        "/api/orders/cart/add/",
        {
            "product": product.id,
            "quantity": 2,
        },
        format="json",
    )

    assert_status(response, 200, "Add product to cart failed")
    print("Cart item created")

    # --------------------------------------------------------
    # 2. Checkout order
    # --------------------------------------------------------

    print_step("Checkout order")

    response = customer_client.post(
        "/api/orders/orders/checkout/",
        {
            "receiver_name": "Shipping Customer",
            "receiver_phone": "+989222222222",
            "province": "Tehran",
            "city": "Tehran",
            "address": "Test delivery address",
            "postal_code": "1234567890",
            "notes": "Shipping flow test order",
        },
        format="json",
    )

    assert_status(response, 201, "Checkout failed")

    order_id = response.data["id"]
    order = Order.objects.get(id=order_id)

    stock.refresh_from_db()

    print("Order:", order.order_number)
    print("Order status after checkout:", order.status)
    print("Reserved after checkout:", stock.reserved_quantity)
    print("Quantity after checkout:", stock.quantity)

    assert order.status == Order.StatusChoices.PENDING_PAYMENT
    assert stock.reserved_quantity == 2
    assert stock.quantity == 20

    # --------------------------------------------------------
    # 3. Create payment
    # --------------------------------------------------------

    print_step("Create payment")

    response = customer_client.post(
        "/api/payments/payments/",
        {
            "order": order.id,
            "provider": "mock",
        },
        format="json",
    )

    assert_status(response, 201, "Create payment failed")

    payment_id = response.data["id"]
    print("Payment ID:", payment_id)

    # --------------------------------------------------------
    # 4. Mark payment success
    # --------------------------------------------------------

    print_step("Mark payment success")

    response = customer_client.post(
        f"/api/payments/payments/{payment_id}/mark-success/",
        {
            "gateway_reference": "SHIP-TEST-PAYMENT-SUCCESS",
            "gateway_response": {
                "source": "test_shipping_flow",
                "result": "success",
            },
        },
        format="json",
    )

    assert_status(response, 200, "Mark payment success failed")

    order.refresh_from_db()
    stock.refresh_from_db()

    print("Order status after payment:", order.status)
    print("Order payment status:", order.payment_status)
    print("Reserved after payment:", stock.reserved_quantity)
    print("Quantity after payment:", stock.quantity)

    assert order.status == Order.StatusChoices.PAID
    assert order.payment_status == Order.PaymentStatusChoices.PAID
    assert stock.reserved_quantity == 0
    assert stock.quantity == 18

    # --------------------------------------------------------
    # 5. Normal customer should NOT create shipment
    # --------------------------------------------------------

    print_step("Customer cannot create shipment")

    response = customer_client.post(
        "/api/shipping/shipments/",
        {
            "order": order.id,
            "carrier": "dhl",
        },
        format="json",
    )

    assert_status(response, 403, "Customer should not create shipment")
    print("Customer blocked correctly")

    # --------------------------------------------------------
    # 6. Staff creates shipment
    # --------------------------------------------------------

    print_step("Admin creates shipment")

    response = admin_client.post(
        "/api/shipping/shipments/",
        {
            "order": order.id,
            "carrier": "dhl",
        },
        format="json",
    )

    assert_status(response, 201, "Create shipment failed")

    shipment_id = response.data["id"]
    shipment = Shipment.objects.get(id=shipment_id)

    print("Shipment:", shipment.shipment_number)
    print("Shipment status:", shipment.status)

    assert shipment.status == Shipment.StatusChoices.PENDING
    assert shipment.order_id == order.id
    assert shipment.user_id == customer.id

    # --------------------------------------------------------
    # 7. Creating second active shipment should fail
    # --------------------------------------------------------

    print_step("Second active shipment should fail")

    response = admin_client.post(
        "/api/shipping/shipments/",
        {
            "order": order.id,
            "carrier": "dhl",
        },
        format="json",
    )

    assert_status(response, 400, "Second active shipment should not be allowed")
    print("Second active shipment blocked correctly")

    # --------------------------------------------------------
    # 8. Mark shipment ready
    # --------------------------------------------------------

    print_step("Mark shipment ready")

    response = admin_client.post(
        f"/api/shipping/shipments/{shipment_id}/mark-ready/",
        {
            "note": "Package prepared.",
        },
        format="json",
    )

    assert_status(response, 200, "Mark ready failed")

    shipment.refresh_from_db()
    print("Shipment status:", shipment.status)

    assert shipment.status == Shipment.StatusChoices.READY_TO_SHIP

    # --------------------------------------------------------
    # 9. Mark shipment shipped
    # --------------------------------------------------------

    print_step("Mark shipment shipped")

    response = admin_client.post(
        f"/api/shipping/shipments/{shipment_id}/mark-shipped/",
        {
            "tracking_number": "DHL-TEST-123456",
            "tracking_url": "https://tracking.example.com/DHL-TEST-123456",
            "note": "Package handed to carrier.",
        },
        format="json",
    )

    assert_status(response, 200, "Mark shipped failed")

    shipment.refresh_from_db()
    order.refresh_from_db()

    print("Shipment status:", shipment.status)
    print("Tracking number:", shipment.tracking_number)
    print("Order status:", order.status)

    assert shipment.status == Shipment.StatusChoices.SHIPPED
    assert shipment.tracking_number == "DHL-TEST-123456"
    assert order.status == Order.StatusChoices.SHIPPED

    # --------------------------------------------------------
    # 10. Customer can see own shipment detail
    # --------------------------------------------------------

    print_step("Customer can retrieve own shipment")

    response = customer_client.get(
        f"/api/shipping/shipments/{shipment_id}/",
        format="json",
    )

    assert_status(response, 200, "Customer retrieve shipment failed")

    print("Customer retrieved shipment:", response.data["shipment_number"])

    # --------------------------------------------------------
    # 11. Mark shipment delivered
    # --------------------------------------------------------

    print_step("Mark shipment delivered")

    response = admin_client.post(
        f"/api/shipping/shipments/{shipment_id}/mark-delivered/",
        {
            "note": "Delivered to customer.",
        },
        format="json",
    )

    assert_status(response, 200, "Mark delivered failed")

    shipment.refresh_from_db()
    order.refresh_from_db()

    print("Shipment status:", shipment.status)
    print("Order status:", order.status)
    print("Delivered at:", shipment.delivered_at)

    assert shipment.status == Shipment.StatusChoices.DELIVERED
    assert order.status == Order.StatusChoices.DELIVERED
    assert shipment.delivered_at is not None
    assert order.delivered_at is not None

    # --------------------------------------------------------
    # 12. Delivered shipment cannot be cancelled
    # --------------------------------------------------------

    print_step("Delivered shipment cannot be cancelled")

    response = admin_client.post(
        f"/api/shipping/shipments/{shipment_id}/cancel/",
        {
            "note": "Try to cancel delivered shipment.",
        },
        format="json",
    )

    assert_status(response, 400, "Delivered shipment should not be cancelled")
    print("Delivered shipment cancel blocked correctly")

    # --------------------------------------------------------
    # 13. List shipments
    # --------------------------------------------------------

    print_step("List shipments")

    response = admin_client.get(
        "/api/shipping/shipments/",
        format="json",
    )

    assert_status(response, 200, "List shipments failed")

    print("Shipments list endpoint works")

    print_step("SUCCESS")
    print("Shipping flow test completed successfully.")


if __name__ == "__main__":
    main()