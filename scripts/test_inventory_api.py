"""Real inventory API smoke test against a running server.

Examples (Windows CMD):
  python scripts\test_inventory_api.py --base-url http://127.0.0.1:8000 --admin-phone 0912xxxxxxx --admin-password yourpass --product-id 1

Notes:
- Uses JWT login via /api/auth/token/
- Runs against your real database through the live API.
- Creates test warehouses/movements/transfers with a unique suffix.
"""

from __future__ import annotations

import argparse
import json
import uuid
from dataclasses import dataclass

import requests


@dataclass
class ApiCtx:
    base_url: str
    token: str

    @property
    def headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }


def fail(label: str, response: requests.Response):
    try:
        body = response.json()
    except Exception:
        body = response.text
    raise RuntimeError(
        f"{label} failed: status={response.status_code}, response={body}"
    )


def expect(label: str, response: requests.Response, expected: int):
    if response.status_code != expected:
        fail(label, response)


def login(base_url: str, phone: str, password: str) -> str:
    url = f"{base_url}/api/auth/token/"
    res = requests.post(url, json={"phone": phone, "password": password}, timeout=20)
    expect("admin login", res, 200)
    data = res.json()
    token = data.get("access")
    if not token:
        raise RuntimeError("admin login failed: no access token in response")
    return token


def post(ctx: ApiCtx, path: str, payload: dict) -> requests.Response:
    return requests.post(
        f"{ctx.base_url}{path}",
        headers=ctx.headers,
        data=json.dumps(payload),
        timeout=30,
    )


def get(ctx: ApiCtx, path: str, params: dict | None = None) -> requests.Response:
    return requests.get(
        f"{ctx.base_url}{path}",
        headers=ctx.headers,
        params=params,
        timeout=30,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--admin-phone", required=True)
    parser.add_argument("--admin-password", required=True)
    parser.add_argument("--product-id", type=int, required=True)
    parser.add_argument("--source-warehouse-id", type=int)
    parser.add_argument("--dest-warehouse-id", type=int)
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    token = login(base_url, args.admin_phone, args.admin_password)
    ctx = ApiCtx(base_url=base_url, token=token)

    suffix = uuid.uuid4().hex[:8]

    # 1) Prepare warehouses (create unless IDs are supplied)
    if args.source_warehouse_id:
        source_id = args.source_warehouse_id
    else:
        res_w1 = post(
            ctx,
            "/api/inventory/warehouses/",
            {
                "name": f"API Main Warehouse {suffix}",
                "code": f"API-MW-{suffix}",
                "type": "main",
                "province": "Tehran",
                "city": "Tehran",
                "address": "Smoke Test - Source",
                "postal_code": "1111111111",
                "phone": "02111111111",
                "email": f"w1-{suffix}@example.com",
                "manager_name": "Smoke Admin",
                "manager_phone": "09120000001",
                "is_active": True,
            },
        )
        expect("create source warehouse", res_w1, 201)
        source_id = res_w1.json()["id"]

    if args.dest_warehouse_id:
        dest_id = args.dest_warehouse_id
    else:
        res_w2 = post(
            ctx,
            "/api/inventory/warehouses/",
            {
                "name": f"API Branch Warehouse {suffix}",
                "code": f"API-BW-{suffix}",
                "type": "branch",
                "province": "Tehran",
                "city": "Tehran",
                "address": "Smoke Test - Destination",
                "postal_code": "2222222222",
                "phone": "02122222222",
                "email": f"w2-{suffix}@example.com",
                "manager_name": "Smoke Admin 2",
                "manager_phone": "09120000002",
                "is_active": True,
            },
        )
        expect("create destination warehouse", res_w2, 201)
        dest_id = res_w2.json()["id"]

    if source_id == dest_id:
        raise RuntimeError("source and destination warehouses must be different")

    # 2) Purchase movement (+30)
    res_purchase = post(
        ctx,
        "/api/inventory/movements/",
        {
            "product": args.product_id,
            "warehouse": source_id,
            "movement_type": "purchase",
            "quantity": 30,
            "reference_id": f"SMOKE-PO-{suffix}",
            "reason": "smoke test purchase",
            "notes": "created by scripts/test_inventory_api.py",
        },
    )
    expect("purchase movement", res_purchase, 201)

    # 3) Validation check: invalid outgoing sign (sale with positive qty)
    res_invalid = post(
        ctx,
        "/api/inventory/movements/",
        {
            "product": args.product_id,
            "warehouse": source_id,
            "movement_type": "sale",
            "quantity": 5,
            "reference_id": f"SMOKE-INVALID-{suffix}",
            "reason": "expect validation error",
        },
    )
    expect("invalid sale sign validation", res_invalid, 400)

    # 4) Create transfer
    res_transfer = post(
        ctx,
        "/api/inventory/transfers/",
        {
            "from_warehouse": source_id,
            "to_warehouse": dest_id,
            "product": args.product_id,
            "quantity": 10,
            "status": "pending",
            "reason": "smoke test transfer",
        },
    )
    expect("create transfer", res_transfer, 201)
    transfer_id = res_transfer.json()["id"]

    # 5) Complete transfer
    res_complete = post(ctx, f"/api/inventory/transfers/{transfer_id}/complete/", {})
    expect("complete transfer", res_complete, 200)

    # 6) Stock list check
    res_stocks = get(ctx, "/api/inventory/stocks/")
    expect("stock list", res_stocks, 200)

    print("✅ Real inventory API smoke test passed")
    print(
        f"product={args.product_id}, source_warehouse={source_id}, "
        f"dest_warehouse={dest_id}, transfer={transfer_id}"
    )


if __name__ == "__main__":
    main()
