from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import (
    AMS,
    AuditSession,
    AuditUnknownScan,
    Dryer,
    Filament,
    Hardware,
    InventoryItem,
    Location,
    Material,
    Printer,
)


class BulkUpdateViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="tester", password="pass")
        self.client.login(username="tester", password="pass")
        self.location_a = Location.objects.create(
            name="Shelf A", default_status=InventoryItem.Status.NEW
        )
        self.location_b = Location.objects.create(
            name="Dry Storage", default_status=InventoryItem.Status.STORED
        )
        product = Filament.objects.create(name="PLA Red", upc="0000000000001")
        self.item1 = InventoryItem.objects.create(
            product=product, location=self.location_a
        )
        self.item2 = InventoryItem.objects.create(
            product=product, location=self.location_a
        )
        self.item3 = InventoryItem.objects.create(
            product=product, location=self.location_b
        )
        self.url = reverse("bulk_update")

    def _post(self, data):
        return self.client.post(self.url, data)

    def test_get_redirects_to_search(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse("inventory_search"))

    def test_requires_login(self):
        self.client.logout()
        response = self._post(
            {
                "item_ids": [self.item1.pk],
                "bulk_status": str(InventoryItem.Status.DEPLETED),
            }
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_no_ids_redirects_with_warning(self):
        response = self._post({"bulk_status": str(InventoryItem.Status.DEPLETED)})
        self.assertRedirects(response, reverse("inventory_search"))
        msgs = list(response.wsgi_request._messages)
        self.assertTrue(any("No items" in str(m) for m in msgs))

    def test_no_fields_redirects_with_warning(self):
        response = self._post({"item_ids": [self.item1.pk]})
        self.assertRedirects(response, reverse("inventory_search"))
        msgs = list(response.wsgi_request._messages)
        self.assertTrue(any("No fields" in str(m) for m in msgs))

    def test_bulk_status_depleted(self):
        self._post(
            {
                "item_ids": [self.item1.pk, self.item2.pk],
                "bulk_status": str(InventoryItem.Status.DEPLETED),
            }
        )
        self.item1.refresh_from_db()
        self.item2.refresh_from_db()
        self.assertEqual(self.item1.status, InventoryItem.Status.DEPLETED)
        self.assertIsNotNone(self.item1.date_depleted)
        self.assertIsNone(self.item1.location)
        self.assertEqual(self.item2.status, InventoryItem.Status.DEPLETED)
        self.assertIsNotNone(self.item2.date_depleted)
        self.assertIsNone(self.item2.location)

    def test_bulk_status_depleted_does_not_reassign_location(self):
        """Providing a location alongside DEPLETED status must not re-assign it."""
        self._post(
            {
                "item_ids": [self.item1.pk],
                "bulk_status": str(InventoryItem.Status.DEPLETED),
                "bulk_location": str(self.location_b.pk),
            }
        )
        self.item1.refresh_from_db()
        self.assertIsNone(self.item1.location)

    def test_bulk_status_sold(self):
        self._post(
            {
                "item_ids": [self.item1.pk],
                "bulk_status": str(InventoryItem.Status.SOLD),
            }
        )
        self.item1.refresh_from_db()
        self.assertEqual(self.item1.status, InventoryItem.Status.SOLD)
        self.assertIsNotNone(self.item1.date_sold)
        self.assertIsNone(self.item1.location)

    def test_bulk_location(self):
        self._post(
            {
                "item_ids": [self.item1.pk, self.item2.pk],
                "bulk_location": str(self.location_b.pk),
            }
        )
        self.item1.refresh_from_db()
        self.item2.refresh_from_db()
        self.assertEqual(self.item1.location, self.location_b)
        self.assertEqual(self.item2.location, self.location_b)

    def test_bulk_shipment(self):
        self._post(
            {
                "item_ids": [self.item1.pk, self.item2.pk],
                "bulk_shipment": "1Z999AA10123456784",
            }
        )
        self.item1.refresh_from_db()
        self.item2.refresh_from_db()
        self.assertEqual(self.item1.shipment, "1Z999AA10123456784")
        self.assertEqual(self.item2.shipment, "1Z999AA10123456784")

    def test_unknown_ids_silently_skipped(self):
        response = self._post(
            {
                "item_ids": [99999],
                "bulk_status": str(InventoryItem.Status.DEPLETED),
            }
        )
        # Should redirect (not 404)
        self.assertEqual(response.status_code, 302)

    def test_success_message_shows_count(self):
        response = self._post(
            {
                "item_ids": [self.item1.pk, self.item2.pk],
                "bulk_status": str(InventoryItem.Status.IN_USE),
            }
        )
        msgs = list(response.wsgi_request._messages)
        self.assertTrue(any("2" in str(m) for m in msgs))

    def test_filter_params_preserved_in_redirect(self):
        response = self._post(
            {
                "item_ids": [self.item1.pk],
                "bulk_status": str(InventoryItem.Status.DEPLETED),
                "sku": "BPR-001",
                "name": "PLA Red",
            }
        )
        self.assertIn("sku=BPR-001", response["Location"])
        self.assertIn("name=PLA+Red", response["Location"])

    def test_invalid_status_redirects_with_error(self):
        response = self._post(
            {
                "item_ids": [self.item1.pk],
                "bulk_status": "999",
            }
        )
        self.assertRedirects(response, reverse("inventory_search"))
        msgs = list(response.wsgi_request._messages)
        self.assertTrue(any("Invalid" in str(m) for m in msgs))

    def test_unmodified_items_unchanged(self):
        """item3 was not selected — must not be touched."""
        self._post(
            {
                "item_ids": [self.item1.pk],
                "bulk_status": str(InventoryItem.Status.DEPLETED),
            }
        )
        self.item3.refresh_from_db()
        self.assertEqual(self.item3.status, InventoryItem.Status.STORED)
        self.assertEqual(self.item3.location, self.location_b)

    def test_explicit_status_not_overridden_by_location_default(self):
        """Explicit bulk_status must survive save() even when bulk_location is also set.
        location_b.default_status = STORED; user explicitly requests IN_USE."""
        self._post(
            {
                "item_ids": [self.item1.pk],
                "bulk_status": str(InventoryItem.Status.IN_USE),
                "bulk_location": str(self.location_b.pk),
            }
        )
        self.item1.refresh_from_db()
        self.assertEqual(self.item1.status, InventoryItem.Status.IN_USE)
        self.assertEqual(self.item1.location, self.location_b)


class FilamentSummaryViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="tester2", password="pass")
        self.client.login(username="tester2", password="pass")
        self.loc = Location.objects.create(
            name="Shelf", default_status=InventoryItem.Status.NEW
        )
        self.mat = Material.objects.create(name="PLA", material_type="")
        # 3 PLA rolls + 1 PETG roll — cards should sort by roll count, PLA first
        pla_black = Filament.objects.create(
            name="PLA Black",
            upc="1000000000001",
            material=self.mat,
            color="Black",
            color_family="BLACK",
            hex_code="",
        )
        petg_mat = Material.objects.create(name="PETG", material_type="")
        petg_white = Filament.objects.create(
            name="PETG White",
            upc="1000000000002",
            material=petg_mat,
            color="White",
            color_family="WHITE",
            hex_code="#ffffff",
        )
        for _ in range(3):
            InventoryItem.objects.create(product=pla_black, location=self.loc)
        InventoryItem.objects.create(product=petg_white, location=self.loc)
        self.url = reverse("filament_summary")

    def test_cards_sorted_by_roll_count_descending(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        cards = resp.context["cards"]
        counts = [c["total_on_hand"] for c in cards]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_black_family_hex_is_not_bootstrap_dark(self):
        """BLACK swatch should be pure black, not Bootstrap's dark (#2c3e50)."""
        resp = self.client.get(self.url)
        cards = resp.context["cards"]
        pla_card = next(c for c in cards if c["name"] == "PLA")
        black_swatch = next(
            s for s in pla_card["visible_swatches"] if s["family"] == "BLACK"
        )
        self.assertEqual(black_swatch["hex"], "#000000")

    def test_row_hex_falls_back_to_family_hex_when_missing(self):
        """Row with no hex_code should get a fallback from COLOR_FAMILY_HEX."""
        resp = self.client.get(self.url)
        rows = resp.context["rows"]
        black_row = next(r for r in rows if r["color"] == "Black")
        # hex_code is empty in the DB, but color_family is BLACK → fallback expected
        self.assertEqual(black_row["hex_code"], "#000000")


class ModelSaveTests(TestCase):
    """One save()/round-trip per model. Catches schema regressions early."""

    def test_material_save(self):
        m = Material.objects.create(name="PLA", material_type="HF")
        self.assertIsNotNone(m.pk)
        self.assertEqual(str(m), "PLA HF")

    def test_location_save(self):
        loc = Location.objects.create(
            name="Shelf 1", default_status=InventoryItem.Status.NEW
        )
        self.assertIsNotNone(loc.pk)

    def test_filament_save_normalizes_hex(self):
        mat = Material.objects.create(name="PLA", material_type="")
        f = Filament.objects.create(
            name="PLA Red",
            upc="2000000000001",
            material=mat,
            color="Red",
            hex_code="#FF0000",
        )
        f.refresh_from_db()
        self.assertEqual(f.hex_code, "#ff0000")
        self.assertEqual(f.color_family, "RED")

    def test_filament_3digit_hex_color_family(self):
        mat = Material.objects.create(name="PLA 3D", material_type="")
        f = Filament.objects.create(
            name="PLA Red Short",
            upc="2000000000099",
            material=mat,
            color="Red",
            hex_code="#F00",
        )
        f.refresh_from_db()
        self.assertEqual(f.hex_code, "#f00")
        self.assertEqual(f.color_family, "RED")

    def test_printer_save_computes_volume(self):
        p = Printer.objects.create(
            name="X1C",
            upc="2000000000002",
            num_extruders=1,
            bed_length_mm=256,
            bed_width_mm=256,
            max_height_mm=256,
        )
        p.refresh_from_db()
        self.assertIsNotNone(p.print_volume_m3)

    def test_dryer_save(self):
        d = Dryer.objects.create(
            name="FilaDryer S2",
            upc="2000000000003",
            mfr="Sunlu",
            model="S2",
            num_slots=1,
            max_temp_degC=70,
        )
        self.assertIsNotNone(d.pk)

    def test_ams_save(self):
        a = AMS.objects.create(name="AMS Lite", upc="2000000000004", num_slots=4)
        self.assertIsNotNone(a.pk)

    def test_hardware_save(self):
        h = Hardware.objects.create(name="Hotend", upc="2000000000005", qty=1)
        self.assertIsNotNone(h.pk)

    def test_inventory_item_save_assigns_default_status_from_location(self):
        mat = Material.objects.create(name="PLA", material_type="")
        f = Filament.objects.create(name="PLA Blue", upc="2000000000006", material=mat)
        loc = Location.objects.create(
            name="Bay 1", default_status=InventoryItem.Status.IN_USE
        )
        item = InventoryItem.objects.create(product=f, location=loc)
        item.refresh_from_db()
        self.assertEqual(item.status, InventoryItem.Status.IN_USE)

    def test_inventory_item_mark_depleted_clears_location(self):
        mat = Material.objects.create(name="PLA", material_type="")
        f = Filament.objects.create(name="PLA Green", upc="2000000000007", material=mat)
        loc = Location.objects.create(
            name="Bay 2", default_status=InventoryItem.Status.NEW
        )
        item = InventoryItem.objects.create(product=f, location=loc)
        item.mark_depleted()
        item.save()
        item.refresh_from_db()
        self.assertIsNotNone(item.date_depleted)
        self.assertIsNone(item.location)
        self.assertEqual(item.status, InventoryItem.Status.DEPLETED)


@override_settings(ENABLE_BARCODE_PRINTING=False)
class ViewRoundTripTests(TestCase):
    """One GET per non-mutating view. Catches template/import-time regressions."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="smoke", password="pass")
        cls.material = Material.objects.create(name="PLA", material_type="")
        cls.location = Location.objects.create(
            name="Shelf", default_status=InventoryItem.Status.NEW
        )
        cls.filament = Filament.objects.create(
            name="PLA Black",
            upc="3000000000001",
            material=cls.material,
            color="Black",
            hex_code="#000000",
        )
        cls.item = InventoryItem.objects.create(
            product=cls.filament, location=cls.location
        )

    def setUp(self):
        self.client = Client()
        self.client.login(username="smoke", password="pass")

    def _assert_ok(self, name, **kwargs):
        resp = self.client.get(reverse(name, **kwargs))
        self.assertEqual(resp.status_code, 200, f"{name} returned {resp.status_code}")

    def test_about(self):
        self._assert_ok("about")

    def test_index(self):
        self._assert_ok("index")

    def test_dashboard(self):
        self._assert_ok("dashboard")

    def test_signup_get(self):
        self._assert_ok("signup")

    def test_add_inventory(self):
        self._assert_ok("add_inventory")

    def test_add_product_choice(self):
        self._assert_ok("add_product_choice")

    def test_add_filament(self):
        self._assert_ok("add_filament")

    def test_add_printer(self):
        self._assert_ok("add_printer")

    def test_add_ams(self):
        self._assert_ok("add_ams")

    def test_add_hardware(self):
        self._assert_ok("add_hardware")

    def test_add_dryer(self):
        self._assert_ok("add_dryer")

    def test_inventory_search(self):
        self._assert_ok("inventory_search")

    def test_inventory_edit(self):
        self._assert_ok("inventory_edit", kwargs={"item_id": self.item.id})

    def test_inventory_edit_shows_has_spool(self):
        resp = self.client.get(
            reverse("inventory_edit", kwargs={"item_id": self.item.id})
        )
        self.assertContains(resp, "Has Spool")

    def test_inventory_export(self):
        self._assert_ok("inventory_export")

    def test_in_use_overview(self):
        self._assert_ok("in_use_overview")

    def test_dry_storage_overview(self):
        self._assert_ok("dry_storage_overview")

    def test_filament_color_guide(self):
        self._assert_ok("filament_color_guide")

    def test_filament_summary(self):
        self._assert_ok("filament_summary")

    def test_print_barcode_unique(self):
        url = reverse(
            "print_barcode", kwargs={"item_id": self.item.id, "mode": "unique"}
        )
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "image/png")

    def test_barcode_redirect_inv(self):
        url = reverse("barcode_redirect", kwargs={"value": f"INV-{self.item.id}"})
        resp = self.client.get(url)
        self.assertRedirects(
            resp, reverse("inventory_edit", kwargs={"item_id": self.item.id})
        )

    def test_views_require_login(self):
        """A representative sample of protected views all redirect when logged out."""
        self.client.logout()
        for name in (
            "dashboard",
            "inventory_search",
            "add_inventory",
            "filament_summary",
        ):
            resp = self.client.get(reverse(name))
            self.assertEqual(
                resp.status_code, 302, f"{name} should redirect when logged out"
            )
            self.assertIn("/login/", resp["Location"])


class SignUpTests(TestCase):
    def test_signup_creates_user_and_logs_in(self):
        resp = self.client.post(
            reverse("signup"),
            {
                "username": "newbie",
                "email": "newbie@example.com",
                "password1": "complex-pw-9876",
                "password2": "complex-pw-9876",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(User.objects.filter(username="newbie").exists())


class InventoryEditFormTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="editor", password="pass")
        self.client.login(username="editor", password="pass")
        self.material = Material.objects.create(name="PLA", material_type="")
        self.filament = Filament.objects.create(
            name="PLA Black",
            upc="4000000000001",
            material=self.material,
            color="Black",
            hex_code="#000000",
        )
        self.loc_a = Location.objects.create(
            name="Shelf A", default_status=InventoryItem.Status.NEW
        )
        self.loc_b = Location.objects.create(
            name="Shelf B", default_status=InventoryItem.Status.STORED
        )
        self.item = InventoryItem.objects.create(
            product=self.filament, location=self.loc_a
        )

    def test_post_updates_location(self):
        url = reverse("inventory_edit", kwargs={"item_id": self.item.id})
        resp = self.client.post(
            url,
            {
                "serial_number": "",
                "location": self.loc_b.id,
                "date_depleted": "",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.location, self.loc_b)


from . import audit  # noqa: E402
from .models import AuditEvent  # noqa: E402


class StickyStatusGuardTests(TestCase):
    """A location-changing save must never overwrite a sticky status."""

    def setUp(self):
        self.product = Filament.objects.create(name="PLA Sticky", upc="9100000000001")
        self.loc_a = Location.objects.create(
            name="Guard A",
            kind=Location.Kind.SHELF,
            default_status=InventoryItem.Status.NEW,
        )
        self.loc_b = Location.objects.create(
            name="Guard B",
            kind=Location.Kind.SHELF,
            default_status=InventoryItem.Status.NEW,
        )

    def test_unknown_survives_location_change(self):
        item = InventoryItem.objects.create(product=self.product, location=self.loc_a)
        item.status = InventoryItem.Status.UNKNOWN
        item._skip_status_from_location = True
        item.save()
        # Reload (drops the ad-hoc skip flag) then move it via a normal save.
        item = InventoryItem.objects.get(pk=item.pk)
        item.location = self.loc_b
        item.save()
        item.refresh_from_db()
        self.assertEqual(item.status, InventoryItem.Status.UNKNOWN)
        self.assertEqual(item.location_id, self.loc_b.id)

    def test_depleted_survives_location_change(self):
        item = InventoryItem.objects.create(product=self.product, location=self.loc_a)
        item.status = InventoryItem.Status.DEPLETED
        item.save()
        item = InventoryItem.objects.get(pk=item.pk)
        item.location = self.loc_b
        item.save()
        item.refresh_from_db()
        self.assertEqual(item.status, InventoryItem.Status.DEPLETED)


class LocationModelTests(TestCase):
    def test_assignable_excludes_containers(self):
        rack = Location.objects.create(name="Rack X", kind=Location.Kind.RACK)
        shelf = Location.objects.create(
            name="Rack X / Shelf 1",
            kind=Location.Kind.SHELF,
            parent=rack,
            default_status=InventoryItem.Status.NEW,
        )
        assignable = list(Location.assignable())
        self.assertIn(shelf, assignable)
        self.assertNotIn(rack, assignable)

    def test_drying_warning_uses_kind(self):
        mat = Material.objects.create(
            name="PLA", material_type="", drying_required=True
        )
        fil = Filament.objects.create(name="PLA Wet", upc="9200000000001", material=mat)
        item = InventoryItem.objects.create(product=fil)
        item.status = InventoryItem.Status.NEW
        dry = Location.objects.create(
            name="DryZone",
            kind=Location.Kind.DRY_STORAGE,
            default_status=InventoryItem.Status.STORED,
        )
        printer = Location.objects.create(
            name="P1",
            kind=Location.Kind.PRINTER,
            default_status=InventoryItem.Status.IN_USE,
        )
        self.assertEqual(item.filament_drying_warning(dry)[0], "error")
        self.assertEqual(item.filament_drying_warning(printer)[0], "warning")


class AuditReconcileTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="auditor", password="pass")
        self.shelf_a = Location.objects.create(
            name="A1", kind=Location.Kind.SHELF, default_status=InventoryItem.Status.NEW
        )
        self.shelf_b = Location.objects.create(
            name="B1",
            kind=Location.Kind.DRY_STORAGE,
            default_status=InventoryItem.Status.STORED,
        )
        self.product = Filament.objects.create(name="PLA Audit", upc="9300000000001")

    def _item(self, location):
        return InventoryItem.objects.create(product=self.product, location=location)

    def test_single_active_session(self):
        audit.start_session(self.user)
        with self.assertRaises(audit.AuditError):
            audit.start_session(self.user)

    def test_present_then_close_does_not_flag(self):
        session = audit.start_session(self.user)
        item = self._item(self.shelf_a)
        audit.visit_location(session, self.shelf_a)
        action = audit.scan_item(session, self.shelf_a, item)
        self.assertEqual(action, AuditEvent.Action.SCANNED_PRESENT)
        audit.close_location(session, self.shelf_a)
        item.refresh_from_db()
        self.assertEqual(item.status, InventoryItem.Status.NEW)
        self.assertEqual(item.location_id, self.shelf_a.id)

    def test_unscanned_flagged_unknown_keeps_location(self):
        session = audit.start_session(self.user)
        item = self._item(self.shelf_a)
        audit.visit_location(session, self.shelf_a)
        audit.close_location(session, self.shelf_a)
        item.refresh_from_db()
        self.assertEqual(item.status, InventoryItem.Status.UNKNOWN)
        self.assertEqual(item.location_id, self.shelf_a.id)

    def test_move_updates_location_and_status(self):
        session = audit.start_session(self.user)
        item = self._item(self.shelf_a)
        audit.visit_location(session, self.shelf_b)
        action = audit.scan_item(session, self.shelf_b, item)
        self.assertEqual(action, AuditEvent.Action.MOVED_IN)
        item.refresh_from_db()
        self.assertEqual(item.location_id, self.shelf_b.id)
        self.assertEqual(item.status, InventoryItem.Status.STORED)

    def test_revive_clears_date_depleted(self):
        session = audit.start_session(self.user)
        item = self._item(self.shelf_a)
        item.mark_depleted()
        item.save()
        item.refresh_from_db()
        self.assertIsNotNone(item.date_depleted)
        audit.visit_location(session, self.shelf_b)
        action = audit.scan_item(session, self.shelf_b, item)
        self.assertEqual(action, AuditEvent.Action.REVIVED)
        item.refresh_from_db()
        self.assertIsNone(item.date_depleted)
        self.assertEqual(item.location_id, self.shelf_b.id)
        self.assertEqual(item.status, InventoryItem.Status.STORED)

    def test_unit_item_rejected(self):
        session = audit.start_session(self.user)
        ams_product = AMS.objects.create(name="AMS Unit", upc="9400000000001")
        unit_item = InventoryItem.objects.create(product=ams_product)
        audit.visit_location(session, self.shelf_a)
        with self.assertRaises(audit.AuditError):
            audit.scan_item(session, self.shelf_a, unit_item)

    def test_finalize_closes_last_location_and_depletes(self):
        session = audit.start_session(self.user)
        item = self._item(self.shelf_a)
        audit.visit_location(session, self.shelf_a)  # not closed yet
        depleted = audit.finalize(session, active_location=self.shelf_a)
        self.assertEqual(len(depleted), 1)
        item.refresh_from_db()
        self.assertEqual(item.status, InventoryItem.Status.DEPLETED)
        self.assertIsNone(item.location)
        session.refresh_from_db()
        self.assertEqual(session.state, AuditSession.State.FINALIZED)


class SeedLocationsCommandTests(TestCase):
    def test_seed_counts_and_idempotent(self):
        from django.core.management import call_command

        call_command("seed_locations", verbosity=0)
        self.assertEqual(
            Location.objects.filter(kind=Location.Kind.AMS_SLOT).count(), 32
        )
        self.assertEqual(
            Location.objects.filter(kind=Location.Kind.DRYER_SLOT).count(), 12
        )
        self.assertEqual(Location.objects.filter(kind=Location.Kind.SHELF).count(), 10)
        total = Location.objects.count()
        call_command("seed_locations", verbosity=0)
        self.assertEqual(Location.objects.count(), total)  # no duplicates


class AuditViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        User.objects.create_user(username="v", password="pass")
        self.client.login(username="v", password="pass")
        self.shelf = Location.objects.create(
            name="V1", kind=Location.Kind.SHELF, default_status=InventoryItem.Status.NEW
        )
        self.product = Filament.objects.create(name="PLA View", upc="9500000000001")

    def test_console_without_session(self):
        self.assertEqual(self.client.get(reverse("audit_console")).status_code, 200)

    def test_full_flow(self):
        item = InventoryItem.objects.create(product=self.product, location=self.shelf)
        missing = InventoryItem.objects.create(
            product=self.product, location=self.shelf
        )
        self.client.post(reverse("audit_start"))
        # Scan the location, then one of the two items.
        self.client.post(reverse("audit_scan"), {"code": f"LOC-{self.shelf.pk}"})
        self.client.post(reverse("audit_scan"), {"code": f"INV-{item.pk}"})
        # Review (closes the location) then finalize.
        self.assertEqual(self.client.get(reverse("audit_finalize")).status_code, 200)
        self.client.post(reverse("audit_finalize"))
        item.refresh_from_db()
        missing.refresh_from_db()
        self.assertNotEqual(item.status, InventoryItem.Status.DEPLETED)
        self.assertEqual(missing.status, InventoryItem.Status.DEPLETED)


class AuditUnknownScanModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="uq", password="pass")
        self.loc = Location.objects.create(
            name="Q1",
            kind=Location.Kind.SHELF,
            default_status=InventoryItem.Status.NEW,
        )

    def test_create_and_defaults(self):
        session = AuditSession.objects.create(user=self.user)
        scan = AuditUnknownScan.objects.create(
            session=session, upc="111222333444", location=self.loc
        )
        self.assertFalse(scan.resolved)
        self.assertFalse(scan.dismissed)
        self.assertIsNone(scan.resolved_item)
        self.assertIsNotNone(scan.created_at)

    def test_added_action_exists(self):
        self.assertEqual(AuditEvent.Action.ADDED, "added")

    def test_open_duplicate_blocked(self):
        from django.db import IntegrityError, transaction

        session = AuditSession.objects.create(user=self.user)
        AuditUnknownScan.objects.create(
            session=session, upc="111222333444", location=self.loc
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AuditUnknownScan.objects.create(
                    session=session, upc="111222333444", location=self.loc
                )

    def test_resolved_duplicate_allowed(self):
        session = AuditSession.objects.create(user=self.user)
        first = AuditUnknownScan.objects.create(
            session=session, upc="111222333444", location=self.loc
        )
        first.resolved = True
        first.save(update_fields=["resolved"])
        # A new open row for the same key is fine once the prior is resolved.
        AuditUnknownScan.objects.create(
            session=session, upc="111222333444", location=self.loc
        )
        self.assertEqual(AuditUnknownScan.objects.filter(upc="111222333444").count(), 2)


class AuditAddOrQueueTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="aq", password="pass")
        self.shelf = Location.objects.create(
            name="AQ1",
            kind=Location.Kind.SHELF,
            default_status=InventoryItem.Status.NEW,
        )
        self.rack = Location.objects.create(name="Rack", kind=Location.Kind.RACK)
        self.product = Filament.objects.create(name="PLA Q", upc="600000000001")

    def test_parse_code_upc(self):
        self.assertEqual(audit.parse_code("600000000001"), ("upc", "600000000001"))
        self.assertEqual(audit.parse_code("LOC-5"), ("loc", 5))
        self.assertEqual(audit.parse_code("INV-12"), ("item", 12))
        with self.assertRaises(audit.AuditError):
            audit.parse_code("not-a-code")

    def test_in_catalog_creates_item_present_immune(self):
        session = audit.start_session(self.user)
        outcome, obj = audit.add_or_queue_upc(session, self.shelf, "600000000001")
        self.assertEqual(outcome, "added")
        self.assertEqual(obj.product_id, self.product.id)
        self.assertEqual(obj.location_id, self.shelf.id)
        self.assertTrue(
            AuditEvent.objects.filter(
                session=session, item=obj, action=AuditEvent.Action.ADDED
            ).exists()
        )
        # Present-immune: closing the location must NOT flag the just-added item.
        audit.close_location(session, self.shelf)
        obj.refresh_from_db()
        self.assertNotEqual(obj.status, InventoryItem.Status.UNKNOWN)

    def test_unknown_upc_queues(self):
        session = audit.start_session(self.user)
        outcome, obj = audit.add_or_queue_upc(session, self.shelf, "999888777666")
        self.assertEqual(outcome, "queued")
        self.assertEqual(obj.upc, "999888777666")
        self.assertEqual(obj.location_id, self.shelf.id)
        self.assertFalse(obj.resolved)

    def test_unknown_upc_dedup(self):
        session = audit.start_session(self.user)
        audit.add_or_queue_upc(session, self.shelf, "999888777666")
        audit.add_or_queue_upc(session, self.shelf, "999888777666")
        self.assertEqual(
            AuditUnknownScan.objects.filter(
                session=session, upc="999888777666", location=self.shelf
            ).count(),
            1,
        )

    def test_no_active_location_raises(self):
        session = audit.start_session(self.user)
        with self.assertRaises(audit.AuditError):
            audit.add_or_queue_upc(session, None, "600000000001")

    def test_container_location_raises(self):
        session = audit.start_session(self.user)
        with self.assertRaises(audit.AuditError):
            audit.add_or_queue_upc(session, self.rack, "600000000001")


@override_settings(ENABLE_BARCODE_PRINTING=False)
class AuditScanUpcViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        User.objects.create_user(username="su", password="pass")
        self.client.login(username="su", password="pass")
        self.shelf = Location.objects.create(
            name="SU1",
            kind=Location.Kind.SHELF,
            default_status=InventoryItem.Status.NEW,
        )
        self.product = Filament.objects.create(name="PLA SU", upc="700000000001")
        self.client.post(reverse("audit_start"))
        self.client.post(reverse("audit_scan"), {"code": f"LOC-{self.shelf.pk}"})

    def test_scan_in_catalog_upc_creates_item(self):
        before = InventoryItem.objects.count()
        resp = self.client.post(
            reverse("audit_scan"),
            {"code": "700000000001"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(InventoryItem.objects.count(), before + 1)
        new_item = InventoryItem.objects.latest("id")
        self.assertEqual(new_item.location_id, self.shelf.id)
        self.assertEqual(new_item.product_id, self.product.id)
        self.assertTrue(
            AuditEvent.objects.filter(
                item=new_item, action=AuditEvent.Action.ADDED
            ).exists()
        )

    def test_scan_unknown_upc_queues(self):
        resp = self.client.post(
            reverse("audit_scan"),
            {"code": "123123123123"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(AuditUnknownScan.objects.filter(upc="123123123123").count(), 1)


class AuditUnknownsPageTests(TestCase):
    def setUp(self):
        self.client = Client()
        User.objects.create_user(username="up", password="pass")
        self.client.login(username="up", password="pass")
        self.loc = Location.objects.create(
            name="UP1",
            kind=Location.Kind.SHELF,
            default_status=InventoryItem.Status.NEW,
        )
        self.session = AuditSession.objects.create()
        self.scan = AuditUnknownScan.objects.create(
            session=self.session, upc="555000111000", location=self.loc
        )

    def test_list_shows_open_only(self):
        AuditUnknownScan.objects.create(
            session=self.session,
            upc="DISMISSEDROW999",
            location=self.loc,
            resolved=True,
        )
        resp = self.client.get(reverse("audit_unknowns"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "555000111000")
        self.assertNotContains(resp, "DISMISSEDROW999")

    def test_dismiss_hides(self):
        self.client.post(reverse("audit_unknown_dismiss", args=[self.scan.pk]))
        self.scan.refresh_from_db()
        self.assertTrue(self.scan.dismissed)

    def test_resolve_sets_pending_inventory(self):
        resp = self.client.post(reverse("audit_unknown_resolve", args=[self.scan.pk]))
        self.assertEqual(resp.status_code, 302)
        pending = self.client.session["pending_inventory"]
        self.assertEqual(pending["upc"], "555000111000")
        self.assertEqual(pending["location_id"], self.loc.id)
        self.assertEqual(pending["unknown_scan_id"], self.scan.id)


class AuditResolveLoopTests(TestCase):
    def setUp(self):
        self.client = Client()
        User.objects.create_user(username="rl", password="pass")
        self.client.login(username="rl", password="pass")
        self.loc = Location.objects.create(
            name="RL1",
            kind=Location.Kind.SHELF,
            default_status=InventoryItem.Status.NEW,
        )
        self.session = AuditSession.objects.create()
        self.scan = AuditUnknownScan.objects.create(
            session=self.session, upc="800000000001", location=self.loc
        )

    def test_in_catalog_add_marks_resolved(self):
        # Product now exists in the catalog (added since the scan).
        Filament.objects.create(name="PLA RL", upc="800000000001")
        # Resolve handoff stashes pending_inventory incl. unknown_scan_id.
        self.client.post(reverse("audit_unknown_resolve", args=[self.scan.pk]))
        # The matched-product path of AddInventoryView creates the item.
        self.client.post(reverse("add_inventory"), {"upc": "800000000001"})
        self.scan.refresh_from_db()
        self.assertTrue(self.scan.resolved)
        self.assertIsNotNone(self.scan.resolved_item)
        self.assertEqual(self.scan.resolved_item.product.upc, "800000000001")

    def test_new_product_path_marks_resolved(self):
        """AddFilamentView form_valid with ?from_inventory=1 must mark the scan
        resolved and link resolved_item to the new inventory item."""
        scan2 = AuditUnknownScan.objects.create(
            session=self.session, upc="810000000002", location=self.loc
        )
        session = self.client.session
        session["pending_inventory"] = {
            "upc": "810000000002",
            "sku": "",
            "shipment": None,
            "location_id": self.loc.id,
            "unknown_scan_id": scan2.id,
        }
        session.save()
        resp = self.client.post(
            reverse("add_filament") + "?from_inventory=1",
            {
                "name": "PLA New",
                "upc": "810000000002",
                # All other FilamentForm fields are blank=True / null=True
            },
        )
        # Should redirect on success; if 200 the form had errors
        if resp.status_code == 200 and "form" in resp.context:
            self.fail(f"Form invalid: {resp.context['form'].errors}")
        scan2.refresh_from_db()
        self.assertTrue(scan2.resolved)
        self.assertIsNotNone(scan2.resolved_item)
        self.assertEqual(scan2.resolved_item.product.upc, "810000000002")


@override_settings(ENABLE_BARCODE_PRINTING=False)
class AuditUiSurfaceTests(TestCase):
    def setUp(self):
        self.client = Client()
        User.objects.create_user(username="ui", password="pass")
        self.client.login(username="ui", password="pass")
        self.loc = Location.objects.create(
            name="UI1",
            kind=Location.Kind.SHELF,
            default_status=InventoryItem.Status.NEW,
        )

    def test_finalize_notes_queued_unknowns(self):
        self.client.post(reverse("audit_start"))
        session = AuditSession.active()
        AuditUnknownScan.objects.create(
            session=session, upc="900000000001", location=self.loc
        )
        resp = self.client.get(reverse("audit_finalize"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "audit/unknowns")
        self.assertContains(resp, "1 unknown UPC")

    def test_body_shows_added_card(self):
        Filament.objects.create(name="PLA UI", upc="900000000777")
        self.client.post(reverse("audit_start"))
        self.client.post(reverse("audit_scan"), {"code": f"LOC-{self.loc.pk}"})
        before = InventoryItem.objects.count()
        resp = self.client.post(
            reverse("audit_scan"),
            {"code": "900000000777"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Added")
        # The scan actually added an item and logged an ADDED event.
        self.assertEqual(InventoryItem.objects.count(), before + 1)
        self.assertTrue(
            AuditEvent.objects.filter(action=AuditEvent.Action.ADDED).exists()
        )


class AuditWholeUnitTests(TestCase):
    """Scanning a unit serial focuses the whole container; reconcile spans slots."""

    def setUp(self):
        self.user = User.objects.create_user(username="wu", password="pass")
        self.ams_container = Location.objects.create(
            name="AMS 1", kind=Location.Kind.AMS
        )
        self.slot1 = Location.objects.create(
            name="AMS 1 / Slot 1",
            kind=Location.Kind.AMS_SLOT,
            parent=self.ams_container,
            slot_index=1,
            default_status=InventoryItem.Status.IN_USE,
        )
        self.slot2 = Location.objects.create(
            name="AMS 1 / Slot 2",
            kind=Location.Kind.AMS_SLOT,
            parent=self.ams_container,
            slot_index=2,
            default_status=InventoryItem.Status.IN_USE,
        )
        self.product = Filament.objects.create(name="PLA WU", upc="9600000000001")
        # The physical AMS unit, linked to its slots via Location.unit.
        ams_product = AMS.objects.create(name="AMS Phys", upc="9600000000099")
        self.unit_item = InventoryItem.objects.create(
            product=ams_product, serial_number="AMSER123"
        )
        self.slot1.unit = self.unit_item
        self.slot2.unit = self.unit_item
        self.slot1.save()
        self.slot2.save()

    def test_focus_leaves_expands_container(self):
        leaves = audit.focus_leaves(self.ams_container)
        self.assertEqual([leaf.id for leaf in leaves], [self.slot1.id, self.slot2.id])

    def test_resolve_serial_returns_container(self):
        self.assertEqual(audit.resolve_serial("AMSER123").id, self.ams_container.id)

    def test_resolve_serial_case_insensitive(self):
        self.assertEqual(audit.resolve_serial("amser123").id, self.ams_container.id)

    def test_resolve_serial_unknown_raises(self):
        with self.assertRaises(audit.AuditError):
            audit.resolve_serial("NOPE")

    def test_present_across_slots_not_flagged(self):
        item1 = InventoryItem.objects.create(product=self.product, location=self.slot1)
        item2 = InventoryItem.objects.create(product=self.product, location=self.slot2)
        session = audit.start_session(self.user)
        audit.visit_location(session, self.ams_container)
        self.assertEqual(
            audit.scan_item(session, self.ams_container, item1),
            AuditEvent.Action.SCANNED_PRESENT,
        )
        self.assertEqual(
            audit.scan_item(session, self.ams_container, item2),
            AuditEvent.Action.SCANNED_PRESENT,
        )
        audit.close_location(session, self.ams_container)
        item1.refresh_from_db()
        item2.refresh_from_db()
        self.assertEqual(item1.status, InventoryItem.Status.IN_USE)
        self.assertEqual(item2.status, InventoryItem.Status.IN_USE)

    def test_unscanned_slot_item_flagged_on_close(self):
        item1 = InventoryItem.objects.create(product=self.product, location=self.slot1)
        item2 = InventoryItem.objects.create(product=self.product, location=self.slot2)
        session = audit.start_session(self.user)
        audit.visit_location(session, self.ams_container)
        audit.scan_item(session, self.ams_container, item1)  # only slot 1 scanned
        flagged = audit.close_location(session, self.ams_container)
        self.assertEqual([f.id for f in flagged], [item2.id])
        item2.refresh_from_db()
        self.assertEqual(item2.status, InventoryItem.Status.UNKNOWN)
        self.assertEqual(item2.location_id, self.slot2.id)

    def test_move_into_unit_lands_in_first_slot(self):
        other = Location.objects.create(
            name="Other",
            kind=Location.Kind.SHELF,
            default_status=InventoryItem.Status.NEW,
        )
        item = InventoryItem.objects.create(product=self.product, location=other)
        session = audit.start_session(self.user)
        audit.visit_location(session, self.ams_container)
        action = audit.scan_item(session, self.ams_container, item)
        self.assertEqual(action, AuditEvent.Action.MOVED_IN)
        item.refresh_from_db()
        self.assertEqual(item.location_id, self.slot1.id)


class AuditUndoAddTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ua", password="pass")
        self.shelf = Location.objects.create(
            name="UA1",
            kind=Location.Kind.SHELF,
            default_status=InventoryItem.Status.NEW,
        )
        self.product = Filament.objects.create(name="PLA UA", upc="9700000000001")

    def test_undo_added_deletes_item(self):
        session = audit.start_session(self.user)
        _, item = audit.add_or_queue_upc(session, self.shelf, "9700000000001")
        item_id = item.id
        self.assertTrue(audit.undo_added(session, item))
        self.assertFalse(InventoryItem.objects.filter(id=item_id).exists())

    def test_undo_non_added_rejected(self):
        session = audit.start_session(self.user)
        normal = InventoryItem.objects.create(product=self.product, location=self.shelf)
        with self.assertRaises(audit.AuditError):
            audit.undo_added(session, normal)
        self.assertTrue(InventoryItem.objects.filter(id=normal.id).exists())


@override_settings(ENABLE_BARCODE_PRINTING=False)
class AuditUndoAddViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        User.objects.create_user(username="uav", password="pass")
        self.client.login(username="uav", password="pass")
        self.shelf = Location.objects.create(
            name="UAV1",
            kind=Location.Kind.SHELF,
            default_status=InventoryItem.Status.NEW,
        )
        self.product = Filament.objects.create(name="PLA UAV", upc="9800000000001")
        self.client.post(reverse("audit_start"))
        self.client.post(reverse("audit_scan"), {"code": f"LOC-{self.shelf.pk}"})

    def test_undo_view_removes_item(self):
        self.client.post(reverse("audit_scan"), {"code": "9800000000001"})
        item = InventoryItem.objects.latest("id")
        resp = self.client.post(
            reverse("audit_undo_add", args=[item.pk]), HTTP_HX_REQUEST="true"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(InventoryItem.objects.filter(id=item.pk).exists())


class AuditFinalizeKeepUnknownTests(TestCase):
    def setUp(self):
        self.client = Client()
        User.objects.create_user(username="fk", password="pass")
        self.client.login(username="fk", password="pass")
        self.shelf = Location.objects.create(
            name="FK1",
            kind=Location.Kind.SHELF,
            default_status=InventoryItem.Status.NEW,
        )
        self.product = Filament.objects.create(name="PLA FK", upc="9900000000001")

    def test_keep_unknown_skips_deplete(self):
        keep = InventoryItem.objects.create(product=self.product, location=self.shelf)
        drop = InventoryItem.objects.create(product=self.product, location=self.shelf)
        self.client.post(reverse("audit_start"))
        self.client.post(reverse("audit_scan"), {"code": f"LOC-{self.shelf.pk}"})
        # Close so both become UNKNOWN, then finalize keeping one.
        self.client.post(reverse("audit_close_location"))
        self.client.post(reverse("audit_finalize"), {"keep_unknown": [keep.pk]})
        keep.refresh_from_db()
        drop.refresh_from_db()
        self.assertEqual(keep.status, InventoryItem.Status.UNKNOWN)
        self.assertEqual(drop.status, InventoryItem.Status.DEPLETED)


@override_settings(ENABLE_BARCODE_PRINTING=False)
class BulkReprintLabelsTests(TestCase):
    def setUp(self):
        self.client = Client()
        User.objects.create_user(username="br", password="pass")
        self.client.login(username="br", password="pass")
        self.shelf = Location.objects.create(
            name="BR1",
            kind=Location.Kind.SHELF,
            default_status=InventoryItem.Status.NEW,
        )
        self.product = Filament.objects.create(name="PLA BR", upc="1100000000001")

    def test_reprint_selected_items(self):
        i1 = InventoryItem.objects.create(product=self.product, location=self.shelf)
        i2 = InventoryItem.objects.create(product=self.product, location=self.shelf)
        resp = self.client.post(
            reverse("bulk_reprint_labels"),
            {"item_ids": [i1.pk, i2.pk]},
        )
        self.assertEqual(resp.status_code, 302)  # redirect back to search
        # Both items still exist; reprint is non-destructive.
        self.assertEqual(InventoryItem.objects.count(), 2)

    def test_reprint_no_selection_warns(self):
        resp = self.client.post(reverse("bulk_reprint_labels"), {})
        self.assertEqual(resp.status_code, 302)


class LocationAdminUnitFieldTests(TestCase):
    """The slot->unit picker must be selectable by serial number.

    Regression: ``unit`` used an autocomplete that rendered every option as
    ``InventoryItem.__str__`` (product UPC + date) and searched only UPC/name,
    so multiple physical units sharing one product UPC were indistinguishable
    and could not be searched by serial number.
    """

    def setUp(self):
        from django.test import RequestFactory

        self.factory = RequestFactory()
        self.user = User.objects.create_superuser("uadmin", "u@a.co", "pass")
        self.filament_item = InventoryItem.objects.create(
            product=Filament.objects.create(name="PLA", upc="1000000000001"),
        )
        self.ams_item = InventoryItem.objects.create(
            product=AMS.objects.create(name="AMS Phys", upc="1000000000099"),
            serial_number="SD-1",
        )

    def _unit_formfield(self):
        from django.contrib.admin.sites import AdminSite

        from .admin import LocationAdmin

        admin_obj = LocationAdmin(Location, AdminSite())
        request = self.factory.get("/")
        request.user = self.user
        return admin_obj.formfield_for_foreignkey(
            Location._meta.get_field("unit"), request
        )

    def test_unit_queryset_limited_to_physical_units(self):
        qs = self._unit_formfield().queryset
        ids = set(qs.values_list("id", flat=True))
        self.assertIn(self.ams_item.id, ids)
        self.assertNotIn(self.filament_item.id, ids)

    def test_unit_label_shows_serial_number(self):
        label = self._unit_formfield().label_from_instance(self.ams_item)
        self.assertIn("SD-1", label)


class SearchBulkActionWiringTests(TestCase):
    """Guard the search-page bulk-action client wiring.

    Regression (Reprint tags / Apply silently no-op'd with "No items selected"):
    the DataTables init passed ``columns: [{title: ...}]``. DataTables overwrites
    each header cell's HTML with the ``title`` string, and column 0's title was
    ``""`` -- which destroyed the ``<input id="select-all">`` checkbox in the
    header. The inline script then hit ``getElementById('select-all')`` (null),
    threw, and aborted *before* attaching the form ``submit`` listener that
    injects the selected ``item_ids``. Row selection still worked (its listener
    attaches earlier), so the bar showed a count but every submit posted empty.

    Fix: use ``columnDefs`` (sets orderable/searchable without rewriting the
    header), keeping the select-all checkbox intact. These assertions fail if the
    header-overwriting ``title`` config is reintroduced.
    """

    def setUp(self):
        self.client = Client()
        User.objects.create_user(username="searcher", password="pass")
        self.client.login(username="searcher", password="pass")

    def test_search_page_preserves_select_all_and_avoids_title_overwrite(self):
        html = self.client.get(reverse("inventory_search")).content.decode()
        # The header select-all checkbox must be server-rendered ...
        self.assertIn('id="select-all"', html)
        # ... and the DataTables config must not overwrite headers (which would
        # delete that checkbox). columnDefs sets flags without touching headers.
        self.assertIn("columnDefs", html)
        self.assertNotIn(
            "{title:",
            html,
            msg="DataTables per-column `title` overwrites the header and deletes "
            "the #select-all checkbox -> submit handler never attaches. Use "
            "columnDefs instead.",
        )


class FilamentColorGuideCountTests(TestCase):
    """The `/filament-color-guide/` header must count spools (inventory items),
    not distinct color/SKU rows.

    Regression: the view set ``total_filaments = len(filaments)`` -- the number
    of distinct Filament rows with active stock -- so the "N spools on hand"
    header under-reported (e.g. 165 vs the Dashboard's 478 actual spools).
    """

    def setUp(self):
        self.client = Client()
        User.objects.create_user(username="cg", password="pass")
        self.client.login(username="cg", password="pass")
        mat = Material.objects.create(name="PLA", material_type="")
        red = Filament.objects.create(
            name="PLA Red",
            upc="7000000000001",
            material=mat,
            color="Red",
            color_family="RED",
            weight=1.0,
        )
        blue = Filament.objects.create(
            name="PLA Blue",
            upc="7000000000002",
            material=mat,
            color="Blue",
            color_family="BLUE",
            weight=1.0,
        )
        # 5 spools total across 2 distinct filaments (default status NEW = active)
        for _ in range(3):
            InventoryItem.objects.create(product=red)
        for _ in range(2):
            InventoryItem.objects.create(product=blue)

    def test_header_counts_spools_not_distinct_filaments(self):
        resp = self.client.get(reverse("filament_color_guide"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["total_spools"], 5)
        self.assertContains(resp, "5 spools on hand")


class PrinterReachabilityTests(TestCase):
    """Printing must fail fast when the label printer is offline, instead of
    blocking the request on the OS socket timeout (the "Add inventory appears
    frozen" report).
    """

    def setUp(self):
        from PIL import Image

        self.img = Image.new("L", (10, 10), 255)

    def test_host_port_parsing(self):
        from .barcode_utils import BROTHER_QL_PORT, _printer_host_port

        self.assertEqual(
            _printer_host_port("10.10.40.2"), ("10.10.40.2", BROTHER_QL_PORT)
        )
        self.assertEqual(
            _printer_host_port("tcp://10.10.40.2"), ("10.10.40.2", BROTHER_QL_PORT)
        )
        self.assertEqual(_printer_host_port("10.10.40.2:9999"), ("10.10.40.2", 9999))

    def test_reachable_false_on_connection_error(self):
        from unittest.mock import patch

        from . import barcode_utils

        with patch(
            "inventory.barcode_utils.socket.create_connection", side_effect=OSError
        ):
            self.assertFalse(barcode_utils._printer_reachable())

    def test_reachable_true_on_success(self):
        from unittest.mock import MagicMock, patch

        from . import barcode_utils

        with patch(
            "inventory.barcode_utils.socket.create_connection", return_value=MagicMock()
        ):
            self.assertTrue(barcode_utils._printer_reachable())

    def test_print_label_image_raises_fast_when_unreachable(self):
        from unittest.mock import patch

        from . import barcode_utils

        with patch(
            "inventory.barcode_utils._printer_reachable", return_value=False
        ), patch("inventory.barcode_utils.convert") as mock_convert:
            with self.assertRaises(barcode_utils.PrinterUnreachableError):
                barcode_utils.print_label_image(self.img)
        # Must bail out before doing any conversion / network work.
        mock_convert.assert_not_called()

    def test_print_label_image_prints_when_reachable(self):
        from unittest.mock import MagicMock, patch

        from . import barcode_utils

        backend = MagicMock()
        with patch(
            "inventory.barcode_utils._printer_reachable", return_value=True
        ), patch(
            "inventory.barcode_utils.convert", return_value=b"instructions"
        ), patch(
            "inventory.barcode_utils._get_backend", return_value=backend
        ):
            barcode_utils.print_label_image(self.img)
        backend.write.assert_called_once_with(b"instructions")

    @override_settings(ENABLE_BARCODE_PRINTING=True)
    def test_generate_and_print_label_fails_fast_end_to_end(self):
        from unittest.mock import patch

        from . import barcode_utils

        with patch("inventory.barcode_utils._printer_reachable", return_value=False):
            with self.assertRaises(barcode_utils.PrinterUnreachableError):
                barcode_utils.generate_and_print_label("INV-1")


class HierarchicalLocationSearchTests(TestCase):
    """Searching a container location returns items in all of its child
    locations (and supports a typed LOC-<id>), per the audit/search request.
    """

    def setUp(self):
        self.client = Client()
        User.objects.create_user(username="ls", password="pass")
        self.client.login(username="ls", password="pass")

        K = Location.Kind
        self.rack = Location.objects.create(name="Rack RP-1", kind=K.RACK)
        self.shelf1 = Location.objects.create(
            name="Shelf One", kind=K.SHELF, parent=self.rack
        )
        self.shelf2 = Location.objects.create(
            name="Shelf Two", kind=K.SHELF, parent=self.rack
        )
        self.ams = Location.objects.create(name="AMS RP-1", kind=K.AMS)
        self.slot1 = Location.objects.create(
            name="Bay Alpha", kind=K.AMS_SLOT, parent=self.ams
        )
        self.slot2 = Location.objects.create(
            name="Bay Beta", kind=K.AMS_SLOT, parent=self.ams
        )
        self.dry = Location.objects.create(name="Dry Box", kind=K.DRY_STORAGE)

        prod = Filament.objects.create(name="PLA Zed", upc="8000000000001")
        self.i_shelf1 = InventoryItem.objects.create(product=prod, location=self.shelf1)
        self.i_shelf2 = InventoryItem.objects.create(product=prod, location=self.shelf2)
        self.i_slot1 = InventoryItem.objects.create(product=prod, location=self.slot1)
        self.i_slot2 = InventoryItem.objects.create(product=prod, location=self.slot2)
        self.i_dry = InventoryItem.objects.create(product=prod, location=self.dry)

    def _ids(self, resp):
        return {i.id for i in resp.context["items"]}

    def test_descendant_ids(self):
        self.assertEqual(
            self.rack.descendant_ids(), {self.rack.id, self.shelf1.id, self.shelf2.id}
        )
        self.assertEqual(
            self.ams.descendant_ids(), {self.ams.id, self.slot1.id, self.slot2.id}
        )
        self.assertEqual(self.dry.descendant_ids(), {self.dry.id})

    def test_explicit_location_filter_expands_container_to_children(self):
        resp = self.client.get(reverse("inventory_search"), {"location": "AMS RP-1"})
        self.assertEqual(self._ids(resp), {self.i_slot1.id, self.i_slot2.id})

    def test_explicit_location_filter_by_loc_id(self):
        resp = self.client.get(
            reverse("inventory_search"), {"location": f"LOC-{self.rack.id}"}
        )
        self.assertEqual(self._ids(resp), {self.i_shelf1.id, self.i_shelf2.id})

    def test_navbar_search_expands_container_to_children(self):
        resp = self.client.get(reverse("inventory_search"), {"name": "Rack RP-1"})
        self.assertEqual(self._ids(resp), {self.i_shelf1.id, self.i_shelf2.id})

    def test_leaf_location_returns_only_that_leaf(self):
        resp = self.client.get(reverse("inventory_search"), {"location": "Bay Alpha"})
        self.assertEqual(self._ids(resp), {self.i_slot1.id})

    def test_unknown_location_returns_nothing(self):
        resp = self.client.get(reverse("inventory_search"), {"location": "Nowhere"})
        self.assertEqual(self._ids(resp), set())
