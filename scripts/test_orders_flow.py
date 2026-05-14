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


from django.contrib.auth import get_user_model  

from apps.inventory.models import Stock, StockMovement, Warehouse  
from apps.orders.models import Order  
from apps.products.models import Brand, Category, Product  
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


# ============================================================
# 2) SETTINGS
# ============================================================

BASE_URL = "http://127.0.0.1:8000"

ADMIN_PHONE = "+989000000001"
ADMIN_EMAIL = "admin@mallbyte.test"
ADMIN_PASSWORD = "AdminPass123!"

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

    This keeps the orders test focused on orders,
    not on auth/register endpoints.
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
        timeout=20,
    )

    try:
        body = response.json()
    except Exception:
        body = response.text

    print(f"\n{method.upper()} {path}")
    print("Status:", response.status_code)
    print("Response:", body)

    if response.status_code != expected:
        raise Exception(
            f"Expected {expected}, got {response.status_code}. Response: {body}"
        )

    return body


def create_admin():
    """
    Create or refresh test admin user.
    """

    admin = User.objects.filter(phone=ADMIN_PHONE).first()

    if not admin:
        admin = User.objects.create_superuser(
            phone=ADMIN_PHONE,
            email=ADMIN_EMAIL,
            full_name="Test Admin",
            password=ADMIN_PASSWORD,
        )
    else:
        admin.email = ADMIN_EMAIL
        admin.full_name = "Test Admin"
        admin.is_staff = True
        admin.is_superuser = True
        admin.is_active = True
        admin.set_password(ADMIN_PASSWORD)
        admin.save()

    return admin


def login(phone, password):
    """
    Login and return access token.
    """

    result = api(
        "post",
        "/api/auth/token/",
        expected=200,
        data={
            "phone": phone,
            "password": password,
        },
    )

    return result["access"]


def create_customer(unique):
    """
    Create test customer with ORM.

    We do not call /api/auth/register/ here because this script is for orders.
    """

    phone = f"+98913{unique[-7:]}"
    email = f"customer_{unique}@mallbyte.test"

    user = User.objects.create_user(
        phone=phone,
        email=email,
        full_name="Test Customer",
        password=CUSTOMER_PASSWORD,
    )

    user.is_active = True
    user.save(update_fields=["is_active"])

    access_token = make_token_for_user(user)

    print("Customer created with ORM.")
    print("Customer phone:", phone)

    return {
        "phone": phone,
        "email": email,
        "access": access_token,
        "user_id": user.id,
    }
def create_test_product(admin, unique):
    """
    Create product using ORM.

    We use ORM here to keep this test focused on orders,
    not on product API.
    """

    category = Category.objects.create(
        name=f"Orders Category {unique}",
        description="Category for orders test",
        is_active=True,
    )

    brand = Brand.objects.create(
        name=f"Orders Brand {unique}",
        description="Brand for orders test",
        is_active=True,
    )

    product = Product.objects.create(
        seller=admin,
        category=category,
        brand=brand,
        name=f"Orders Test Product {unique}",
        description="Product created for orders flow test",
        short_description="Orders test product",
        price=100000,
        compare_price=None,
        cost_per_item=70000,
        status=Product.StatusChoices.APPROVED,
        sku=f"ORDER-SKU-{unique}",
        low_stock_threshold=5,
        barcode=f"ORDER-BAR-{unique}",
        labels=["new"],
        is_active=True,
    )

    return product


def create_stock_for_product(admin, product, unique):
    """
    Create warehouse and add stock using StockMovement.

    This uses the inventory logic we already tested.
    """

    warehouse = Warehouse.objects.create(
        name=f"Orders Warehouse {unique}",
        code=f"OW{unique[-6:]}",
        type=Warehouse.TypeChoices.MAIN,
        province="Tehran",
        city="Tehran",
        address="Orders test warehouse address",
        postal_code="1234567890",
        phone="02111111111",
        email=f"orders_warehouse_{unique}@mallbyte.test",
        manager_name="Orders Manager",
        manager_phone="09121111111",
        is_active=True,
        created_by=admin,
    )

    StockMovement.objects.create(
        product=product,
        warehouse=warehouse,
        movement_type=StockMovement.MovementType.PURCHASE,
        quantity=50,
        reference_id=f"orders-test-{unique}",
        reason="Initial stock for orders test",
        created_by=admin,
        notes="Created by orders e2e script",
    )

    return warehouse


# ============================================================
# 4) MAIN TEST FLOW
# ============================================================

def main():
    unique = str(int(time.time()))

    step("1) Create admin")
    admin = create_admin()

    step("2) Login admin")
    admin_token = login(ADMIN_PHONE, ADMIN_PASSWORD)

    step("3) Create customer")
    customer = create_customer(unique)
    customer_token = customer["access"]

    step("4) Create product")
    product = create_test_product(admin, unique)
    print("Product ID:", product.id)

    step("5) Create warehouse and stock")
    warehouse = create_stock_for_product(admin, product, unique)
    print("Warehouse ID:", warehouse.id)
    print("Product available stock:", product.available_stock)

    step("6) Show empty cart")
    cart = api(
        "get",
        "/api/orders/cart/",
        token=customer_token,
        expected=200,
    )

    step("7) Add product to cart")
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

    step("8) Update cart item quantity")
    cart = api(
        "patch",
        f"/api/orders/cart/items/{cart_item_id}/",
        token=customer_token,
        expected=200,
        data={
            "quantity": 3,
        },
    )

    step("9) Checkout")
    order = api(
        "post",
        "/api/orders/orders/checkout/",
        token=customer_token,
        expected=201,
        data={
            "receiver_name": "Test Customer",
            "receiver_phone": "09123456789",
            "province": "Tehran",
            "city": "Tehran",
            "address": "Test full address for order",
            "postal_code": "1234567890",
            "customer_note": "Please deliver fast.",
            "shipping_cost": 20000,
        },
    )

    order_id = order["id"]
    print("Order ID:", order_id)
    print("Order Number:", order["order_number"])
    print("Order Total:", order["total_amount"])
    reserved_after_checkout = Stock.objects.get(
    product=product,
    warehouse=warehouse,
        ).reserved_quantity

    print("Reserved stock after checkout:", reserved_after_checkout)

    if reserved_after_checkout != 3:
        raise Exception(
            f"Expected reserved stock to be 3 after checkout, got {reserved_after_checkout}"
        )
    step("10) Check cart is empty after checkout")
    api(
        "get",
        "/api/orders/cart/",
        token=customer_token,
        expected=200,
    )

    step("11) List my orders")
    api(
        "get",
        "/api/orders/orders/",
        token=customer_token,
        expected=200,
    )

    step("12) Retrieve order detail")
    api(
        "get",
        f"/api/orders/orders/{order_id}/",
        token=customer_token,
        expected=200,
    )

    step("13) Cancel order")
    cancelled_order = api(
        "post",
        f"/api/orders/orders/{order_id}/cancel/",
        token=customer_token,
        expected=200,
    )

    if cancelled_order["status"] != Order.StatusChoices.CANCELLED:
        raise Exception("Order was not cancelled correctly.")

    step("14) Verify order in database")
    db_order = Order.objects.get(id=order_id)

    print("DB Order status:", db_order.status)
    print("DB Order total:", db_order.total_amount)
    print("DB Order items:", db_order.items.count())
    reserved_after_cancel = Stock.objects.get(
    product=product,
    warehouse=warehouse,
    ).reserved_quantity

    print("Reserved stock after cancel:", reserved_after_cancel)

    if reserved_after_cancel != 0:
        raise Exception(
            f"Expected reserved stock to be 0 after cancel, got {reserved_after_cancel}"
        )
    print("\nSUCCESS: Orders flow test completed.")


if __name__ == "__main__":
    main()