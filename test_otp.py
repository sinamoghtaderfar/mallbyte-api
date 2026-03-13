# test_otp.py

import requests
import json

BASE_URL = "http://127.0.0.1:8000/api/auth"
PHONE = "+491771789261"

# Request OTP
print("\nRequesting OTP...")
response = requests.post(f"{BASE_URL}/otp/request/", json={"phone": PHONE})
print(f"Status: {response.status_code}")
print(f"Response: {response.json()}\n")

# Wait for user to enter code from console
code = input("Enter OTP code from console: ")

# Verify OTP
print("\nVerifying OTP...")
response = requests.post(f"{BASE_URL}/otp/verify/", json={
    "phone": PHONE,
    "code": code
})
print(f"Status: {response.status_code}")
print(f"Response: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")