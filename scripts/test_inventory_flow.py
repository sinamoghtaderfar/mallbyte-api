# scripts/test_inventory_flow.py

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
from apps.accounts.models import OTP, Seller  # noqa: E402
from apps.products.models import Category, Brand, Product  # noqa: E402


User = get_user_model()


# ============================================================
# 2) SETTINGS
# ============================================================

BASE_URL = "http://127.0.0.1:8000"

ADMIN_PHONE = "+989000000001"
ADMIN_EMAIL = "admin@mallbyte.test"
ADMIN_PASSWORD = "AdminPass123!"

TEST_PASSWORD = "TestPass123!"


# ============================================================
# 3) SMALL HELPERS
# ============================================================

def step(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def api(method, path, token=None, expected=200, data=None):
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


def get_latest_otp(phone):
    otp = OTP.objects.filter(phone=phone, is_used=False).latest("created_at")
    return otp.code


def create_test_product(seller_user, unique):
    category = Category.objects.create(
        name=f"Test Category {unique}",
        description="Test category",
        is_active=True,
    )

    brand = Brand.objects.create(
        name=f"Test Brand {unique}",
        description="Test brand",
        is_active=True,
    )

    product = Product.objects.create(
        seller=seller_user,
        category=category,
        brand=brand,
        name=f"Test Product {unique}",
        description="Test product for inventory flow",
        short_description="Inventory test product",
        price=100000,
        compare_price=None,
        cost_per_item=70000,
        status="approved",
        sku=f"SKU-{unique}",
        low_stock_threshold=5,
        barcode=f"BAR-{unique}",
        labels=["new"],
        is_active=True,
    )

    return product


# ============================================================
# 4) MAIN FLOW
# ============================================================

def main():
    unique = str(int(time.time()))

    user_phone = f"+98912{unique[-7:]}"
    user_email = f"user_{unique}@mallbyte.test"
    seller_email = f"seller_{unique}@mallbyte.test"
    store_name = f"Test Store {unique}"

    step("1) Create admin")
    admin = create_admin()

    step("2) Login admin")
    admin_token = login(ADMIN_PHONE, ADMIN_PASSWORD)

    step("3) Register user")
    register_result = api(
        "post",
        "/api/auth/register/",
        expected=201,
        data={
            "phone": user_phone,
            "email": user_email,
            "full_name": "Test User",
            "password": TEST_PASSWORD,
            "password2": TEST_PASSWORD,
        },
    )

    user_token = register_result["access"]

    step("4) Request OTP")
    api(
        "post",
        "/api/auth/otp/request/",
        expected=200,
        data={
            "phone": user_phone,
        },
    )

    otp_code = get_latest_otp(user_phone)
    print("OTP code from database:", otp_code)

    step("5) Verify OTP")
    otp_result = api(
        "post",
        "/api/auth/otp/verify/",
        expected=200,
        data={
            "phone": user_phone,
            "code": otp_code,
        },
    )

    user_token = otp_result["access"]

    step("6) Apply as seller")
    api(
        "post",
        "/api/auth/seller/apply/",
        token=user_token,
        expected=201,
        data={
            "store_name": store_name,
            "description": "Test seller",
            "business_phone": user_phone,
            "business_email": seller_email,
            "website": "",
            "bank_info": {
                "bank_name": "Test Bank",
                "iban": "TEST-IBAN",
            },
            "documents": [],
        },
    )

    step("7) Approve seller with ORM")
    seller = Seller.objects.get(user__phone=user_phone)
    seller.approve(admin)
    seller.refresh_from_db()

    user = User.objects.get(phone=user_phone)
    print("Seller status:", seller.status)

    step("8) Create test product with ORM")
    product = create_test_product(user, unique)
    print("Product ID:", product.id)

    step("9) Create first warehouse")
    warehouse_1 = api(
        "post",
        "/api/inventory/warehouses/",
        token=admin_token,
        expected=201,
        data={
            "name": f"Main Warehouse {unique}",
            "code": f"MW{unique[-6:]}",
            "type": "main",
            "province": "Tehran",
            "city": "Tehran",
            "address": "Test address 1",
            "postal_code": "1234567890",
            "phone": "02111111111",
            "email": f"w1_{unique}@mallbyte.test",
            "manager_name": "Manager One",
            "manager_phone": "09121111111",
            "is_active": True,
        },
    )

    warehouse_1_id = warehouse_1["id"]

    step("10) Create second warehouse")
    warehouse_2 = api(
        "post",
        "/api/inventory/warehouses/",
        token=admin_token,
        expected=201,
        data={
            "name": f"Branch Warehouse {unique}",
            "code": f"BW{unique[-6:]}",
            "type": "branch",
            "province": "Tehran",
            "city": "Karaj",
            "address": "Test address 2",
            "postal_code": "1234567891",
            "phone": "02122222222",
            "email": f"w2_{unique}@mallbyte.test",
            "manager_name": "Manager Two",
            "manager_phone": "09122222222",
            "is_active": True,
        },
    )

    warehouse_2_id = warehouse_2["id"]

    step("11) Add stock with purchase movement")
    api(
        "post",
        "/api/inventory/stock-movements/",
        token=admin_token,
        expected=201,
        data={
            "product": product.id,
            "warehouse": warehouse_1_id,
            "movement_type": "purchase",
            "quantity": 100,
            "reference_id": f"purchase-{unique}",
            "reason": "Initial stock",
            "notes": "Test script",
        },
    )

    step("12) Check stock")
    api(
        "get",
        f"/api/inventory/stocks/?product={product.id}&warehouse={warehouse_1_id}",
        token=admin_token,
        expected=200,
    )

    step("13) Reserve stock")
    api(
        "post",
        "/api/inventory/stocks/reserve/",
        token=admin_token,
        expected=200,
        data={
            "product": product.id,
            "warehouse": warehouse_1_id,
            "quantity": 10,
        },
    )

    step("14) Release reservation")
    api(
        "post",
        "/api/inventory/stocks/release-reservation/",
        token=admin_token,
        expected=200,
        data={
            "product": product.id,
            "warehouse": warehouse_1_id,
            "quantity": 5,
        },
    )

    step("15) Create stock transfer")
    transfer = api(
        "post",
        "/api/inventory/stock-transfers/",
        token=admin_token,
        expected=201,
        data={
            "from_warehouse": warehouse_1_id,
            "to_warehouse": warehouse_2_id,
            "product": product.id,
            "quantity": 20,
            "reason": "Test transfer",
            "tracking_number": "",
        },
    )

    transfer_id = transfer["id"]

    step("16) Mark transfer in transit")
    api(
        "post",
        f"/api/inventory/stock-transfers/{transfer_id}/mark-in-transit/",
        token=admin_token,
        expected=200,
        data={
            "tracking_number": f"TRK-{unique}",
        },
    )

    step("17) Complete transfer")
    api(
        "post",
        f"/api/inventory/stock-transfers/{transfer_id}/complete/",
        token=admin_token,
        expected=200,
        data={},
    )

    step("18) Final stock in first warehouse")
    api(
        "get",
        f"/api/inventory/stocks/?product={product.id}&warehouse={warehouse_1_id}",
        token=admin_token,
        expected=200,
    )

    step("19) Final stock in second warehouse")
    api(
        "get",
        f"/api/inventory/stocks/?product={product.id}&warehouse={warehouse_2_id}",
        token=admin_token,
        expected=200,
    )

    print("\nSUCCESS: Inventory flow test completed.")


if __name__ == "__main__":
    main()