"""
Synthetic retail dataset generator for AgenticDB demo.
Creates customers, products, orders, and order_items tables.
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta

import pandas as pd

logger = logging.getLogger(__name__)

CATEGORIES = ["Electronics", "Clothing", "Books", "Home & Kitchen", "Sports", "Toys"]
CITIES = ["Mumbai", "Delhi", "Bangalore", "Hyderabad", "Chennai", "Pune", "Kolkata"]
STATES = ["MH", "DL", "KA", "TG", "TN", "MH", "WB"]


def generate_customers(n: int = 500, seed: int = 42) -> pd.DataFrame:
    rng = random.Random(seed)
    records = []
    for i in range(1, n + 1):
        city_idx = rng.randint(0, len(CITIES) - 1)
        records.append({
            "customer_id": i,
            "first_name": rng.choice(["Aarav", "Priya", "Rahul", "Anjali", "Ravi", "Sneha", "Kiran", "Divya"]),
            "last_name": rng.choice(["Sharma", "Patel", "Reddy", "Nair", "Singh", "Kumar", "Mehta", "Gupta"]),
            "email": f"user{i}@example.com",
            "city": CITIES[city_idx],
            "state": STATES[city_idx],
            "registration_date": (
                datetime(2022, 1, 1) + timedelta(days=rng.randint(0, 730))
            ).strftime("%Y-%m-%d"),
            "is_premium": rng.random() > 0.8,
        })
    return pd.DataFrame(records)


def generate_products(n: int = 200, seed: int = 42) -> pd.DataFrame:
    rng = random.Random(seed + 1)
    records = []
    for i in range(1, n + 1):
        cat = rng.choice(CATEGORIES)
        price = round(rng.uniform(5.0, 1500.0), 2)
        records.append({
            "product_id": i,
            "name": f"{cat} Product {i}",
            "category": cat,
            "price": price,
            "stock_quantity": rng.randint(0, 500),
            "is_active": rng.random() > 0.1,
        })
    return pd.DataFrame(records)


def generate_orders(customers: pd.DataFrame, n: int = 2000, seed: int = 42) -> pd.DataFrame:
    rng = random.Random(seed + 2)
    customer_ids = customers["customer_id"].tolist()
    statuses = ["completed", "completed", "completed", "pending", "cancelled"]
    records = []
    for i in range(1, n + 1):
        order_date = datetime(2023, 1, 1) + timedelta(days=rng.randint(0, 730))
        records.append({
            "order_id": i,
            "customer_id": rng.choice(customer_ids),
            "order_date": order_date.strftime("%Y-%m-%d"),
            "status": rng.choice(statuses),
            "shipping_city": rng.choice(CITIES),
            "total_amount": 0.0,  # updated after items
        })
    return pd.DataFrame(records)


def generate_order_items(
    orders: pd.DataFrame, products: pd.DataFrame, seed: int = 42
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = random.Random(seed + 3)
    order_ids = orders["order_id"].tolist()
    product_records = products[["product_id", "price"]].to_dict("records")

    items = []
    totals: dict[int, float] = {}
    item_id = 1
    for oid in order_ids:
        n_items = rng.randint(1, 5)
        chosen = rng.sample(product_records, min(n_items, len(product_records)))
        for p in chosen:
            qty = rng.randint(1, 4)
            unit_price = p["price"]
            subtotal = round(qty * unit_price, 2)
            items.append({
                "item_id": item_id,
                "order_id": oid,
                "product_id": p["product_id"],
                "quantity": qty,
                "unit_price": unit_price,
                "subtotal": subtotal,
            })
            totals[oid] = totals.get(oid, 0.0) + subtotal
            item_id += 1

    df_items = pd.DataFrame(items)
    orders_updated = orders.copy()
    orders_updated["total_amount"] = orders_updated["order_id"].map(totals).round(2)
    return df_items, orders_updated


def generate_all(rows: int = 1000, seed: int = 42) -> dict[str, pd.DataFrame]:
    """
    Generate all retail tables. `rows` approximates total order items.
    Returns dict of table_name -> DataFrame.
    """
    n_customers = max(50, rows // 4)
    n_products = max(20, rows // 10)
    n_orders = max(100, rows // 2)

    customers = generate_customers(n_customers, seed)
    products = generate_products(n_products, seed)
    orders_raw = generate_orders(customers, n_orders, seed)
    order_items, orders = generate_order_items(orders_raw, products, seed)

    logger.info(
        "Generated retail data: %d customers, %d products, %d orders, %d items",
        len(customers), len(products), len(orders), len(order_items),
    )

    return {
        "customers": customers,
        "products": products,
        "orders": orders,
        "order_items": order_items,
    }
