#!/usr/bin/env python3
"""
Export inventory statistics to JSON for Home Assistant consumption.

Reads the SQLite DB directly (no Django stack required) and writes a JSON
snapshot to ~/ha-stats/inventory_stats.json, served by the nginx container
at http://10.10.20.17:8080/ha-stats/inventory_stats.json.

Run from a cron job every 5 minutes:
  */5 * * * * /usr/bin/python3 ~/ha_stats_export.py >> ~/ha-stats/export.log 2>&1

InventoryItem.Status integer values (from models.py):
  1 = NEW, 2 = IN_USE, 3 = DRYING, 4 = STORED, 5 = DEPLETED, 6 = SOLD
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path.home() / "inventory_db.sqlite3"
OUT_DIR = Path.home() / "ha-stats"
OUT_FILE = OUT_DIR / "inventory_stats.json"

STATUS_IN_USE = 2
STATUS_DRYING = 3
STATUS_DEPLETED = 5
STATUS_SOLD = 6
ACTIVE_STATUSES = (1, 2, 3, 4)  # NEW, IN_USE, DRYING, STORED

LOW_QUANTITY = int(os.environ.get("LOW_QUANTITY", 3))


def query(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def build_summary(conn):
    rows = query(conn, """
        SELECT
            COUNT(*) FILTER (WHERE status IN (1,2,3,4)) AS total_active,
            COUNT(*) FILTER (WHERE status = 2)          AS in_use,
            COUNT(*) FILTER (WHERE status = 3)          AS drying,
            COUNT(*) FILTER (WHERE status = 4)          AS stored,
            COUNT(*) FILTER (WHERE status = 1)          AS new_items
        FROM inventory_inventoryitem
    """)
    return rows[0]


def build_in_use(conn):
    return query(conn, """
        SELECT
            ii.id,
            p.name        AS product_name,
            p.sku,
            m.name        AS material,
            f.color,
            f.hex_code,
            f.color_family,
            CAST(ii.percent_remaining AS REAL) AS percent_remaining,
            l.name        AS location
        FROM inventory_inventoryitem ii
        JOIN inventory_product p  ON ii.product_id = p.id
        LEFT JOIN inventory_filament  f ON f.product_ptr_id = p.id
        LEFT JOIN inventory_material  m ON f.material_id    = m.id
        LEFT JOIN inventory_location  l ON ii.location_id   = l.id
        WHERE ii.status = ?
        ORDER BY p.name
    """, (STATUS_IN_USE,))


def build_drying(conn):
    return query(conn, """
        SELECT
            ii.id,
            p.name        AS product_name,
            m.name        AS material,
            f.color,
            f.hex_code,
            CAST(ii.percent_remaining AS REAL) AS percent_remaining,
            l.name        AS location
        FROM inventory_inventoryitem ii
        JOIN inventory_product p  ON ii.product_id = p.id
        LEFT JOIN inventory_filament  f ON f.product_ptr_id = p.id
        LEFT JOIN inventory_material  m ON f.material_id    = m.id
        LEFT JOIN inventory_location  l ON ii.location_id   = l.id
        WHERE ii.status = ?
        ORDER BY p.name
    """, (STATUS_DRYING,))


def build_low_stock(conn):
    rows = query(conn, """
        SELECT
            p.name  AS product_name,
            p.sku,
            m.name  AS material,
            f.color,
            f.hex_code,
            COUNT(*) AS active_count,
            COUNT(*) FILTER (WHERE ii.status = 2) AS in_use_count,
            COUNT(*) FILTER (WHERE
                ii.status = 5
                AND ii.date_depleted >= datetime('now', '-30 days')
            ) AS recently_depleted
        FROM inventory_inventoryitem ii
        JOIN inventory_product p  ON ii.product_id = p.id
        LEFT JOIN inventory_filament  f ON f.product_ptr_id = p.id
        LEFT JOIN inventory_material  m ON f.material_id    = m.id
        WHERE ii.status IN (1,2,3,4)
        GROUP BY p.id
        HAVING active_count < ?
        ORDER BY active_count, p.name
    """, (LOW_QUANTITY,))

    for row in rows:
        if row["active_count"] == 0 and row["recently_depleted"] > 0:
            row["urgency"] = "danger"
            row["urgency_label"] = "Out of Stock"
        elif row["recently_depleted"] > 0:
            row["urgency"] = "warning"
            row["urgency_label"] = "Running Low"
        else:
            row["urgency"] = "secondary"
            row["urgency_label"] = "Low Stock"
    return rows


def build_stock_by_name(conn):
    """
    Dict keyed by product name for AMS tray cross-reference.
    The Bambu integration exposes tray contents by the filament product name
    (e.g. 'Bambu ABS'), which should match Product.name in the inventory DB.
    """
    rows = query(conn, """
        SELECT
            p.name AS product_name,
            COUNT(*) AS total_active,
            COUNT(*) FILTER (WHERE ii.status = 2) AS in_use,
            COUNT(*) FILTER (WHERE ii.status = 3) AS drying,
            COUNT(*) FILTER (WHERE ii.status = 4) AS stored
        FROM inventory_inventoryitem ii
        JOIN inventory_product p ON ii.product_id = p.id
        WHERE ii.status IN (1,2,3,4)
        GROUP BY p.id
    """)
    return {row["product_name"]: {
        "active": row["total_active"],
        "in_use": row["in_use"],
        "drying": row["drying"],
        "stored": row["stored"],
    } for row in rows}


def build_stock_by_material(conn):
    rows = query(conn, """
        SELECT
            m.name AS material,
            COUNT(*) AS total_active,
            COUNT(*) FILTER (WHERE ii.status = 2) AS in_use,
            COUNT(*) FILTER (WHERE ii.status = 3) AS drying,
            COUNT(*) FILTER (WHERE ii.status = 4) AS stored
        FROM inventory_inventoryitem ii
        JOIN inventory_product p  ON ii.product_id = p.id
        JOIN inventory_filament  f ON f.product_ptr_id = p.id
        JOIN inventory_material  m ON f.material_id    = m.id
        WHERE ii.status IN (1,2,3,4)
        GROUP BY m.name
        ORDER BY total_active DESC
    """)
    return {row["material"]: {
        "active": row["total_active"],
        "in_use": row["in_use"],
        "drying": row["drying"],
        "stored": row["stored"],
    } for row in rows}


def main():
    if not DB_PATH.exists():
        print(f"ERROR: DB not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    OUT_DIR.mkdir(exist_ok=True)

    # Open read-only; URI mode prevents write locks
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row

    try:
        payload = {
            "updated": datetime.now(timezone.utc).isoformat(),
            "summary": build_summary(conn),
            "in_use": build_in_use(conn),
            "drying": build_drying(conn),
            "low_stock": build_low_stock(conn),
            "stock_by_name": build_stock_by_name(conn),
            "stock_by_material": build_stock_by_material(conn),
        }
    finally:
        conn.close()

    # Write atomically via temp file to avoid HA reading a partial JSON
    tmp = OUT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str))
    tmp.replace(OUT_FILE)
    print(f"OK: wrote {OUT_FILE} at {payload['updated']}")


if __name__ == "__main__":
    main()
