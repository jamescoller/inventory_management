"""SQLite FTS5 index over InventoryItem for the keyword search.

One FTS row per InventoryItem (``rowid = InventoryItem.pk``), ``unicode61`` tokenizer
(prefix matching). Owned end-to-end here: DDL constants (shared with migration 0040),
document build, incremental index/unindex, full rebuild, and the ranked query helper.
Model imports are deferred into functions so this module is import-safe from migrations.
"""

import re

from django.db import connection

FTS_TABLE = "inventory_item_fts"
COLUMNS = [
    "name",
    "color",
    "material",
    "manufacturer",
    "serial",
    "upc",
    "sku",
    "location",
]
FTS_CREATE_SQL = (
    f"CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_TABLE} USING fts5("
    + ", ".join(COLUMNS)
    + ", tokenize='unicode61')"
)
FTS_DROP_SQL = f"DROP TABLE IF EXISTS {FTS_TABLE}"


def _location_path(loc):
    """Root→leaf location names joined, so a parent (rack) name matches child items."""
    names, seen = [], set()
    while loc is not None and loc.pk not in seen:
        seen.add(loc.pk)
        names.append(loc.name or "")
        loc = loc.parent
    return " ".join(reversed(names)).strip()


def build_document(item):
    """Searchable text for one InventoryItem, from its real product subclass."""
    product = item.product
    real = (
        product.get_real_instance()
        if hasattr(product, "get_real_instance")
        else product
    )
    mat = getattr(real, "material", None)
    return {
        "name": getattr(real, "name", "") or "",
        "color": getattr(real, "color", "") or "",
        "material": (f"{mat.name} {mat.material_type}".strip() if mat else ""),
        "manufacturer": getattr(real, "manufacturer", "") or "",
        "serial": item.serial_number or "",
        "upc": getattr(product, "upc", "") or "",
        "sku": getattr(product, "sku", "") or "",
        "location": _location_path(item.location),
    }


def index_item(item):
    doc = build_document(item)
    placeholders = ", ".join(["%s"] * len(COLUMNS))
    with connection.cursor() as cur:
        cur.execute(f"DELETE FROM {FTS_TABLE} WHERE rowid = %s", [item.pk])
        cur.execute(
            f"INSERT INTO {FTS_TABLE} (rowid, {', '.join(COLUMNS)}) "
            f"VALUES (%s, {placeholders})",
            [item.pk] + [doc[c] for c in COLUMNS],
        )


def unindex_item(pk):
    with connection.cursor() as cur:
        cur.execute(f"DELETE FROM {FTS_TABLE} WHERE rowid = %s", [pk])


def rebuild_all():
    from inventory.models import InventoryItem

    with connection.cursor() as cur:
        cur.execute(f"DELETE FROM {FTS_TABLE}")
    count = 0
    for item in InventoryItem.objects.select_related("location").iterator():
        index_item(item)
        count += 1
    return count


def _to_match_query(raw):
    """Sanitize user input into a safe FTS5 MATCH expression (prefix + phrases)."""
    raw = (raw or "").strip()
    if not raw:
        return None
    parts = []
    for phrase in re.findall(r'"([^"]+)"', raw):
        cleaned = re.sub(r"[^\w\s]", " ", phrase, flags=re.UNICODE).strip()
        if cleaned:
            parts.append('"' + cleaned + '"')
    rest = re.sub(r'"[^"]*"', " ", raw)
    for term in re.sub(r"[^\w\s]", " ", rest, flags=re.UNICODE).split():
        parts.append(term + "*")
    return " ".join(parts) or None


def search_ids(query):
    """Item pks matching ``query`` ranked by bm25. None => caller should fall back
    (degenerate query or FTS error); [] => valid query, no hits."""
    match = _to_match_query(query)
    if not match:
        return None
    try:
        with connection.cursor() as cur:
            cur.execute(
                f"SELECT rowid FROM {FTS_TABLE} WHERE {FTS_TABLE} MATCH %s "
                f"ORDER BY bm25({FTS_TABLE})",
                [match],
            )
            return [row[0] for row in cur.fetchall()]
    except Exception:
        return None
