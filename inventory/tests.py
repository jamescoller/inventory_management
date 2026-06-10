from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.timezone import now as timezone_now

from . import items, printjobs
from .models import (
    AMS,
    AuditSession,
    AuditUnknownScan,
    Dryer,
    Filament,
    Hardware,
    InventoryItem,
    Location,
    MaintenanceEvent,
    Material,
    NozzleConfig,
    Printer,
    PrintJob,
    PrintJobFilament,
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


@override_settings(ENABLE_BARCODE_PRINTING=False)
class FilamentHubTests(TestCase):
    """Phase 18.2: a hub ties the three filament pages together, the three
    standalone URLs keep working, and the inline JS now lives in static files
    loaded via {% static %} with server data passed through json_script."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="hubuser", password="pass")
        cls.mat = Material.objects.create(name="PLA", material_type="")
        cls.loc = Location.objects.create(
            name="Shelf", default_status=InventoryItem.Status.NEW
        )
        cls.fil = Filament.objects.create(
            name="PLA Black",
            upc="5000000000001",
            material=cls.mat,
            color="Black",
            color_family="BLACK",
        )
        InventoryItem.objects.create(product=cls.fil, location=cls.loc)

    def setUp(self):
        self.client = Client()
        self.client.login(username="hubuser", password="pass")

    def test_hub_renders_and_links_to_each_mode(self):
        resp = self.client.get(reverse("filament_hub"))
        self.assertEqual(resp.status_code, 200)
        for name in ("filament_summary", "filament_color_guide", "filament_guide"):
            self.assertContains(resp, reverse(name))

    def test_hub_requires_login(self):
        self.client.logout()
        resp = self.client.get(reverse("filament_hub"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp["Location"])

    def test_standalone_filament_urls_still_work(self):
        for name in (
            "filament_summary",
            "filament_color_guide",
            "filament_guide",
        ):
            resp = self.client.get(reverse(name))
            self.assertEqual(resp.status_code, 200, f"{name} -> {resp.status_code}")

    def test_each_page_carries_the_hub_tab_bar(self):
        """Every filament page links back to the hub via the shared tab bar."""
        hub_url = reverse("filament_hub")
        for name in (
            "filament_summary",
            "filament_color_guide",
            "filament_guide",
        ):
            resp = self.client.get(reverse(name))
            self.assertContains(resp, hub_url, msg_prefix=name)

    def test_summary_loads_external_js_not_inline(self):
        resp = self.client.get(reverse("filament_summary"))
        self.assertContains(resp, "inventory/js/filament_summary.js")
        # The old inline implementation defined applyFilters() in the page.
        self.assertNotContains(resp, "function applyFilters()")

    def test_summary_context_intact(self):
        resp = self.client.get(reverse("filament_summary"))
        for key in ("cards", "rows", "grand_total_rolls", "total_materials"):
            self.assertIn(key, resp.context)


@override_settings(ENABLE_BARCODE_PRINTING=False)
class DashboardJsExtractionTests(TestCase):
    """Dashboard inline JS moved to a static file; chart data flows through
    json_script blocks rather than being interpolated into a <script>."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="dashuser", password="pass")
        cls.mat = Material.objects.create(name="PLA", material_type="")
        cls.loc = Location.objects.create(
            name="Shelf", default_status=InventoryItem.Status.NEW
        )
        cls.fil = Filament.objects.create(
            name="PLA Black",
            upc="5100000000001",
            material=cls.mat,
            color="Black",
            color_family="BLACK",
        )
        InventoryItem.objects.create(product=cls.fil, location=cls.loc)

    def setUp(self):
        self.client = Client()
        self.client.login(username="dashuser", password="pass")

    def test_dashboard_loads_external_js(self):
        resp = self.client.get(reverse("dashboard"))
        self.assertContains(resp, "inventory/js/dashboard.js")

    def test_dashboard_exposes_chart_data_via_json_script(self):
        resp = self.client.get(reverse("dashboard"))
        for el_id in ("type-labels", "type-data", "color-colors"):
            self.assertContains(resp, f'id="{el_id}"')

    def test_dashboard_context_has_type_chart_data(self):
        resp = self.client.get(reverse("dashboard"))
        self.assertIn("type_chart_data", resp.context)
        data = resp.context["type_chart_data"]
        self.assertIn("labels", data)
        self.assertIn("data", data)


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

    def test_filament_guide(self):
        self._assert_ok("filament_guide")

    def test_filament_hub(self):
        self._assert_ok("filament_hub")

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


class LocationUnitValidationTests(TestCase):
    """``Location.unit`` may only point at a physical AMS/dryer/printer unit.

    Regression: a slot's ``unit`` FK was hand-linked to a filament roll's
    InventoryItem instead of the AMS unit. That made ``_is_unit_item`` treat the
    roll as a tracked container, so it could not be audited as slot contents.
    The admin picker queryset (PR #117) only filters rendered choices; this is
    the model-layer guard that also covers shell/bulk/migration writes.
    """

    def setUp(self):
        self.ams_item = InventoryItem.objects.create(
            product=AMS.objects.create(name="AMS Phys", upc="2000000000099"),
            serial_number="SD-9",
        )
        self.filament_item = InventoryItem.objects.create(
            product=Filament.objects.create(name="PLA WU", upc="2000000000001"),
        )

    def test_unit_pointing_at_filament_is_rejected(self):
        loc = Location(
            name="Bad Slot", kind=Location.Kind.AMS_SLOT, unit=self.filament_item
        )
        with self.assertRaises(ValidationError):
            loc.full_clean()

    def test_unit_pointing_at_physical_unit_is_allowed(self):
        loc = Location(
            name="Good Slot", kind=Location.Kind.AMS_SLOT, unit=self.ams_item
        )
        loc.full_clean()  # must not raise

    def test_unit_may_be_null(self):
        loc = Location(name="Empty Slot", kind=Location.Kind.AMS_SLOT)
        loc.full_clean()  # must not raise


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
        # ... and the DataTables/bulk JS must be loaded from the extracted static
        # module (Phase 11.2 extraction), not inlined.
        self.assertIn("inventory/js/inventory_search.js", html)

    def test_search_js_uses_columndefs_not_title_overwrite(self):
        """The extracted JS must keep the columnDefs invariant: a per-column
        `title:` in the `columns` option overwrites each header cell's HTML,
        deleting the #select-all checkbox so the submit handler never attaches.
        """
        import os

        from django.conf import settings

        js_path = os.path.join(
            settings.BASE_DIR,
            "inventory",
            "static",
            "inventory",
            "js",
            "inventory_search.js",
        )
        with open(js_path, encoding="utf-8") as fh:
            js = fh.read()
        self.assertIn("columnDefs", js)
        self.assertNotIn("{title:", js)


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

    def test_navbar_typed_loc_id_filters_not_redirects(self):
        """A typed LOC-<id> in the navbar search FILTERS results (expands the
        location's subtree); it does NOT redirect to the audit console. (Only a
        *scanned* LOC- barcode, via BarcodeRedirectView, jumps to the console.)
        """
        resp = self.client.get(
            reverse("inventory_search"), {"name": f"LOC-{self.rack.id}"}
        )
        self.assertEqual(resp.status_code, 200)  # filtered page, not a 302 redirect
        self.assertEqual(self._ids(resp), {self.i_shelf1.id, self.i_shelf2.id})

    def test_leaf_location_returns_only_that_leaf(self):
        resp = self.client.get(reverse("inventory_search"), {"location": "Bay Alpha"})
        self.assertEqual(self._ids(resp), {self.i_slot1.id})

    def test_unknown_location_returns_nothing(self):
        resp = self.client.get(reverse("inventory_search"), {"location": "Nowhere"})
        self.assertEqual(self._ids(resp), set())


class InventorySearchFilterTests(TestCase):
    """Phase 11.2 — the search page exposes real, working filters.

    The old view hardcoded ``exclude(status=5)`` and never read the template's
    ``status`` field, so DEPLETED/SOLD/UNKNOWN items were unfindable ("I can't
    find my lost items"). These tests pin the redone filter contract: multi-select
    status (incl. UNKNOWN/DEPLETED/SOLD), item-type, location subtree, date-added
    range, and the Lost & Found preset.
    """

    def setUp(self):
        self.client = Client()
        User.objects.create_user(username="sf", password="pass")
        self.client.login(username="sf", password="pass")

        K = Location.Kind
        self.rack = Location.objects.create(name="Rack S-1", kind=K.RACK)
        self.shelf = Location.objects.create(
            name="Shelf S-1", kind=K.SHELF, parent=self.rack
        )
        self.dry = Location.objects.create(name="Dry Box S", kind=K.DRY_STORAGE)

        fil = Filament.objects.create(name="PLA Find", upc="7100000000001")
        prn = Printer.objects.create(
            name="X1C Find",
            upc="7100000000002",
            num_extruders=1,
            bed_length_mm=256,
            bed_width_mm=256,
            max_height_mm=256,
        )
        ams = AMS.objects.create(name="AMS Find", upc="7100000000003")
        dry_p = Dryer.objects.create(name="Dryer Find", upc="7100000000004")
        hw = Hardware.objects.create(name="HW Find", upc="7100000000005")

        S = InventoryItem.Status
        # One item per status (filament) at the shelf
        self.i_new = InventoryItem.objects.create(
            product=fil, location=self.shelf, status=S.NEW
        )
        self.i_in_use = InventoryItem.objects.create(
            product=fil, location=self.shelf, status=S.IN_USE
        )
        self.i_depleted = InventoryItem.objects.create(
            product=fil, location=self.shelf, status=S.DEPLETED
        )
        self.i_sold = InventoryItem.objects.create(
            product=fil, location=self.shelf, status=S.SOLD
        )
        self.i_unknown = InventoryItem.objects.create(
            product=fil, location=self.shelf, status=S.UNKNOWN
        )
        # An UNKNOWN item with no location (a "retired/empty location" recovery case)
        self.i_unknown_nowhere = InventoryItem.objects.create(
            product=fil, location=None, status=S.UNKNOWN
        )
        # One item of each non-filament type at the dry box
        self.i_printer = InventoryItem.objects.create(product=prn, location=self.dry)
        self.i_ams = InventoryItem.objects.create(product=ams, location=self.dry)
        self.i_dryer = InventoryItem.objects.create(product=dry_p, location=self.dry)
        self.i_hardware = InventoryItem.objects.create(product=hw, location=self.dry)

    def _ids(self, resp):
        return {i.id for i in resp.context["items"]}

    # --- default view -------------------------------------------------------
    def test_default_view_hides_depleted_and_sold_but_keeps_unknown(self):
        """No status filter → hide DEPLETED/SOLD noise, but UNKNOWN stays visible."""
        resp = self.client.get(reverse("inventory_search"))
        ids = self._ids(resp)
        self.assertNotIn(self.i_depleted.id, ids)
        self.assertNotIn(self.i_sold.id, ids)
        self.assertIn(self.i_unknown.id, ids)
        self.assertIn(self.i_new.id, ids)

    # --- status (the bug) ---------------------------------------------------
    def test_status_filter_finds_depleted(self):
        resp = self.client.get(
            reverse("inventory_search"),
            {"status": str(int(InventoryItem.Status.DEPLETED))},
        )
        self.assertEqual(self._ids(resp), {self.i_depleted.id})

    def test_status_filter_finds_unknown(self):
        resp = self.client.get(
            reverse("inventory_search"),
            {"status": str(int(InventoryItem.Status.UNKNOWN))},
        )
        self.assertEqual(
            self._ids(resp), {self.i_unknown.id, self.i_unknown_nowhere.id}
        )

    def test_status_filter_is_multiselect(self):
        resp = self.client.get(
            reverse("inventory_search"),
            {
                "status": [
                    str(int(InventoryItem.Status.DEPLETED)),
                    str(int(InventoryItem.Status.SOLD)),
                ]
            },
        )
        self.assertEqual(self._ids(resp), {self.i_depleted.id, self.i_sold.id})

    def test_invalid_status_value_is_ignored(self):
        """A non-integer/garbage status must not 500; falls back to default view."""
        resp = self.client.get(reverse("inventory_search"), {"status": "banana"})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(self.i_depleted.id, self._ids(resp))

    # --- item type ----------------------------------------------------------
    def test_item_type_filter_filament(self):
        resp = self.client.get(reverse("inventory_search"), {"item_type": "filament"})
        ids = self._ids(resp)
        self.assertIn(self.i_new.id, ids)
        self.assertNotIn(self.i_printer.id, ids)

    def test_item_type_filter_printer(self):
        resp = self.client.get(reverse("inventory_search"), {"item_type": "printer"})
        self.assertEqual(self._ids(resp), {self.i_printer.id})

    def test_item_type_filter_multiselect(self):
        resp = self.client.get(
            reverse("inventory_search"), {"item_type": ["ams", "dryer"]}
        )
        self.assertEqual(self._ids(resp), {self.i_ams.id, self.i_dryer.id})

    # --- location subtree ---------------------------------------------------
    def test_location_subtree_expands_container(self):
        """Searching the rack returns items in its child shelf (active ones)."""
        resp = self.client.get(reverse("inventory_search"), {"location": "Rack S-1"})
        ids = self._ids(resp)
        self.assertIn(self.i_new.id, ids)  # on the shelf, a child of the rack
        self.assertNotIn(self.i_printer.id, ids)  # in the dry box, not under the rack

    # --- date range ---------------------------------------------------------
    def test_date_added_range(self):
        from datetime import timedelta

        from django.utils.timezone import now

        old = now() - timedelta(days=30)
        InventoryItem.objects.filter(pk=self.i_new.pk).update(date_added=old)
        today = now().date().isoformat()
        resp = self.client.get(reverse("inventory_search"), {"date_from": today})
        self.assertNotIn(self.i_new.id, self._ids(resp))

        cutoff = (now() - timedelta(days=15)).date().isoformat()
        resp = self.client.get(reverse("inventory_search"), {"date_to": cutoff})
        self.assertIn(self.i_new.id, self._ids(resp))
        self.assertNotIn(self.i_in_use.id, self._ids(resp))

    # --- Lost & Found preset ------------------------------------------------
    def test_lost_and_found_preset_returns_unknown_items(self):
        resp = self.client.get(reverse("inventory_search"), {"preset": "lost_found"})
        ids = self._ids(resp)
        self.assertIn(self.i_unknown.id, ids)
        self.assertIn(self.i_unknown_nowhere.id, ids)
        self.assertNotIn(self.i_new.id, ids)

    # --- combined / regression ---------------------------------------------
    def test_status_and_type_combine(self):
        resp = self.client.get(
            reverse("inventory_search"),
            {
                "status": str(int(InventoryItem.Status.UNKNOWN)),
                "item_type": "filament",
            },
        )
        self.assertEqual(
            self._ids(resp), {self.i_unknown.id, self.i_unknown_nowhere.id}
        )

    def test_status_choices_in_context_include_all(self):
        resp = self.client.get(reverse("inventory_search"))
        values = {int(v) for v, _ in resp.context["status_choices"]}
        self.assertIn(int(InventoryItem.Status.UNKNOWN), values)
        self.assertIn(int(InventoryItem.Status.DEPLETED), values)

    def test_type_choices_in_context(self):
        resp = self.client.get(reverse("inventory_search"))
        models = {m for m, _ in resp.context["type_choices"]}
        self.assertEqual(models, {"filament", "printer", "ams", "dryer", "hardware"})

    def test_export_honors_status_filter(self):
        """The Excel export shares the search filters, so a status filter that
        surfaces DEPLETED rows must export them (the old export hardcoded
        ``exclude(status=5)`` and could never export depleted items).
        """
        import io

        import openpyxl

        resp = self.client.get(
            reverse("inventory_export"),
            {"status": str(int(InventoryItem.Status.DEPLETED))},
        )
        self.assertEqual(resp.status_code, 200)
        wb = openpyxl.load_workbook(io.BytesIO(resp.content))
        ws = wb.active
        # Header row + exactly the one depleted item.
        self.assertEqual(ws.max_row, 2)


@override_settings(LOW_QUANTITY=3)
class LowStockAlertTests(TestCase):
    """Low-stock alerts must key off the SKU's true active count.

    Regression: out-of-stock was computed as ``depleted_map - active_map`` where
    active_map was pre-filtered to ``active_count < LOW_QUANTITY``. A well-stocked
    SKU (>= LOW_QUANTITY) was therefore absent from active_map, so any such SKU
    with a depletion in the last 30 days was falsely flagged "Out of Stock" with
    count 0 -- e.g. PLA Basic Black showing out of stock while 3 rolls exist.
    """

    def _deplete(self, item, days_ago=1):
        from datetime import timedelta

        from django.utils.timezone import now

        InventoryItem.objects.filter(pk=item.pk).update(
            status=InventoryItem.Status.DEPLETED,
            date_depleted=now() - timedelta(days=days_ago),
        )

    def _alerts_by_sku(self):
        from .views import _build_low_stock_alerts

        return {a["product__sku"]: a for a in _build_low_stock_alerts()}

    def test_well_stocked_recently_depleted_is_not_flagged(self):
        p = Filament.objects.create(
            name="PLA Basic Black", sku="10101", upc="9000000000001"
        )
        for _ in range(3):
            InventoryItem.objects.create(product=p)  # 3 active (== LOW_QUANTITY)
        self._deplete(InventoryItem.objects.create(product=p))  # recent depletion
        self.assertNotIn("10101", self._alerts_by_sku())

    def test_zero_active_recently_depleted_is_out_of_stock(self):
        p = Filament.objects.create(
            name="PETG HF Black", sku="33102", upc="9000000000002"
        )
        self._deplete(InventoryItem.objects.create(product=p))
        alerts = self._alerts_by_sku()
        self.assertIn("33102", alerts)
        self.assertEqual(alerts["33102"]["active_count"], 0)
        self.assertEqual(alerts["33102"]["urgency_label"], "Out of Stock")

    def test_low_but_present_is_low_stock(self):
        p = Filament.objects.create(name="ABS Red", sku="40200", upc="9000000000003")
        InventoryItem.objects.create(product=p)  # 1 active, below LOW_QUANTITY
        alerts = self._alerts_by_sku()
        self.assertIn("40200", alerts)
        self.assertEqual(alerts["40200"]["active_count"], 1)


class MoveServiceTests(TestCase):
    """The inventory.items service is the single chokepoint for move/deplete/
    set_status. It owns the _skip_status_from_location dance and the move guard
    (container + slot-capacity rejection)."""

    def setUp(self):
        self.product = Filament.objects.create(name="PLA Move", upc="9400000000001")
        self.shelf = Location.objects.create(
            name="Move Shelf",
            kind=Location.Kind.SHELF,
            default_status=InventoryItem.Status.NEW,
        )
        self.dry = Location.objects.create(
            name="Move Dry",
            kind=Location.Kind.DRY_STORAGE,
            default_status=InventoryItem.Status.STORED,
        )
        self.printer = Location.objects.create(
            name="Move Printer",
            kind=Location.Kind.PRINTER,
            default_status=InventoryItem.Status.IN_USE,
        )
        self.rack = Location.objects.create(name="Move Rack", kind=Location.Kind.RACK)

    # --- status derivation -------------------------------------------------
    def test_move_derives_status_from_default(self):
        item = InventoryItem.objects.create(product=self.product, location=self.shelf)
        result = items.move_to(item, self.dry)
        self.assertTrue(result.ok)
        item.refresh_from_db()
        self.assertEqual(item.location_id, self.dry.id)
        self.assertEqual(item.status, InventoryItem.Status.STORED)

    def test_move_explicit_status_overrides_default(self):
        item = InventoryItem.objects.create(product=self.product, location=self.shelf)
        result = items.move_to(item, self.dry, status=InventoryItem.Status.DRYING)
        self.assertTrue(result.ok)
        item.refresh_from_db()
        self.assertEqual(item.location_id, self.dry.id)
        self.assertEqual(item.status, InventoryItem.Status.DRYING)

    def test_move_to_location_without_default_keeps_status(self):
        # A leaf with no default_status leaves the current status untouched.
        no_default = Location.objects.create(
            name="No Default Leaf", kind=Location.Kind.SHELF, default_status=None
        )
        item = InventoryItem.objects.create(product=self.product, location=self.shelf)
        item.status = InventoryItem.Status.IN_USE
        item._skip_status_from_location = True
        item.save()
        result = items.move_to(item, no_default)
        self.assertTrue(result.ok)
        item.refresh_from_db()
        self.assertEqual(item.location_id, no_default.id)
        self.assertEqual(item.status, InventoryItem.Status.IN_USE)

    # --- sticky preservation ----------------------------------------------
    def test_move_preserves_sticky_unknown(self):
        item = InventoryItem.objects.create(product=self.product, location=self.shelf)
        item.status = InventoryItem.Status.UNKNOWN
        item._skip_status_from_location = True
        item.save()
        item = InventoryItem.objects.get(pk=item.pk)  # drop transient flag
        result = items.move_to(item, self.dry)
        self.assertTrue(result.ok)
        item.refresh_from_db()
        self.assertEqual(item.status, InventoryItem.Status.UNKNOWN)
        self.assertEqual(item.location_id, self.dry.id)

    def test_move_preserves_sticky_depleted(self):
        item = InventoryItem.objects.create(product=self.product, location=self.shelf)
        item.status = InventoryItem.Status.DEPLETED
        item.save()
        item = InventoryItem.objects.get(pk=item.pk)
        result = items.move_to(item, self.dry)
        self.assertTrue(result.ok)
        item.refresh_from_db()
        # Sticky status is preserved; mark_depleted re-clears location on save.
        self.assertEqual(item.status, InventoryItem.Status.DEPLETED)

    def test_explicit_status_can_revive_sticky_item(self):
        # Passing status= bypasses the sticky guard via the skip flag (audit revive).
        item = InventoryItem.objects.create(product=self.product, location=self.shelf)
        item.status = InventoryItem.Status.UNKNOWN
        item._skip_status_from_location = True
        item.save()
        item = InventoryItem.objects.get(pk=item.pk)
        result = items.move_to(item, self.dry, status=InventoryItem.Status.STORED)
        self.assertTrue(result.ok)
        item.refresh_from_db()
        self.assertEqual(item.status, InventoryItem.Status.STORED)
        self.assertEqual(item.location_id, self.dry.id)

    # --- container rejection ----------------------------------------------
    def test_move_into_container_rejected(self):
        item = InventoryItem.objects.create(product=self.product, location=self.shelf)
        result = items.move_to(item, self.rack)
        self.assertFalse(result.ok)
        self.assertIn("container", result.message.lower())
        item.refresh_from_db()
        self.assertEqual(item.location_id, self.shelf.id)  # unchanged

    # --- capacity rejection -----------------------------------------------
    def test_move_into_full_slot_rejected(self):
        slot = Location.objects.create(
            name="Cap Slot",
            kind=Location.Kind.AMS_SLOT,
            default_status=InventoryItem.Status.STORED,
            capacity=1,
        )
        first = InventoryItem.objects.create(product=self.product)
        items.move_to(first, slot)
        second = InventoryItem.objects.create(product=self.product, location=self.shelf)
        result = items.move_to(second, slot)
        self.assertFalse(result.ok)
        self.assertIn("full", result.message.lower())
        second.refresh_from_db()
        self.assertEqual(second.location_id, self.shelf.id)

    def test_capacity_counts_only_active_items(self):
        # A depleted item sitting at a slot does not consume capacity.
        slot = Location.objects.create(
            name="Cap Slot 2",
            kind=Location.Kind.AMS_SLOT,
            default_status=InventoryItem.Status.STORED,
            capacity=1,
        )
        stale = InventoryItem.objects.create(product=self.product, location=slot)
        # Force a DEPLETED row that still records this slot (mark_depleted would
        # clear the location); a bare .update() bypasses save() so the fixture
        # mirrors stale data — a depleted item must not consume slot capacity.
        InventoryItem.objects.filter(pk=stale.pk).update(
            status=InventoryItem.Status.DEPLETED, location=slot
        )
        live = InventoryItem.objects.create(product=self.product, location=self.shelf)
        result = items.move_to(live, slot)
        self.assertTrue(result.ok)
        live.refresh_from_db()
        self.assertEqual(live.location_id, slot.id)

    def test_unlimited_capacity_allows_many(self):
        # A shelf (capacity null) holds an arbitrary number of items.
        for _ in range(5):
            it = InventoryItem.objects.create(product=self.product)
            self.assertTrue(items.move_to(it, self.shelf).ok)

    def test_moving_item_already_in_slot_not_blocked_by_itself(self):
        slot = Location.objects.create(
            name="Cap Slot 3",
            kind=Location.Kind.AMS_SLOT,
            default_status=InventoryItem.Status.STORED,
            capacity=1,
        )
        item = InventoryItem.objects.create(product=self.product)
        items.move_to(item, slot)
        # Re-moving the same item into the same full slot must not reject it.
        result = items.move_to(item, slot)
        self.assertTrue(result.ok)

    # --- drying-warning surfacing -----------------------------------------
    def test_drying_warning_surfaced_in_result(self):
        mat = Material.objects.create(name="PLA Dry", drying_required=True)
        fil = Filament.objects.create(
            name="PLA Wet Move", upc="9400000000099", material=mat
        )
        item = InventoryItem.objects.create(product=fil)
        item.status = InventoryItem.Status.NEW
        item.save()
        result = items.move_to(item, self.printer)
        self.assertTrue(result.ok)
        self.assertIsNotNone(result.drying_warning)
        self.assertEqual(result.drying_warning[0], "warning")

    def test_drying_warning_skipped_when_requested(self):
        mat = Material.objects.create(name="PLA Dry2", drying_required=True)
        fil = Filament.objects.create(
            name="PLA Wet Move2", upc="9400000000098", material=mat
        )
        item = InventoryItem.objects.create(product=fil)
        item.status = InventoryItem.Status.NEW
        item.save()
        result = items.move_to(item, self.printer, skip_drying_check=True)
        self.assertTrue(result.ok)
        self.assertIsNone(result.drying_warning)

    # --- deplete -----------------------------------------------------------
    def test_deplete_sets_status_and_clears_location(self):
        item = InventoryItem.objects.create(product=self.product, location=self.shelf)
        result = items.deplete(item)
        self.assertTrue(result.ok)
        item.refresh_from_db()
        self.assertEqual(item.status, InventoryItem.Status.DEPLETED)
        self.assertIsNone(item.location_id)
        self.assertIsNotNone(item.date_depleted)

    def test_deplete_accepts_reason(self):
        item = InventoryItem.objects.create(product=self.product, location=self.shelf)
        result = items.deplete(item, reason="used up")
        self.assertTrue(result.ok)
        self.assertEqual(result.reason, "used up")

    # --- set_status --------------------------------------------------------
    def test_set_status_does_not_recompute_from_location(self):
        # Setting IN_USE while sitting on a NEW-default shelf must stick.
        item = InventoryItem.objects.create(product=self.product, location=self.shelf)
        result = items.set_status(item, InventoryItem.Status.IN_USE)
        self.assertTrue(result.ok)
        item.refresh_from_db()
        self.assertEqual(item.status, InventoryItem.Status.IN_USE)
        self.assertEqual(item.location_id, self.shelf.id)

    def test_set_status_sold_clears_location(self):
        item = InventoryItem.objects.create(product=self.product, location=self.shelf)
        result = items.set_status(item, InventoryItem.Status.SOLD)
        self.assertTrue(result.ok)
        item.refresh_from_db()
        self.assertEqual(item.status, InventoryItem.Status.SOLD)
        self.assertIsNone(item.location_id)


class LocationCapacityTests(TestCase):
    def test_slot_kinds_default_to_capacity_one(self):
        ams_slot = Location.objects.create(
            name="AMS Slot Cap", kind=Location.Kind.AMS_SLOT
        )
        dryer_slot = Location.objects.create(
            name="Dryer Slot Cap", kind=Location.Kind.DRYER_SLOT
        )
        self.assertEqual(ams_slot.capacity, 1)
        self.assertEqual(dryer_slot.capacity, 1)

    def test_non_slot_assignables_default_unlimited(self):
        shelf = Location.objects.create(name="Shelf Cap", kind=Location.Kind.SHELF)
        dry = Location.objects.create(name="Dry Cap", kind=Location.Kind.DRY_STORAGE)
        printer = Location.objects.create(
            name="Printer Cap", kind=Location.Kind.PRINTER
        )
        self.assertIsNone(shelf.capacity)
        self.assertIsNone(dry.capacity)
        self.assertIsNone(printer.capacity)


# ---------------------------------------------------------------------------
# Phase 17.1 — Filament TDS parsing -> review CSV (no DB writes)
# ---------------------------------------------------------------------------

import csv  # noqa: E402
import importlib.util  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402

from django.conf import settings  # noqa: E402
from django.core.management import call_command  # noqa: E402

from inventory.filament_tds import (  # noqa: E402
    CSV_FIELDS,
    TdsRow,
    parse_tds_text,
)

_FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "tests_fixtures")
_HAS_PYPDF = importlib.util.find_spec("pypdf") is not None


def _load_fixture(name):
    with open(os.path.join(_FIXTURE_DIR, name), encoding="utf-8") as fh:
        return fh.read()


class FilamentTdsParserTests(TestCase):
    """Unit-test the pure text parser against a committed real-TDS fixture.

    The fixture is the pypdf-extracted text of
    ``Bambu_PLA_Basic_Technical_Data_Sheet.pdf`` -- so these tests never need
    ``pypdf`` (a dev-only dep that prod never installs).
    """

    def test_parses_pla_basic_fixture(self):
        row = parse_tds_text(
            _load_fixture("pla_basic_tds.txt"),
            source_file="Bambu_PLA_Basic_Technical_Data_Sheet.pdf",
        )
        self.assertEqual(row.name, "PLA")
        self.assertEqual(row.material_type, "Basic")
        self.assertEqual(row.mfr, "Bambu Lab")
        self.assertEqual(row.dry_temp_ideal_degC, 50)
        self.assertEqual(row.dry_time_hrs, 8)
        self.assertEqual(row.print_temp_min_degC, 190)
        self.assertEqual(row.print_temp_max_degC, 230)
        # build plate: comma-joined surfaces, "or" normalised to a comma
        self.assertIn("Cool Plate", row.build_plate_compat)
        self.assertIn("Textured PEI Plate", row.build_plate_compat)
        self.assertNotIn(" or ", row.build_plate_compat)
        # PLA Basic has no hardened-nozzle recommendation -> stays blank
        self.assertEqual(row.hot_end_compat, "")

    def test_drying_line_variants(self):
        # ASCII comma + "hours" word + glued "DryingSettings" (PLA Sparkle style)
        r1 = parse_tds_text("DryingSettings before Printing 55°C, 8 hours")
        self.assertEqual((r1.dry_temp_ideal_degC, r1.dry_time_hrs), (55, 8))
        # fullwidth comma + a time range "8 -12h" -> take the first value
        r2 = parse_tds_text("Drying Settings before Printing 80°C，8 -12h")
        self.assertEqual((r2.dry_temp_ideal_degC, r2.dry_time_hrs), (80, 8))

    def test_build_plate_label_variants(self):
        bed = parse_tds_text(
            "Build Plate Type Cool Plate Supertack / Textured PEI Plate "
            "Bed Temperature 65 - 75 °C"
        )
        self.assertEqual(
            bed.build_plate_compat, "Cool Plate Supertack, Textured PEI Plate"
        )

    def test_hot_end_extracted_only_when_explicit(self):
        # Marketing copy mentioning "wear resistance" must NOT trigger a match.
        soft = parse_tds_text("ABS-GF inherits water resistance, wear resistance.")
        self.assertEqual(soft.hot_end_compat, "")
        # A genuine recommendation IS captured.
        hard = parse_tds_text("A hardened steel nozzle is required for this filament.")
        self.assertIn("hardened steel", hard.hot_end_compat.lower())

    def test_name_type_split(self):
        self.assertEqual(parse_tds_text("ABS-CF").name, "ABS")
        self.assertEqual(parse_tds_text("ABS-CF").material_type, "CF")
        self.assertEqual(parse_tds_text("PA6-GF").name, "PA6")
        self.assertEqual(parse_tds_text("PA6-GF").material_type, "GF")
        # base polymer + word subtype
        wood = parse_tds_text("Bambu Filament Technical Data Sheet\nPLA Wood\n")
        self.assertEqual((wood.name, wood.material_type), ("PLA", "Wood"))

    def test_missing_fields_left_blank_not_guessed(self):
        # Garbage with no recognisable rows yields an all-blank row, not a crash.
        row = parse_tds_text("totally unrelated text with no settings table")
        self.assertIsNone(row.dry_temp_ideal_degC)
        self.assertIsNone(row.dry_time_hrs)
        self.assertEqual(row.build_plate_compat, "")
        self.assertEqual(row.hot_end_compat, "")

    def test_csv_dict_renders_none_as_blank(self):
        d = TdsRow(name="PLA", dry_temp_ideal_degC=None).as_csv_dict()
        self.assertEqual(set(d.keys()), set(CSV_FIELDS))
        self.assertEqual(d["dry_temp_ideal_degC"], "")
        self.assertEqual(d["name"], "PLA")


@unittest.skipUnless(_HAS_PYPDF, "pypdf (dev-only) not installed")
class ParseFilamentTdsCommandTests(TestCase):
    """The management command writes a review CSV and never touches the DB.

    Skipped where ``pypdf`` is absent (prod), since reading the PDFs needs it.
    """

    def _write_pdf_dir(self):
        """Point the command at the repo's real committed TDS directory."""
        return os.path.join(settings.BASE_DIR, "filament_TDS")

    def test_command_writes_csv_without_touching_db(self):
        before = Material.objects.count()
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "review.csv")
            call_command(
                "parse_filament_tds",
                tds_dir=self._write_pdf_dir(),
                out=out,
                verbosity=0,
            )
            self.assertTrue(os.path.exists(out))
            with open(out, encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
        # CSV has the expected header and at least one parsed sheet.
        self.assertTrue(rows)
        self.assertEqual(set(rows[0].keys()), set(CSV_FIELDS))
        # PLA Basic is in the repo; assert it round-tripped through the CSV.
        pla = [r for r in rows if r["name"] == "PLA" and r["material_type"] == "Basic"]
        self.assertTrue(pla, "expected a PLA Basic row in the review CSV")
        self.assertEqual(pla[0]["dry_temp_ideal_degC"], "50")
        # The command must be read-only w.r.t. the DB.
        self.assertEqual(Material.objects.count(), before)


class MaterialTdsFieldsTests(TestCase):
    """The new TDS compatibility fields save and round-trip."""

    def test_build_plate_and_hot_end_persist(self):
        m = Material.objects.create(
            name="ASA",
            material_type="CF",
            build_plate_compat="Textured PEI Plate, Smooth PEI Plate",
            hot_end_compat="Hardened steel nozzle required",
        )
        m.refresh_from_db()
        self.assertEqual(m.build_plate_compat, "Textured PEI Plate, Smooth PEI Plate")
        self.assertEqual(m.hot_end_compat, "Hardened steel nozzle required")

    def test_fields_default_blank(self):
        m = Material.objects.create(name="PLA", material_type="")
        self.assertEqual(m.build_plate_compat, "")
        self.assertEqual(m.hot_end_compat, "")


class ItemHistoryTests(TestCase):
    """django-simple-history capture + derived location/status timeline."""

    def setUp(self):
        self.product = Filament.objects.create(name="PLA Hist", upc="9300000000001")
        self.loc_a = Location.objects.create(
            name="Shelf 5",
            kind=Location.Kind.SHELF,
            default_status=InventoryItem.Status.NEW,
        )
        self.loc_b = Location.objects.create(
            name="Shelf 4",
            kind=Location.Kind.SHELF,
            default_status=InventoryItem.Status.NEW,
        )

    def test_save_creates_historical_row(self):
        item = InventoryItem.objects.create(product=self.product, location=self.loc_a)
        self.assertEqual(item.history.count(), 1)
        item.serial_number = "ABC"
        item.save()
        self.assertEqual(item.history.count(), 2)

    def test_timeline_records_location_change(self):
        item = InventoryItem.objects.create(product=self.product, location=self.loc_a)
        item.location = self.loc_b
        item.save()
        timeline = item.location_status_timeline()
        self.assertEqual(len(timeline), 1)
        entry = timeline[0]
        self.assertTrue(entry["location_changed"])
        self.assertEqual(entry["location_from"], self.loc_a)
        self.assertEqual(entry["location_to"], self.loc_b)

    def test_timeline_records_status_change(self):
        item = InventoryItem.objects.create(product=self.product, location=self.loc_a)
        item.status = InventoryItem.Status.IN_USE
        item._skip_status_from_location = True
        item.save()
        timeline = item.location_status_timeline()
        self.assertEqual(len(timeline), 1)
        entry = timeline[0]
        self.assertTrue(entry["status_changed"])
        self.assertEqual(entry["status_from"], InventoryItem.Status.NEW)
        self.assertEqual(entry["status_to"], InventoryItem.Status.IN_USE)

    def test_combined_location_and_status_change_is_one_entry(self):
        """An audit move that flips both fields reads as a single timeline entry."""
        item = InventoryItem.objects.create(product=self.product, location=self.loc_a)
        # One save changes both location and status.
        item.location = self.loc_b
        item.status = InventoryItem.Status.IN_USE
        item._skip_status_from_location = True
        item.save()
        timeline = item.location_status_timeline()
        self.assertEqual(len(timeline), 1)
        entry = timeline[0]
        self.assertTrue(entry["location_changed"])
        self.assertTrue(entry["status_changed"])
        self.assertEqual(entry["location_from"], self.loc_a)
        self.assertEqual(entry["location_to"], self.loc_b)
        self.assertEqual(entry["status_from"], InventoryItem.Status.NEW)
        self.assertEqual(entry["status_to"], InventoryItem.Status.IN_USE)

    def test_timeline_ignores_unrelated_field_change(self):
        """A change to a non-location/status field does NOT appear in the timeline."""
        item = InventoryItem.objects.create(product=self.product, location=self.loc_a)
        item.serial_number = "XYZ-1"
        item.save()
        item.shipment = "TRACK-123"
        item.save()
        self.assertEqual(item.location_status_timeline(), [])

    def test_timeline_is_newest_first(self):
        item = InventoryItem.objects.create(product=self.product, location=self.loc_a)
        item.location = self.loc_b
        item.save()
        item.location = self.loc_a
        item.save()
        timeline = item.location_status_timeline()
        self.assertEqual(len(timeline), 2)
        # Newest change (B -> A) first.
        self.assertEqual(timeline[0]["location_to"], self.loc_a)
        self.assertEqual(timeline[1]["location_to"], self.loc_b)

    def test_item_edit_page_shows_timeline_section(self):
        User.objects.create_user(username="hist", password="pass")
        self.client.login(username="hist", password="pass")
        item = InventoryItem.objects.create(product=self.product, location=self.loc_a)
        item.location = self.loc_b
        item.save()
        resp = self.client.get(reverse("inventory_edit", kwargs={"item_id": item.id}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Location &amp; Status History")
        self.assertContains(resp, "Shelf 5")
        self.assertContains(resp, "Shelf 4")

    def test_admin_history_url_loads(self):
        User.objects.create_superuser(username="admin", password="pass", email="a@b.c")
        self.client.login(username="admin", password="pass")
        item = InventoryItem.objects.create(product=self.product, location=self.loc_a)
        url = reverse("admin:inventory_inventoryitem_history", args=[item.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)


from . import maintenance  # noqa: E402


def _make_printer_item(upc, *, serial="", days_old=None, model=None, mfr=None):
    """Helper: a Printer product + an owned InventoryItem, optionally back-dated.

    ``model``/``mfr`` override the Printer subclass defaults so tests can create
    distinct product models (the reliability rollup groups by product model).
    """
    extra = {}
    if model is not None:
        extra["model"] = model
    if mfr is not None:
        extra["mfr"] = mfr
    product = Printer.objects.create(
        name=f"Printer {upc}",
        upc=upc,
        num_extruders=1,
        bed_length_mm=256,
        bed_width_mm=256,
        max_height_mm=256,
        **extra,
    )
    item = InventoryItem.objects.create(product=product, serial_number=serial)
    if days_old is not None:
        # date_added is auto_now_add; back-date it with an UPDATE so MTBF age math
        # has a known operating window.
        past = timezone.now() - timedelta(days=days_old)
        InventoryItem.objects.filter(pk=item.pk).update(date_added=past)
        item.refresh_from_db()
    return product, item


class MaintenanceModelTests(TestCase):
    def setUp(self):
        _, self.printer_item = _make_printer_item("3000000000001")
        self.hotend = Hardware.objects.create(
            name="Hardened Hotend",
            upc="3000000000010",
            kind=Hardware.HardwareType.PARTS,
        )
        self.filament = Filament.objects.create(name="PLA", upc="3000000000020")
        self.filament_item = InventoryItem.objects.create(product=self.filament)

    def test_create_event_with_cost_downtime_and_part(self):
        e = MaintenanceEvent.objects.create(
            unit=self.printer_item,
            kind=MaintenanceEvent.Kind.PART_REPLACE,
            severity=MaintenanceEvent.Severity.MAJOR,
            title="Replaced hotend",
            part=self.hotend,
            cost=Decimal("24.99"),
            downtime_hours=Decimal("1.50"),
        )
        e.refresh_from_db()
        self.assertEqual(e.cost, Decimal("24.99"))
        self.assertEqual(e.downtime_hours, Decimal("1.50"))
        self.assertEqual(e.part_id, self.hotend.pk)
        self.assertEqual(e.kind, MaintenanceEvent.Kind.PART_REPLACE)
        # related_name reachable from the machine item
        self.assertIn(e, self.printer_item.maintenance_events.all())

    def test_clean_rejects_non_machine_unit(self):
        e = MaintenanceEvent(
            unit=self.filament_item,
            kind=MaintenanceEvent.Kind.CLEAN,
            title="Nope",
        )
        with self.assertRaises(ValidationError):
            e.full_clean()

    def test_clean_accepts_machine_unit(self):
        e = MaintenanceEvent(
            unit=self.printer_item,
            kind=MaintenanceEvent.Kind.CLEAN,
            title="Wiped bed",
        )
        e.full_clean()  # must not raise

    def test_hms_code_defaults_blank(self):
        e = MaintenanceEvent.objects.create(
            unit=self.printer_item,
            title="Calibrate",
            kind=MaintenanceEvent.Kind.CALIBRATE,
        )
        self.assertEqual(e.hms_code, "")
        self.assertTrue(e.resolved)  # default resolved True

    def test_nozzle_config_one_to_one(self):
        cfg = NozzleConfig.objects.create(
            printer=self.printer_item,
            nozzle_diameter_mm=Decimal("0.40"),
            nozzle_type="hardened steel",
        )
        self.assertEqual(self.printer_item.nozzle_config, cfg)

    def test_nozzle_config_rejects_non_printer(self):
        ams = AMS.objects.create(name="AMS", upc="3000000000030")
        ams_item = InventoryItem.objects.create(product=ams)
        cfg = NozzleConfig(printer=ams_item, nozzle_diameter_mm=Decimal("0.40"))
        with self.assertRaises(ValidationError):
            cfg.full_clean()


class MaintenanceServiceTests(TestCase):
    def setUp(self):
        _, self.printer_item = _make_printer_item("3100000000001")
        self.dryer = Dryer.objects.create(name="Dryer", upc="3100000000002")
        self.dryer_item = InventoryItem.objects.create(product=self.dryer)
        self.filament = Filament.objects.create(name="PLA", upc="3100000000020")
        self.filament_item = InventoryItem.objects.create(product=self.filament)
        self.hotend = Hardware.objects.create(name="Hotend", upc="3100000000010")

    def test_log_event_rejects_non_machine(self):
        with self.assertRaises(maintenance.MaintenanceError):
            maintenance.log_event(
                self.filament_item, kind=MaintenanceEvent.Kind.CLEAN, title="x"
            )

    def test_log_event_creates_for_machine(self):
        e = maintenance.log_event(
            self.dryer_item,
            kind=MaintenanceEvent.Kind.CLEAN,
            title="Cleaned dryer",
            cost=Decimal("0.00"),
        )
        self.assertEqual(e.unit_id, self.dryer_item.pk)

    def test_open_and_resolve_fault(self):
        e = maintenance.open_fault(
            self.printer_item, title="Heatbreak clog", hms_code="0300_0100"
        )
        self.assertFalse(e.resolved)
        self.assertEqual(e.kind, MaintenanceEvent.Kind.FAULT)
        self.assertEqual(e.hms_code, "0300_0100")
        maintenance.resolve_fault(e)
        e.refresh_from_db()
        self.assertTrue(e.resolved)

    def test_swap_hotend_writes_event_and_nozzle_config(self):
        event, config = maintenance.swap_hotend(
            self.printer_item,
            nozzle_diameter_mm=Decimal("0.60"),
            nozzle_type="hardened steel",
            part=self.hotend,
            cost=Decimal("19.99"),
        )
        self.assertEqual(event.kind, MaintenanceEvent.Kind.HOTEND_SWAP)
        self.assertEqual(event.part_id, self.hotend.pk)
        self.assertEqual(config.nozzle_diameter_mm, Decimal("0.60"))
        self.assertIsNotNone(config.hotend_changed_at)
        # Second swap updates the same (one-per-printer) config row.
        _, config2 = maintenance.swap_hotend(
            self.printer_item, nozzle_diameter_mm=Decimal("0.40")
        )
        self.assertEqual(config.pk, config2.pk)
        self.assertEqual(config2.nozzle_diameter_mm, Decimal("0.40"))

    def test_unit_summary_aggregates(self):
        maintenance.open_fault(self.printer_item, title="f1")
        maintenance.open_fault(self.printer_item, title="f2")
        maintenance.log_event(
            self.printer_item,
            kind=MaintenanceEvent.Kind.REPAIR,
            title="r1",
            cost=Decimal("10.00"),
            downtime_hours=Decimal("2.00"),
        )
        s = maintenance.unit_summary(self.printer_item)
        self.assertEqual(s["faults"], 2)
        self.assertEqual(s["open_faults"], 2)
        self.assertEqual(s["total_events"], 3)
        self.assertEqual(s["total_cost"], Decimal("10.00"))
        self.assertEqual(s["total_downtime_hours"], Decimal("2.00"))


class MaintenanceReliabilityTests(TestCase):
    def test_model_reliability_math(self):
        # Two physical units of the SAME catalog product (one product_id), one
        # 200 days old, one 100 (fleet age 300) — they roll up into one model row.
        product, p1 = _make_printer_item(
            "3200000000001", days_old=200, model="X1 Carbon"
        )
        p2 = InventoryItem.objects.create(product=product, serial_number="P2")
        past = timezone.now() - timedelta(days=100)
        InventoryItem.objects.filter(pk=p2.pk).update(date_added=past)
        p2.refresh_from_db()
        # 3 faults on printers total + 1 repair.
        maintenance.open_fault(p1, title="f1")
        maintenance.open_fault(p1, title="f2")
        maintenance.resolve_fault(maintenance.open_fault(p2, title="f3"))
        maintenance.log_event(
            p2,
            kind=MaintenanceEvent.Kind.REPAIR,
            title="repair",
            cost=Decimal("50.00"),
            downtime_hours=Decimal("4.00"),
        )

        rows = maintenance.model_reliability()
        # Distinct product rows even within one polymorphic type → key by label.
        by_label = {r["model_label"]: r for r in rows}
        self.assertIn("Bambu Lab X1 Carbon", by_label)
        printer = by_label["Bambu Lab X1 Carbon"]
        self.assertEqual(printer["ctype"], "printer")
        self.assertEqual(printer["units"], 2)
        self.assertEqual(printer["faults"], 3)
        self.assertEqual(printer["open_faults"], 2)  # f3 was resolved
        self.assertEqual(printer["total_cost"], Decimal("50.00"))
        self.assertEqual(printer["total_downtime_hours"], Decimal("4.00"))
        self.assertAlmostEqual(printer["faults_per_unit"], 1.5, places=2)
        # MTBF = fleet age (~300 d) / 3 faults ~= 100 d.
        self.assertIsNotNone(printer["mtbf_days"])
        self.assertAlmostEqual(printer["mtbf_days"], 100.0, delta=1.0)

    def test_two_printer_models_yield_two_rows(self):
        # Two DIFFERENT printer models — the rebuy/refund decision is per-model,
        # so they must not collapse into one "printer" bucket.
        _, x1 = _make_printer_item("3200000001001", days_old=100, model="X1 Carbon")
        _, a1 = _make_printer_item("3200000001002", days_old=50, model="A1 mini")
        # X1 Carbon: 2 faults; A1 mini: 1 fault.
        maintenance.open_fault(x1, title="x-f1")
        maintenance.open_fault(x1, title="x-f2")
        maintenance.open_fault(a1, title="a-f1")

        rows = maintenance.model_reliability()
        by_label = {r["model_label"]: r for r in rows}
        self.assertIn("Bambu Lab X1 Carbon", by_label)
        self.assertIn("Bambu Lab A1 mini", by_label)
        self.assertEqual(len(rows), 2)

        x1_row = by_label["Bambu Lab X1 Carbon"]
        a1_row = by_label["Bambu Lab A1 mini"]
        # Both are printers by polymorphic type but distinct product models.
        self.assertEqual(x1_row["ctype"], "printer")
        self.assertEqual(a1_row["ctype"], "printer")
        # Units and faults attributed to the correct model only.
        self.assertEqual(x1_row["units"], 1)
        self.assertEqual(a1_row["units"], 1)
        self.assertEqual(x1_row["faults"], 2)
        self.assertEqual(a1_row["faults"], 1)
        # Worst-first ordering: X1 Carbon (2 faults/unit) before A1 mini (1).
        self.assertEqual(rows[0]["model_label"], "Bambu Lab X1 Carbon")

    def test_model_with_zero_faults_has_none_mtbf(self):
        _make_printer_item("3200000000010", days_old=30)
        rows = maintenance.model_reliability()
        printer = next(r for r in rows if r["ctype"] == "printer")
        self.assertEqual(printer["faults"], 0)
        self.assertIsNone(printer["mtbf_days"])

    def test_empty_fleet_returns_empty(self):
        self.assertEqual(maintenance.model_reliability(), [])


class MaintenanceViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="maint", password="pass")
        self.client.login(username="maint", password="pass")
        _, self.printer_item = _make_printer_item("3300000000001", serial="P1SER")
        self.filament = Filament.objects.create(name="PLA", upc="3300000000020")
        self.filament_item = InventoryItem.objects.create(product=self.filament)

    def test_summary_view_renders(self):
        maintenance.open_fault(self.printer_item, title="boom")
        resp = self.client.get(reverse("maintenance_summary"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Reliability")

    def test_unit_timeline_renders(self):
        maintenance.log_event(
            self.printer_item, kind=MaintenanceEvent.Kind.CLEAN, title="Wiped bed"
        )
        resp = self.client.get(reverse("unit_maintenance", args=[self.printer_item.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Wiped bed")

    def test_log_create_get_renders(self):
        resp = self.client.get(reverse("maintenance_log", args=[self.printer_item.id]))
        self.assertEqual(resp.status_code, 200)

    def test_log_create_post_creates_event(self):
        resp = self.client.post(
            reverse("maintenance_log", args=[self.printer_item.id]),
            {
                "kind": MaintenanceEvent.Kind.CALIBRATE,
                "severity": MaintenanceEvent.Severity.INFO,
                "occurred_at": "2026-06-09T10:00",
                "title": "Flow calibration",
                "detail": "",
                "cost": "",
                "downtime_hours": "",
                "resolved": "on",
            },
        )
        self.assertEqual(resp.status_code, 302)
        e = MaintenanceEvent.objects.get(unit=self.printer_item)
        self.assertEqual(e.title, "Flow calibration")
        self.assertEqual(e.kind, MaintenanceEvent.Kind.CALIBRATE)

    def test_log_create_hotend_swap_updates_nozzle(self):
        self.client.post(
            reverse("maintenance_log", args=[self.printer_item.id]),
            {
                "kind": MaintenanceEvent.Kind.HOTEND_SWAP,
                "severity": MaintenanceEvent.Severity.INFO,
                "occurred_at": "2026-06-09T10:00",
                "title": "Swapped to 0.6",
                "detail": "",
                "cost": "",
                "downtime_hours": "",
                "resolved": "on",
            },
        )
        self.printer_item.refresh_from_db()
        self.assertTrue(hasattr(self.printer_item, "nozzle_config"))
        self.assertIsNotNone(self.printer_item.nozzle_config.hotend_changed_at)

    def test_log_create_rejects_non_machine(self):
        resp = self.client.get(reverse("maintenance_log", args=[self.filament_item.id]))
        # Redirected back to the item edit page with an error message.
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(MaintenanceEvent.objects.count(), 0)

    def test_item_page_shows_maintenance_link_for_machine(self):
        resp = self.client.get(reverse("inventory_edit", args=[self.printer_item.id]))
        self.assertContains(
            resp, reverse("unit_maintenance", args=[self.printer_item.id])
        )

    def test_item_page_hides_maintenance_link_for_filament(self):
        resp = self.client.get(reverse("inventory_edit", args=[self.filament_item.id]))
        self.assertNotContains(
            resp, reverse("unit_maintenance", args=[self.filament_item.id])
        )

    def test_maintenance_views_require_login(self):
        self.client.logout()
        for name, args in [
            ("maintenance_summary", []),
            ("unit_maintenance", [self.printer_item.id]),
            ("maintenance_log", [self.printer_item.id]),
        ]:
            resp = self.client.get(reverse(name, args=args))
            self.assertEqual(resp.status_code, 302)
            self.assertIn("/login", resp.url)


class LocationDetailViewTests(TestCase):
    """Read-only location page + inline capacity-enforced move (Phase 12.1)."""

    def setUp(self):
        K = Location.Kind
        self.user = User.objects.create_user(username="loc", password="pass")
        self.client = Client()
        self.client.login(username="loc", password="pass")

        # A rack with two shelves; one shelf holds an item.
        self.rack = Location.objects.create(name="Rack LD", kind=K.RACK)
        self.shelf1 = Location.objects.create(
            name="Rack LD / Shelf 1",
            kind=K.SHELF,
            parent=self.rack,
            default_status=InventoryItem.Status.NEW,
        )
        self.shelf2 = Location.objects.create(
            name="Rack LD / Shelf 2",
            kind=K.SHELF,
            parent=self.rack,
            default_status=InventoryItem.Status.STORED,
        )
        self.product = Filament.objects.create(name="PLA LD", upc="9700000000001")
        self.item1 = InventoryItem.objects.create(
            product=self.product, location=self.shelf1
        )
        self.item2 = InventoryItem.objects.create(
            product=self.product, location=self.shelf2
        )

    def _url(self, loc):
        return reverse("location_detail", kwargs={"location_id": loc.id})

    # ---- rendering ----

    def test_leaf_lists_only_its_items(self):
        resp = self.client.get(self._url(self.shelf1))
        self.assertEqual(resp.status_code, 200)
        ctx = resp.context
        self.assertEqual(ctx["item_count"], 1)
        items_here = [i for lst in ctx["grouped_items"].values() for i in lst]
        self.assertEqual({i.id for i in items_here}, {self.item1.id})

    def test_container_aggregates_subtree(self):
        resp = self.client.get(self._url(self.rack))
        self.assertEqual(resp.status_code, 200)
        ctx = resp.context
        self.assertEqual(ctx["item_count"], 2)
        # Grouped by leaf, not pinned to the container.
        leaf_names = {leaf.name for leaf in ctx["grouped_items"].keys()}
        self.assertEqual(leaf_names, {self.shelf1.name, self.shelf2.name})

    def test_depleted_item_excluded(self):
        items.deplete(self.item1)
        resp = self.client.get(self._url(self.rack))
        self.assertEqual(resp.context["item_count"], 1)

    def test_empty_leaf_renders(self):
        empty = Location.objects.create(
            name="Empty Shelf",
            kind=Location.Kind.SHELF,
            default_status=InventoryItem.Status.NEW,
        )
        resp = self.client.get(self._url(empty))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["item_count"], 0)

    def test_requires_login(self):
        self.client.logout()
        resp = self.client.get(self._url(self.shelf1))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp["Location"])

    # ---- slot map ----

    def test_slot_map_shows_occupancy(self):
        K = Location.Kind
        ams = Location.objects.create(name="AMS LD", kind=K.AMS)
        slot1 = Location.objects.create(
            name="AMS LD / 1",
            kind=K.AMS_SLOT,
            parent=ams,
            slot_index=1,
            default_status=InventoryItem.Status.IN_USE,
        )
        slot2 = Location.objects.create(
            name="AMS LD / 2",
            kind=K.AMS_SLOT,
            parent=ams,
            slot_index=2,
            default_status=InventoryItem.Status.IN_USE,
        )
        occupant = InventoryItem.objects.create(product=self.product, location=slot1)

        resp = self.client.get(self._url(ams))
        self.assertEqual(resp.status_code, 200)
        maps = resp.context["slot_maps"]
        self.assertEqual(len(maps), 1)
        rows = maps[0]["rows"]
        self.assertEqual([r["location"].id for r in rows], [slot1.id, slot2.id])
        self.assertEqual(rows[0]["item"].id, occupant.id)
        self.assertIsNone(rows[1]["item"])

    def test_container_renders_child_unit_slot_map(self):
        # A rack page draws slot maps for any AMS/dryer children.
        K = Location.Kind
        dryer = Location.objects.create(name="Dryer LD", kind=K.DRYER, parent=self.rack)
        Location.objects.create(
            name="Dryer LD / 1", kind=K.DRYER_SLOT, parent=dryer, slot_index=1
        )
        resp = self.client.get(self._url(self.rack))
        unit_names = {m["unit"].name for m in resp.context["slot_maps"]}
        self.assertIn("Dryer LD", unit_names)

    # ---- inline move ----

    def test_inline_move_relocates_item(self):
        resp = self.client.post(
            self._url(self.shelf1),
            {"item_id": self.item1.id, "dest_location": self.shelf2.id},
        )
        self.assertEqual(resp.status_code, 302)
        self.item1.refresh_from_db()
        self.assertEqual(self.item1.location_id, self.shelf2.id)
        # Status follows the destination's default_status.
        self.assertEqual(self.item1.status, InventoryItem.Status.STORED)

    def test_inline_move_rejected_when_slot_full(self):
        K = Location.Kind
        slot = Location.objects.create(
            name="Full Slot",
            kind=K.AMS_SLOT,
            slot_index=1,
            default_status=InventoryItem.Status.IN_USE,
        )  # capacity defaults to 1
        InventoryItem.objects.create(product=self.product, location=slot)  # occupies it

        resp = self.client.post(
            self._url(self.shelf1),
            {"item_id": self.item1.id, "dest_location": slot.id},
            follow=True,
        )
        self.item1.refresh_from_db()
        self.assertEqual(self.item1.location_id, self.shelf1.id)  # NOT moved
        msgs = [m.message for m in resp.context["messages"]]
        self.assertTrue(any("full" in m.lower() for m in msgs))

    def test_inline_move_surfaces_drying_warning(self):
        mat = Material.objects.create(
            name="PLA Wet LD", material_type="", drying_required=True
        )
        wet = Filament.objects.create(
            name="PLA Wet LD F", upc="9700000000099", material=mat
        )
        item = InventoryItem.objects.create(
            product=wet, location=self.shelf1, status=InventoryItem.Status.NEW
        )
        printer = Location.objects.create(
            name="Printer LD",
            kind=Location.Kind.PRINTER,
            default_status=InventoryItem.Status.IN_USE,
        )
        resp = self.client.post(
            self._url(self.shelf1),
            {"item_id": item.id, "dest_location": printer.id},
            follow=True,
        )
        item.refresh_from_db()
        self.assertEqual(item.location_id, printer.id)  # moved (warning is advisory)
        msgs = [m.message for m in resp.context["messages"]]
        self.assertTrue(any("requires drying" in m.lower() for m in msgs))

    def test_inline_move_bad_destination_errors(self):
        resp = self.client.post(
            self._url(self.shelf1),
            {"item_id": self.item1.id, "dest_location": ""},
            follow=True,
        )
        self.item1.refresh_from_db()
        self.assertEqual(self.item1.location_id, self.shelf1.id)
        msgs = [m.message for m in resp.context["messages"]]
        self.assertTrue(any("destination" in m.lower() for m in msgs))


class LocationBarcodeRoutingTests(TestCase):
    """LOC- scan routes to the audit console during a session, else to the
    location page. Must not regress the search-based typed-LOC behavior."""

    def setUp(self):
        self.user = User.objects.create_user(username="route", password="pass")
        self.client = Client()
        self.client.login(username="route", password="pass")
        self.shelf = Location.objects.create(
            name="Route Shelf",
            kind=Location.Kind.SHELF,
            default_status=InventoryItem.Status.NEW,
        )

    def _loc_url(self):
        return reverse("barcode_redirect", kwargs={"value": f"LOC-{self.shelf.id}"})

    def test_loc_scan_no_audit_goes_to_location_detail(self):
        resp = self.client.get(self._loc_url())
        self.assertRedirects(
            resp,
            reverse("location_detail", kwargs={"location_id": self.shelf.id}),
        )

    def test_loc_scan_during_audit_goes_to_console(self):
        AuditSession.objects.create(user=self.user)
        resp = self.client.get(self._loc_url())
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("audit_console"), resp["Location"])
        self.assertIn(f"loc={self.shelf.id}", resp["Location"])

    def test_search_typed_loc_still_filters_not_redirects(self):
        # Guard: the search path is independent of the scan-routing change.
        rack = Location.objects.create(name="Route Rack", kind=Location.Kind.RACK)
        child = Location.objects.create(
            name="Route Rack / S1",
            kind=Location.Kind.SHELF,
            parent=rack,
            default_status=InventoryItem.Status.NEW,
        )
        prod = Filament.objects.create(name="PLA Route", upc="9800000000001")
        it = InventoryItem.objects.create(product=prod, location=child)
        resp = self.client.get(reverse("inventory_search"), {"name": f"LOC-{rack.id}"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual({i.id for i in resp.context["items"]}, {it.id})


class PrintJobModelTests(TestCase):
    """Model creation + derived-duration round trips."""

    def setUp(self):
        printer_product = Printer.objects.create(
            name="X1C", upc="9000000000001", num_extruders=1
        )
        self.printer = InventoryItem.objects.create(
            product=printer_product, serial_number="PR-1"
        )

    def test_create_print_job_and_filament_line(self):
        mat = Material.objects.create(name="PLA")
        fil = Filament.objects.create(
            name="PLA Red", upc="9000000000002", material=mat, weight=Decimal("1.00")
        )
        spool = InventoryItem.objects.create(product=fil)
        job = PrintJob.objects.create(printer=self.printer, name="benchy.3mf")
        line = PrintJobFilament.objects.create(
            job=job, item=spool, grams_used=Decimal("12.50")
        )
        self.assertEqual(job.filaments.count(), 1)
        self.assertEqual(line.job, job)
        self.assertEqual(job.result, PrintJob.Result.SUCCESS)
        self.assertEqual(job.source, PrintJob.Source.MANUAL)
        self.assertFalse(job.completed)

    def test_effective_duration_from_explicit_seconds(self):
        job = PrintJob.objects.create(printer=self.printer, duration_s=7200)
        self.assertEqual(job.effective_duration_s, 7200)
        self.assertEqual(job.duration_hours, 2.0)

    def test_effective_duration_derived_from_start_end(self):
        start = timezone_now()
        job = PrintJob.objects.create(
            printer=self.printer,
            started_at=start,
            ended_at=start + timedelta(hours=3),
        )
        self.assertEqual(job.effective_duration_s, 3 * 3600)


class PrintJobConsumptionTests(TestCase):
    """complete_job decrements percent_remaining and depletes via items.deplete."""

    def setUp(self):
        printer_product = Printer.objects.create(
            name="X1C", upc="9100000000001", num_extruders=1
        )
        self.printer = InventoryItem.objects.create(
            product=printer_product, serial_number="PR-2"
        )
        self.mat = Material.objects.create(name="PLA")
        # 1 kg spool → 1000 g full.
        self.fil = Filament.objects.create(
            name="PLA Blue",
            upc="9100000000002",
            material=self.mat,
            weight=Decimal("1.00"),
        )

    def _spool(self, percent=Decimal("100")):
        return InventoryItem.objects.create(product=self.fil, percent_remaining=percent)

    def test_grams_decrement_partial(self):
        spool = self._spool()
        job = PrintJob.objects.create(printer=self.printer)
        PrintJobFilament.objects.create(
            job=job, item=spool, grams_used=Decimal("250.00")
        )
        depleted = printjobs.complete_job(job)
        spool.refresh_from_db()
        # 250 g of a 1000 g spool = 25% used → 75% remaining.
        self.assertEqual(spool.percent_remaining, Decimal("75.00"))
        self.assertEqual(spool.status, InventoryItem.Status.NEW)
        self.assertEqual(depleted, [])

    def test_percent_used_fallback_when_no_weight(self):
        no_weight_fil = Filament.objects.create(
            name="PLA NW", upc="9100000000003", material=self.mat, weight=None
        )
        spool = InventoryItem.objects.create(
            product=no_weight_fil, percent_remaining=Decimal("100")
        )
        job = PrintJob.objects.create(printer=self.printer)
        PrintJobFilament.objects.create(
            job=job, item=spool, percent_used=Decimal("40.00")
        )
        printjobs.complete_job(job)
        spool.refresh_from_db()
        self.assertEqual(spool.percent_remaining, Decimal("60.00"))

    def test_spool_hitting_zero_is_depleted_via_service(self):
        spool = self._spool(percent=Decimal("20"))
        job = PrintJob.objects.create(printer=self.printer)
        # 250 g = 25% > remaining 20% → drives below zero → deplete.
        PrintJobFilament.objects.create(
            job=job, item=spool, grams_used=Decimal("250.00")
        )
        depleted = printjobs.complete_job(job)
        spool.refresh_from_db()
        self.assertEqual(spool.status, InventoryItem.Status.DEPLETED)
        self.assertEqual(spool.percent_remaining, Decimal("0"))
        self.assertIsNone(spool.location_id)
        self.assertIsNotNone(spool.date_depleted)
        self.assertEqual(depleted, [spool])

    def test_completion_is_idempotent(self):
        spool = self._spool()
        job = PrintJob.objects.create(printer=self.printer)
        PrintJobFilament.objects.create(
            job=job, item=spool, grams_used=Decimal("100.00")
        )
        printjobs.complete_job(job)
        job.refresh_from_db()
        self.assertTrue(job.completed)
        # A second call must not decrement again.
        printjobs.complete_job(job)
        spool.refresh_from_db()
        self.assertEqual(spool.percent_remaining, Decimal("90.00"))

    def test_already_depleted_spool_is_skipped(self):
        spool = self._spool()
        items.deplete(spool)
        job = PrintJob.objects.create(printer=self.printer)
        PrintJobFilament.objects.create(
            job=job, item=spool, grams_used=Decimal("100.00")
        )
        depleted = printjobs.complete_job(job)
        spool.refresh_from_db()
        # Still depleted, percent untouched (was set to 0 by deplete? no — deplete
        # doesn't zero percent), but the line is skipped entirely.
        self.assertEqual(spool.status, InventoryItem.Status.DEPLETED)
        self.assertEqual(depleted, [])

    def test_ended_at_stamped_on_completion(self):
        spool = self._spool()
        job = PrintJob.objects.create(printer=self.printer)
        PrintJobFilament.objects.create(
            job=job, item=spool, grams_used=Decimal("50.00")
        )
        self.assertIsNone(job.ended_at)
        printjobs.complete_job(job)
        job.refresh_from_db()
        self.assertIsNotNone(job.ended_at)


class PrinterUtilizationTests(TestCase):
    """DB-aggregated utilization: hours, success %, kg by material."""

    def setUp(self):
        printer_product = Printer.objects.create(
            name="X1C", upc="9200000000001", num_extruders=1
        )
        self.printer = InventoryItem.objects.create(
            product=printer_product, serial_number="PR-3"
        )
        self.mat = Material.objects.create(name="PLA")
        self.fil = Filament.objects.create(
            name="PLA Green",
            upc="9200000000002",
            material=self.mat,
            color="Green",
            color_family="GREEN",
            weight=Decimal("1.00"),
        )
        # 3 jobs: 2 success, 1 failed. Hours 1 + 2 + 0.5 = 3.5. Grams 100+200+50.
        for dur, res, grams in [
            (3600, PrintJob.Result.SUCCESS, Decimal("100")),
            (7200, PrintJob.Result.SUCCESS, Decimal("200")),
            (1800, PrintJob.Result.FAILED, Decimal("50")),
        ]:
            j = PrintJob.objects.create(
                printer=self.printer, duration_s=dur, result=res
            )
            spool = InventoryItem.objects.create(product=self.fil)
            PrintJobFilament.objects.create(job=j, item=spool, grams_used=grams)

    def test_printer_utilization_aggregations(self):
        stats = printjobs.printer_utilization(self.printer)
        self.assertEqual(stats["jobs"], 3)
        self.assertEqual(stats["hours"], 3.5)
        self.assertEqual(stats["success"], 2)
        self.assertEqual(stats["success_rate"], round(2 / 3 * 100, 1))
        self.assertEqual(stats["grams"], 350.0)
        self.assertEqual(stats["kg"], 0.35)

    def test_consumption_by_material(self):
        rows = printjobs.consumption_by_material()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["material"], "PLA")
        self.assertEqual(rows[0]["color"], "Green")
        self.assertEqual(rows[0]["grams"], 350.0)

    def test_utilization_summary_row_per_printer(self):
        rows = printjobs.utilization_summary()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["printer_id"], self.printer.id)
        self.assertEqual(row["jobs"], 3)
        self.assertEqual(row["hours"], 3.5)
        self.assertEqual(row["kg"], 0.35)


class PrintJobViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="pj", password="pass")
        self.client.login(username="pj", password="pass")
        printer_product = Printer.objects.create(
            name="X1C", upc="9300000000001", num_extruders=1
        )
        self.printer = InventoryItem.objects.create(
            product=printer_product, serial_number="PR-4"
        )
        self.mat = Material.objects.create(name="PLA")
        self.fil = Filament.objects.create(
            name="PLA Red",
            upc="9300000000002",
            material=self.mat,
            weight=Decimal("1.00"),
        )
        self.spool = InventoryItem.objects.create(product=self.fil)

    def test_utilization_view_renders(self):
        resp = self.client.get(reverse("printer_utilization"))
        self.assertEqual(resp.status_code, 200)

    def test_print_job_list_renders(self):
        PrintJob.objects.create(printer=self.printer, name="a.3mf", duration_s=3600)
        resp = self.client.get(reverse("print_job_list"))
        self.assertEqual(resp.status_code, 200)

    def test_create_view_renders(self):
        resp = self.client.get(reverse("print_job_create"))
        self.assertEqual(resp.status_code, 200)

    def test_create_job_with_filament_line_and_complete(self):
        resp = self.client.post(
            reverse("print_job_create"),
            {
                "printer": self.printer.pk,
                "name": "cube.3mf",
                "duration_s": 3600,
                "result": PrintJob.Result.SUCCESS,
                "filaments-TOTAL_FORMS": "1",
                "filaments-INITIAL_FORMS": "0",
                "filaments-MIN_NUM_FORMS": "0",
                "filaments-MAX_NUM_FORMS": "1000",
                "filaments-0-item": self.spool.pk,
                "filaments-0-grams_used": "500.00",
            },
        )
        self.assertEqual(resp.status_code, 302)
        job = PrintJob.objects.get(name="cube.3mf")
        self.assertTrue(job.completed)
        self.spool.refresh_from_db()
        # 500 g of a 1 kg spool = 50% used.
        self.assertEqual(self.spool.percent_remaining, Decimal("50.00"))

    def test_per_printer_utilization_view(self):
        PrintJob.objects.create(printer=self.printer, duration_s=3600)
        resp = self.client.get(
            reverse("printer_utilization_detail", args=[self.printer.pk])
        )
        self.assertEqual(resp.status_code, 200)

    def test_login_required(self):
        self.client.logout()
        resp = self.client.get(reverse("print_job_list"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.url)


# Phase 14 — Procurement & receiving
# ---------------------------------------------------------------------------

from decimal import Decimal  # noqa: E402

from . import procurement  # noqa: E402
from .models import (  # noqa: E402
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseReceipt,
    PurchaseReceiptLine,
    Supplier,
)


class ProcurementModelTests(TestCase):
    """Model creation, relationships, and computed properties."""

    def setUp(self):
        self.supplier = Supplier.objects.create(name="Acme Filament")
        self.product = Filament.objects.create(name="PLA Proc", upc="9500000000001")
        self.po = PurchaseOrder.objects.create(supplier=self.supplier)

    def test_supplier_unique_name(self):
        from django.db import IntegrityError

        with self.assertRaises(IntegrityError):
            Supplier.objects.create(name="Acme Filament")

    def test_order_default_status_draft(self):
        self.assertEqual(self.po.status, PurchaseOrder.Status.DRAFT)

    def test_line_relationships_and_totals(self):
        line = PurchaseOrderLine.objects.create(
            order=self.po,
            product=self.product,
            qty_ordered=4,
            unit_cost=Decimal("19.99"),
        )
        self.assertEqual(line.order, self.po)
        self.assertEqual(list(self.po.lines.all()), [line])
        self.assertEqual(line.line_total, Decimal("79.96"))
        self.assertEqual(line.qty_outstanding, 4)
        self.assertEqual(line.received_total, Decimal("0"))

    def test_qty_outstanding_never_negative(self):
        line = PurchaseOrderLine.objects.create(
            order=self.po,
            product=self.product,
            qty_ordered=2,
            qty_received=5,
            unit_cost=Decimal("1.00"),
        )
        self.assertEqual(line.qty_outstanding, 0)

    def test_track_individually_defaults_true(self):
        line = PurchaseOrderLine.objects.create(
            order=self.po, product=self.product, unit_cost=Decimal("1.00")
        )
        self.assertTrue(line.track_individually)

    def test_order_grand_total_includes_shipping_and_tax(self):
        self.po.shipping_cost = Decimal("5.00")
        self.po.tax = Decimal("2.50")
        self.po.save()
        PurchaseOrderLine.objects.create(
            order=self.po,
            product=self.product,
            qty_ordered=2,
            unit_cost=Decimal("10.00"),
        )
        self.assertEqual(self.po.lines_subtotal, Decimal("20.00"))
        self.assertEqual(self.po.grand_total, Decimal("27.50"))

    def test_receipt_and_receipt_line_relationships(self):
        line = PurchaseOrderLine.objects.create(
            order=self.po, product=self.product, unit_cost=Decimal("1.00")
        )
        receipt = PurchaseReceipt.objects.create(order=self.po)
        rl = PurchaseReceiptLine.objects.create(
            receipt=receipt, order_line=line, qty_received=1
        )
        self.assertEqual(receipt.order, self.po)
        self.assertEqual(list(self.po.receipts.all()), [receipt])
        self.assertEqual(rl.order_line, line)
        self.assertEqual(list(line.receipt_lines.all()), [rl])
        self.assertEqual(list(receipt.lines.all()), [rl])

    def test_attachment_field_is_inert_and_optional(self):
        """The FileField exists for forward-compat but must be blank/null-able and
        require no MEDIA settings to be saved (it is never populated yet)."""
        receipt = PurchaseReceipt.objects.create(order=self.po)
        self.assertFalse(receipt.attachment)  # falsy empty FieldFile

    def test_deleting_po_keeps_item_cost_history(self):
        """source_line is SET_NULL: deleting the PO must not erase an item's
        unit_cost (the whole point of denormalizing cost onto the item)."""
        line = PurchaseOrderLine.objects.create(
            order=self.po, product=self.product, unit_cost=Decimal("12.34")
        )
        item = InventoryItem.objects.create(
            product=self.product, unit_cost=Decimal("12.34"), source_line=line
        )
        self.po.delete()
        item.refresh_from_db()
        self.assertIsNone(item.source_line_id)
        self.assertEqual(item.unit_cost, Decimal("12.34"))


class NoMediaSettingsTest(TestCase):
    def test_no_media_root_configured(self):
        """The deferred upload infra must NOT be wired: settings.py must not set a
        MEDIA_ROOT, so uploads have nowhere to land and the FileField stays inert.
        (Django's framework default MEDIA_ROOT is '' / MEDIA_URL is '/', both
        unusable for serving uploads — that is exactly the inert state we want.)"""
        from django.conf import settings

        self.assertFalse(getattr(settings, "MEDIA_ROOT", ""))

    def test_settings_module_does_not_define_media(self):
        """Guard against someone wiring MEDIA_ROOT/MEDIA_URL into settings.py as
        part of this change (the infra is deferred to James)."""
        import inspect

        from django.conf import settings as dj_settings

        source = inspect.getsource(
            __import__(dj_settings.SETTINGS_MODULE, fromlist=[""])
        )
        self.assertNotIn("MEDIA_ROOT", source)
        self.assertNotIn("MEDIA_URL", source)


class ProcurementReceiveTests(TestCase):
    """Receiving mints items at the receiving rack via move_to and reconciles."""

    def setUp(self):
        self.supplier = Supplier.objects.create(name="Bolt Depot")
        self.spool = Filament.objects.create(name="PETG Recv", upc="9500000000010")
        self.screw = Hardware.objects.create(name="M3 Screws", upc="9500000000020")
        self.rack = Location.objects.create(
            name="Receiving Rack Leaf",
            kind=Location.Kind.SHELF,
            default_status=InventoryItem.Status.NEW,
        )
        self.po = PurchaseOrder.objects.create(
            supplier=self.supplier, status=PurchaseOrder.Status.ORDERED
        )
        self.spool_line = PurchaseOrderLine.objects.create(
            order=self.po,
            product=self.spool,
            qty_ordered=2,
            unit_cost=Decimal("24.50"),
            track_individually=True,
        )
        self.screw_line = PurchaseOrderLine.objects.create(
            order=self.po,
            product=self.screw,
            qty_ordered=100,
            unit_cost=Decimal("0.05"),
            track_individually=False,
        )
        self.receipt = PurchaseReceipt.objects.create(order=self.po)

    def test_receive_tracked_mints_item_with_cost_and_source(self):
        result = procurement.receive_scan(self.receipt, "9500000000010", self.rack)
        self.assertTrue(result.tracked)
        item = result.item
        item.refresh_from_db()
        self.assertEqual(item.location_id, self.rack.id)
        self.assertEqual(item.unit_cost, Decimal("24.50"))
        self.assertEqual(item.source_line_id, self.spool_line.id)
        # status derived from the rack default via move_to
        self.assertEqual(item.status, InventoryItem.Status.NEW)
        self.spool_line.refresh_from_db()
        self.assertEqual(self.spool_line.qty_received, 1)
        # a receipt line was recorded
        self.assertEqual(
            PurchaseReceiptLine.objects.filter(order_line=self.spool_line).count(), 1
        )

    def test_receive_cost_only_mints_no_item(self):
        before = InventoryItem.objects.count()
        result = procurement.receive_scan(self.receipt, "9500000000020", self.rack)
        self.assertFalse(result.tracked)
        self.assertIsNone(result.item)
        self.assertEqual(InventoryItem.objects.count(), before)
        self.screw_line.refresh_from_db()
        self.assertEqual(self.screw_line.qty_received, 1)

    def test_po_status_partial_then_received(self):
        procurement.receive_scan(self.receipt, "9500000000010", self.rack)
        self.po.refresh_from_db()
        self.assertEqual(self.po.status, PurchaseOrder.Status.PARTIAL)
        # finish both lines
        procurement.receive_scan(self.receipt, "9500000000010", self.rack)
        for _ in range(100):
            procurement.receive_scan(self.receipt, "9500000000020", self.rack)
        self.po.refresh_from_db()
        self.assertEqual(self.po.status, PurchaseOrder.Status.RECEIVED)

    def test_unknown_upc_raises(self):
        with self.assertRaises(procurement.ProcurementError):
            procurement.receive_scan(self.receipt, "0000000000000", self.rack)

    def test_fully_received_line_has_no_open_line(self):
        self.spool_line.qty_received = 2
        self.spool_line.save()
        with self.assertRaises(procurement.ProcurementError):
            procurement.receive_scan(self.receipt, "9500000000010", self.rack)

    def test_ambiguous_open_line_raises(self):
        # second open line for the same product
        PurchaseOrderLine.objects.create(
            order=self.po,
            product=self.spool,
            qty_ordered=1,
            unit_cost=Decimal("20.00"),
        )
        with self.assertRaises(procurement.ProcurementError):
            procurement.receive_scan(self.receipt, "9500000000010", self.rack)

    def test_no_location_raises(self):
        with self.assertRaises(procurement.ProcurementError):
            procurement.receive_scan(self.receipt, "9500000000010", None)

    def test_receive_into_container_rejected(self):
        rack = Location.objects.create(name="Container Rack", kind=Location.Kind.RACK)
        with self.assertRaises(procurement.ProcurementError):
            procurement.receive_scan(self.receipt, "9500000000010", rack)


class ProcurementReconcileTests(TestCase):
    def setUp(self):
        self.supplier = Supplier.objects.create(name="Recon Supplier")
        self.spool = Filament.objects.create(name="PLA Recon", upc="9500000000030")
        self.po = PurchaseOrder.objects.create(
            supplier=self.supplier, status=PurchaseOrder.Status.ORDERED
        )
        self.line = PurchaseOrderLine.objects.create(
            order=self.po,
            product=self.spool,
            qty_ordered=5,
            qty_received=2,
            unit_cost=Decimal("10.00"),
        )

    def test_reconcile_totals(self):
        data = procurement.reconcile(self.po)
        self.assertEqual(data["qty_ordered"], 5)
        self.assertEqual(data["qty_received"], 2)
        self.assertEqual(data["qty_outstanding"], 3)
        self.assertEqual(data["subtotal"], Decimal("50.00"))
        self.assertEqual(data["received_value"], Decimal("20.00"))
        self.assertEqual(len(data["lines"]), 1)
        self.assertEqual(data["lines"][0]["outstanding"], 3)


class ProcurementSpendTests(TestCase):
    """Spend report unions tracked unit_costs with cost-only line totals."""

    def setUp(self):
        self.supplier = Supplier.objects.create(name="Spend Supplier")
        self.spool = Filament.objects.create(name="PLA Spend", upc="9500000000040")
        self.screw = Hardware.objects.create(name="Screws Spend", upc="9500000000050")
        self.po = PurchaseOrder.objects.create(
            supplier=self.supplier, status=PurchaseOrder.Status.ORDERED
        )
        # cost-only line: 50 received of 100 ordered @ 0.10 => 5.00 spend
        self.screw_line = PurchaseOrderLine.objects.create(
            order=self.po,
            product=self.screw,
            qty_ordered=100,
            qty_received=50,
            unit_cost=Decimal("0.10"),
            track_individually=False,
        )
        # two tracked items @ 24.50 and 30.00 => 54.50 tracked spend
        InventoryItem.objects.create(product=self.spool, unit_cost=Decimal("24.50"))
        InventoryItem.objects.create(product=self.spool, unit_cost=Decimal("30.00"))
        # an item with no unit_cost must not count
        InventoryItem.objects.create(product=self.spool)

    def test_spend_unions_tracked_and_consumable(self):
        summary = procurement.spend_summary()
        self.assertEqual(summary["tracked_spend"], Decimal("54.50"))
        self.assertEqual(summary["tracked_count"], 2)
        # cost-only counts RECEIVED units only: 50 * 0.10 = 5.00 (not 100 ordered)
        self.assertEqual(summary["consumable_spend"], Decimal("5.00"))
        self.assertEqual(summary["total_spend"], Decimal("59.50"))

    def test_consumable_spend_ignores_zero_received_lines(self):
        PurchaseOrderLine.objects.create(
            order=self.po,
            product=self.screw,
            qty_ordered=10,
            qty_received=0,
            unit_cost=Decimal("1.00"),
            track_individually=False,
        )
        summary = procurement.spend_summary()
        self.assertEqual(summary["consumable_spend"], Decimal("5.00"))


class ProcurementViewTests(TestCase):
    """Views render and the receiving scan endpoint works end to end."""

    def setUp(self):
        self.user = User.objects.create_user(username="proc", password="pw")
        self.client = Client()
        self.client.login(username="proc", password="pw")
        self.supplier = Supplier.objects.create(name="View Supplier")
        self.spool = Filament.objects.create(name="PLA View", upc="9500000000060")
        self.rack = Location.objects.create(
            name="View Rack",
            kind=Location.Kind.SHELF,
            default_status=InventoryItem.Status.NEW,
        )
        self.po = PurchaseOrder.objects.create(
            supplier=self.supplier, status=PurchaseOrder.Status.ORDERED
        )
        self.line = PurchaseOrderLine.objects.create(
            order=self.po,
            product=self.spool,
            qty_ordered=2,
            unit_cost=Decimal("15.00"),
        )
        self.receipt = PurchaseReceipt.objects.create(order=self.po)

    def test_po_list_renders(self):
        resp = self.client.get(reverse("po_list"))
        self.assertEqual(resp.status_code, 200)

    def test_po_detail_renders(self):
        resp = self.client.get(reverse("po_detail", args=[self.po.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_spend_report_renders(self):
        resp = self.client.get(reverse("spend_report"))
        self.assertEqual(resp.status_code, 200)

    def test_receiving_console_renders(self):
        resp = self.client.get(reverse("receiving_console", args=[self.po.pk]))
        self.assertEqual(resp.status_code, 200)

    @override_settings(ENABLE_BARCODE_PRINTING=False)
    def test_receiving_scan_creates_item(self):
        resp = self.client.post(
            reverse("receiving_scan", args=[self.po.pk]),
            {"code": "9500000000060", "location": self.rack.pk},
        )
        self.assertIn(resp.status_code, (200, 302))
        self.line.refresh_from_db()
        self.assertEqual(self.line.qty_received, 1)
        item = InventoryItem.objects.filter(source_line=self.line).first()
        self.assertIsNotNone(item)
        self.assertEqual(item.unit_cost, Decimal("15.00"))

    def test_views_require_login(self):
        self.client.logout()
        for name, args in (
            ("po_list", []),
            ("po_detail", [self.po.pk]),
            ("spend_report", []),
            ("receiving_console", [self.po.pk]),
        ):
            resp = self.client.get(reverse(name, args=args))
            self.assertEqual(resp.status_code, 302)
            self.assertIn("/login", resp.url)


class SqlitePragmaUnitTests(TestCase):
    """The WAL receiver is exercised against a real *file* DB because WAL is not
    observable on an in-memory DB (which always reports journal_mode='memory')."""

    def test_pragmas_enable_wal_on_file_db(self):
        import os
        import sqlite3
        import tempfile

        from inventory.db_pragmas import enable_sqlite_pragmas

        with tempfile.TemporaryDirectory() as d:
            raw = sqlite3.connect(os.path.join(d, "t.sqlite3"))

            class FakeConn:
                vendor = "sqlite"

                def cursor(self):
                    return raw.cursor()

            enable_sqlite_pragmas(sender=None, connection=FakeConn())

            cur = raw.cursor()
            self.assertEqual(
                cur.execute("PRAGMA journal_mode;").fetchone()[0].lower(), "wal"
            )
            self.assertEqual(
                cur.execute("PRAGMA synchronous;").fetchone()[0], 1
            )  # NORMAL
            self.assertEqual(cur.execute("PRAGMA busy_timeout;").fetchone()[0], 5000)
            raw.close()

    def test_receiver_is_noop_on_non_sqlite(self):
        from inventory.db_pragmas import enable_sqlite_pragmas

        class FakeConn:
            vendor = "postgresql"

            def cursor(self):
                raise AssertionError("must not touch cursor on non-sqlite")

        enable_sqlite_pragmas(sender=None, connection=FakeConn())


class SqlitePragmaIntegrationTests(TestCase):
    def test_synchronous_normal_applied_to_live_connection(self):
        """Proves the connection_created receiver is wired and fires for real
        connections: it sets synchronous=NORMAL (1), whereas Django's default
        leaves it FULL (2). (busy_timeout is a poor probe here — Django already
        defaults it to 5000. journal_mode can't be asserted either: the test DB
        is in-memory and always reports 'memory'. WAL is verified in the prod
        runbook.)"""
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("PRAGMA synchronous;")
            self.assertEqual(cursor.fetchone()[0], 1)


class TelemetryModelTests(TestCase):
    def test_models_create_and_constrain(self):
        from inventory.models import (
            AMSChannelState,
            AMSUnitState,
            PrinterDevice,
            PrinterState,
            TelemetrySample,
        )

        dev = PrinterDevice.objects.create(
            serial="0948CD531200537", name="H2Laser", ip_address="10.10.30.11"
        )
        PrinterState.objects.create(device=dev, gcode_state="RUNNING", mc_percent=42)
        AMSUnitState.objects.create(device=dev, ams_index=0, humidity=5)
        AMSChannelState.objects.create(
            device=dev, ams_index=0, tray_index=0, tray_type="PETG", remain_pct=-1
        )
        TelemetrySample.objects.create(
            device=dev, ts=timezone_now(), gcode_state="RUNNING"
        )
        self.assertEqual(dev.state.mc_percent, 42)
        self.assertEqual(dev.ams_channels.first().remain_pct, -1)  # -1 preserved
        from django.db import IntegrityError, transaction

        with self.assertRaises(IntegrityError):  # unique_together(device, ams_index)
            with transaction.atomic():
                AMSUnitState.objects.create(device=dev, ams_index=0)


class TelemetryHelperTests(TestCase):
    def test_coercions(self):
        from decimal import Decimal

        from inventory.telemetry import _to_decimal, _to_int, _to_str

        self.assertEqual(_to_int("100"), 100)
        self.assertEqual(_to_int(69), 69)
        self.assertEqual(_to_int("-1"), -1)
        self.assertIsNone(_to_int(""))
        self.assertIsNone(_to_int(None))
        self.assertEqual(_to_decimal("24.6"), Decimal("24.6"))
        self.assertEqual(_to_decimal(23.0), Decimal("23.0"))
        self.assertIsNone(_to_decimal(""))
        self.assertEqual(_to_str(None), "")
        self.assertEqual(_to_str("PETG"), "PETG")

    def test_should_sample(self):
        from datetime import timedelta

        from inventory.models import PrinterDevice, TelemetrySample
        from inventory.telemetry import should_sample

        now = timezone_now()
        self.assertTrue(should_sample(None, "IDLE", now=now))  # first ever
        dev = PrinterDevice.objects.create(serial="s", name="n", ip_address="10.0.0.1")
        prev = TelemetrySample.objects.create(device=dev, ts=now, gcode_state="RUNNING")
        self.assertFalse(
            should_sample(prev, "RUNNING", now=now)
        )  # same state, no interval
        self.assertTrue(should_sample(prev, "FINISH", now=now))  # state transition
        self.assertTrue(
            should_sample(prev, "RUNNING", now=now + timedelta(seconds=301))
        )  # interval while running
        self.assertFalse(
            should_sample(prev, "RUNNING", now=now + timedelta(seconds=120))
        )  # running but under interval
