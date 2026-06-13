# FTS5 Full-Text Search — Design

**Date:** 2026-06-13
**Status:** Design approved
**Roadmap:** `todo.md` New Ideas — "Expose a full FTS5 search box (wildcards / contains across fields)."

## Goal

Replace the inventory keyword search (the 11.2 `name` "navbar quick-search", an OR of `icontains`
across a few fields with no ranking) with an FTS5-backed search: ranked, multi-term, prefix
(`unicode61`) matching across many fields, composing with the existing structured filters. The
exact-match filters (`sku=`, `upc=`, `serial=`, `item_id=`) and barcode flows are unchanged.

## Decisions (locked)
- **Tokenizer:** `unicode61` + prefix (`term*`). Word/prefix matching, not substring.
- **Sync:** Django signals on `InventoryItem` (`post_save`/`post_delete`) + a `rebuild_search_index`
  management command for full rebuilds. No SQL triggers.
- **Index unit:** one FTS row per `InventoryItem`, `rowid = InventoryItem.pk`.

## Architecture

### FTS virtual table (migration `0040`, raw SQL, reversible)
```
CREATE VIRTUAL TABLE inventory_item_fts USING fts5(
    name, color, material, manufacturer, serial, upc, sku, location,
    tokenize='unicode61'
)
```
`rowid` is the `InventoryItem.pk` (set explicitly on insert), so a MATCH maps straight back to the
item. The migration creates the table (reverse = `DROP TABLE`) **and** populates it via `RunPython`
calling `rebuild_all()` — so the index is live immediately after deploy with **no manual prod step**
(it's derived data; signals keep it fresh afterward). The DDL lives in `search_index.FTS_CREATE_SQL`
so the migration and tests share one definition (DRY).

### Indexer — `inventory/search_index.py`
Single responsibility: own the FTS table's contents and queries. Public surface:
- `FTS_CREATE_SQL` / `FTS_DROP_SQL` — the DDL constants.
- `build_document(item) -> dict` — the searchable text for one item, pulled from the **real**
  product subclass (`item.product.get_real_instance()` — never `select_related("product")`, per the
  known polymorphic gotcha): `name`; Filament → `color`, `material` (`"{name} {material_type}"`),
  `manufacturer`; `serial` (`item.serial_number`); `upc`/`sku` (Product); `location` = the **full
  ancestor path** of `item.location` (root→leaf names joined, e.g. `"Rack A Shelf 3"`) so a rack/parent
  name still matches items on child shelves (preserves the old `_expanded_location_ids` behavior).
- `index_item(item)` — DELETE then INSERT the row at `rowid=item.pk` (raw cursor on the default
  connection). `unindex_item(pk)` — DELETE. `rebuild_all()` — DELETE all + re-insert every item;
  returns the count.
- `search_ids(query) -> list[int] | None` — sanitize → `MATCH` → return item pks ordered by
  `bm25()`. Returns `None` on a degenerate/empty query **or** an FTS syntax error (caller falls back
  to the legacy `icontains` fan-out); returns `[]` for a valid query with no hits.
- `_to_match_query(raw)` — robust sanitizer: extract `"quoted phrases"` → FTS phrases; strip FTS
  metacharacters from the rest; each bare term → `term*` (prefix); join (implicit AND). A `try/except`
  around the `MATCH` in `search_ids` is the final safety net so search never 500s.

### Sync — `inventory/signals.py`
Add `post_save(InventoryItem)` → `index_item`, `post_delete(InventoryItem)` → `unindex_item`
(alongside the existing `pre_save` logger; registered the same way via `apps.ready()`). Related-model
renames (Material/Location) refresh on the item's next save or via the rebuild command — acceptable
staleness for a household app, documented. Indexer calls are wrapped defensively so a write never
breaks an item save.

### Command — `inventory/management/commands/rebuild_search_index.py`
Thin wrapper over `rebuild_all()`; prints the row count. For full refreshes after bulk imports or
catalog/Material/Location edits.

### Integration — `_filtered_search_items` (`views.py`)
When the `name` keyword is present, route it through `search_ids(name)`:
- `None` → fall back to the legacy OR-`icontains` fan-out (degenerate query safety).
- list → `items.filter(id__in=ids).order_by(<rank>)` where rank preserves bm25 order via
  `Case(When(id=pk, then=pos) ...)`. Composes with status/type/location/date filters (applied to the
  same queryset). The exact filters (`sku`/`upc`/`serial`/`item_id`) keep their own exact branches.
This unifies the navbar quick-search and the search-page keyword field on one ranked engine.

## Testing
- `_to_match_query`: prefix tokens; quoted phrase; metacharacter stripping; empty → None.
- `index_item`/`unindex_item`/`rebuild_all`: round-trip; `search_ids` finds a created item, ranks
  multi-field hits, prefix matches (`"lat"` → "Latte"), returns `[]` for no hits and `None` for junk.
- Location ancestor path: an item on a child shelf is found by the rack name.
- Signals: creating an item indexes it; deleting unindexes it.
- View: keyword search returns expected items, composes with a status filter, and a degenerate
  query falls back without error.
- Tests create the FTS table from `FTS_CREATE_SQL` (it also exists via the migration in the test DB).

## Deploy
Migration `0040` creates **and** populates the index automatically on deploy — **no manual step**.
Reversible (drops the table). No new dependency (FTS5 + unicode61 confirmed present on prod sqlite
3.46). `rebuild_search_index` is available for later manual full refreshes.

## Non-goals
- No trigram/substring matching (prefix chosen).
- No separate search UI — reuses the existing search box/param.
- No cross-model trigger cascade — the rebuild command covers related-rename staleness.
- Item-id *substring* search is dropped (the exact `item_id=` param + `INV-` barcode cover it).
