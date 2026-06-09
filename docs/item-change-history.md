# Item change history — design decision

**Status:** Approach decided (2026-06-09). Full design + implementation plan **not yet
written** — brainstorming was paused here to fold this into a larger planning pass.
**Owner decision captured below so the next session needn't re-derive it.**

## Motivation

During Audit No. 15 a spool was mis-scanned: `INV-553` was typed instead of `INV-563`
(old barcodes that no longer scan are entered by hand, which is where the fat-finger
happened). The item got moved digitally. When James went to undo it, **there was no
item history anywhere** — not in the admin, not on the public pages.

The data to reconstruct it *did* exist in the `AuditEvent` log, but:

1. It's never surfaced in any UI.
2. It records the **destination** of a move (`MOVED_IN`), not the origin — you
   reconstruct "where it came from" by walking prior events.
3. It only covers **audit-time** changes — admin edits, bulk edits, and the add flow
   leave no trail at all.

(For the record: `INV-553` self-healed — it was bounced to Shelf 4 then scanned back to
its real home, Shelf 5 / id 37, later in the same audit. No correction was needed. But
the lack of a visible history is the real gap.)

## Goal

A full change history for `InventoryItem`, viewable from **both** the Django admin and
the "public" (logged-in) web pages.

## Decisions

| Question | Decision |
|---|---|
| **Library vs. custom** | **`django-simple-history`** (≥ 3.11.0). |
| **What's captured** | **All fields** on `InventoryItem` (snapshot per save) — latent forensic value, in the DB from day one. |
| **What's surfaced (v1)** | **Location + status** timeline only, on the public item page. The rest stays in the DB, unsurfaced. |
| **Attribution (v1)** | None surfaced — "just the change" (old → new + timestamp). |
| **Backfill** | **None** — start fresh at deploy. Past changes remain only in `AuditEvent`. |
| **Admin** | Use simple-history's built-in history view + revert (free). |
| **Public page** | Custom timeline section on the inventory item page (likely `inventory_edit.html` / the item detail view). |

### How the clean view is derived from full snapshots

simple-history writes a snapshot row per save. The public location+status timeline is a
*derived* view: query the item's historical records, `diff_against` consecutive pairs
with `included_fields=['location', 'status']` and `foreign_keys_are_objs=True` (resolves
the `location` FK to the real `Location`), and render only entries where one of those
two fields changed. Full data underneath, high-signal timeline on top — so an audit move
that flips both fields reads as one entry (`Shelf 5 → Shelf 4 / NEW → IN_USE`).

## Why `django-simple-history` over a custom model

A custom `InventoryItemHistory` written in `InventoryItem.save()` was the leading
candidate while the scope was *narrow* (location+status only, no actor, start fresh) —
zero dependency, ~50 lines, a clean timeline by construction. **What flipped it:** the
ask grew to include latent **all-field** auditing ("nice to have, even if just sitting
in the DB"). That is precisely simple-history's core competency; a custom model would
have to grow into an all-fields snapshot tracker — a worse, unmaintained clone of the
library. Once all-field capture is in scope:

- The library's "a row on every save" behaviour stops being *noise* and becomes the
  desired forensic record; the clean view is a derived (`diff_against`) presentation
  layer we hand-build anyway.
- `diff_against(included_fields=…)` removes the one real representation advantage the
  custom model had (combined `from → to` rows).
- Admin history + revert come free.

Verified facts (2026-06-09): simple-history **3.11.0** (Dec 2025) supports Django 6.0 +
Python 3.12/3.13/3.14 — matches prod (Django 6.0.5 / Py 3.12); actively maintained under
django-commons.

## Cons accepted

- **New dependency** → `requirements.txt` + `INSTALLED_APPS` + image rebuild on deploy.
  Pure-Python, no heavy transitive deps. *(CLAUDE.md dependency-confirmation gate: James
  accepted this.)*
- **Shadow-table migration coupling** — a `HistoricalInventoryItem` table mirrors all
  `InventoryItem` columns; future field changes auto-generate a migration on it too.
- **View discipline** — the public timeline must filter to `included_fields` so it stays
  location+status even though the table holds everything.

## Capture-path note

Nearly every `InventoryItem` location/status mutation already funnels through
`item.save()` — audit moves (`audit.py`), bulk edits (per-item `save()` in
`BulkUpdateView`), admin, and the add flows — so simple-history's `post_save` hook
catches them. **Caveat:** a raw `queryset.update()` bypasses `post_save` (and would
bypass a custom `save()` hook too). None touch item location/status today; a future one
would need simple-history's `bulk_update_with_history` / `bulk_create_with_history`.

## Near-free future lever (not v1)

Adding `simple_history.middleware.HistoryRequestMiddleware` later auto-captures the
acting user on web-driven saves — turns "just the change" into "who did it" with one
middleware line and no schema rework. Consistent with capturing for later value;
deliberately out of v1 scope.

## Open / next steps

1. Full design (data flow, the public template/section, admin wiring, tests) — paused;
   resume via the brainstorming → writing-plans flow.
2. Implementation plan + PR.
3. No `.env` changes needed.

## Related

- `AuditEvent` (in `inventory/models.py`) — the audit-session-scoped log. **Distinct
  concern**: it records what happened *during an audit walk*; this feature records
  *any* change to an item over its whole life. They coexist.
- `Location.unit` guard — PR #128 (separate fix from the same audit).
- Phase 6 — audit mode + location hierarchy (the surrounding subsystem).
