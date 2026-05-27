from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import (
    AMS,
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
