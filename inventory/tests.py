from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User

from .models import Filament, InventoryItem, Location, Material


class BulkUpdateViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="tester", password="pass")
        self.client.login(username="tester", password="pass")
        self.location_a = Location.objects.create(name="Shelf A", default_status=InventoryItem.Status.NEW)
        self.location_b = Location.objects.create(name="Dry Storage", default_status=InventoryItem.Status.STORED)
        product = Filament.objects.create(name="PLA Red", upc="0000000000001")
        self.item1 = InventoryItem.objects.create(product=product, location=self.location_a)
        self.item2 = InventoryItem.objects.create(product=product, location=self.location_a)
        self.item3 = InventoryItem.objects.create(product=product, location=self.location_b)
        self.url = reverse("bulk_update")

    def _post(self, data):
        return self.client.post(self.url, data)

    def test_get_redirects_to_search(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse("inventory_search"))

    def test_requires_login(self):
        self.client.logout()
        response = self._post({"item_ids": [self.item1.pk], "bulk_status": str(InventoryItem.Status.DEPLETED)})
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
        self._post({
            "item_ids": [self.item1.pk, self.item2.pk],
            "bulk_status": str(InventoryItem.Status.DEPLETED),
        })
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
        self._post({
            "item_ids": [self.item1.pk],
            "bulk_status": str(InventoryItem.Status.DEPLETED),
            "bulk_location": str(self.location_b.pk),
        })
        self.item1.refresh_from_db()
        self.assertIsNone(self.item1.location)

    def test_bulk_status_sold(self):
        self._post({
            "item_ids": [self.item1.pk],
            "bulk_status": str(InventoryItem.Status.SOLD),
        })
        self.item1.refresh_from_db()
        self.assertEqual(self.item1.status, InventoryItem.Status.SOLD)
        self.assertIsNotNone(self.item1.date_sold)
        self.assertIsNone(self.item1.location)

    def test_bulk_location(self):
        self._post({
            "item_ids": [self.item1.pk, self.item2.pk],
            "bulk_location": str(self.location_b.pk),
        })
        self.item1.refresh_from_db()
        self.item2.refresh_from_db()
        self.assertEqual(self.item1.location, self.location_b)
        self.assertEqual(self.item2.location, self.location_b)

    def test_bulk_shipment(self):
        self._post({
            "item_ids": [self.item1.pk, self.item2.pk],
            "bulk_shipment": "1Z999AA10123456784",
        })
        self.item1.refresh_from_db()
        self.item2.refresh_from_db()
        self.assertEqual(self.item1.shipment, "1Z999AA10123456784")
        self.assertEqual(self.item2.shipment, "1Z999AA10123456784")

    def test_unknown_ids_silently_skipped(self):
        response = self._post({
            "item_ids": [99999],
            "bulk_status": str(InventoryItem.Status.DEPLETED),
        })
        # Should redirect (not 404)
        self.assertEqual(response.status_code, 302)

    def test_success_message_shows_count(self):
        response = self._post({
            "item_ids": [self.item1.pk, self.item2.pk],
            "bulk_status": str(InventoryItem.Status.IN_USE),
        })
        msgs = list(response.wsgi_request._messages)
        self.assertTrue(any("2" in str(m) for m in msgs))

    def test_filter_params_preserved_in_redirect(self):
        response = self._post({
            "item_ids": [self.item1.pk],
            "bulk_status": str(InventoryItem.Status.DEPLETED),
            "sku": "BPR-001",
            "name": "PLA Red",
        })
        self.assertIn("sku=BPR-001", response["Location"])
        self.assertIn("name=PLA+Red", response["Location"])

    def test_invalid_status_redirects_with_error(self):
        response = self._post({
            "item_ids": [self.item1.pk],
            "bulk_status": "999",
        })
        self.assertRedirects(response, reverse("inventory_search"))
        msgs = list(response.wsgi_request._messages)
        self.assertTrue(any("Invalid" in str(m) for m in msgs))

    def test_unmodified_items_unchanged(self):
        """item3 was not selected — must not be touched."""
        self._post({
            "item_ids": [self.item1.pk],
            "bulk_status": str(InventoryItem.Status.DEPLETED),
        })
        self.item3.refresh_from_db()
        self.assertEqual(self.item3.status, InventoryItem.Status.STORED)
        self.assertEqual(self.item3.location, self.location_b)

    def test_explicit_status_not_overridden_by_location_default(self):
        """Explicit bulk_status must survive save() even when bulk_location is also set.
        location_b.default_status = STORED; user explicitly requests IN_USE."""
        self._post({
            "item_ids": [self.item1.pk],
            "bulk_status": str(InventoryItem.Status.IN_USE),
            "bulk_location": str(self.location_b.pk),
        })
        self.item1.refresh_from_db()
        self.assertEqual(self.item1.status, InventoryItem.Status.IN_USE)
        self.assertEqual(self.item1.location, self.location_b)


class FilamentSummaryViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="tester2", password="pass")
        self.client.login(username="tester2", password="pass")
        self.loc = Location.objects.create(name="Shelf", default_status=InventoryItem.Status.NEW)
        self.mat = Material.objects.create(name="PLA", material_type="")
        # 3 PLA rolls + 1 PETG roll — cards should sort by roll count, PLA first
        pla_black = Filament.objects.create(
            name="PLA Black", upc="1000000000001",
            material=self.mat, color="Black", color_family="BLACK",
            hex_code="",
        )
        petg_mat = Material.objects.create(name="PETG", material_type="")
        petg_white = Filament.objects.create(
            name="PETG White", upc="1000000000002",
            material=petg_mat, color="White", color_family="WHITE",
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
        black_swatch = next(s for s in pla_card["visible_swatches"] if s["family"] == "BLACK")
        self.assertEqual(black_swatch["hex"], "#000000")

    def test_row_hex_falls_back_to_family_hex_when_missing(self):
        """Row with no hex_code should get a fallback from COLOR_FAMILY_HEX."""
        resp = self.client.get(self.url)
        rows = resp.context["rows"]
        black_row = next(r for r in rows if r["color"] == "Black")
        # hex_code is empty in the DB, but color_family is BLACK → fallback expected
        self.assertEqual(black_row["hex_code"], "#000000")
