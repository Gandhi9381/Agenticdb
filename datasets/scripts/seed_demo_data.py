"""
AgenticDB Demo Seeding Script
Generates sample CSV datasets and seeds the database with retail data,
incidents, query history, optimizations, approvals, and experiments.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

# Fix Windows cp1252 stdout encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Ensure backend can be imported
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "backend"))
sys.path.insert(0, BACKEND_DIR)

from app.database.engine import SessionLocal, init_db
from app.models import (
    DatasetModel, QueryHistoryModel, MonitoringMetricModel,
    IncidentModel, IncidentSeverity, IncidentStatus,
    OptimizationModel, OptimizationStatus,
    ApprovalModel, ApprovalStatus,
    ExperimentModel,
)
from app.services.data_generator import generate_all
from app.services.dataset_service import import_dataframe_to_db

SAMPLE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sample"))


def seed_all():
    print("🌱 Initializing AgenticDB schema...")
    init_db()

    os.makedirs(SAMPLE_DIR, exist_ok=True)
    db = SessionLocal()

    try:
        # 1. Generate & export CSV files + seed tables
        print("📦 Generating retail dataset (customers, products, orders, order_items)...")
        tables = generate_all(rows=1200, seed=42)

        for name, df in tables.items():
            csv_path = os.path.join(SAMPLE_DIR, f"{name}.csv")
            df.to_csv(csv_path, index=False)
            print(f"   ✓ Wrote {csv_path} ({len(df)} rows)")

            res = import_dataframe_to_db(db, df, name, source="synthetic", overwrite=True)
            print(f"   ✓ Loaded into database table '{name}' ({res.get('rows_inserted', 0)} rows)")

        # 2. Seed realistic query history
        print("📊 Seeding query execution history...")
        queries = [
            (
                "Find top 10 customers by total spend in 2023",
                "SELECT c.customer_id, c.first_name, c.last_name, SUM(o.total_amount) AS total_spend "
                "FROM customers c JOIN orders o ON c.customer_id = o.customer_id "
                "WHERE o.order_date >= '2023-01-01' AND o.order_date <= '2023-12-31' "
                "GROUP BY c.customer_id, c.first_name, c.last_name "
                "ORDER BY total_spend DESC LIMIT 10",
                745.2, 10, "success", None
            ),
            (
                "List all electronics products currently active with stock under 50",
                "SELECT product_id, name, category, price, stock_quantity "
                "FROM products WHERE category = 'Electronics' AND is_active = 1 AND stock_quantity < 50 "
                "ORDER BY stock_quantity ASC LIMIT 50",
                42.1, 8, "success", None
            ),
            (
                "Get revenue breakdown by city and order status",
                "SELECT shipping_city, status, COUNT(*) AS order_count, ROUND(SUM(total_amount), 2) AS revenue "
                "FROM orders GROUP BY shipping_city, status ORDER BY revenue DESC LIMIT 50",
                128.5, 35, "success", None
            ),
            (
                "Slow unindexed join on order items by product category",
                "SELECT p.category, COUNT(oi.item_id) AS total_sold, SUM(oi.subtotal) AS gross_sales "
                "FROM order_items oi JOIN products p ON oi.product_id = p.product_id "
                "GROUP BY p.category ORDER BY gross_sales DESC",
                890.4, 6, "success", None
            ),
            (
                "Lookup order details by date without indexing",
                "SELECT * FROM orders WHERE order_date = '2023-11-24' AND status = 'completed'",
                512.8, 14, "success", None
            ),
        ]

        for q_nl, q_sql, lat, rows, st, err in queries:
            qh = QueryHistoryModel(
                natural_language=q_nl,
                generated_sql=q_sql,
                execution_time_ms=lat,
                row_count=rows,
                status=st,
                error_message=err,
                source="user",
                created_at=datetime.utcnow() - timedelta(minutes=int(lat % 60)),
            )
            db.add(qh)
        db.commit()
        print(f"   ✓ Seeded {len(queries)} query history records.")

        # 3. Seed Incidents
        print("🚨 Seeding performance incidents...")
        inc1 = IncidentModel(
            title="Slow Join Latency: unindexed customer_id foreign key lookup in orders",
            description="Repeated analytical queries joining orders on customer_id trigger sequential scans, causing execution time to exceed the 500ms SLA threshold (avg 745ms).",
            severity=IncidentSeverity.high,
            status=IncidentStatus.open,
            evidence={
                "trigger_query": "SELECT c.customer_id, SUM(o.total_amount) FROM customers c JOIN orders o ON c.customer_id = o.customer_id GROUP BY c.customer_id",
                "p95_latency_ms": 745.2,
                "scan_type": "SEQUENTIAL TABLE SCAN",
                "affected_table": "orders",
                "missing_index": "customer_id",
            },
            root_cause="Missing B-tree index on orders(customer_id) forces an O(N) full table scan for every join operation across 1,200 orders.",
            query_fingerprint="orders_customer_id_join_scan",
            agent_log=[
                {"step": "anomaly_detection", "status": "anomaly_detected", "detail": "P95 latency 745ms > 500ms threshold"},
                {"step": "root_cause_analysis", "status": "diagnosed", "detail": "Explain plan shows SCAN TABLE orders"},
                {"step": "optimization", "status": "candidate_created", "detail": "Recommended B-Tree index creation on orders(customer_id)"},
            ],
            detected_at=datetime.utcnow() - timedelta(hours=2),
        )
        db.add(inc1)
        db.flush()

        inc2 = IncidentModel(
            title="High execution time in order_items aggregation scan",
            description="Aggregation queries on order_items without a covering index for product_id and subtotal experience elevated latencies (890ms).",
            severity=IncidentSeverity.medium,
            status=IncidentStatus.investigating,
            evidence={
                "trigger_query": "SELECT p.category, SUM(oi.subtotal) FROM order_items oi JOIN products p ON oi.product_id = p.product_id GROUP BY p.category",
                "p95_latency_ms": 890.4,
                "scan_type": "SEQUENTIAL SCAN",
                "affected_table": "order_items",
            },
            root_cause="order_items requires product_id lookup across all lines. Creating composite or foreign key index will allow index-only scanning.",
            query_fingerprint="order_items_product_id_agg",
            detected_at=datetime.utcnow() - timedelta(hours=5),
        )
        db.add(inc2)
        db.flush()

        # 4. Seed Optimizations & Approvals
        print("⚡ Seeding optimization candidates & approvals...")
        opt1 = OptimizationModel(
            incident_id=inc1.id,
            title="Add Index on orders(customer_id)",
            original_sql="SELECT c.customer_id, c.first_name, c.last_name, SUM(o.total_amount) FROM customers c JOIN orders o ON c.customer_id = o.customer_id GROUP BY c.customer_id",
            proposed_sql="CREATE INDEX IF NOT EXISTS idx_orders_customer_id ON orders(customer_id);",
            optimization_type="index",
            reasoning="An index on orders(customer_id) transforms the nested loop join from an O(N) sequential table scan into an O(log N) index seek.",
            expected_benefit="Reduces join query latency from ~745ms to ~45ms (approx 16x speedup).",
            risks="Minimal storage overhead (~40KB). Negligible INSERT impact on orders table.",
            status=OptimizationStatus.pending,
            baseline_latency_ms=745.2,
            optimized_latency_ms=46.1,
            improvement_pct=93.8,
        )
        db.add(opt1)
        db.flush()

        app1 = ApprovalModel(
            optimization_id=opt1.id,
            action_class="C",
            proposed_action="CREATE INDEX IF NOT EXISTS idx_orders_customer_id ON orders(customer_id);",
            explanation="Creates an index on orders(customer_id) to eliminate full table scan on joins with customers.",
            expected_benefit="~93.8% query latency reduction; removes unindexed scan bottleneck.",
            risk_assessment="Low risk. Read operations are non-blocking during creation in SQLite/PostgreSQL with CONCURRENTLY.",
            rollback_strategy="DROP INDEX IF EXISTS idx_orders_customer_id;",
            status=ApprovalStatus.pending,
        )
        db.add(app1)

        opt2 = OptimizationModel(
            incident_id=inc2.id,
            title="Add Index on order_items(product_id)",
            original_sql="SELECT oi.product_id, SUM(oi.subtotal) FROM order_items oi GROUP BY oi.product_id",
            proposed_sql="CREATE INDEX IF NOT EXISTS idx_order_items_product_id ON order_items(product_id);",
            optimization_type="index",
            reasoning="Index enables covering or fast grouped index scan on product_id.",
            expected_benefit="Reduces grouping and aggregation latency by ~70%.",
            risks="Low. Slight index update cost on order item insertion.",
            status=OptimizationStatus.validated,
            baseline_latency_ms=890.4,
            optimized_latency_ms=180.2,
            improvement_pct=79.7,
        )
        db.add(opt2)
        db.flush()

        # 5. Seed Benchmark Experiment
        print("🔬 Seeding benchmark experiment verification...")
        exp1 = ExperimentModel(
            optimization_id=opt1.id,
            name="Verification Benchmark: orders(customer_id) index tuning",
            description="Comparing 5 runs of customer-orders join before and after adding idx_orders_customer_id in isolated transaction environment.",
            baseline_sql=opt1.original_sql,
            candidate_sql=opt1.original_sql,  # same query, executed with index enabled
            baseline_runs=[742.1, 755.0, 738.4, 761.2, 729.3],
            candidate_runs=[46.5, 45.2, 44.8, 47.1, 46.9],
            baseline_avg_ms=745.2,
            candidate_avg_ms=46.1,
            improvement_pct=93.8,
            correctness_check=True,
            correctness_detail="Row count (500) and aggregate sums match baseline perfectly across all runs.",
            status="completed",
            run_at=datetime.utcnow() - timedelta(minutes=30),
        )
        db.add(exp1)

        # 6. Seed Monitoring Metrics
        print("📈 Seeding monitoring timeseries metrics...")
        base_time = datetime.utcnow() - timedelta(minutes=60)
        for i in range(12):
            t = base_time + timedelta(minutes=i * 5)
            # Simulated latency spike around minute 30
            spike = 350.0 if (25 <= i * 5 <= 40) else 45.0
            db.add(MonitoringMetricModel(
                metric_name="avg_query_latency_ms",
                metric_value=spike + (i * 2.5),
                metric_json={"p95": spike * 1.4, "p99": spike * 1.8},
                collected_at=t,
                source="synthetic_monitor",
            ))
            db.add(MonitoringMetricModel(
                metric_name="active_connections",
                metric_value=5.0 + (i % 3),
                metric_json={"idle": 12, "active": 5 + (i % 3)},
                collected_at=t,
                source="synthetic_monitor",
            ))

        db.commit()
        print("✅ Database seeding complete! All tables, metrics, and incident records are ready.")

    except Exception as e:
        db.rollback()
        print(f"❌ Error during seeding: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_all()
