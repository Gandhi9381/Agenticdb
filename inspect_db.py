"""Inspect the actual AgenticDB SQLite databases."""
import sqlite3
import os

backend_dir = r'c:\Users\Konda Vishnu Teja\OneDrive\Desktop\agentic ai\agenticdb\backend'
root_dir = r'c:\Users\Konda Vishnu Teja\OneDrive\Desktop\agentic ai\agenticdb'
dbs = [
    os.path.join(backend_dir, 'agenticdb.db'),
    os.path.join(root_dir, 'agenticdb.db'),
]

for db_path in dbs:
    if not os.path.exists(db_path):
        print(f'NOT FOUND: {db_path}')
        continue
    print(f'\n=== DB: {db_path} ({os.path.getsize(db_path)} bytes) ===')
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    # tables
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    print('Tables:', tables)

    # custom indexes
    cur.execute("SELECT name, tbl_name, sql FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'ix_%'")
    idxs = cur.fetchall()
    print('Custom Indexes (non-ORM):')
    for idx in idxs:
        print(' ', idx)

    # check specific indexes
    for idx_name, tbl_name in [
        ('idx_orders_customer_id', 'orders'),
        ('idx_order_items_customer_id', 'order_items'),
    ]:
        cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND name=? AND tbl_name=?", (idx_name, tbl_name))
        exists = cur.fetchone() is not None
        print(f'  {idx_name} on {tbl_name}: EXISTS={exists}')

    # optimizations count, columns present
    try:
        cur.execute('PRAGMA table_info(optimizations)')
        cols = [r[1] for r in cur.fetchall()]
        print('optimizations columns:', cols)
        cur.execute('SELECT COUNT(*) FROM optimizations')
        print('Total optimizations:', cur.fetchone()[0])
        cur.execute('SELECT id, title, optimization_type, status, execution_status, original_sql, proposed_sql, target_table, target_columns, index_name, index_identity_key FROM optimizations ORDER BY id')
        rows = cur.fetchall()
        print(f'Optimizations ({len(rows)}):')
        for r in rows:
            print(' ', r)
    except Exception as e:
        print('Error reading optimizations:', e)

    # approvals
    try:
        cur.execute('PRAGMA table_info(approvals)')
        cols = [r[1] for r in cur.fetchall()]
        print('approvals columns:', cols)
        cur.execute('SELECT id, optimization_id, action_class, status, decision_at, proposed_action FROM approvals ORDER BY id')
        arows = cur.fetchall()
        print(f'Approvals ({len(arows)}):')
        for r in arows:
            print(' ', r)
    except Exception as e:
        print('Error reading approvals:', e)

    con.close()
