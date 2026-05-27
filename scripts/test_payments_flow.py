# scripts/test_payments_flow.py

import os
import sys
import time

import django
import requests


# ============================================================
# 1) DJANGO SETUP
# ============================================================

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")
django.setup()


from django.contrib.auth import get_user_model  # noqa: E402
from rest_framework_simplejwt.tokens import RefreshToken  # noqa: E402

from apps.inventory.models import Stock, StockMovement, Warehouse  # noqa: E402
from apps.orders.models import Order  # noqa: E402
from apps.payments.models import Payment  # noqa: E402
from apps.products.models import Brand, Category, Product  # noqa: E402


User = get_user_model()


# ============================================================
# 2) SETTINGS
# ============================================================

BASE_URL = "http://127.0.0.1:8000"

ADMIN_PHONE = "+989000000001"
ADMIN_EMAIL = "admin@mallbyte.test"

CUSTOMER_PASSWORD = "CustomerPass123!"


# ============================================================
# 3) SMALL HELPERS
# ============================================================

def step(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def make_token_for_user(user):
    """
    Create JWT access token directly for a user.

    This keeps the test focused on payments,
    not on auth/login/register.
    """
    if not user.is_active:
        raise Exception("Cannot create token for inactive user.")

    refresh = RefreshToken.for_user(user)
    return str(refresh.access_token)


def api(method, path, token=None, expected=200, data=None):
    """
    Send HTTP request to local API.
    """

    url = BASE_URL + path

    headers = {}

    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = requests.request(
        method=method,
        url=url,
        headers=headers,
        json=data,
        timeout=60,
    )

    try:
        body = response.json()
    except Exception:
        body = response.text

    print(f"\n{method.upper()} {path}")
    print("Status:", response.status_code)
    print("Response:", body)

    if isinstance(expected, (list, tuple, set)):
        valid_statuses = expected
    else:
        valid_statuses = [expected]

    if response.status_code not in valid_statuses:
        raise Exception(
            f"Expected {valid_statuses}, got {response.status_code}. Response: {body}"
        )

    return body


def create_admin():
    """
    Create or refresh test admin user.
    """

    admin = User.objects.filter(phone=ADMIN_PHONE).first()

    if admin:
        admin.email = ADMIN_EMAIL
        admin.full_name = "Test Admin"
        admin.is_staff = True
        admin.is_superuser = True
        admin.is_active = True
        admin.save(
            update_fields=[
                "email",
                "full_name",
                "is_staff",
                "is_superuser",
                "is_active",
            ]
        )
        return admin

    admin = User.objects.create_superuser(
        phone=ADMIN_PHONE,
        email=ADMIN_EMAIL,
        full_name="Test Admin",
        password="AdminPass123!",
    )

    return admin


def create_customer(unique):
    """
    Create test customer with ORM.
    """

    phone = f"+98914{unique[-7:]}"
    email = f"payment_customer_{unique}@mallbyte.test"

    user = User.objects.create_user(
        phone=phone,
        email=email,
        full_name="Payment Test Customer",
        password=CUSTOMER_PASSWORD,
    )

    user.is_active = True
    user.save(update_fields=["is_active"])

    return user


def create_test_product(admin, unique):
    """
    Create approved product with ORM.
    """

    category = Category.objects.create(
        name=f"Payments Category {unique}",
        description="Category for payments test",
        is_active=True,
    )

    brand = Brand.objects.create(
        name=f"Payments Brand {unique}",
        description="Brand for payments test",
        is_active=True,
    )

    product = Product.objects.create(
        seller=admin,
        category=category,
        brand=brand,
        name=f"Payments Test Product {unique}",
        description="Product created for payments flow test",
        short_description="Payments test product",
        price=100000,
        compare_price=None,
        cost_per_item=70000,
        status=Product.StatusChoices.APPROVED,
        sku=f"PAY-SKU-{unique}",
        low_stock_threshold=5,
        barcode=f"PAY-BAR-{unique}",
        labels=["new"],
        is_active=True,
    )

    return product


def create_stock_for_product(admin, product, unique):
    """
    Create warehouse and add stock using inventory logic.
    """

    warehouse = Warehouse.objects.create(
        name=f"Payments Warehouse {unique}",
        code=f"PW{unique[-6:]}",
        type=Warehouse.TypeChoices.MAIN,
        province="Tehran",
        city="Tehran",
        address="Payments test warehouse address",
        postal_code="1234567890",
        phone="02111111111",
        email=f"payments_warehouse_{unique}@mallbyte.test",
        manager_name="Payments Manager",
        manager_phone="09121111111",
        is_active=True,
        created_by=admin,
    )

    StockMovement.objects.create(
        product=product,
        warehouse=warehouse,
        movement_type=StockMovement.MovementType.PURCHASE,
        quantity=50,
        reference_id=f"payments-test-{unique}",
        reason="Initial stock for payments test",
        created_by=admin,
        notes="Created by payments e2e script",
    )

    return warehouse


# ============================================================
# 4) MAIN TEST FLOW
# ============================================================

def main():
    unique = str(int(time.time()))

    step("1) Create admin and customer")
    admin = create_admin()
    customer = create_customer(unique)

    admin_token = make_token_for_user(admin)
    customer_token = make_token_for_user(customer)

    print("Admin ID:", admin.id)
    print("Customer ID:", customer.id)

    step("2) Create product and stock")
    product = create_test_product(admin, unique)
    warehouse = create_stock_for_product(admin, product, unique)

    stock = Stock.objects.get(product=product, warehouse=warehouse)

    print("Product ID:", product.id)
    print("Warehouse ID:", warehouse.id)
    print("Initial quantity:", stock.quantity)
    print("Initial reserved:", stock.reserved_quantity)

    if stock.quantity != 50:
        raise Exception(f"Expected initial quantity 50, got {stock.quantity}")

    step("3) Add product to cart")
    cart = api(
        "post",
        "/api/orders/cart/add/",
        token=customer_token,
        expected=200,
        data={
            "product": product.id,
            "quantity": 2,
        },
    )

    cart_item_id = cart["items"][0]["id"]
    print("Cart Item ID:", cart_item_id)

    step("4) Update cart item quantity to 3")
    api(
        "patch",
        f"/api/orders/cart/items/{cart_item_id}/",
        token=customer_token,
        expected=200,
        data={
            "quantity": 3,
        },
    )

    step("5) Checkout order")
    order = api(
        "post",
        "/api/orders/orders/checkout/",
        token=customer_token,
        expected=201,
        data={
            "receiver_name": "Payment Test Customer",
            "receiver_phone": "09123456789",
            "province": "Tehran",
            "city": "Tehran",
            "address": "Payment test full address",
            "postal_code": "1234567890",
            "customer_note": "Payment test order.",
            "shipping_cost": 20000,
        },
    )

    order_id = order["id"]

    print("Order ID:", order_id)
    print("Order Number:", order["order_number"])
    print("Order Total:", order["total_amount"])

    stock.refresh_from_db()

    print("Reserved after checkout:", stock.reserved_quantity)
    print("Quantity after checkout:", stock.quantity)

    if stock.reserved_quantity != 3:
        raise Exception(
            f"Expected reserved stock 3 after checkout, got {stock.reserved_quantity}"
        )

    if stock.quantity != 50:
        raise Exception(
            f"Expected quantity to stay 50 after checkout, got {stock.quantity}"
        )

    step("6) Create first payment attempt")
    payment_1 = api(
        "post",
        "/api/payments/payments/",
        token=customer_token,
        expected=201,
        data={
            "order": order_id,
            "provider": "mock",
        },
    )

    payment_1_id = payment_1["id"]

    print("Payment 1 ID:", payment_1_id)

    step("7) Mark first payment as failed")
    payment_1_failed = api(
        "post",
        f"/api/payments/payments/{payment_1_id}/mark-failed/",
        token=customer_token,
        expected=200,
        data={
            "reason": "Mock gateway declined payment.",
            "gateway_response": {
                "mock_status": "declined",
            },
        },
    )

    if payment_1_failed["status"] != Payment.StatusChoices.FAILED:
        raise Exception("Payment 1 was not marked as failed.")

    db_order = Order.objects.get(id=order_id)
    stock.refresh_from_db()

    print("Order status after failed payment:", db_order.status)
    print("Payment status after failed payment:", db_order.payment_status)
    print("Reserved after failed payment:", stock.reserved_quantity)
    print("Quantity after failed payment:", stock.quantity)

    if db_order.status != Order.StatusChoices.PENDING_PAYMENT:
        raise Exception("Order status should still be pending_payment after failed payment.")

    if stock.reserved_quantity != 3:
        raise Exception("Reserved stock should remain 3 after failed payment.")

    if stock.quantity != 50:
        raise Exception("Quantity should remain 50 after failed payment.")

    step("8) Create second payment attempt")
    payment_2 = api(
        "post",
        "/api/payments/payments/",
        token=customer_token,
        expected=201,
        data={
            "order": order_id,
            "provider": "mock",
        },
    )

    payment_2_id = payment_2["id"]

    print("Payment 2 ID:", payment_2_id)

    step("9) Mark second payment as successful")
    payment_2_success = api(
        "post",
        f"/api/payments/payments/{payment_2_id}/mark-success/",
        token=customer_token,
        expected=200,
        data={
            "gateway_reference": f"MOCK-PAY-{unique}",
            "gateway_response": {
                "mock_status": "paid",
                "provider": "mock",
            },
        },
    )

    if payment_2_success["status"] != Payment.StatusChoices.SUCCESS:
        raise Exception("Payment 2 was not marked as success.")

    step("10) Verify order and stock after successful payment")
    db_order.refresh_from_db()
    stock.refresh_from_db()

    print("Order status:", db_order.status)
    print("Order payment status:", db_order.payment_status)
    print("Reserved after success:", stock.reserved_quantity)
    print("Quantity after success:", stock.quantity)

    if db_order.status != Order.StatusChoices.PAID:
        raise Exception(f"Expected order status paid, got {db_order.status}")

    if db_order.payment_status != Order.PaymentStatusChoices.PAID:
        raise Exception(
            f"Expected order payment status paid, got {db_order.payment_status}"
        )

    if stock.reserved_quantity != 0:
        raise Exception(
            f"Expected reserved stock 0 after payment success, got {stock.reserved_quantity}"
        )

    if stock.quantity != 47:
        raise Exception(
            f"Expected quantity 47 after payment success, got {stock.quantity}"
        )

    step("11) List customer payments")
    api(
        "get",
        "/api/payments/payments/",
        token=customer_token,
        expected=200,
    )

    step("12) Retrieve successful payment detail")
    api(
        "get",
        f"/api/payments/payments/{payment_2_id}/",
        token=customer_token,
        expected=200,
    )

    print("\nSUCCESS: Payments flow test completed.")


if __name__ == "__main__":
    main()