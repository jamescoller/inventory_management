import logging
import re
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlencode

import openpyxl
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Count, Max, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.utils.html import escape
from django.utils.timezone import localtime
from django.utils.timezone import now as timezone_now
from django.views.generic import CreateView, TemplateView, UpdateView, View

from . import audit
from .barcode_utils import generate_and_print_barcode
from .forms import (
    AMSForm,
    DryerForm,
    FilamentForm,
    HardwareForm,
    InventoryEditForm,
    InventoryItemForm,
    PrinterForm,
    UserRegisterForm,
)
from .models import (
    AMS,
    AuditEvent,
    AuditSession,
    AuditUnknownScan,
    Dryer,
    Filament,
    Hardware,
    InventoryItem,
    Location,
    Material,
    Printer,
    Product,
)

logger = logging.getLogger("inventory")

# InventoryItem statuses that count as "active" (not consumed or sold)
_ACTIVE_STATUSES = [
    InventoryItem.Status.NEW,
    InventoryItem.Status.IN_USE,
    InventoryItem.Status.DRYING,
    InventoryItem.Status.STORED,
]

# Representative hex color for each filament color family
COLOR_FAMILY_HEX = {
    "RED": "#e74c3c",
    "ORANGE": "#e67e22",
    "YELLOW": "#f1c40f",
    "GREEN": "#27ae60",
    "BLUE": "#2980b9",
    "PURPLE": "#8e44ad",
    "PINK": "#fd79a8",
    "BROWN": "#8B4513",
    "BLACK": "#000000",
    "GRAY": "#95a5a6",
    "WHITE": "#ecf0f1",
    "TRANSLUCENT": "#dfe6e9",
}

FAMILY_ORDER = [
    "RED",
    "ORANGE",
    "YELLOW",
    "GREEN",
    "BLUE",
    "PURPLE",
    "PINK",
    "BROWN",
    "BLACK",
    "GRAY",
    "WHITE",
    "TRANSLUCENT",
]

# ---- Barcode Writer Helpers --------


class PrintBarcodeView(LoginRequiredMixin, View):

    def get(self, request, item_id, mode):
        # 1. Get the item
        item = get_object_or_404(
            InventoryItem.objects.select_related("product"), id=item_id
        )

        try:
            # 2. Generate and print the barcode (returns PIL image)
            response = generate_and_print_barcode(item, mode)

            # 3. Return as HTTP response
            return response

        except Exception as e:
            return HttpResponse(f"Barcode generation failed: {str(e)}", status=500)

    def post(self, request, item_id, mode):
        item = get_object_or_404(InventoryItem, id=item_id)
        try:
            generate_and_print_barcode(item, mode)
        except Exception as e:
            logger.error(f"Barcode generation failed: {str(e)}")
            return HttpResponse(str(e), status=500)

        if request.headers.get("HX-Request"):
            html_body = render_to_string(
                "inventory/partials/print_confirmations.html",
                {
                    "item": item,
                    "mode": mode,
                },
            )
            html_wrapped = f'<div id="print-result" class="alert alert-success mt-2">{html_body}</div>'
            return HttpResponse(html_wrapped)

        return redirect("inventory_edit", item_id=item_id)


class BarcodeRedirectView(LoginRequiredMixin, View):
    def get(self, request, value):
        if value.startswith("INV-"):
            item_id = value.replace("INV-", "")
            return redirect("inventory_edit", item_id=item_id)
        if value.startswith("LOC-"):
            loc_id = value.replace("LOC-", "")
            location = Location.objects.filter(pk=loc_id).first()
            if location is None:
                return HttpResponse("Unknown location", status=404)
            # A scanned location barcode jumps into the audit console focused there.
            # Containers (AMS/dryer/rack) audit all their slots together.
            return redirect(f"{reverse('audit_console')}?loc={location.pk}")
        return HttpResponse("Invalid barcode", status=400)


class AboutView(TemplateView):
    template_name = "inventory/about.html"


class AddProductChoiceView(LoginRequiredMixin, CreateView):
    def get(self, request):
        upc = request.session.get("pending_inventory", {}).get("upc", "")
        return render(request, "inventory/add_product_choice.html", {"upc": upc})


def _expanded_location_ids(term):
    """Resolve a location search term to a set of Location ids, expanded to the
    full subtree of any matched container.

    Accepts a name fragment (case-insensitive) or a ``LOC-<id>`` code. So
    searching "AMS RP-1", a rack, or dry storage returns items in all child
    slots/shelves, not just items pinned to the container itself. Returns an
    empty set when nothing matches.
    """
    term = (term or "").strip()
    if not term:
        return set()
    loc_match = re.match(r"^LOC-(\d+)$", term, re.IGNORECASE)
    if loc_match:
        matched = Location.objects.filter(pk=int(loc_match.group(1)))
    else:
        matched = Location.objects.filter(name__icontains=term)
    ids = set()
    for loc in matched:
        ids |= loc.descendant_ids()
    return ids


class InventorySearchView(LoginRequiredMixin, View):
    def get(self, request):
        # Get search parameters from the query string
        sku = request.GET.get("sku", "")
        upc = request.GET.get("upc", "")
        name = request.GET.get("name", "")
        location = request.GET.get("location", "")
        serial_number = request.GET.get("serial_number", "")
        item_id = request.GET.get("item_id", "")

        # Check for INV_xxx pattern
        inv_pattern = re.match(r"^INV-(\d+)$", name.strip())
        if inv_pattern:
            item_id = inv_pattern.group(1)
            return redirect("inventory_edit", item_id=item_id)

        # Base queryset, excluding depleted items
        items = InventoryItem.objects.exclude(status=5).select_related(
            "product", "location"
        )

        # If there's a simple search from the navbar, search across multiple fields
        if name and not any([sku, upc, location, serial_number, item_id]):
            name_q = (
                Q(product__name__icontains=name)
                | Q(product__sku__icontains=name)
                | Q(product__upc__icontains=name)
                | Q(serial_number__icontains=name)
                | Q(id__icontains=name)
            )
            # Location dimension: expand a matched container to its whole subtree
            # (and support a typed LOC-<id>). Covers direct name matches too.
            loc_ids = _expanded_location_ids(name)
            if loc_ids:
                name_q |= Q(location_id__in=loc_ids)
            items = items.filter(name_q)
        else:
            # Apply specific filters
            if sku:
                items = items.filter(product__sku=sku)
            if upc:
                items = items.filter(product__upc=upc)
            if name:
                items = items.filter(product__name__icontains=name)
            if location:
                items = items.filter(location_id__in=_expanded_location_ids(location))
            if serial_number:
                items = items.filter(serial_number=serial_number)
            if item_id:
                items = items.filter(id=item_id)

        # Pass filtered items to the template
        context = {
            "items": items or InventoryItem.objects.none(),
            "search_values": {
                "sku": sku,
                "upc": upc,
                "name": name,
                "location": location,
                "serial_number": serial_number,
                "item_id": item_id,
            },
            "status_choices": InventoryItem.Status.choices,
            "locations": Location.objects.all().order_by("name"),
        }

        return render(request, "inventory/inventory_search.html", context)


class InventoryEditView(LoginRequiredMixin, UpdateView):
    def get(self, request, item_id):
        item = get_object_or_404(
            InventoryItem.objects.select_related("product"), id=item_id
        )
        form = InventoryEditForm(instance=item)
        product = item.product.get_real_instance()
        return render(
            request,
            "inventory/inventory_edit.html",
            {
                "form": form,
                "item": item,
                "product": product,
                "is_filament": isinstance(product, Filament),
            },
        )

    def post(self, request, item_id):
        item = get_object_or_404(InventoryItem, id=item_id)
        action = request.POST.get("action")

        # Handle depleted/sold actions
        if action in ["deplete", "sell"]:
            if action == "deplete":
                if hasattr(item, "mark_depleted"):
                    item.mark_depleted()
                    item.save()
                    messages.success(
                        request, f"Item '{item}' has been marked as depleted."
                    )
                else:
                    messages.error(request, "This item cannot be marked as depleted.")
            elif action == "sell":
                if hasattr(item, "mark_sold"):
                    item.mark_sold()
                    item.save()
                    messages.success(request, f"Item '{item}' has been marked as sold.")
                else:
                    messages.error(request, "This item cannot be marked as sold.")
            return redirect("inventory_edit", item_id=item_id)

        # Handle the regular form submission
        form = InventoryEditForm(request.POST, instance=item)  # Bind form with instance
        product = item.product.get_real_instance()
        base_ctx = {
            "form": form,
            "item": item,
            "product": product,
            "is_filament": isinstance(product, Filament),
        }

        if form.is_valid():
            new_location = form.cleaned_data["location"]
            warning = item.filament_drying_warning(new_location)

            if warning:
                level, message, needs_ack = warning

                if level == "error":
                    form.add_error("location", message)
                    return render(request, "inventory/inventory_edit.html", base_ctx)

                if needs_ack and not request.POST.get("acknowledged"):
                    return render(
                        request,
                        "inventory/inventory_edit.html",
                        {
                            **base_ctx,
                            "warning_level": level,
                            "warning_message": message,
                            "requires_ack": True,
                            "pending_location": new_location.id,
                        },
                    )

                if level == "info":
                    messages.info(request, message)
                elif level == "warning":
                    messages.warning(request, message)

            form.save()
            return redirect("inventory_search")
        else:
            # Form is not valid, render the page with errors
            return render(request, "inventory/inventory_edit.html", base_ctx)


class AddInventoryView(LoginRequiredMixin, CreateView):
    model = InventoryItem
    form_class = InventoryItemForm
    template_name = "inventory/item_form.html"
    success_url = reverse_lazy("add_inventory")

    def get_initial(self):
        initial = super().get_initial()
        # Drop a stale unknown_scan_id if the user navigated here directly.
        pending = self.request.session.get("pending_inventory")
        if pending and "unknown_scan_id" in pending and not self.request.GET.get("upc"):
            pending.pop("unknown_scan_id", None)
            self.request.session["pending_inventory"] = pending
        if InventoryItem.objects.exists():
            latest = InventoryItem.objects.order_by("-id").first()
            initial["shipment"] = latest.shipment
            initial["location"] = latest.location
        return initial

    def post(self, request, **kwargs):

        form = self.form_class(request.POST)

        if not form.is_valid():
            return self.form_invalid(form)

        upc = form.cleaned_data.get("upc")
        sku = form.cleaned_data.get("sku")
        shipment = form.cleaned_data.get("shipment")
        location = form.cleaned_data.get("location")

        if not upc and not sku:
            messages.error(request, "You must provide either a UPC or SKU.")
            return redirect("add_inventory")

        product = None

        if upc:
            product = Product.objects.filter(upc=upc).first()

        if product is None and sku:
            product = Product.objects.filter(sku=sku).first()

        # If still no product found, redirect to 'add_product_choice'
        if product is None:
            # Store scanned data temporarily in session
            request.session["pending_inventory"] = {
                "upc": upc,
                "sku": sku,
                "shipment": shipment,
                "location_id": location.id if location else None,
            }
            messages.warning(
                request,
                "No product found with that UPC or SKU. Please add the product before continuing.",
            )
            return redirect("add_product_choice")  # This is a new view we’ll create
            # messages.error(request, f"No product found with UPC: {upc}")
            # return redirect('add_inventory')

        # Create InventoryItem only if a product was found
        messages.info(
            request,
            f"Matched product: {product.name} (SKU: {product.sku}, UPC: {product.upc})",
        )

        new_item = InventoryItem.objects.create(
            product=product,
            shipment=shipment,
            location=location,
        )
        _resolve_pending_unknown(request, new_item)

        messages.success(request, f"Added {product.name} to inventory")
        logger.info(f"Added {product.name} to inventory")

        try:
            generate_and_print_barcode(new_item, mode="unique")
            # generate_and_print_barcode(new_item, mode="upc")
        except Exception as e:
            messages.warning(request, f"Label printing failed: {e}")
            logger.error(f"Label printing failed: {e}")

        # After successful item creation and label printing
        html = render_to_string(
            "inventory/partials/print_confirmations.html",
            {
                "item": new_item,
                "mode": "unique",
            },
        )
        messages.success(request, html)

        return redirect("add_inventory")

    def form_valid(self, form):
        response = super().form_valid(form)

        try:
            generate_and_print_barcode(self.object, mode="unique")
        except Exception as e:
            messages.error(self.request, f"Label print failed: {e}")
            logger.error(f"label printing failed: {e}")

        return response


class Index(TemplateView):
    template_name = "inventory/index.html"


MAX_BULK = 200


def _bulk_redirect_back(request):
    """Round-trip back to the search results, preserving the active filters."""
    filter_keys = (
        "sku",
        "upc",
        "name",
        "status",
        "location",
        "serial_number",
        "item_id",
    )
    params = {
        k: request.POST.get(k, "") for k in filter_keys if request.POST.get(k, "")
    }
    url = reverse("inventory_search")
    if params:
        url += "?" + urlencode(params)
    return redirect(url)


def _parse_bulk_item_ids(request):
    """Parse selected item ids from a bulk form. Returns ``(ids, redirect)`` where
    exactly one is truthy: a non-empty id list, or a redirect carrying an error
    message for the empty/invalid/too-many cases."""
    raw_ids = request.POST.getlist("item_ids")
    try:
        item_ids = [int(i) for i in raw_ids if str(i).strip()]
    except (ValueError, TypeError):
        messages.warning(request, "Invalid item selection.")
        return None, _bulk_redirect_back(request)
    if not item_ids:
        messages.warning(request, "No items selected.")
        return None, _bulk_redirect_back(request)
    if len(item_ids) > MAX_BULK:
        messages.error(request, f"Cannot act on more than {MAX_BULK} items at once.")
        return None, _bulk_redirect_back(request)
    return item_ids, None


class BulkReprintLabelsView(LoginRequiredMixin, View):
    """Reprint the INV-XXX barcode tags for the selected search results — used to
    replace missing or unreadable tags found during an audit."""

    def get(self, request):
        return redirect("inventory_search")

    def post(self, request):
        item_ids, early = _parse_bulk_item_ids(request)
        if early:
            return early

        items = list(
            InventoryItem.objects.filter(id__in=item_ids).select_related("product")
        )
        printed = 0
        failed = 0
        for item in items:
            try:
                generate_and_print_barcode(item, mode="unique")
                printed += 1
            except Exception as e:
                failed += 1
                logger.error(f"Reprint failed for INV-{item.id}: {e}")

        if printed:
            messages.success(
                request,
                f"Reprinted {printed} inventory tag{'' if printed == 1 else 's'}.",
            )
        if failed:
            messages.error(
                request,
                f"{failed} tag{'' if failed == 1 else 's'} failed to print — see logs.",
            )
        return _bulk_redirect_back(request)


class BulkUpdateView(LoginRequiredMixin, View):
    def get(self, request):
        return redirect("inventory_search")

    def post(self, request):
        item_ids, early = _parse_bulk_item_ids(request)
        if early:
            return early

        new_status_raw = request.POST.get("bulk_status", "").strip()
        new_location_id = request.POST.get("bulk_location", "").strip()
        new_shipment = request.POST.get("bulk_shipment", "").strip() or None

        if new_shipment and len(new_shipment) > 100:
            messages.error(request, "Shipment value is too long (max 100 characters).")
            return _bulk_redirect_back(request)

        new_status = None
        if new_status_raw:
            try:
                val = int(new_status_raw)
                InventoryItem.Status(val)  # raises ValueError if not a valid choice
                new_status = val
            except ValueError:
                messages.error(request, "Invalid status value.")
                return _bulk_redirect_back(request)

        new_location = None
        if new_location_id:
            try:
                new_location = Location.objects.get(pk=new_location_id)
            except Location.DoesNotExist:
                messages.error(request, "Invalid location.")
                return _bulk_redirect_back(request)
            if new_location.is_container:
                messages.error(
                    request,
                    f"{new_location.name} is a container and can't hold items.",
                )
                return _bulk_redirect_back(request)

        if new_status is None and new_location is None and new_shipment is None:
            messages.warning(request, "No fields selected — nothing was changed.")
            return _bulk_redirect_back(request)

        count = 0
        with transaction.atomic():
            for item in InventoryItem.objects.filter(id__in=item_ids):
                status_clears_location = False
                if new_status is not None:
                    item.status = new_status
                    item._skip_status_from_location = True
                    if new_status in (
                        InventoryItem.Status.DEPLETED,
                        InventoryItem.Status.SOLD,
                    ):
                        status_clears_location = True
                if new_location is not None and not status_clears_location:
                    item.location = new_location
                if new_shipment is not None:
                    item.shipment = new_shipment
                item.save()
                count += 1

        messages.success(request, f"Updated {count} item{'s' if count != 1 else ''}.")
        return _bulk_redirect_back(request)


class SignUpView(View):
    def get(self, request):
        form = UserRegisterForm()
        return render(request, "inventory/signup.html", {"form": form})

    def post(self, request):
        form = UserRegisterForm(request.POST)

        if form.is_valid():
            form.save()
            user = authenticate(
                username=form.cleaned_data["username"],
                password=form.cleaned_data["password1"],
            )
            logger.info(f"User created: {user.username}")

            login(request, user)
            return redirect("index")

        return render(request, "inventory/signup.html", {"form": form})


def _build_low_stock_alerts():
    """Return low-stock alert rows, sorted by urgency.

    Two DB queries:
    1. Active (non-depleted, non-sold) items grouped by product SKU — filtered to < LOW_QUANTITY.
    2. Items depleted in the last 30 days grouped by product SKU — used as "recently consumed" signal.

    Products with zero active items that were recently depleted are included as "Out of Stock".
    """
    low_qty = getattr(settings, "LOW_QUANTITY", 3)
    thirty_days_ago = timezone_now() - timedelta(days=30)

    # TRUE active (non-depleted, non-sold) count per SKU — every SKU with at
    # least one active item. NOT pre-filtered to < LOW_QUANTITY: a well-stocked
    # SKU must still be recorded here so it can't fall through to "out of stock"
    # just because it isn't "low" (the prior bug).
    active_map = {
        row["product__sku"]: {
            "product__name": row["product__name"],
            "product_type": row["product__polymorphic_ctype__model"].title(),
            "active_count": row["active_count"],
            "in_use_count": row["in_use_count"],
        }
        for row in InventoryItem.objects.exclude(
            status__in=[InventoryItem.Status.DEPLETED, InventoryItem.Status.SOLD]
        )
        .values("product__sku", "product__name", "product__polymorphic_ctype__model")
        .annotate(
            active_count=Count("id"),
            in_use_count=Count("id", filter=Q(status=InventoryItem.Status.IN_USE)),
        )
    }

    # Products depleted in the last 30 days (captures active consumption)
    depleted_map = {
        row["product__sku"]: row
        for row in InventoryItem.objects.filter(
            status=InventoryItem.Status.DEPLETED,
            date_depleted__gte=thirty_days_ago,
        )
        .values("product__sku", "product__name", "product__polymorphic_ctype__model")
        .annotate(recently_depleted=Count("id"))
    }

    # Alert candidates:
    #  - low_skus: have some active stock but below LOW_QUANTITY
    #  - out_of_stock_skus: genuinely zero active (absent from active_map) AND
    #    recently depleted
    # Well-stocked SKUs (active_count >= LOW_QUANTITY) are intentionally NOT
    # alerted, even if a roll was depleted in the window.
    low_skus = {sku for sku, row in active_map.items() if row["active_count"] < low_qty}
    out_of_stock_skus = set(depleted_map) - set(active_map)
    alert_skus = low_skus | out_of_stock_skus

    urgency_rank = {"danger": 0, "warning": 1, "secondary": 2}
    alerts = []
    for sku in alert_skus:
        if sku in active_map:
            row = {"product__sku": sku, **active_map[sku]}
        else:
            d = depleted_map[sku]
            row = {
                "product__sku": sku,
                "product__name": d["product__name"],
                "product_type": d["product__polymorphic_ctype__model"].title(),
                "active_count": 0,
                "in_use_count": 0,
            }
        row["recently_depleted"] = depleted_map.get(sku, {}).get("recently_depleted", 0)

        if row["active_count"] == 0 and row["recently_depleted"] > 0:
            row["urgency"] = "danger"
            row["urgency_label"] = "Out of Stock"
        elif row["recently_depleted"] > 0:
            row["urgency"] = "warning"
            row["urgency_label"] = "Running Low"
        else:
            row["urgency"] = "secondary"
            row["urgency_label"] = "Low Stock"

        alerts.append(row)

    alerts.sort(
        key=lambda r: (
            urgency_rank[r["urgency"]],
            r["active_count"],
            r["product__name"],
        )
    )
    return alerts


class FilamentColorGuideView(LoginRequiredMixin, TemplateView):
    template_name = "inventory/filament_color_guide.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        filaments = list(
            Filament.objects.annotate(
                active_count=Count(
                    "inventory_items",
                    filter=Q(inventory_items__status__in=_ACTIVE_STATUSES),
                )
            )
            .filter(active_count__gt=0)
            .select_related("material")
            .order_by("color_family", "color")
        )

        grouped = {}
        for f in filaments:
            grouped.setdefault(f.color_family or "OTHER", []).append(f)

        # Preserve defined family order; append any unlisted families at the end
        ordered = {k: grouped[k] for k in FAMILY_ORDER if k in grouped}
        for k, v in grouped.items():
            if k not in ordered:
                ordered[k] = v

        context["grouped_filaments"] = ordered
        # Spools on hand = active inventory items, NOT the number of distinct
        # color/SKU rows (len(filaments)), which badly under-counted the header.
        context["total_spools"] = sum(f.active_count for f in filaments)
        return context


class FilamentSummaryView(LoginRequiredMixin, TemplateView):
    template_name = "inventory/filament_summary.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone_now()
        cutoff_7 = now - timedelta(days=7)
        cutoff_30 = now - timedelta(days=30)
        cutoff_365 = now - timedelta(days=365)
        DEPLETED = InventoryItem.Status.DEPLETED

        # Active inventory grouped by (material, subtype, color, family)
        active_qs = list(
            Filament.objects.filter(material__isnull=False)
            .values(
                "material__name",
                "material__material_type",
                "color",
                "color_family",
            )
            .annotate(
                on_hand=Count(
                    "inventory_items",
                    filter=Q(inventory_items__status__in=_ACTIVE_STATUSES),
                ),
                hex_code=Max("hex_code"),
                weight=Max("weight"),
            )
            .filter(on_hand__gt=0)
        )

        # Depleted counts for all three windows in one query
        depleted_map = {
            (
                row["material__name"],
                row["material__material_type"],
                row["color"],
                row["color_family"],
            ): row
            for row in Filament.objects.filter(material__isnull=False)
            .values(
                "material__name",
                "material__material_type",
                "color",
                "color_family",
            )
            .annotate(
                depleted_7=Count(
                    "inventory_items",
                    filter=Q(
                        inventory_items__status=DEPLETED,
                        inventory_items__date_depleted__gte=cutoff_7,
                    ),
                ),
                depleted_30=Count(
                    "inventory_items",
                    filter=Q(
                        inventory_items__status=DEPLETED,
                        inventory_items__date_depleted__gte=cutoff_30,
                    ),
                ),
                depleted_365=Count(
                    "inventory_items",
                    filter=Q(
                        inventory_items__status=DEPLETED,
                        inventory_items__date_depleted__gte=cutoff_365,
                    ),
                ),
            )
            .filter(Q(depleted_7__gt=0) | Q(depleted_30__gt=0) | Q(depleted_365__gt=0))
        }

        # Build table rows
        rows = []
        for row in active_qs:
            key = (
                row["material__name"],
                row["material__material_type"],
                row["color"],
                row["color_family"],
            )
            dep = depleted_map.get(key, {})
            on_hand = row["on_hand"]
            weight = row["weight"]
            est_kg = round(float(weight) * on_hand, 2) if weight and on_hand else None
            rows.append(
                {
                    "material_name": row["material__name"] or "",
                    "material_type": row["material__material_type"] or "",
                    "color": row["color"] or "",
                    "color_family": row["color_family"] or "",
                    "hex_code": row["hex_code"]
                    or COLOR_FAMILY_HEX.get(row["color_family"] or "", ""),
                    "on_hand": on_hand,
                    "used_7d": dep.get("depleted_7", 0),
                    "used_30d": dep.get("depleted_30", 0),
                    "used_365d": dep.get("depleted_365", 0),
                    "est_weight_kg": est_kg,
                }
            )
        rows.sort(key=lambda r: (r["material_name"], r["material_type"], r["color"]))

        # Build material cards
        cards_dict = {}
        for row in rows:
            mat = row["material_name"]
            if mat not in cards_dict:
                cards_dict[mat] = {
                    "name": mat,
                    "total_on_hand": 0,
                    "subtypes": set(),
                    "family_counts": {},
                }
            cards_dict[mat]["total_on_hand"] += row["on_hand"]
            if row["material_type"]:
                cards_dict[mat]["subtypes"].add(row["material_type"])
            fam = row["color_family"]
            if fam:
                cards_dict[mat]["family_counts"][fam] = (
                    cards_dict[mat]["family_counts"].get(fam, 0) + row["on_hand"]
                )

        cards = []
        for mat_name in sorted(
            cards_dict, key=lambda m: (-cards_dict[m]["total_on_hand"], m)
        ):
            data = cards_dict[mat_name]
            all_swatches = sorted(
                [
                    {
                        "family": fam,
                        "hex": COLOR_FAMILY_HEX.get(fam, "#cccccc"),
                        "count": cnt,
                    }
                    for fam, cnt in data["family_counts"].items()
                ],
                key=lambda x: -x["count"],
            )
            cards.append(
                {
                    "name": data["name"],
                    "total_on_hand": data["total_on_hand"],
                    "subtype_count": len(data["subtypes"]),
                    "visible_swatches": all_swatches[:8],
                    "hidden_swatches": all_swatches[8:],
                    "extra_count": max(0, len(all_swatches) - 8),
                }
            )

        context["cards"] = cards
        context["rows"] = rows
        context["grand_total_rolls"] = sum(r["on_hand"] for r in rows)
        context["total_filament_types"] = len(rows)
        context["total_materials"] = len(cards)
        return context


class FilamentGuideView(LoginRequiredMixin, TemplateView):
    template_name = "inventory/filament_guide.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["materials"] = (
            Material.objects.filter(filament__isnull=False)
            .distinct()
            .order_by("name", "material_type")
        )
        return context


class Dashboard(LoginRequiredMixin, View):
    def get(self, request):
        item_counts_by_type = [
            {
                "class_name": row["product__polymorphic_ctype__model"].title(),
                "count": row["count"],
            }
            for row in InventoryItem.objects.values("product__polymorphic_ctype__model")
            .annotate(count=Count("id"))
            .order_by("-count")
        ]

        total_value = InventoryItem.objects.aggregate(total=Sum("product__price"))[
            "total"
        ] or Decimal("0.00")

        materials = (
            Filament.objects.values("material__name")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        filament_chart_data = {
            "labels": [row["material__name"] for row in materials],
            "data": [row["count"] for row in materials],
        }

        colors = list(
            Filament.objects.values("color_family")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        color_chart_data = {
            "labels": [row["color_family"] or "Unknown" for row in colors],
            "data": [row["count"] for row in colors],
            "colors": [
                COLOR_FAMILY_HEX.get(row["color_family"] or "", "#cccccc")
                for row in colors
            ],
        }

        inventory_by_sku = [
            {
                "product__name": row["product__name"],
                "product__sku": row["product__sku"],
                "product__class_name": row["product__polymorphic_ctype__model"].title(),
                "total_quantity": row["total_quantity"],
            }
            for row in InventoryItem.objects.values(
                "product__sku",
                "product__name",
                "product__polymorphic_ctype__model",
            )
            .annotate(total_quantity=Count("id"))
            .order_by("-total_quantity")
        ]

        low_stock_alerts = _build_low_stock_alerts()

        grand_total = InventoryItem.objects.count()
        distinct_products = InventoryItem.objects.values("product").distinct().count()
        latest_item = InventoryItem.objects.order_by("-last_modified").first()
        latest_timestamp = latest_item.last_modified if latest_item else None

        return render(
            request,
            "inventory/dashboard.html",
            {
                "distinct_products": distinct_products,
                "latest_timestamp": latest_timestamp,
                "item_counts_by_type": item_counts_by_type,
                "locations": Location.objects.all(),
                "grand_total": grand_total,
                "value": total_value,
                "filament_chart_data": filament_chart_data,
                "color_chart_data": color_chart_data,
                "inventory_by_sku": inventory_by_sku,
                "low_stock_alerts": low_stock_alerts,
                "low_qty_threshold": getattr(settings, "LOW_QUANTITY", 3),
            },
        )


class BaseAddProductView(LoginRequiredMixin, CreateView):
    template_name = "inventory/add_product.html"
    success_url = reverse_lazy("add_inventory")
    form_title = ""
    submit_label = "Save"

    def get_initial(self):
        initial = super().get_initial()
        pending = self.request.session.get("pending_inventory")
        if pending:
            initial["upc"] = pending.get("upc")
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form_title"] = self.form_title
        context["submit_label"] = self.submit_label
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.request.GET.get("from_inventory"):
            pending = self.request.session.pop("pending_inventory", None)
            if pending:
                new_item = InventoryItem.objects.create(
                    product=self.object,
                    shipment=pending.get("shipment") or "",
                    location_id=pending.get("location_id"),
                )
                scan_id = pending.get("unknown_scan_id")
                if scan_id:
                    AuditUnknownScan.objects.filter(pk=scan_id, resolved=False).update(
                        resolved=True, resolved_item=new_item
                    )
                messages.success(
                    self.request, f"{self.object.name} and inventory item created."
                )
                return redirect("add_inventory")
        return response


class AddFilamentView(BaseAddProductView):
    model = Filament
    form_class = FilamentForm
    form_title = "Add New Filament"
    submit_label = "Save Filament"


class AddPrinterView(BaseAddProductView):
    model = Printer
    form_class = PrinterForm
    form_title = "Add New Printer"
    submit_label = "Save Printer"


class AddDryerView(BaseAddProductView):
    model = Dryer
    form_class = DryerForm
    form_title = "Add New Dryer"
    submit_label = "Save Dryer"


class AddHardwareView(BaseAddProductView):
    model = Hardware
    form_class = HardwareForm
    form_title = "Add New Hardware"
    submit_label = "Save Hardware"


class AddAMSView(BaseAddProductView):
    model = AMS
    form_class = AMSForm
    form_title = "Add New AMS"
    submit_label = "Save AMS"


class InventoryExportView(LoginRequiredMixin, View):
    def get(self, request):
        # Get filters from query parameters
        sku = request.GET.get("sku", "")
        upc = request.GET.get("upc", "")
        name = request.GET.get("name", "")
        location = request.GET.get("location", "")

        # Rebuild the filtered queryset
        items = InventoryItem.objects.exclude(status=5).select_related(
            "product", "location"
        )
        if sku:
            items = items.filter(product__sku=sku)
        if upc:
            items = items.filter(product__upc=upc)
        if name:
            items = items.filter(product__name__icontains=name)
        if location:
            items = items.filter(location__name__icontains=location)

        # Create Excel workbook
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Inventory Export"

        # Write headers
        headers = ["Product", "SKU", "UPC", "Date Added", "Location"]
        ws.append(headers)

        # Write data rows
        for item in items:
            ws.append(
                [
                    item.product.name,
                    item.product.sku,
                    item.product.upc,
                    localtime(item.date_added).strftime("%Y-%m-%d %H:%M:%S"),
                    item.location.name if item.location else "",
                ]
            )

        # Return as downloadable file
        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        filename = "inventory_export.xlsx"
        response["Content-Disposition"] = f"attachment; filename={filename}"
        wb.save(response)
        return response


class InUseOverviewView(LoginRequiredMixin, TemplateView):
    template_name = "inventory/in_use_overview.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        in_use_items = InventoryItem.objects.filter(
            status=InventoryItem.Status.IN_USE
        ).select_related("location", "product")

        grouped_by_location = {}
        for item in in_use_items:
            loc = item.location.name if item.location else "Unassigned"
            item.product_type = str(
                item.product.polymorphic_ctype.model
            )  # Add model type

            tooltip_lines = []
            if item.serial_number:
                tooltip_lines.append(
                    f"<strong>Serial:</strong> {escape(item.serial_number)}"
                )

            if (
                item.product_type == "filament"
                and hasattr(item.product.filament, "color")
                and item.product.filament.color
            ):
                tooltip_lines.append(
                    f"<strong>Color:</strong> {escape(item.product.filament.color)}"
                )
            item.tooltip_html = "'{}'".format(
                "<br>".join(tooltip_lines).replace('"', "&quot;")
            )

            grouped_by_location.setdefault(loc, []).append(item)

        context["grouped_items"] = grouped_by_location
        return context


class DryStorageOverviewView(LoginRequiredMixin, TemplateView):
    template_name = "inventory/dry_storage_overview.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        stored_items = InventoryItem.objects.filter(
            status=InventoryItem.Status.STORED
        ).select_related("location", "product")

        grouped_by_location = {}
        for item in stored_items:
            loc = item.location.name if item.location else "Unassigned"
            item.product_type = str(
                item.product.polymorphic_ctype.model
            )  # Add model type

            tooltip_lines = []
            if item.serial_number:
                tooltip_lines.append(
                    f"<strong>Serial:</strong> {escape(item.serial_number)}"
                )

            if (
                item.product_type == "filament"
                and hasattr(item.product.filament, "color")
                and item.product.filament.color
            ):
                tooltip_lines.append(
                    f"<strong>Color:</strong> {escape(item.product.filament.color)}"
                )
            item.tooltip_html = "'{}'".format(
                "<br>".join(tooltip_lines).replace('"', "&quot;")
            )

            grouped_by_location.setdefault(loc, []).append(item)

        context["grouped_items"] = grouped_by_location
        return context


# ---------------------------------------------------------------------------
# Inventory audit mode
# ---------------------------------------------------------------------------

_AUDIT_ACTIVE_LOC_KEY = "audit_active_location_id"


def _resolve_pending_unknown(request, item):
    """If the current pending_inventory carries an unknown_scan_id, mark that
    AuditUnknownScan resolved against the freshly created item, then drop the id
    so a later unrelated add can't re-trigger on it. No-op otherwise."""
    pending = request.session.get("pending_inventory") or {}
    scan_id = pending.get("unknown_scan_id")
    if not scan_id:
        return
    AuditUnknownScan.objects.filter(pk=scan_id, resolved=False).update(
        resolved=True, resolved_item=item
    )
    pending.pop("unknown_scan_id", None)
    request.session["pending_inventory"] = pending


def _active_location(request):
    """The location currently in focus for this audit, or None.

    Active-location focus is ephemeral UI state kept in the request session;
    re-scanning a location barcode re-establishes it.
    """
    loc_id = request.session.get(_AUDIT_ACTIVE_LOC_KEY)
    if not loc_id:
        return None
    return Location.objects.filter(pk=loc_id).first()


def _set_active_location(request, location):
    if location is None:
        request.session.pop(_AUDIT_ACTIVE_LOC_KEY, None)
    else:
        request.session[_AUDIT_ACTIVE_LOC_KEY] = location.pk


def _audit_context(request, session, active_location, last_result=None):
    """Build the context shared by the console page and its HTMX body partial."""
    items_here = []
    present_here = 0
    if active_location is not None:
        leaves = audit.focus_leaves(active_location)
        leaf_ids = [leaf.id for leaf in leaves]
        scanned_ids = set(
            AuditEvent.objects.filter(
                session=session,
                location_id__in=leaf_ids,
                action__in=audit.PRESENT_ACTIONS,
            ).values_list("item_id", flat=True)
        )
        for item in (
            InventoryItem.objects.filter(location_id__in=leaf_ids)
            .select_related("product", "location")
            .order_by("location__slot_index", "location__name", "id")
        ):
            item.audit_scanned = item.id in scanned_ids
            if item.audit_scanned:
                present_here += 1
            items_here.append(item)

    return {
        "session": session,
        "active_location": active_location,
        "active_is_unit": active_location.is_container if active_location else False,
        "items_here": items_here,
        "expected_count": len(items_here),
        "present_count": present_here,
        "pending_count": len(items_here) - present_here,
        "added_items": audit.session_added_items(session),
        "unknown_items": audit.session_unknown_items(session),
        "unknown_count": AuditUnknownScan.objects.filter(
            resolved=False, dismissed=False
        ).count(),
        "tally": {
            "moved": AuditEvent.objects.filter(
                session=session, action=AuditEvent.Action.MOVED_IN
            ).count(),
            "present": AuditEvent.objects.filter(
                session=session, action=AuditEvent.Action.SCANNED_PRESENT
            ).count(),
            "revived": AuditEvent.objects.filter(
                session=session, action=AuditEvent.Action.REVIVED
            ).count(),
            "closed": AuditEvent.objects.filter(
                session=session, action=AuditEvent.Action.CLOSED
            ).count(),
            "added": AuditEvent.objects.filter(
                session=session, action=AuditEvent.Action.ADDED
            ).count(),
        },
        "recent_events": (
            AuditEvent.objects.filter(session=session)
            .select_related("item__product", "location")
            .order_by("-created_at")[:12]
        ),
        "last_result": last_result,
    }


class AuditStartView(LoginRequiredMixin, View):
    def post(self, request):
        try:
            audit.start_session(request.user)
        except audit.AuditError as exc:
            messages.error(request, str(exc))
        else:
            _set_active_location(request, None)
            messages.success(request, "Audit started. Scan a location to begin.")
        return redirect("audit_console")


class AuditConsoleView(LoginRequiredMixin, TemplateView):
    template_name = "inventory/audit_console.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        session = AuditSession.active()
        context["session"] = session
        if session is None:
            _set_active_location(self.request, None)
            return context

        # A LOC barcode scanned outside the console (?loc=) sets focus here.
        loc_param = self.request.GET.get("loc")
        active = _active_location(self.request)
        if loc_param:
            target = Location.objects.filter(pk=loc_param).first()
            if target:
                try:
                    audit.visit_location(session, target, previous_location=active)
                except audit.AuditError as exc:
                    messages.error(self.request, str(exc))
                else:
                    _set_active_location(self.request, target)
                    active = target

        context.update(_audit_context(self.request, session, active))
        return context


class AuditScanView(LoginRequiredMixin, View):
    """Input-agnostic scan endpoint: a wedge form-submit or a camera JS POST both
    deliver a ``code`` string here and get back the refreshed console body."""

    def post(self, request):
        session = AuditSession.active()
        if session is None:
            messages.error(request, "No audit in progress.")
            return redirect("audit_console")

        active = _active_location(request)
        last_result = None
        raw_code = request.POST.get("code", "")
        try:
            try:
                kind, value = audit.parse_code(raw_code)
            except audit.AuditError:
                # Fall back to a unit serial-number scan (e.g. an AMS/dryer/printer
                # front-panel tag) before giving up on an unrecognized code.
                value = audit.resolve_serial(raw_code.strip())
                kind = "loc_obj"
            if kind in ("loc", "loc_obj"):
                if kind == "loc_obj":
                    location = value  # already a resolved Location
                else:
                    location = Location.objects.filter(pk=value).first()
                    if location is None:
                        raise audit.AuditError(f"No location with id {value}.")
                audit.visit_location(session, location, previous_location=active)
                _set_active_location(request, location)
                active = location
                last_result = ("info", f"At {location.name}.")
            elif kind == "upc":
                outcome, obj = audit.add_or_queue_upc(session, active, value)
                if outcome == "added":
                    try:
                        generate_and_print_barcode(obj, mode="unique")
                    except Exception as e:  # label print is non-fatal
                        messages.warning(request, f"Label printing failed: {e}")
                        logger.error(f"Label printing failed: {e}")
                    last_result = (
                        "success",
                        f"Added {obj.product.name} (INV-{obj.pk}).",
                    )
                else:  # queued
                    last_result = (
                        "warning",
                        f"Unknown UPC {value} queued for review.",
                    )
            else:  # item
                item = InventoryItem.objects.filter(pk=value).first()
                if item is None:
                    raise audit.AuditError(f"No item with id {value}.")
                action = audit.scan_item(session, active, item)
                labels = {
                    AuditEvent.Action.SCANNED_PRESENT: ("success", "Present"),
                    AuditEvent.Action.MOVED_IN: ("success", "Moved here"),
                    AuditEvent.Action.REVIVED: ("warning", "Revived here"),
                }
                tag, verb = labels[action]
                last_result = (tag, f"{verb}: {item.product.name} (INV-{item.pk}).")
        except audit.AuditError as exc:
            last_result = ("danger", str(exc))

        context = _audit_context(request, session, active, last_result=last_result)
        if request.headers.get("HX-Request"):
            return render(request, "inventory/partials/audit_body.html", context)
        return redirect("audit_console")


class AuditCloseLocationView(LoginRequiredMixin, View):
    def post(self, request):
        session = AuditSession.active()
        if session is None:
            messages.error(request, "No audit in progress.")
            return redirect("audit_console")
        active = _active_location(request)
        if active is not None:
            present = audit.location_present_count(session, active)
            flagged = audit.close_location(session, active)
            _set_active_location(request, None)
            messages.info(
                request,
                f"Closed {active.name}. {present} accounted for, "
                f"{len(flagged)} flagged unknown.",
            )
        return redirect("audit_console")


class AuditFinalizeView(LoginRequiredMixin, View):
    def get(self, request):
        session = AuditSession.active()
        if session is None:
            messages.error(request, "No audit in progress.")
            return redirect("audit_console")
        # Close the still-open location so its unscanned items are included.
        active = _active_location(request)
        if active is not None:
            audit.close_location(session, active)
            _set_active_location(request, None)
        return render(
            request,
            "inventory/audit_finalize.html",
            {
                "session": session,
                "unknown_items": audit.session_unknown_items(session),
                "added_items": audit.session_added_items(session),
                "unknown_count": AuditUnknownScan.objects.filter(
                    resolved=False, dismissed=False
                ).count(),
            },
        )

    def post(self, request):
        session = AuditSession.active()
        if session is None:
            messages.error(request, "No audit in progress.")
            return redirect("audit_console")
        # Items the auditor chose to leave UNKNOWN ("in limbo") instead of depleting.
        keep_ids = request.POST.getlist("keep_unknown")
        depleted = audit.finalize(
            session,
            active_location=_active_location(request),
            keep_unknown_ids=keep_ids,
        )
        _set_active_location(request, None)
        kept = len(keep_ids)
        msg = (
            f"Audit finalized. {len(depleted)} item"
            f"{'' if len(depleted) == 1 else 's'} marked depleted."
        )
        if kept:
            msg += f" {kept} left unknown for follow-up."
        messages.success(request, msg)
        return redirect("dashboard")


class AuditAbandonView(LoginRequiredMixin, View):
    def post(self, request):
        session = AuditSession.active()
        if session is not None:
            audit.abandon(session)
        _set_active_location(request, None)
        messages.warning(
            request,
            "Audit abandoned. Items flagged unknown were left as-is for review.",
        )
        return redirect("dashboard")


class AuditUndoAddView(LoginRequiredMixin, View):
    """Remove an item mistakenly added this session (e.g. a UPC scanned in place of
    an INV tag). Re-renders the console body for HTMX, else redirects to the page
    the request came from (console or finalize)."""

    def post(self, request, item_id):
        session = AuditSession.active()
        if session is None:
            messages.error(request, "No audit in progress.")
            return redirect("audit_console")

        item = get_object_or_404(InventoryItem, pk=item_id)
        name = item.product.name
        try:
            audit.undo_added(session, item)
        except audit.AuditError as exc:
            last_result = ("danger", str(exc))
        else:
            last_result = ("success", f"Removed {name} (INV-{item_id}).")

        if request.headers.get("HX-Request"):
            active = _active_location(request)
            context = _audit_context(request, session, active, last_result=last_result)
            return render(request, "inventory/partials/audit_body.html", context)

        messages.add_message(
            request,
            messages.SUCCESS if last_result[0] == "success" else messages.ERROR,
            last_result[1],
        )
        if request.POST.get("next") == "finalize":
            return redirect("audit_finalize")
        return redirect("audit_console")


class AuditUnknownsView(LoginRequiredMixin, TemplateView):
    """Post-walk review of UPCs that matched no catalog Product."""

    template_name = "inventory/audit_unknowns.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["scans"] = (
            AuditUnknownScan.objects.filter(resolved=False, dismissed=False)
            .select_related("location")
            .order_by("created_at")
        )
        return context


class AuditUnknownResolveView(LoginRequiredMixin, View):
    """Hand a queued UPC into the existing add-product flow, threading the scan id
    so item creation marks this queue row resolved (see _resolve_pending_unknown)."""

    def post(self, request, pk):
        scan = get_object_or_404(
            AuditUnknownScan, pk=pk, resolved=False, dismissed=False
        )
        request.session["pending_inventory"] = {
            "upc": scan.upc,
            "sku": "",
            "shipment": None,
            "location_id": scan.location_id,
            "unknown_scan_id": scan.id,
        }
        messages.info(
            request, f"Add the product for UPC {scan.upc}, then it returns here."
        )
        return redirect("add_product_choice")


class AuditUnknownDismissView(LoginRequiredMixin, View):
    def post(self, request, pk):
        scan = get_object_or_404(
            AuditUnknownScan, pk=pk, resolved=False, dismissed=False
        )
        scan.dismissed = True
        scan.save(update_fields=["dismissed"])
        messages.info(request, f"Dismissed UPC {scan.upc}.")
        return redirect("audit_unknowns")
