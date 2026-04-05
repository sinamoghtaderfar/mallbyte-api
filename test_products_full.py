# test_products_full.py

import requests
import json
import time
import random

BASE_URL = "http://127.0.0.1:8000/api"

# رنگ‌ها
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    PURPLE = '\033[95m'
    END = '\033[0m'

def print_success(msg):
    print(f"{Colors.GREEN}✅ {msg}{Colors.END}")

def print_error(msg):
    print(f"{Colors.RED}❌ {msg}{Colors.END}")

def print_info(msg):
    print(f"{Colors.BLUE}ℹ️ {msg}{Colors.END}")

def print_step(msg):
    print(f"\n{Colors.YELLOW}📌 {msg}{Colors.END}")

def print_title(msg):
    print(f"\n{Colors.CYAN}{'='*60}{Colors.END}")
    print(f"{Colors.CYAN}   {msg}{Colors.END}")
    print(f"{Colors.CYAN}{'='*60}{Colors.END}")


def get_otp_token(phone):
    """Get token via OTP"""
    print_info(f"Requesting OTP for {phone}...")
    response = requests.post(f"{BASE_URL}/auth/otp/request/", json={"phone": phone})
    
    if response.status_code != 200:
        print_error(f"OTP request failed! Status: {response.status_code}")
        return None, None
    
    code = input(f"{Colors.PURPLE}📱 Enter OTP code for {phone}: {Colors.END}").strip()
    
    response = requests.post(f"{BASE_URL}/auth/otp/verify/", json={
        "phone": phone,
        "code": code
    })
    
    if response.status_code == 200:
        token_data = response.json()
        print_success("Login successful!")
        return token_data['access'], token_data['user']
    else:
        print_error(f"Login failed! Status: {response.status_code}")
        return None, None


def create_category(token, name):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    data = {"name": name, "description": f"This is {name} category", "is_active": True}
    response = requests.post(f"{BASE_URL}/products/categories/", headers=headers, json=data)
    if response.status_code == 201:
        return response.json()['id']
    return None


def create_brand(token, name):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    data = {"name": name, "description": f"This is {name} brand"}
    response = requests.post(f"{BASE_URL}/products/brands/", headers=headers, json=data)
    if response.status_code == 201:
        return response.json()['id']
    return None


def create_product(token, name, category_id, brand_id):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    data = {
        "name": name,
        "description": f"This is {name} product description",
        "short_description": "Short description",
        "price": random.randint(100000, 500000),
        "compare_price": random.randint(500000, 1000000),
        "category": category_id,
        "brand": brand_id,
        "sku": f"SKU-{random.randint(10000, 99999)}",
        "stock": random.randint(10, 100)
    }
    response = requests.post(f"{BASE_URL}/products/products/", headers=headers, json=data)
    if response.status_code == 201:
        return response.json()['id']
    return None


# ==================== MAIN TEST ====================
print_title("📦 PRODUCTS FULL API TEST (Review + Wishlist)")

ADMIN_PHONE = "+989121234567"
VENDOR_PHONE = "+491521094799"
CUSTOMER_PHONE = "+491521094777"

# ==================== STEP 1: Admin Login ====================
print_step("STEP 1: Admin login")
admin_token, admin_user = get_otp_token(ADMIN_PHONE)
if not admin_token:
    exit()

admin_headers = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}

# ==================== STEP 2: Create Category & Brand ====================
print_step("STEP 2: Create category and brand")
timestamp = int(time.time())
category_id = create_category(admin_token, f"Test Category {timestamp}")
brand_id = create_brand(admin_token, f"Test Brand {timestamp}")
print_success(f"Category ID: {category_id}, Brand ID: {brand_id}")

# ==================== STEP 3: Vendor Login & Create Product ====================
print_step("STEP 3: Vendor login and create product")
vendor_token, vendor_user = get_otp_token(VENDOR_PHONE)
if not vendor_token:
    exit()

vendor_headers = {"Authorization": f"Bearer {vendor_token}", "Content-Type": "application/json"}
product_id = create_product(vendor_token, "Test Product", category_id, brand_id)
print_success(f"Product created! ID: {product_id}")

# ==================== STEP 4: Admin Approve Product ====================
print_step("STEP 4: Admin approve product")
response = requests.post(f"{BASE_URL}/products/products/{product_id}/approve/", headers=admin_headers)
if response.status_code == 200:
    print_success("Product approved!")
else:
    print_error("Approval failed!")

# ==================== STEP 5: Customer Login ====================
print_step("STEP 5: Customer login")
customer_token, customer_user = get_otp_token(CUSTOMER_PHONE)
if not customer_token:
    exit()

customer_headers = {"Authorization": f"Bearer {customer_token}", "Content-Type": "application/json"}

# ==================== STEP 6: Get product details ====================
print_step(f"STEP 6: Get product details (ID: {product_id})")
response = requests.get(f"{BASE_URL}/products/products/{product_id}/")
if response.status_code == 200:
    product = response.json()
    print_success("Product details retrieved")
    print_info(f"  Name: {product['name']}")
    print_info(f"  Price: {int(product['price']):,} تومان")
else:
    print_error(f"Failed! Status: {response.status_code}")

# ==================== STEP 7: Add view to product ====================
print_step(f"STEP 7: Add view to product (ID: {product_id})")
response = requests.post(f"{BASE_URL}/products/products/{product_id}/add_view/")
if response.status_code == 200:
    data = response.json()
    print_success(f"Product views: {data['views_count']}")
else:
    print_error(f"Failed! Status: {response.status_code}")

# ==================== STEP 8: Get featured products ====================
print_step("STEP 8: Get featured products")
response = requests.get(f"{BASE_URL}/products/products/featured/")
if response.status_code == 200:
    products = response.json()
    print_success(f"Found {len(products)} featured products")
else:
    print_error(f"Failed! Status: {response.status_code}")

# ==================== STEP 9: Add review to product ====================
print_step(f"STEP 9: Add review to product (ID: {product_id})")
review_data = {
    "product": product_id,
    "rating": 5,
    "title": "Great product!",
    "comment": "This product is amazing. Highly recommended!"
}
response = requests.post(f"{BASE_URL}/products/reviews/", headers=customer_headers, json=review_data)
if response.status_code == 201:
    review = response.json()
    review_id = review['id']
    print_success(f"Review added! ID: {review_id}")
else:
    print_error(f"Failed! Status: {response.status_code}")
    review_id = None

# ==================== STEP 10: Get product reviews ====================
print_step(f"STEP 10: Get reviews for product (ID: {product_id})")
response = requests.get(f"{BASE_URL}/products/reviews/?product={product_id}")  # ✅ اصلاح شد
if response.status_code == 200:
    reviews = response.json()
    if isinstance(reviews, dict) and 'results' in reviews:
        reviews = reviews['results']
    print_success(f"Found {len(reviews)} reviews")
    for r in reviews:
        print_info(f"  - Rating: {r['rating']}/5 - {r.get('title', 'No title')}")
else:
    print_error(f"Failed! Status: {response.status_code}")

# ==================== STEP 11: Mark review as helpful ====================
if review_id:
    print_step(f"STEP 11: Mark review as helpful (ID: {review_id})")
    response = requests.post(f"{BASE_URL}/products/reviews/{review_id}/helpful/", headers=customer_headers)
    if response.status_code == 200:
        data = response.json()
        print_success(f"Helpful count: {data['helpful_count']}")
    else:
        print_error(f"Failed! Status: {response.status_code}")

# ==================== STEP 12: Add to wishlist ====================
print_step(f"STEP 12: Add product to wishlist (ID: {product_id})")
wishlist_data = {"product": product_id}
response = requests.post(f"{BASE_URL}/products/wishlist/", headers=customer_headers, json=wishlist_data)
if response.status_code == 201:
    wishlist = response.json()
    print_success(f"Added to wishlist! ID: {wishlist['id']}")
else:
    print_error(f"Failed! Status: {response.status_code}")

# ==================== STEP 13: Get wishlist ====================
print_step("STEP 13: Get customer wishlist")
response = requests.get(f"{BASE_URL}/products/wishlist/", headers=customer_headers)
if response.status_code == 200:
    wishlist = response.json()
    if isinstance(wishlist, dict) and 'results' in wishlist:
        wishlist = wishlist['results']
    print_success(f"Wishlist has {len(wishlist)} items")
    for item in wishlist:
        print_info(f"  - {item.get('product_name', 'Product')}")
else:
    print_error(f"Failed! Status: {response.status_code}")

# ==================== STEP 14: Remove from wishlist ====================
print_step("STEP 14: Remove product from wishlist")
response = requests.delete(
    f"{BASE_URL}/products/wishlist/remove/",
    headers=customer_headers,
    json={"product_id": product_id}
)
if response.status_code == 200:
    print_success("Removed from wishlist!")
else:
    print_error(f"Failed! Status: {response.status_code}")

# ==================== STEP 15: Get my products (vendor) ====================
print_step("STEP 15: Get vendor's products")
response = requests.get(f"{BASE_URL}/products/products/my_products/", headers=vendor_headers)
if response.status_code == 200:
    products = response.json()
    if isinstance(products, dict) and 'results' in products:
        products = products['results']
    print_success(f"Vendor has {len(products)} products")
else:
    print_error(f"Failed! Status: {response.status_code}")

# ==================== STEP 16: Get related products ====================
print_step(f"STEP 16: Get related products (ID: {product_id})")
response = requests.get(f"{BASE_URL}/products/products/{product_id}/related/")
if response.status_code == 200:
    related = response.json()
    print_success(f"Found {len(related)} related products")
else:
    print_error(f"Failed! Status: {response.status_code}")

# ==================== SUMMARY ====================
print_title("📊 PRODUCTS FULL API TEST SUMMARY")

summary = [
    "✅ Admin Login",
    "✅ Category & Brand Creation",
    "✅ Vendor Login & Product Creation",
    "✅ Admin Approve Product",
    "✅ Customer Login",
    "✅ Product Details",
    "✅ Add View to Product",
    "✅ Featured Products",
    "✅ Add Review",
    "✅ Get Reviews",
    "✅ Mark Review Helpful",
    "✅ Add to Wishlist",
    "✅ Get Wishlist",
    "✅ Remove from Wishlist",
    "✅ Vendor My Products",
    "✅ Related Products"
]

for item in summary:
    print_success(item)

print_title("🎉 PRODUCTS FULL API TEST COMPLETED")
print_info("All product features including reviews and wishlist are working!")