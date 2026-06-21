# Spool-sync dry-run matcher — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A read-only `sync_spools` management command that resolves each Bambu AMS tray to the inventory spool in its slot and proposes `serial_number`/`percent_remaining` writes — with **zero inventory writes**.

**Architecture:** Three new modules. `inventory/spool_sync.py` is the pure matcher (classification + `build_report`), reading the `AMSChannelState` telemetry mirror and inventory via the ORM. `inventory/bambu_mqtt.py` fetches the deterministic AMS-serial bridge live via Bambu's `get_version` MQTT command. `inventory/management/commands/sync_spools.py` wires them together, writes a JSON artifact, and prints a summary. The matcher is the unit-tested surface; the MQTT layer's *parsing* is tested, its *networking* is not.

**Tech Stack:** Django 6.0, Python 3.12, `paho-mqtt` (already a dependency — the telemetry consumer uses it), `dataclasses`, `manage.py` commands.

**Spec:** `docs/superpowers/specs/2026-06-21-spool-sync-dryrun-design.md`

## Global Constraints

- **Zero inventory writes.** `build_report` must not call `.save()` / `.update()` on any `InventoryItem`. Tests assert the DB is unchanged.
- **No new production dependency.** `paho-mqtt` is already present; nothing else may be added.
- **Additive only.** No migrations, no schema changes, no changes to the telemetry consumer this session.
- **`--apply` is hard-blocked** — it must raise `CommandError("live writes not enabled (16.3 go-live)")`.
- **Validate every changed Python file** with `~/.venvs/inventory/bin/python manage.py check` before committing.
- Branch: `feat/spool-sync-dryrun` (already created; the spec is committed there).
- Run tests with `~/.venvs/inventory/bin/python manage.py test inventory.tests.SpoolSyncTests` (and `BambuMqttParseTests`, `SyncSpoolsCommandTests`).
- AMS module name → AMS unit rule (verbatim): a `get_version` module is an AMS iff its `name` matches `^(?:ams|n3f|n3s)/(\d+)$`; the captured group is the telemetry `ams_index`.
- The all-zeros placeholder UUID is the 32-char string `"0" * 32`.
- `tray_index` (0-based) maps to `Location.slot_index` (1-based): `slot_index = tray_index + 1`.

---

### Task 1: Hex normalization + tray classification

**Files:**
- Create: `inventory/spool_sync.py`
- Test: `inventory/tests.py` (append class `SpoolSyncTests`)

**Interfaces:**
- Produces: `ALL_ZEROS: str`; `normalize_hex(value) -> str | None` (6-char lowercase RGB, or None); `classify_tray(tray_uuid, tray_type, color_hex) -> str` returning `"BAMBU"` | `"NON_BAMBU"` | `"EMPTY"`; `material_matches(tray_type, filament) -> bool | None`.

- [ ] **Step 1: Write the failing test**

Append to `inventory/tests.py`:
```python
class SpoolSyncTests(TestCase):
    def test_normalize_hex(self):
        from inventory.spool_sync import normalize_hex

        self.assertEqual(normalize_hex("#FFFFFF"), "ffffff")
        self.assertEqual(normalize_hex("057748FF"), "057748")  # RRGGBBAA -> first 6
        self.assertEqual(normalize_hex("4d5054"), "4d5054")     # no leading #
        self.assertIsNone(normalize_hex(""))
        self.assertIsNone(normalize_hex(None))
        self.assertIsNone(normalize_hex("xyz"))

    def test_classify_tray(self):
        from inventory.spool_sync import classify_tray

        # Bambu RFID roll (real uuid)
        self.assertEqual(
            classify_tray("31D95EE890CA468D8119FE4946EB21B2", "PETG", "FFFFFFFF"),
            "BAMBU",
        )
        # Non-Bambu Polymaker roll: zeros uuid but type+color present
        self.assertEqual(classify_tray("0" * 32, "ASA", "057748FF"), "NON_BAMBU")
        self.assertEqual(classify_tray("", "ASA", "057748FF"), "NON_BAMBU")
        # Empty slot: no type, no color
        self.assertEqual(classify_tray("0" * 32, "", ""), "EMPTY")
        self.assertEqual(classify_tray("", None, None), "EMPTY")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.SpoolSyncTests -v 2`
Expected: FAIL — `ModuleNotFoundError: No module named 'inventory.spool_sync'`.

- [ ] **Step 3: Write minimal implementation**

Create `inventory/spool_sync.py`:
```python
"""Pure matcher for the Bambu spool-sync dry-run (Phase 16.3, trust gate).

Reads the AMSChannelState telemetry mirror + inventory via the ORM and produces
*proposed* writes — it never writes. The (device, ams_index) -> AMS-serial bridge
is passed in (fetched live from get_version by inventory.bambu_mqtt); see
docs/superpowers/specs/2026-06-21-spool-sync-dryrun-design.md.
"""

from .models import AMS, Filament, InventoryItem

ALL_ZEROS = "0" * 32
_HEXDIGITS = set("0123456789abcdef")


def normalize_hex(value):
    """Return a 6-char lowercase RGB hex (drops '#' and any alpha), or None."""
    if not value:
        return None
    h = str(value).strip().lstrip("#").lower()
    if len(h) < 6:
        return None
    h = h[:6]
    if any(c not in _HEXDIGITS for c in h):
        return None
    return h


def classify_tray(tray_uuid, tray_type, color_hex):
    """BAMBU (real RFID), NON_BAMBU (roll present, no RFID), or EMPTY."""
    uuid = (tray_uuid or "").strip()
    if uuid and uuid != ALL_ZEROS:
        return "BAMBU"
    if (tray_type or "").strip() or normalize_hex(color_hex):
        return "NON_BAMBU"
    return "EMPTY"


def material_matches(tray_type, filament):
    """Advisory: is the telemetry material consistent with the spool's? None if unknown."""
    if not tray_type or filament is None or filament.material is None:
        return None
    mat = filament.material
    haystack = f"{mat.name} {mat.material_type}".lower()
    return tray_type.strip().lower() in haystack
```

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.SpoolSyncTests -v 2`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
~/.venvs/inventory/bin/python manage.py check
git add inventory/spool_sync.py inventory/tests.py
git commit -m "feat: spool-sync tray classification + hex normalization"
```

---

### Task 2: Bridge & slot resolution helpers

**Files:**
- Modify: `inventory/spool_sync.py`
- Test: `inventory/tests.py` (extend `SpoolSyncTests`)

**Interfaces:**
- Consumes: `AMS`, `Filament`, `InventoryItem` (from Task 1's imports).
- Produces: `resolve_ams_item(serial) -> InventoryItem | None` (the AMS unit whose `serial_number` matches, case-insensitive); `slot_for(ams_item, tray_index) -> Location | None`; `spools_in_slot(slot) -> list[InventoryItem]` (in-stock only); `filament_of(item) -> Filament | None`.

- [ ] **Step 1: Write the failing test**

Add to `SpoolSyncTests`:
```python
    def _make_ams_unit(self, serial):
        from inventory.models import AMS, InventoryItem, Location

        product = AMS.objects.create(name="Bambu Lab AMS", upc=f"upc{serial[:9]}")
        ams_item = InventoryItem.objects.create(product=product, serial_number=serial)
        slots = []
        for i in range(1, 5):
            slots.append(
                Location.objects.create(
                    name=f"{serial}-slot{i}",
                    kind=Location.Kind.AMS_SLOT,
                    unit=ams_item,
                    slot_index=i,
                    default_status=InventoryItem.Status.IN_USE,
                )
            )
        return ams_item, slots

    def test_resolve_and_slot_and_spools(self):
        from decimal import Decimal

        from inventory.models import Filament, InventoryItem, Material
        from inventory.spool_sync import (
            filament_of,
            resolve_ams_item,
            slot_for,
            spools_in_slot,
        )

        ams_item, slots = self._make_ams_unit("00600A452241166")
        self.assertEqual(resolve_ams_item("00600a452241166"), ams_item)  # case-insensitive
        self.assertIsNone(resolve_ams_item("NOPE"))
        self.assertIsNone(resolve_ams_item(""))

        # tray_index 0 -> slot_index 1
        self.assertEqual(slot_for(ams_item, 0), slots[0])
        self.assertEqual(slot_for(ams_item, 3), slots[3])

        mat = Material.objects.create(name="PLA", material_type="Basic")
        fil = Filament.objects.create(
            name="PLA White", upc="ss0000001", material=mat, hex_code="#ffffff"
        )
        spool = InventoryItem.objects.create(
            product=fil, location=slots[0], percent_remaining=Decimal("100")
        )
        self.assertEqual(spools_in_slot(slots[0]), [spool])
        self.assertEqual(spools_in_slot(slots[1]), [])
        self.assertEqual(filament_of(spool), fil)
        self.assertIsNone(filament_of(ams_item))  # an AMS is not a Filament

        # sticky (depleted) item is not "in stock"
        spool.status = InventoryItem.Status.DEPLETED
        spool.save()
        self.assertEqual(spools_in_slot(slots[0]), [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.SpoolSyncTests.test_resolve_and_slot_and_spools -v 2`
Expected: FAIL — `ImportError: cannot import name 'resolve_ams_item'`.

- [ ] **Step 3: Write minimal implementation**

Append to `inventory/spool_sync.py`:
```python
from .models import Location  # noqa: E402  (grouped with the model imports above)


def resolve_ams_item(serial):
    """The AMS unit InventoryItem whose serial_number matches (case-insensitive)."""
    if not serial:
        return None
    for item in InventoryItem.objects.filter(serial_number__iexact=serial):
        if isinstance(item.product.get_real_instance(), AMS):
            return item
    return None


def slot_for(ams_item, tray_index):
    """The ams_slot Location for this unit at slot_index = tray_index + 1."""
    return Location.objects.filter(
        kind=Location.Kind.AMS_SLOT, unit=ams_item, slot_index=tray_index + 1
    ).first()


def spools_in_slot(slot):
    """In-stock InventoryItems in this slot (excludes DEPLETED/SOLD/UNKNOWN)."""
    return list(
        InventoryItem.objects.filter(location=slot).exclude(
            status__in=InventoryItem.STICKY_STATUSES
        )
    )


def filament_of(item):
    """The real Filament product for an item, or None (polymorphic-safe)."""
    product = item.product.get_real_instance()
    return product if isinstance(product, Filament) else None
```
(Move the `from .models import Location` up next to the other model import if your linter prefers; `ruff --fix` in pre-commit will consolidate.)

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.SpoolSyncTests -v 2`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
~/.venvs/inventory/bin/python manage.py check
git add inventory/spool_sync.py inventory/tests.py
git commit -m "feat: spool-sync AMS-serial bridge + slot/spool resolution"
```

---

### Task 3: `build_report` — categorization & proposals

**Files:**
- Modify: `inventory/spool_sync.py`
- Test: `inventory/tests.py` (extend `SpoolSyncTests`)

**Interfaces:**
- Consumes: all Task 1 + Task 2 helpers; `PrinterDevice`, `AMSChannelState` models.
- Produces: dataclasses `Proposal`, `Flag`, `SyncReport`; `build_report(ams_serial_map, *, generated_at=None) -> SyncReport`. `ams_serial_map` keys are `(device_id, ams_index)` tuples → AMS serial string. `SyncReport.counts` keys: `match, non_bambu_ok, color_mismatch, missing_item, inventory_only, serial_conflict, unmapped_ams, missing_slot, slot_overfilled, empty_skipped`.

- [ ] **Step 1: Write the failing test**

Add to `SpoolSyncTests`:
```python
    def _device(self):
        from inventory.models import PrinterDevice

        return PrinterDevice.objects.create(
            serial="00M09D460801722", name="Scooby Doo",
            ip_address="10.10.30.14", access_code="x",
        )

    def _channel(self, dev, ams_index, tray_index, uuid, ttype, color, remain):
        from inventory.models import AMSChannelState

        return AMSChannelState.objects.create(
            device=dev, ams_index=ams_index, tray_index=tray_index,
            tray_uuid=uuid, tray_type=ttype, color_hex=color, remain_pct=remain,
        )

    def _spool(self, slot, hexc, percent="100", serial=""):
        from decimal import Decimal

        from inventory.models import Filament, InventoryItem, Material

        mat = Material.objects.create(name="PLA", material_type="Basic")
        fil = Filament.objects.create(
            name=f"PLA {hexc}", upc=f"u{abs(hash((slot.id, hexc))) % 10**9}",
            material=mat, hex_code=hexc,
        )
        return InventoryItem.objects.create(
            product=fil, location=slot,
            percent_remaining=Decimal(percent), serial_number=serial,
        )

    def test_bambu_match_proposes_serial_and_percent(self):
        from inventory.spool_sync import build_report

        dev = self._device()
        ams, slots = self._make_ams_unit("00600A452241166")
        self._spool(slots[0], "#ffffff", percent="100")
        self._channel(dev, 0, 0, "31D95EE890CA468D8119FE4946EB21B2", "PLA", "FFFFFFFF", 67)

        rep = build_report({(dev.id, 0): "00600A452241166"})
        self.assertEqual(rep.counts["match"], 1)
        self.assertEqual(len(rep.proposals), 1)
        p = rep.proposals[0]
        self.assertEqual(p.write_serial, "31D95EE890CA468D8119FE4946EB21B2")
        self.assertEqual(p.write_percent_to, 67)
        self.assertTrue(p.color_match)

    def test_non_bambu_present_proposes_nothing(self):
        from inventory.spool_sync import build_report

        dev = self._device()
        ams, slots = self._make_ams_unit("00600A452241166")
        self._spool(slots[0], "#057748")  # matches the Polymaker green
        self._channel(dev, 0, 0, "0" * 32, "ASA", "057748FF", -1)

        rep = build_report({(dev.id, 0): "00600A452241166"})
        self.assertEqual(rep.counts["non_bambu_ok"], 1)
        self.assertEqual(rep.proposals, [])

    def test_color_mismatch_flags_no_write(self):
        from inventory.spool_sync import build_report

        dev = self._device()
        ams, slots = self._make_ams_unit("00600A452241166")
        self._spool(slots[0], "#00a95c")  # inventory green != telemetry green
        self._channel(dev, 0, 0, "AAAA1111BBBB2222CCCC3333DDDD4444", "ASA", "057748FF", 80)

        rep = build_report({(dev.id, 0): "00600A452241166"})
        self.assertEqual(rep.counts["color_mismatch"], 1)
        self.assertEqual(rep.proposals, [])
        self.assertEqual(rep.flags[0].category, "COLOR_MISMATCH")

    def test_missing_item_and_inventory_only_and_unmapped(self):
        from inventory.spool_sync import build_report

        dev = self._device()
        ams, slots = self._make_ams_unit("00600A452241166")
        # occupied tray, empty slot -> MISSING_ITEM
        self._channel(dev, 0, 0, "11112222333344445555666677778888", "PLA", "FFFFFFFF", 50)
        # empty tray, occupied slot -> INVENTORY_ONLY
        self._spool(slots[1], "#ffffff")
        self._channel(dev, 0, 1, "", "", "", -1)
        # a tray whose ams_index has no serial bridge -> UNMAPPED_AMS
        self._channel(dev, 9, 0, "99998888777766665555444433332222", "PLA", "000000FF", 30)

        rep = build_report({(dev.id, 0): "00600A452241166"})
        self.assertEqual(rep.counts["missing_item"], 1)
        self.assertEqual(rep.counts["inventory_only"], 1)
        self.assertEqual(rep.counts["unmapped_ams"], 1)

    def test_serial_conflict_never_overwrites(self):
        from inventory.spool_sync import build_report

        dev = self._device()
        ams, slots = self._make_ams_unit("00600A452241166")
        self._spool(slots[0], "#ffffff", serial="PRE-EXISTING-SERIAL")
        self._channel(dev, 0, 0, "31D95EE890CA468D8119FE4946EB21B2", "PLA", "FFFFFFFF", 67)

        rep = build_report({(dev.id, 0): "00600A452241166"})
        self.assertEqual(rep.counts["serial_conflict"], 1)
        self.assertEqual(rep.proposals, [])

    def test_build_report_writes_nothing(self):
        from inventory.models import InventoryItem
        from inventory.spool_sync import build_report

        dev = self._device()
        ams, slots = self._make_ams_unit("00600A452241166")
        spool = self._spool(slots[0], "#ffffff", percent="100")
        self._channel(dev, 0, 0, "31D95EE890CA468D8119FE4946EB21B2", "PLA", "FFFFFFFF", 67)

        build_report({(dev.id, 0): "00600A452241166"})
        spool.refresh_from_db()
        self.assertEqual(spool.serial_number, "")          # unchanged
        self.assertEqual(int(spool.percent_remaining), 100)  # unchanged
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.SpoolSyncTests -v 2`
Expected: FAIL — `ImportError: cannot import name 'build_report'`.

- [ ] **Step 3: Write minimal implementation**

Append to `inventory/spool_sync.py`:
```python
import dataclasses  # noqa: E402  (move to top with the stdlib imports)

from django.utils import timezone  # noqa: E402

from .models import AMSChannelState, PrinterDevice  # noqa: E402


@dataclasses.dataclass
class Proposal:
    device: str
    ams_index: int
    tray_index: int
    tray_uuid: str
    item_id: int
    item_label: str
    write_serial: str | None
    write_percent_from: int | None
    write_percent_to: int | None
    material_match: bool | None
    color_telemetry: str | None
    color_inventory: str | None
    color_match: bool


@dataclasses.dataclass
class Flag:
    category: str
    device: str
    ams_index: int
    tray_index: int
    detail: str
    item_id: int | None = None


@dataclasses.dataclass
class SyncReport:
    generated_at: str
    ams_bridge: dict
    proposals: list
    flags: list
    counts: dict


_COUNT_KEYS = (
    "match", "non_bambu_ok", "color_mismatch", "missing_item", "inventory_only",
    "serial_conflict", "unmapped_ams", "missing_slot", "slot_overfilled",
    "empty_skipped",
)


def build_report(ams_serial_map, *, generated_at=None):
    """Categorize every AMS tray against inventory and return proposed writes.

    ``ams_serial_map``: {(device_id, ams_index): ams_serial}. Reads only; never
    mutates inventory.
    """
    proposals, flags = [], []
    counts = {k: 0 for k in _COUNT_KEYS}
    bridge = {}

    for device in PrinterDevice.objects.filter(enabled=True).order_by("name"):
        dev_bridge = bridge.setdefault(device.name, {})
        channels = AMSChannelState.objects.filter(device=device).order_by(
            "ams_index", "tray_index"
        )
        for ch in channels:
            kind = classify_tray(ch.tray_uuid, ch.tray_type, ch.color_hex)
            serial = ams_serial_map.get((device.id, ch.ams_index))
            ams_item = resolve_ams_item(serial) if serial else None
            dev_bridge[ch.ams_index] = {
                "serial": serial,
                "item_id": ams_item.id if ams_item else None,
                "matched": ams_item is not None,
            }

            if ams_item is None:
                if kind == "EMPTY":
                    counts["empty_skipped"] += 1
                else:
                    counts["unmapped_ams"] += 1
                    why = (
                        f"serial {serial!r} not in inventory" if serial
                        else "no get_version AMS module"
                    )
                    flags.append(Flag("UNMAPPED_AMS", device.name, ch.ams_index,
                                      ch.tray_index, f"ams_index {ch.ams_index}: {why}."))
                continue

            slot = slot_for(ams_item, ch.tray_index)
            if slot is None:
                if kind == "EMPTY":
                    counts["empty_skipped"] += 1
                else:
                    counts["missing_slot"] += 1
                    flags.append(Flag("MISSING_SLOT", device.name, ch.ams_index,
                                      ch.tray_index,
                                      f"No ams_slot for {ams_item} slot {ch.tray_index + 1}.",
                                      item_id=ams_item.id))
                continue

            spools = spools_in_slot(slot)

            if kind == "EMPTY":
                if spools:
                    counts["inventory_only"] += 1
                    flags.append(Flag("INVENTORY_ONLY", device.name, ch.ams_index,
                                      ch.tray_index,
                                      f"AMS slot empty but inventory has {spools[0]}.",
                                      item_id=spools[0].id))
                else:
                    counts["empty_skipped"] += 1
                continue

            if not spools:
                counts["missing_item"] += 1
                flags.append(Flag("MISSING_ITEM", device.name, ch.ams_index,
                                  ch.tray_index,
                                  f"AMS sees a {ch.tray_type or '?'} roll but {slot.name} is empty."))
                continue
            if len(spools) > 1:
                counts["slot_overfilled"] += 1
                flags.append(Flag("SLOT_OVERFILLED", device.name, ch.ams_index,
                                  ch.tray_index,
                                  f"{len(spools)} in-stock items in {slot.name}; reconcile to 1:1.",
                                  item_id=spools[0].id))
                continue

            item = spools[0]
            fil = filament_of(item)
            color_t = normalize_hex(ch.color_hex)
            color_f = normalize_hex(getattr(fil, "hex_code", None)) if fil else None
            color_match = bool(color_t and color_f and color_t == color_f)
            existing = (item.serial_number or "").strip()

            if kind == "BAMBU" and existing and existing.lower() != ch.tray_uuid.strip().lower():
                counts["serial_conflict"] += 1
                flags.append(Flag("SERIAL_CONFLICT", device.name, ch.ams_index,
                                  ch.tray_index,
                                  f"{item} already has serial {existing!r}; not overwriting.",
                                  item_id=item.id))
                continue

            if not color_match:
                counts["color_mismatch"] += 1
                flags.append(Flag("COLOR_MISMATCH", device.name, ch.ams_index,
                                  ch.tray_index,
                                  f"AMS #{color_t or '?'} ({ch.tray_type}) vs inventory "
                                  f"#{color_f or '?'}; verify the slot's item.",
                                  item_id=item.id))
                continue

            if kind == "NON_BAMBU":
                counts["non_bambu_ok"] += 1
                continue

            # BAMBU confident match -> propose writes
            counts["match"] += 1
            write_serial = ch.tray_uuid if not existing else None
            cur_int = int(item.percent_remaining or 0)
            write_pct = (
                ch.remain_pct
                if (ch.remain_pct is not None and ch.remain_pct >= 0 and ch.remain_pct != cur_int)
                else None
            )
            if write_serial is not None or write_pct is not None:
                proposals.append(Proposal(
                    device=device.name, ams_index=ch.ams_index, tray_index=ch.tray_index,
                    tray_uuid=ch.tray_uuid, item_id=item.id, item_label=str(item),
                    write_serial=write_serial,
                    write_percent_from=cur_int if write_pct is not None else None,
                    write_percent_to=write_pct,
                    material_match=material_matches(ch.tray_type, fil),
                    color_telemetry=color_t, color_inventory=color_f,
                    color_match=color_match,
                ))

    return SyncReport(
        generated_at=generated_at or timezone.now().isoformat(),
        ams_bridge=bridge, proposals=proposals, flags=flags, counts=counts,
    )
```
(Consolidate the `import dataclasses` / `from django.utils import timezone` / model imports to the top of the file; `ruff --fix` will handle ordering.)

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.SpoolSyncTests -v 2`
Expected: PASS (all `SpoolSyncTests`).

- [ ] **Step 5: Commit**

```bash
~/.venvs/inventory/bin/python manage.py check
git add inventory/spool_sync.py inventory/tests.py
git commit -m "feat: spool-sync build_report categorization + proposals"
```

---

### Task 4: `get_version` AMS-serial probe

**Files:**
- Create: `inventory/bambu_mqtt.py`
- Test: `inventory/tests.py` (append class `BambuMqttParseTests`)

**Interfaces:**
- Produces: `parse_ams_modules(modules) -> dict[int, str]` (pure; `{ams_index: sn}`); `fetch_ams_serials(device, *, timeout=15) -> dict[int, str]` (one printer, live); `fetch_ams_serials_all(devices) -> dict[tuple[int, int], str]` keyed `(device.id, ams_index)`.
- Only `parse_ams_modules` is unit-tested; the network functions are smoke-tested manually.

- [ ] **Step 1: Write the failing test**

Append to `inventory/tests.py`:
```python
class BambuMqttParseTests(TestCase):
    def test_parse_ams_modules(self):
        from inventory.bambu_mqtt import parse_ams_modules

        modules = [
            {"name": "ota", "sn": "0948CD531200537"},      # not an AMS
            {"name": "ams/0", "sn": "00600A452241166"},     # AMS-Lite
            {"name": "ams/1", "sn": "00600A462518921"},
            {"name": "n3f/2", "sn": "19C06A510501697"},     # H2D AMS 2 Pro
            {"name": "n3s/128", "sn": "19F06A532302491"},   # H2D AMS-HT
            {"name": "mc-sub", "sn": "N/A"},                # ignored
            {"name": "ams/3"},                              # no sn -> ignored
        ]
        self.assertEqual(
            parse_ams_modules(modules),
            {
                0: "00600A452241166",
                1: "00600A462518921",
                2: "19C06A510501697",
                128: "19F06A532302491",
            },
        )
        self.assertEqual(parse_ams_modules(None), {})
        self.assertEqual(parse_ams_modules([]), {})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.BambuMqttParseTests -v 2`
Expected: FAIL — `ModuleNotFoundError: No module named 'inventory.bambu_mqtt'`.

- [ ] **Step 3: Write minimal implementation**

Create `inventory/bambu_mqtt.py`:
```python
"""Live Bambu MQTT helper for the spool-sync dry-run: fetch the AMS hardware
serials via the `get_version` command (the deterministic (device, ams_index) ->
AMS unit bridge). Read-only; mirrors the connection params of the telemetry
consumer (run_telemetry_consumer.py). Only `parse_ams_modules` is unit-tested.
"""

import json
import logging
import re
import ssl
import time

import paho.mqtt.client as mqtt

logger = logging.getLogger("inventory")

# A get_version module is an AMS iff its name is ams/N (AMS-Lite), n3f/N (H2D AMS
# 2 Pro) or n3s/N (H2D AMS-HT). The captured group is the telemetry ams_index.
_AMS_MODULE = re.compile(r"^(?:ams|n3f|n3s)/(\d+)$")
GET_VERSION = json.dumps({"info": {"sequence_id": "0", "command": "get_version"}})


def parse_ams_modules(modules):
    """{ams_index: sn} from a get_version `info.module` list."""
    out = {}
    for module in modules or []:
        match = _AMS_MODULE.match(str(module.get("name", "")))
        sn = module.get("sn")
        if match and sn and sn != "N/A":
            out[int(match.group(1))] = sn
    return out


def fetch_ams_serials(device, *, timeout=15):
    """Connect to one printer, request get_version, return {ams_index: sn}.

    Returns {} on connect failure or timeout — the caller treats absent indices
    as UNMAPPED_AMS rather than crashing.
    """
    result = {}
    done = {"flag": False}

    def on_connect(client, userdata, flags, reason_code, properties=None):
        if reason_code != 0:
            logger.warning("get_version connect rc=%s for %s", reason_code, device.serial)
            return
        client.subscribe(f"device/{device.serial}/report")
        client.publish(f"device/{device.serial}/request", GET_VERSION)

    def on_message(client, userdata, msg):
        try:
            info = (json.loads(msg.payload) or {}).get("info")
        except (ValueError, TypeError):
            return
        if isinstance(info, dict) and isinstance(info.get("module"), list):
            result.update(parse_ams_modules(info["module"]))
            done["flag"] = True
            client.disconnect()

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2, client_id=f"inv-syncprobe-{device.serial}"
    )
    client.username_pw_set("bblp", device.access_code)
    client.tls_set(cert_reqs=ssl.CERT_NONE)
    client.tls_insecure_set(True)
    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(device.ip_address, 8883, keepalive=30)
    except OSError:
        logger.warning("get_version connect failed for %s", device.serial)
        return {}
    client.loop_start()
    ticks = timeout * 2
    while ticks > 0 and not done["flag"]:
        time.sleep(0.5)
        ticks -= 1
    client.loop_stop()
    try:
        client.disconnect()
    except Exception:  # noqa: BLE001
        pass
    return result


def fetch_ams_serials_all(devices):
    """{(device.id, ams_index): sn} across all given devices."""
    out = {}
    for device in devices:
        for ams_index, sn in fetch_ams_serials(device).items():
            out[(device.id, ams_index)] = sn
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.BambuMqttParseTests -v 2`
Expected: PASS (1 test).

- [ ] **Step 5: Commit**

```bash
~/.venvs/inventory/bin/python manage.py check
git add inventory/bambu_mqtt.py inventory/tests.py
git commit -m "feat: get_version AMS-serial probe (spool-sync bridge)"
```

---

### Task 5: `sync_spools` command + gitignore

**Files:**
- Create: `inventory/management/commands/sync_spools.py`
- Modify: `.gitignore`
- Test: `inventory/tests.py` (append class `SyncSpoolsCommandTests`)

**Interfaces:**
- Consumes: `inventory.bambu_mqtt.fetch_ams_serials_all`, `inventory.spool_sync.build_report`.
- Produces: management command `sync_spools` (options: `--apply` [blocked], `--out-dir <path>`). Writes `spool-sync-<ts>.json` (a `dataclasses.asdict(SyncReport)` dump) into the out dir.

- [ ] **Step 1: Write the failing test**

Append to `inventory/tests.py`:
```python
class SyncSpoolsCommandTests(TestCase):
    def test_apply_is_blocked(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("sync_spools", "--apply")

    def test_dryrun_writes_artifact_and_no_db_writes(self):
        import json
        import tempfile
        from decimal import Decimal
        from pathlib import Path
        from unittest.mock import patch

        from django.core.management import call_command

        from inventory.models import (
            AMS, AMSChannelState, Filament, InventoryItem, Location, Material,
            PrinterDevice,
        )

        dev = PrinterDevice.objects.create(
            serial="00M09D460801722", name="Scooby Doo",
            ip_address="10.10.30.14", access_code="x",
        )
        ams_item = InventoryItem.objects.create(
            product=AMS.objects.create(name="AMS", upc="upc900000001"),
            serial_number="00600A452241166",
        )
        slot = Location.objects.create(
            name="AMS-slot1", kind=Location.Kind.AMS_SLOT, unit=ams_item, slot_index=1,
            default_status=InventoryItem.Status.IN_USE,
        )
        mat = Material.objects.create(name="PLA", material_type="Basic")
        fil = Filament.objects.create(name="PLA W", upc="ss1", material=mat, hex_code="#ffffff")
        spool = InventoryItem.objects.create(
            product=fil, location=slot, percent_remaining=Decimal("100"),
        )
        AMSChannelState.objects.create(
            device=dev, ams_index=0, tray_index=0,
            tray_uuid="31D95EE890CA468D8119FE4946EB21B2",
            tray_type="PLA", color_hex="FFFFFFFF", remain_pct=67,
        )

        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "inventory.management.commands.sync_spools.bambu_mqtt.fetch_ams_serials_all",
                return_value={(dev.id, 0): "00600A452241166"},
            ):
                call_command("sync_spools", "--out-dir", tmp)
            files = list(Path(tmp).glob("spool-sync-*.json"))
            self.assertEqual(len(files), 1)
            data = json.loads(files[0].read_text())
            self.assertEqual(data["counts"]["match"], 1)
            self.assertEqual(data["proposals"][0]["write_percent_to"], 67)

        spool.refresh_from_db()
        self.assertEqual(spool.serial_number, "")
        self.assertEqual(int(spool.percent_remaining), 100)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.SyncSpoolsCommandTests -v 2`
Expected: FAIL — `CommandError: Unknown command: 'sync_spools'`.

- [ ] **Step 3: Write minimal implementation**

Create `inventory/management/commands/sync_spools.py`:
```python
"""Dry-run Bambu spool sync (Phase 16.3 trust gate): propose serial_number /
percent_remaining writes from AMS telemetry — ZERO inventory writes. Writes a
JSON artifact + prints a summary. `--apply` is intentionally blocked.
"""

import dataclasses
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from inventory import bambu_mqtt, spool_sync
from inventory.models import PrinterDevice


class Command(BaseCommand):
    help = "Dry-run Bambu spool sync: propose serial/percent writes (zero inventory writes)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="(blocked) live writes are not enabled in this phase.",
        )
        parser.add_argument(
            "--out-dir", default=None,
            help="Artifact dir (default: <BASE_DIR>/telemetry_review).",
        )

    def handle(self, *args, **options):
        if options["apply"]:
            raise CommandError("live writes not enabled (16.3 go-live)")

        out_dir = Path(options["out_dir"] or (Path(settings.BASE_DIR) / "telemetry_review"))
        devices = list(PrinterDevice.objects.filter(enabled=True))
        self.stdout.write(f"Probing get_version on {len(devices)} printer(s)…")
        serial_map = bambu_mqtt.fetch_ams_serials_all(devices)
        report = spool_sync.build_report(serial_map)

        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = report.generated_at.translate({ord(c): None for c in ":-"})[:15]
        path = out_dir / f"spool-sync-{stamp}.json"
        path.write_text(json.dumps(dataclasses.asdict(report), indent=2))

        self._print_summary(report)
        self.stdout.write(self.style.SUCCESS(f"Report: {path}"))

    def _print_summary(self, report):
        self.stdout.write("\n== Spool sync (DRY-RUN — no writes) ==")
        for key, value in report.counts.items():
            self.stdout.write(f"  {key:16} {value}")
        if report.proposals:
            self.stdout.write("\n-- Proposed writes --")
            for p in report.proposals:
                bits = []
                if p.write_serial:
                    bits.append(f"serial←{p.write_serial}")
                if p.write_percent_to is not None:
                    bits.append(f"%←{p.write_percent_from}→{p.write_percent_to}")
                self.stdout.write(
                    f"  {p.device} ams{p.ams_index}/t{p.tray_index} {p.item_label}: "
                    f"{', '.join(bits)}"
                )
        if report.flags:
            self.stdout.write("\n-- Flags --")
            for f in report.flags:
                self.stdout.write(
                    f"  [{f.category}] {f.device} ams{f.ams_index}/t{f.tray_index}: {f.detail}"
                )
```

- [ ] **Step 4: Add the gitignore entry**

Append to `.gitignore`:
```
# Spool-sync dry-run artifacts (Phase 16.3) — generated by `sync_spools`,
# human-reviewed before any go-live; never committed.
telemetry_review/
```

- [ ] **Step 5: Run test to verify it passes**

Run: `~/.venvs/inventory/bin/python manage.py test inventory.tests.SyncSpoolsCommandTests -v 2`
Expected: PASS (2 tests).

- [ ] **Step 6: Run the full new suite + check**

Run:
```bash
~/.venvs/inventory/bin/python manage.py test inventory.tests.SpoolSyncTests inventory.tests.BambuMqttParseTests inventory.tests.SyncSpoolsCommandTests -v 2
~/.venvs/inventory/bin/python manage.py check
```
Expected: all PASS; check reports no issues.

- [ ] **Step 7: Commit**

```bash
git add inventory/management/commands/sync_spools.py .gitignore inventory/tests.py
git commit -m "feat: sync_spools dry-run command + artifact output"
```

---

### Task 6: Live read-only first run on prod (verification, no code)

**Files:** none (operational verification).

This is the payoff: produce the first real report against the live stack. Reads only; the command performs zero inventory writes by construction.

- [ ] **Step 1: Deploy is not required for a one-off** — run the command in the telemetry container (which has `paho-mqtt`, the access codes, and the WAL DB):

```bash
ssh inventory-manager 'docker exec -i inventory_management-telemetry-1 \
  python manage.py sync_spools --out-dir /tmp/telemetry_review'
```
Expected: a counts banner, proposed writes (Bambu rolls), and flags (the Polymaker color mismatches, any missing items), then `Report: /tmp/telemetry_review/spool-sync-*.json`.

- [ ] **Step 2: Sanity-check the bridge** — confirm the `ams_bridge` in the JSON shows `matched: true` for every occupied `ams_index` across all 4 printers (no `UNMAPPED_AMS` for live units). If H2D indices `2`/`128` are unmapped, note it (the `get_version` probe may need a longer timeout for the H2D).

- [ ] **Step 3: Confirm zero writes** — re-run the read-only match probe (`/tmp/match_probe.py` equivalent) or a quick shell: filament `serial_number` count still 0, `percent_remaining` unchanged. The command never writes, but verify the invariant on real data.

- [ ] **Step 4: Report findings to James** — summarize match/flag counts; this is the trust-gate evidence that decides whether `--apply` is built next session. Do **not** build `--apply`.

---

## Self-Review

**1. Spec coverage:**
- §2 module layout → Tasks 1–5 (spool_sync, bambu_mqtt, command, gitignore). ✓
- §3.1 classification → Task 1 `classify_tray`. ✓
- §3.2 bridge/slot/spool → Task 2. ✓
- §3.3 category matrix (all 10 counts incl. NON_BAMBU no-write, serial-conflict, inventory-only, slot-overfilled, unmapped, missing-slot) → Task 3 + tests. ✓
- §3.4 SyncReport shape → Task 3 dataclasses. ✓
- §4 artifact + stdout → Task 5. ✓
- §5 error handling (unreachable printer → {} → UNMAPPED_AMS; no rows; malformed) → Task 3 (unmapped path) + Task 4 (`fetch_ams_serials` returns {} on OSError). ✓
- §6 testing incl. no-writes invariant → Task 3 `test_build_report_writes_nothing` + Task 5 DB-unchanged assert. ✓
- §7 out-of-scope (`--apply` blocked) → Task 5 `test_apply_is_blocked`. ✓

**2. Placeholder scan:** none — every step has full code/commands.

**3. Type consistency:** `build_report(ams_serial_map)` keys `(device_id, ams_index)` used identically in Tasks 3 & 5 and `fetch_ams_serials_all` (Task 4). `SyncReport` fields (`counts`, `proposals`, `flags`, `ams_bridge`, `generated_at`) consumed consistently by the command. `Proposal.write_percent_to` / `write_serial` names match across Task 3 producer and Task 5 consumer. `classify_tray` return strings (`BAMBU`/`NON_BAMBU`/`EMPTY`) consistent across Tasks 1 & 3.

> **Note for go-live (not this plan):** promote the `get_version` capture into the telemetry consumer + an `AMSUnitState.serial` field so the matcher reads the bridge from the DB instead of a live probe; then build `--apply` behind the trust gate.
