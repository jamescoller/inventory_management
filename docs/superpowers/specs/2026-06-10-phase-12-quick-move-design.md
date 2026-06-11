# Phase 12 — Quick-Move & Phone Scanning — Design

**Date:** 2026-06-10
**Status:** Approved (brainstorm 2026-06-10), pending implementation plan
**Scope:** todo.md Phase 12.2 (quick scan-to-move) + 12.3 (phone camera, QR labels, PWA),
shipped together in **one PR** (James's call).
**Roadmap refs:** `todo.md` §12; wireframes `ideas.md` §1.2 / §1.3; workflow rule
`docs/workflow-and-domain-design.md` §1, §6.

---

## 1. Goal

A fast, phone-first way to **move an item into a location by scanning** — no audit session,
no slow edit form. Scan an item, scan (or pick) a destination, done. Status follows the
destination's `default_status`. Slot capacity is enforced, with a one-tap path to make room
(evict the current occupant, depleting it if it's empty — the common "AMS spool ran out"
swap). Phone camera scanning and QR labels make it work hands-on in the field.

This is the everyday workflow. Its gate (Phase 11.3 `items.move_to()`) already shipped, so
the move primitive, capacity guard, sticky-status semantics, and drying-warning surfacing all
exist — Phase 12 is the **flow and the inputs** on top of them.

---

## 2. Design rules (inherited)

Per `docs/workflow-and-domain-design.md`: every new subsystem copies the **audit pattern** —
a service module (`quickmove.py`) holding the logic, thin CBVs that call it. All `InventoryItem`
state changes go through `items.move_to()` / `items.deplete()`; **no view touches the sticky
flags.** Scanned-code parsing reuses `audit.parse_code` / `audit.resolve_serial` (no duplication).

---

## 3. Decisions (from the brainstorm)

| # | Decision | Rationale |
|---|---|---|
| D1 | **One PR** for 12.2 + 12.3. | James's call; HTTPS now available so the camera is in scope. |
| D2 | **Client-carried flow state** (hidden field in the HTMX fragment), not server session. | Single entry point; no cross-tab coupling; reload = re-scan. Simpler than audit's session focus. |
| D3 | **Evict → chain-prompt**, with a one-tap **evict & deplete** for empty spools, plus **Deplete** as a standard item-card action. | The evicted spool is usually either empty (deplete) or going elsewhere (re-home). Both are one tap. |
| D4 | **QR encodes a full URL** (`SITE_BASE_URL + /barcode/INV-<id>/`). | Native phone camera opens the right page over HTTP today; in-app scanner strips it back to a code. |
| D5 | **PWA = manifest only** (installable, no service worker). | Phone is always on-LAN when used; offline shows no data. Installability is the value. |
| D6 | **In-app camera via `@zxing/browser`**, secure-context gated. | HTTPS (`inventory.home.collerco.com`) is now live, so getUserMedia works; degrades on plain HTTP. |
| D7 | Container-scan → **slot-picker**; **shared camera on the audit console** too. | Cheap, reuses `_slot_map_for_unit`; serves the AMS/dryer workflow. Droppable at review. |

---

## 4. Architecture & new surfaces

### Service — `inventory/quickmove.py`
Pure-ish functions + a small result type, mirroring `inventory/audit.py`. Owns the flow's
*decision* logic; delegates *mutation* to `items`.

- `resolve_active_item(code) -> Result` — parse a scan into the item being moved. Accepts
  `INV-`/item-pk, a spool serial (via `resolve_serial`, but only a real item — reject machine
  units), or a stripped URL. Rejects `LOC-` ("scan an item first") and bare UPC ("catalog code —
  add via Audit").
- `resolve_destination(code) -> Result` — parse a scan into a destination. Accepts `LOC-` leaf,
  or a unit serial/`LOC-` that resolves to a **container** (→ signals "pick a slot"). Returns the
  `Location` + a `needs_slot_pick` flag.
- `attempt_move(item, dest) -> Result` — thin wrapper over `items.move_to(item, dest,
  enforce_capacity=True)`; classifies the rejection (container / **full** → who's the occupant).
- `evict_and_place(occupant, incoming, dest, *, deplete_old) -> Result` — frees the slot first
  (`items.deplete(occupant, reason="swap")` **or** `items.move_to(occupant, None)`), then
  `items.move_to(incoming, dest)`. Returns the evicted occupant when re-homing (the chain).

`quickmove` never imports Django views; it's unit-testable in isolation.

### Views — `inventory/views.py`
- `QuickMoveView (LoginRequiredMixin, TemplateView)` → `inventory/quick_move.html` (page shell).
- `QuickMoveScanView (LoginRequiredMixin, View)` → POST, returns the
  `inventory/partials/quick_move_body.html` fragment (HTMX-aware, like `AuditScanView`).
  Reads `code`, `active_item_id`, and an optional `action` (`evict_deplete` / `evict_rehome` /
  `pick_slot` / `cancel`). Surfaces `drying_warning` via `messages` exactly as the edit view does.

### URLs — `inventory/urls.py`
```
path("move/",      QuickMoveView.as_view(),     name="quick_move")
path("move/scan/", QuickMoveScanView.as_view(), name="quick_move_scan")
```

### Templates
- `inventory/quick_move.html` — extends base; scan input + camera button; HTMX target div.
- `inventory/partials/quick_move_body.html` — renders the current state (below). One fragment,
  state-driven by context, swapped on every scan/action POST.

### Static / JS
- `static/inventory/js/vendor/zxing-browser.min.js` — vendored UMD build (no npm/bundler in repo).
- `static/inventory/js/scanner.js` — reusable camera module (see §6). Feature-detects secure
  context; used by quick-move **and** the audit console.
- `static/inventory/js/quick_move.js` — page glue (wire scan box + camera + HTMX submit).
- `static/inventory/manifest.json`, `static/inventory/images/icon-192.png` + `icon-512.png`
  (generated once from `invIcon.png` with Pillow, committed).

### Nav
- `navigation.html` gains a **Move** link.
- Camera-scan button added to the quick-move page and the audit console (shared `scanner.js`).
- *Out of scope:* the global mode-aware omni-scan box (`ideas.md` §1.1, candidate).

---

## 5. Quick-move flow (state machine)

States rendered by `quick_move_body.html`, state carried in a hidden `active_item_id` (+ pending
fields for the evict/slot sub-states). Input is **input-agnostic**: typed, USB-wedge, or camera
all POST the same `code`.

```
IDLE ──scan item──► ITEM_SELECTED ──scan dest──► attempt_move
  ▲                     │                            │
  │                     │ scan container             ├─ ok ─────────────► flash + IDLE
  │                     ▼                            │   (+drying warning)
  │              DEST_IS_CONTAINER                   ├─ container ──────► error, stay ITEM_SELECTED
  │              (slot picker; tap a slot)           │
  │                     │                            └─ FULL ───────────► SLOT_FULL_CONFIRM
  │                     └─ tap slot ─► attempt_move                            │
  │                                                                            │
  └───────────────────────────────────────────── flash + IDLE ◄──────────────┤ [Evict & place — empty]
                                                                               │   deplete(old)+place
            ITEM_SELECTED(old, "scan where it goes") ◄──────────────────────── ┤ [Evict & place — re-home]
                  (chain; card has [Deplete] too)                              │   place, old→active
                                                                               └─ [Pick another] → ITEM_SELECTED
```

**States**
1. **IDLE** — "Scan an item (INV / QR)."
2. **ITEM_SELECTED** — item card: product name, `INV-<id>`, status chip, current location,
   % remaining. Prompt: "Scan destination (LOC / serial)." Actions: **[Deplete]**, **[Cancel]**.
   (Optional [Edit]/[Print] links to existing views.)
3. **DEST_IS_CONTAINER** — scanned an AMS/dryer unit: render its slot map (reuse
   `_slot_map_for_unit`); each open slot is a button that re-POSTs with that leaf `LOC-`.
4. **SLOT_FULL_CONFIRM** — destination leaf full: show occupant. Buttons:
   **[Evict & place — old is empty]** (one-tap deplete), **[Evict & place — re-home old]**
   (chain), **[Pick another slot]**.

**Status:** on a plain place, `items.move_to(item, dest)` with `status=None` lets the model derive
status from `dest.default_status` (dry storage→STORED, AMS/printer→IN_USE, dryer→DRYING).

**Sticky statuses are preserved — no special-casing.** Quick-move always calls `move_to` with
`status=None`, so DEPLETED/SOLD/UNKNOWN are kept by the model guard even when the item is scanned
and re-placed. In particular, scanning and moving an **UNKNOWN** item does **not** auto-clear it:
that's a deliberate choice to keep quick-move from silently resurrecting sticky states. The
sanctioned way to un-stick a found item is the editable **status dropdown on `/edit/`** (PR #147,
just merged) — which is precisely why that dropdown was left unlocked. This keeps the move
primitive's contract intact and gives a clean two-step story: quick-move *places*, the edit
dropdown *un-sticks*. Tests assert this (an UNKNOWN item moved via quick-move stays UNKNOWN).

**Drying safety:** `move_to` already returns `filament_drying_warning(dest)`; the view flashes it
(`warning`/`error`) exactly as `InventoryEditView` does. Wet filament → dry-storage stays blocked
at the view layer (mirror the edit view's `error`-level block before committing the move).

---

## 6. Camera & scanning (`scanner.js`)

Wraps `@zxing/browser` `BrowserMultiFormatReader` in a Bootstrap modal `<video>`.

- **API:** `Scanner.open({mode, onCode})` / `Scanner.close()`. `mode="feed"` → call `onCode(code)`
  (quick-move/audit submit the code to their scan endpoint via HTMX). `mode="navigate"` → set
  `window.location` to the decoded URL (a label scanned cold).
- **URL handling:** a decoded value matching `^https?://<host>/barcode/(.+)$` is stripped to the
  trailing code in feed mode (so a URL-QR feeds `INV-563`); otherwise the raw text is used.
- **Secure-context gate:** if `!window.isSecureContext || !navigator.mediaDevices?.getUserMedia`,
  the camera button is disabled with a tooltip: "Camera needs HTTPS — type, use a USB wedge, or
  scan the QR with your phone's camera." Live on `https://inventory.home.collerco.com`; degrades on
  `http://inventory.home`.
- **Reuse:** the same module powers the camera button on the **audit console** (`/audit/`), whose
  scan endpoint is already input-agnostic.

Native-camera + URL-QR is the always-available navigation path (HTTP-safe) regardless of the
in-app camera.

---

## 7. QR labels (`inventory/barcode_utils.py`)

- **New dependency:** `qrcode` (pure-Python, renders to a PIL image, reuses the existing Pillow).
  ⚠️ **Flag:** new prod package → image rebuild. Lazy-import inside the render function (brother_ql
  style).
- **Content:** `SITE_BASE_URL + reverse("barcode_redirect", args=[value])`, e.g.
  `https://inventory.home.collerco.com/barcode/INV-563/`. `value` is the canonical `INV-<id>` /
  `LOC-<id>` the existing code already builds.
- **Layout:** `create_label_image` gains a QR on the left; Code128 + human-readable text on the
  right. Profile-driven via `LabelProfile.include_qr` (default True) + `qr_ratio`. The 17×54 mm /
  566×165 px default is unchanged structurally.
- ⚠️ **Legibility risk:** QR + Code128 + text on a 17×54 label is tight. Verification is a
  **with-the-printer** step (James). Escape hatch: bump `LabelProfile.code` to a **larger Brother
  label** (one-line profile change — James will size up if needed) and/or drop to QR-prominent /
  QR-only. No code rework required for the size bump.

---

## 8. PWA (manifest-only)

- `manifest.json`: `name`, `short_name`, `start_url:"/"`, `display:"standalone"`, `theme_color`,
  `background_color`, `icons` (192 + 512). Served from static; linked in `base.html` via
  `{% static %}`.
- `base.html`: `<link rel="manifest">`, `<meta name="theme-color">`, keep the existing
  apple-touch-icon, add `apple-mobile-web-app-capable`.
- Generate `icon-192.png` / `icon-512.png` from `invIcon.png` (Pillow, one-time, committed).
- **No service worker.** Installable, full-screen, online-only.
- *Correction to todo.md:* it claims "manifest + icons already exist." Icons exist and are linked;
  **there is no manifest.json and no service worker** — both are created here.

---

## 9. Settings / infra (flagged)

- **`SITE_BASE_URL`** = `config("SITE_BASE_URL", default="https://inventory.home.collerco.com")`
  in `settings.py` (QR URL building). Non-secret path-like value → also add to `docker-compose.yml`
  `web` `environment:` (not `~/.env_inventory`, which is root-owned). ⚠️ **Flag: confirm the host.**
- **`CSRF_TRUSTED_ORIGINS`** += `https://inventory.home.collerco.com`. **Required** — the move flow
  is all POSTs; over the new HTTPS host they 403 without it. Done in this PR. (James already added
  the host to `ALLOWED_HOSTS`.)
- **`SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")`** — *consider* if the
  TLS-terminating proxy forwards that header and `request.is_secure()` / secure cookies are wanted.
  ⚠️ **Flag — James's proxy; not strictly required for the move flow.** Not set unless confirmed.
- **`qrcode`** dependency (see §7). ⚠️ **Flag.**
- **No DB migration** — Phase 12 adds no model fields (`Location.capacity` already shipped in 11.3).

---

## 10. Testing

**Service (`quickmove`)** — unit, no HTTP:
- item-then-destination happy path; status follows `default_status`.
- destination full → classified FULL with the right occupant.
- `evict_and_place(deplete_old=True)` → old DEPLETED + cleared location, incoming placed.
- `evict_and_place(deplete_old=False)` → old re-homed as the chain's active item.
- container destination → `needs_slot_pick`.
- drying warning surfaced on a wet→printer move; wet→dry-storage blocked.
- sticky-status item (DEPLETED/SOLD/UNKNOWN) handling via `move_to` (no silent recompute).

**Views** — GET `move/`; POST scan transitions (idle→item, item→dest ok/full/container), the three
evict/slot actions, cancel/reset. Login required; CSRF.

**Labels** — QR content equals the expected URL; `create_label_image(include_qr=True)` returns an
image of the profile's pixel size; QR data round-trips (decode in-test or assert the encoded
payload). `include_qr=False` still renders Code128-only.

**Manifest** — valid JSON, required keys present, icon paths resolve via staticfiles.

**Not automated:** camera/getUserMedia (browser), real-print legibility — both manual on James's
phone/printer.

---

## 11. Out of scope

- Global mode-aware navbar omni-scan box (`ideas.md` §1.1 — candidate, not scheduled).
- Service worker / offline PWA.
- HTTPS infra itself (James handled: `collerco.com` CA + `inventory.home.collerco.com`).
- FTS5 search box (new `todo.md` item — separate work).
- Unified item timeline, notifications (candidates).

---

## 12. Build sequence (for the plan)

1. `quickmove.py` service + unit tests (TDD) — no Django views yet.
2. CBVs + URLs + templates (`quick_move.html`, `partials/quick_move_body.html`) + view tests.
3. `barcode_utils` QR support + `qrcode` dep + label tests; `SITE_BASE_URL` setting +
   `CSRF_TRUSTED_ORIGINS` + compose env.
4. `scanner.js` (+ vendored zxing) + `quick_move.js`; camera button on quick-move + audit console.
5. PWA manifest + icons + `base.html` links.
6. Nav link; `manage.py check`; full test suite; pre-commit.
7. Update `readme.md` / `todo.md` (mark 12.2/12.3; fix the PWA-exists claim).
