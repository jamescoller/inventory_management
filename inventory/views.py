import logging
import re
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlencode

import openpyxl
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
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

from . import audit, items, maintenance, printjobs, procurement, quickmove
from .barcode_utils import (
    PrinterUnreachableError,
    generate_and_print_barcode,
    print_unit_label,
)
from .forms import (
    AMSForm,
    DryerForm,
    FilamentForm,
    HardwareForm,
    InventoryEditForm,
    InventoryItemForm,
    MaintenanceEventForm,
    PrinterForm,
    PrintJobFilamentFormSet,
    PrintJobForm,
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
    MaintenanceEvent,
    Material,
    NozzleConfig,
    Printer,
    PrintJob,
    Product,
    PurchaseOrder,
    PurchaseReceipt,
    is_machine_item,
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


class MachineUnitLabelView(LoginRequiredMixin, View):
    """Print a DK-1201 unit label for a machine item straight from its edit page.

    The edit-page "Print Barcode"/"Print Inventory Tag" buttons make 17x54 labels;
    AMS/dryer/printer units carry a larger DK-1201 (29x90) "unit label" (SN
    Code128 + a QR to the unit's location), previously reachable only via the
    Location admin action. This resolves the item's machine location by kind
    (the AMS/dryer container or the printer leaf — slots are excluded) and prints
    the shared :func:`barcode_utils.print_unit_label`.
    """

    def get(self, request, item_id):
        item = get_object_or_404(InventoryItem, pk=item_id)
        loc = Location.objects.filter(
            unit=item,
            kind__in=(
                Location.Kind.AMS,
                Location.Kind.DRYER,
                Location.Kind.PRINTER,
            ),
        ).first()
        if loc is None:
            messages.error(
                request,
                "This item is not a tracked AMS/dryer/printer unit, or it isn't "
                "linked to a location.",
            )
            return redirect("inventory_edit", item_id=item_id)

        sn = (item.serial_number or "").strip()
        if not sn:
            messages.error(request, "This unit has no serial number to print.")
            return redirect("inventory_edit", item_id=item_id)

        try:
            return print_unit_label(sn, loc.pk, loc.name)
        except PrinterUnreachableError as exc:
            messages.error(request, str(exc))
            return redirect("inventory_edit", item_id=item_id)
        except Exception as exc:  # noqa: BLE001 - surface any print failure, never 500
            # The usual cause is a media mismatch: the printer rejects a 29x90 job
            # ("wrong size") unless the DK-1201 roll is loaded. Hint at the roll
            # instead of letting the brother_ql error bubble up as a 500.
            messages.error(
                request,
                f"Couldn't print the unit label: {exc}. Unit labels need the "
                "DK-1201 (29x90) roll loaded — check the roll and clear the "
                "printer's error state, then try again.",
            )
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
            # Routing: during an active audit, a scanned LOC barcode jumps into the
            # console focused there (containers audit all their slots together).
            # Otherwise it opens the read-only location detail page. This keeps the
            # audit scan workflow intact while making the location page reachable by
            # scan the rest of the time.
            if AuditSession.active() is not None:
                return redirect(f"{reverse('audit_console')}?loc={location.pk}")
            return redirect("location_detail", location_id=location.pk)
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


# Polymorphic Product subclasses exposed by the item-type filter, in nav order.
# Keyed on `product__polymorphic_ctype__model` (lowercase model name), matching
# the dashboard pattern (`views.py` Dashboard.get).
_ITEM_TYPE_MODELS = (Filament, Printer, AMS, Dryer, Hardware)


def _item_type_choices():
    """(model_name, Verbose Label) pairs for the item-type filter."""
    overrides = {"ams": "AMS"}
    return [
        (
            m._meta.model_name,
            overrides.get(m._meta.model_name, m._meta.verbose_name.title()),
        )
        for m in _ITEM_TYPE_MODELS
    ]


def _valid_type_models():
    return {m._meta.model_name for m in _ITEM_TYPE_MODELS}


def _parse_status_params(raw_values):
    """Coerce raw ``status`` GET values to a set of valid Status ints.

    Garbage (non-integer / out-of-range) values are silently dropped so a
    fat-fingered URL can never 500 the search page.
    """
    valid = {int(v) for v in InventoryItem.Status.values}
    out = set()
    for raw in raw_values:
        try:
            v = int(raw)
        except (TypeError, ValueError):
            continue
        if v in valid:
            out.add(v)
    return out


# Statuses hidden by default (terminal/noisy) when no explicit status filter is
# given. UNKNOWN is deliberately NOT hidden — finding lost items is the point.
_DEFAULT_HIDDEN_STATUSES = (
    InventoryItem.Status.DEPLETED,
    InventoryItem.Status.SOLD,
)


def _filtered_search_items(params):
    """Build the filtered ``InventoryItem`` queryset for the search/export pages.

    ``params`` is a request ``QueryDict`` (``request.GET`` or ``request.POST``).
    Returns ``(queryset, parsed)`` where ``parsed`` carries the normalised filter
    values for re-rendering the form. Shared by ``InventorySearchView`` and
    ``InventoryExportView`` so the export honours the same filters (and no longer
    re-introduces the dead ``exclude(status=5)`` bug).

    A bare navbar ``INV-<id>`` is NOT handled here — that redirect belongs to the
    view; this function only filters.
    """
    sku = params.get("sku", "")
    upc = params.get("upc", "")
    name = params.get("name", "")
    location = params.get("location", "")
    serial_number = params.get("serial_number", "")
    item_id = params.get("item_id", "")
    date_from = params.get("date_from", "")
    date_to = params.get("date_to", "")
    preset = params.get("preset", "")
    material = params.get("material", "")
    material_type = params.get("material_type", "")
    manufacturer = params.get("manufacturer", "")
    color = params.get("color", "")
    color_family = params.get("color_family", "")

    selected_statuses = _parse_status_params(params.getlist("status"))
    selected_types = {
        t for t in params.getlist("item_type") if t in _valid_type_models()
    }

    items = InventoryItem.objects.select_related("product", "location")

    # --- Lost & Found preset ----------------------------------------------
    # One click → recover audit casualties: anything UNKNOWN, plus anything
    # orphaned with no location (left at a retired/empty location). Applied as a
    # Q so it composes with any other explicit filter the user adds.
    if preset == "lost_found":
        items = items.filter(
            Q(status=InventoryItem.Status.UNKNOWN) | Q(location__isnull=True)
        )

    # --- text / field filters ---------------------------------------------
    # Navbar quick-search: a lone `name` fans out across many fields.
    navbar_mode = bool(name) and not any([sku, upc, location, serial_number, item_id])
    if navbar_mode:
        name_q = (
            Q(product__name__icontains=name)
            | Q(product__sku__icontains=name)
            | Q(product__upc__icontains=name)
            | Q(serial_number__icontains=name)
            | Q(id__icontains=name)
        )
        loc_ids = _expanded_location_ids(name)
        if loc_ids:
            name_q |= Q(location_id__in=loc_ids)
        items = items.filter(name_q)
    else:
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

    # --- status -----------------------------------------------------------
    if selected_statuses:
        items = items.filter(status__in=selected_statuses)
    elif preset != "lost_found":
        # Default view: hide terminal/noisy statuses (keep UNKNOWN).
        items = items.exclude(status__in=_DEFAULT_HIDDEN_STATUSES)

    # --- item type --------------------------------------------------------
    if selected_types:
        items = items.filter(product__polymorphic_ctype__model__in=selected_types)

    # --- filament-scoped filters ------------------------------------------
    # The polymorphic ``product__filament__*`` join only resolves for Filament
    # products, so these naturally restrict to filament rows (non-filament
    # products yield null and drop out) — no item_type gating needed. Reached
    # by clicking a row/card in the three filament views.
    if material:
        items = items.filter(product__filament__material__name=material)
    if material_type:
        items = items.filter(product__filament__material__material_type=material_type)
    if manufacturer:
        items = items.filter(product__filament__manufacturer=manufacturer)
    if color:
        items = items.filter(product__filament__color=color)
    if color_family:
        items = items.filter(product__filament__color_family=color_family)

    # --- date-added range -------------------------------------------------
    if date_from:
        items = items.filter(date_added__date__gte=date_from)
    if date_to:
        items = items.filter(date_added__date__lte=date_to)

    parsed = {
        "search_values": {
            "sku": sku,
            "upc": upc,
            "name": name,
            "location": location,
            "serial_number": serial_number,
            "item_id": item_id,
            "date_from": date_from,
            "date_to": date_to,
            "preset": preset,
            "material": material,
            "material_type": material_type,
            "manufacturer": manufacturer,
            "color": color,
            "color_family": color_family,
        },
        "selected_statuses": selected_statuses,
        "selected_types": selected_types,
    }
    return items, parsed


class InventorySearchView(LoginRequiredMixin, View):
    """Inventory search with real, composable filters (Phase 11.2).

    Query contract (all optional, all AND-combined):

    - ``name`` — navbar quick-search. When it is the *only* field present it
      fans out across product name/sku/upc, serial, id, and the location subtree
      (a typed ``LOC-<id>`` FILTERS here; it never redirects to the audit
      console — only a *scanned* barcode does, via ``BarcodeRedirectView``). An
      ``INV-<id>`` value still short-circuits to that item's edit page.
    - ``sku`` / ``upc`` / ``serial_number`` / ``item_id`` — exact field matches.
    - ``location`` — name fragment or ``LOC-<id>``; expanded to the whole subtree
      of any matched container via ``_expanded_location_ids``.
    - ``status`` — repeatable; integer Status codes (incl. DEPLETED/SOLD/UNKNOWN).
      Omitted → default view hides DEPLETED/SOLD noise but keeps UNKNOWN findable.
    - ``item_type`` — repeatable; polymorphic model name (filament/printer/ams/
      dryer/hardware).
    - ``date_from`` / ``date_to`` — inclusive ``date_added`` range (``YYYY-MM-DD``).
    - ``preset=lost_found`` — audit-recovery shortcut: UNKNOWN items ∪ items with
      no location (left at a retired/empty location).
    """

    def get(self, request):
        # A navbar INV-<id> jumps straight to that item's edit page (preserved
        # from the original view).
        name = request.GET.get("name", "")
        inv_pattern = re.match(r"^INV-(\d+)$", name.strip())
        if inv_pattern:
            return redirect("inventory_edit", item_id=inv_pattern.group(1))

        items, parsed = _filtered_search_items(request.GET)

        context = {
            "items": items,
            "status_choices": InventoryItem.Status.choices,
            "type_choices": _item_type_choices(),
            "locations": Location.objects.all().order_by("name"),
            **parsed,
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
                "location_status_timeline": item.location_status_timeline(),
                "is_machine": is_machine_item(item),
                "is_printer": isinstance(product, Printer),
            },
        )

    def post(self, request, item_id):
        item = get_object_or_404(InventoryItem, id=item_id)
        action = request.POST.get("action")

        # Handle depleted/sold actions
        if action in ["deplete", "sell"]:
            if action == "deplete":
                items.deplete(item)
                messages.success(request, f"Item '{item}' has been marked as depleted.")
            elif action == "sell":
                items.set_status(item, InventoryItem.Status.SOLD)
                messages.success(request, f"Item '{item}' has been marked as sold.")
            return redirect("inventory_edit", item_id=item_id)

        # Handle the regular form submission
        form = InventoryEditForm(request.POST, instance=item)  # Bind form with instance
        product = item.product.get_real_instance()
        base_ctx = {
            "form": form,
            "item": item,
            "product": product,
            "is_filament": isinstance(product, Filament),
            "location_status_timeline": item.location_status_timeline(),
            "is_machine": is_machine_item(item),
            "is_printer": isinstance(product, Printer),
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

            # Location/serial/date are already on the bound instance; set status
            # explicitly so the model does NOT re-derive it from the new location
            # (honours the user's pick + the sticky-status mechanism).
            items.set_status(form.instance, form.cleaned_data["status"])
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
    """Round-trip back to the search results, preserving the active filters.

    ``status`` and ``item_type`` are multi-valued, so use ``getlist`` +
    ``urlencode(..., doseq=True)`` to faithfully reproduce every selected value.
    """
    single_keys = (
        "sku",
        "upc",
        "name",
        "location",
        "serial_number",
        "item_id",
        "date_from",
        "date_to",
        "preset",
    )
    multi_keys = ("status", "item_type")
    params = []
    for k in single_keys:
        v = request.POST.get(k, "")
        if v:
            params.append((k, v))
    for k in multi_keys:
        for v in request.POST.getlist(k):
            if v != "":
                params.append((k, v))
    url = reverse("inventory_search")
    if params:
        url += "?" + urlencode(params, doseq=True)
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
            # Reject containers up front so the whole batch fails fast with one
            # clear message (the per-item move guard would also catch it).
            if new_location.is_container:
                messages.error(
                    request,
                    f"{new_location.name} is a container and can't hold items.",
                )
                return _bulk_redirect_back(request)

        if new_status is None and new_location is None and new_shipment is None:
            messages.warning(request, "No fields selected — nothing was changed.")
            return _bulk_redirect_back(request)

        status_clears_location = new_status in (
            InventoryItem.Status.DEPLETED,
            InventoryItem.Status.SOLD,
        )

        count = 0
        with transaction.atomic():
            for item in InventoryItem.objects.filter(id__in=item_ids):
                if new_shipment is not None:
                    item.shipment = new_shipment

                # Delegate status/location writes to the items service so this
                # view never touches the model's transient flags. Capacity is not
                # enforced on the bulk path (it mirrors the prior behavior; a
                # power-user batch shouldn't fail mid-loop on a full slot).
                if new_status is not None and not status_clears_location:
                    # Move (if a location was given) carrying the explicit status,
                    # else just set the status in place.
                    if new_location is not None:
                        items.move_to(
                            item,
                            new_location,
                            status=new_status,
                            skip_drying_check=True,
                            enforce_capacity=False,
                        )
                    else:
                        items.set_status(item, new_status)
                elif new_status is not None:
                    # DEPLETED/SOLD: set the terminal status (clears location); any
                    # requested location is intentionally ignored, as before.
                    items.set_status(item, new_status)
                elif new_location is not None:
                    items.move_to(
                        item,
                        new_location,
                        skip_drying_check=True,
                        enforce_capacity=False,
                    )
                else:
                    # Shipment-only change.
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


class FilamentHubView(LoginRequiredMixin, TemplateView):
    """Landing page that ties the three filament views together with mode tabs.

    Intentionally a thin shell: it does *not* duplicate or reimplement the
    Summary / Color Guide / Guide views — it links out to their existing
    URLs, which all remain live so the change is fully reversible. ``active``
    lets the same template highlight the current tab when those pages render
    inside the hub navbar (see ``filament_nav.html``).
    """

    template_name = "inventory/filament_hub.html"


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
                "manufacturer",
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
                row["manufacturer"],
                row["color"],
                row["color_family"],
            ): row
            for row in Filament.objects.filter(material__isnull=False)
            .values(
                "material__name",
                "material__material_type",
                "manufacturer",
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
                row["manufacturer"],
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
                    "manufacturer": row["manufacturer"] or "",
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
        rows.sort(
            key=lambda r: (
                r["material_name"],
                r["material_type"],
                r["color"],
                r["manufacturer"],
            )
        )

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


class MaintenanceSummaryView(LoginRequiredMixin, TemplateView):
    """Reliability / "rebuy-or-refund" dashboard.

    Per machine *model*: fault count, faults-per-unit, open faults, total
    downtime, maintenance spend, and MTBF. Computed via DB aggregations in
    :func:`maintenance.model_reliability`.
    """

    template_name = "inventory/maintenance_summary.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["rows"] = maintenance.model_reliability()
        context["recent_events"] = MaintenanceEvent.objects.select_related(
            "unit__product__polymorphic_ctype", "part"
        ).order_by("-occurred_at", "-created_at")[:25]
        return context


class UnitMaintenanceView(LoginRequiredMixin, TemplateView):
    """Per-machine maintenance timeline, reached from the item page."""

    template_name = "inventory/unit_maintenance.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        item = get_object_or_404(
            InventoryItem.objects.select_related("product"), id=kwargs["item_id"]
        )
        context["item"] = item
        context["product"] = item.product.get_real_instance()
        context["is_machine"] = is_machine_item(item)
        context["events"] = maintenance.unit_events(item)
        context["summary"] = maintenance.unit_summary(item)
        context["nozzle_config"] = getattr(item, "nozzle_config", None)
        return context


class MaintenanceLogCreateView(LoginRequiredMixin, CreateView):
    """Log a maintenance event against a specific machine ``InventoryItem``.

    ``unit`` is bound from the URL (not the form), and a hotend-swap event also
    updates the printer's live :class:`NozzleConfig` via the service module.
    """

    model = MaintenanceEvent
    form_class = MaintenanceEventForm
    template_name = "inventory/maintenance_log_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.unit = get_object_or_404(
            InventoryItem.objects.select_related("product"), id=kwargs["item_id"]
        )
        if not is_machine_item(self.unit):
            messages.error(
                request,
                "Maintenance can only be logged on a machine (printer, AMS, or dryer).",
            )
            return redirect("inventory_edit", item_id=self.unit.id)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["item"] = self.unit
        context["product"] = self.unit.product.get_real_instance()
        return context

    def form_valid(self, form):
        event = form.save(commit=False)
        event.unit = self.unit
        event.full_clean()  # enforce the machine-only model guard server-side
        event.save()
        # A hotend swap also advances the printer's live nozzle state.
        if event.kind == MaintenanceEvent.Kind.HOTEND_SWAP and isinstance(
            self.unit.product.get_real_instance(), Printer
        ):
            config, _ = NozzleConfig.objects.get_or_create(printer=self.unit)
            config.hotend_changed_at = event.occurred_at
            config.save(update_fields=["hotend_changed_at"])
        messages.success(self.request, f"Logged maintenance: {event.title}")
        return redirect("unit_maintenance", item_id=self.unit.id)


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

        # Chart-ready labels/data for the product-type pie. Derived from
        # item_counts_by_type so the template can ship it via json_script
        # (XSS-safe) instead of interpolating into inline JS.
        type_chart_data = {
            "labels": [e["class_name"] for e in item_counts_by_type],
            "data": [e["count"] for e in item_counts_by_type],
        }

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
                "type_chart_data": type_chart_data,
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
        # Rebuild the same filtered queryset the search page rendered, so the
        # export matches what the user is looking at (honours status/type/date/
        # preset, not just the legacy sku/upc/name/location subset).
        items, _ = _filtered_search_items(request.GET)

        # Create Excel workbook
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Inventory Export"

        # Write headers
        headers = [
            "Serial",
            "Product",
            "SKU",
            "UPC",
            "Status",
            "Date Added",
            "Location",
        ]
        ws.append(headers)

        # Write data rows
        for item in items:
            ws.append(
                [
                    item.serial_number,
                    item.product.name,
                    item.product.sku,
                    item.product.upc,
                    item.get_status_display(),
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


def build_location_tree(roots, *, statuses=None):
    """Build a nested, expandable location tree for the given ``roots``.

    Returns a list of node dicts (one per root), each shaped::

        {
            "location": <Location>,
            "item_count": <int>,   # active items in this node's WHOLE subtree
            "items": [<InventoryItem>, ...],  # active items DIRECTLY here
            "children": [<node>, ...],        # child nodes, recursively
        }

    "Active" excludes :data:`items.TERMINAL_STATUSES` (depleted/sold). When
    ``statuses`` is given, items are *additionally* restricted to those statuses
    (e.g. dry-storage shows only ``STORED``). Children are ordered by
    ``(slot_index, name)`` and the walk recurses to arbitrary depth via the
    ``parent`` reverse relation (rack→shelf, rack→ams→slot, etc.).

    To avoid N+1, every location in each root's subtree is gathered up front, the
    active items for the whole set are fetched in one query, and subtree counts
    are rolled up from the leaves.
    """
    # Gather every location in the subtrees rooted at ``roots`` (BFS over parent).
    all_locs = {}
    children_of = {}
    frontier = []
    for root in roots:
        all_locs[root.id] = root
        children_of.setdefault(root.id, [])
        frontier.append(root.id)
    while frontier:
        kids = list(
            Location.objects.filter(parent_id__in=frontier).order_by(
                "slot_index", "name"
            )
        )
        frontier = []
        for kid in kids:
            if kid.id in all_locs:
                continue
            all_locs[kid.id] = kid
            children_of.setdefault(kid.id, [])
            children_of.setdefault(kid.parent_id, []).append(kid)
            frontier.append(kid.id)

    # One query for all active items located anywhere in these subtrees.
    item_qs = (
        InventoryItem.objects.filter(location_id__in=all_locs.keys())
        .exclude(status__in=items.TERMINAL_STATUSES)
        .select_related("product", "location")
    )
    if statuses is not None:
        item_qs = item_qs.filter(status__in=statuses)

    direct_items = {loc_id: [] for loc_id in all_locs}
    for item in item_qs.order_by("id"):
        direct_items[item.location_id].append(item)

    def build_node(loc):
        children = [build_node(child) for child in children_of.get(loc.id, [])]
        own = direct_items.get(loc.id, [])
        subtree_count = len(own) + sum(c["item_count"] for c in children)
        return {
            "location": loc,
            "item_count": subtree_count,
            "items": own,
            "children": children,
        }

    return [build_node(root) for root in roots]


class DryStorageOverviewView(LoginRequiredMixin, TemplateView):
    template_name = "inventory/dry_storage_overview.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        roots = list(
            Location.objects.filter(
                parent__isnull=True,
                kind__in=[Location.Kind.RACK, Location.Kind.DRY_STORAGE],
            ).order_by("name")
        )
        context["location_tree"] = build_location_tree(
            roots, statuses=[InventoryItem.Status.STORED]
        )
        return context


class ReceivingOverviewView(LoginRequiredMixin, TemplateView):
    """Expandable tree of the receiving rack(s) — what's currently in receiving.

    Prefers racks whose name mentions "receiv" if any exist, otherwise shows all
    racks. Items are shown for all active statuses (not just NEW) so anything
    physically sitting in receiving by shelf is visible.
    """

    template_name = "inventory/receiving_overview.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        racks = Location.objects.filter(kind=Location.Kind.RACK)
        receiving = list(racks.filter(name__icontains="receiv").order_by("name"))
        roots = receiving if receiving else list(racks.order_by("name"))
        context["location_tree"] = build_location_tree(roots, statuses=None)
        return context


def _slot_map_for_unit(container):
    """Build an ordered slot-occupancy map for an AMS/dryer container.

    Returns a list of ``{"location": <leaf>, "item": <InventoryItem|None>}`` rows
    ordered by ``slot_index`` (then name), one per assignable child slot. ``item``
    is the single active occupant of that slot, or None when empty. Used to render
    the visual slot grid (ideas.md wireframe C). Returns ``[]`` for a container
    with no slots (so the template simply omits the grid).
    """
    slots = list(
        container.children.filter(kind__in=Location.ASSIGNABLE_KINDS).order_by(
            "slot_index", "name"
        )
    )
    if not slots:
        return []
    slot_ids = [s.id for s in slots]
    occupants = {}
    for item in (
        InventoryItem.objects.filter(location_id__in=slot_ids)
        .exclude(status__in=items.TERMINAL_STATUSES)
        .select_related("product", "location")
    ):
        # One active occupant per slot (capacity 1); first wins if data is dirty.
        occupants.setdefault(item.location_id, item)
    return [{"location": slot, "item": occupants.get(slot.id)} for slot in slots]


class LocationDetailView(LoginRequiredMixin, View):
    """Read-only "what's here" page for a location, plus inline item-move.

    For a leaf, lists the active items physically at that location. For a
    container (rack/dry-storage/AMS/dryer), aggregates items across its whole
    subtree via :meth:`Location.descendant_ids`, grouped by the child leaf they
    sit in. AMS/dryer units (the location itself, or any container child) render a
    visual slot map.

    POST moves a single item to another assignable leaf via
    :func:`items.move_to` with ``enforce_capacity=True`` — this is the first
    production caller to enforce slot capacity. Rejections (full slot / container)
    surface ``result.message``; drying warnings flash exactly as the edit view.
    """

    template_name = "inventory/location_detail.html"

    def _get_location(self, location_id):
        return get_object_or_404(Location, pk=location_id)

    def _grouped_items(self, location):
        """Active items in ``location``'s subtree (or the leaf itself), grouped by
        the leaf location they sit in, ordered for display."""
        if location.is_container:
            scope_ids = location.descendant_ids()
        else:
            scope_ids = {location.id}
        qs = (
            InventoryItem.objects.filter(location_id__in=scope_ids)
            .exclude(status__in=items.TERMINAL_STATUSES)
            .select_related("product", "location")
            .order_by("location__slot_index", "location__name", "id")
        )
        grouped = {}
        total = 0
        for item in qs:
            grouped.setdefault(item.location, []).append(item)
            total += 1
        return grouped, total

    def _slot_maps(self, location):
        """Slot maps to render: the location itself if it's an AMS/dryer, plus any
        AMS/dryer container children (so a rack page still draws its units)."""
        maps = []
        if location.kind in (Location.Kind.AMS, Location.Kind.DRYER):
            rows = _slot_map_for_unit(location)
            if rows:
                maps.append({"unit": location, "rows": rows})
        else:
            for child in location.children.filter(
                kind__in=(Location.Kind.AMS, Location.Kind.DRYER)
            ).order_by("name"):
                rows = _slot_map_for_unit(child)
                if rows:
                    maps.append({"unit": child, "rows": rows})
        return maps

    def _context(self, request, location):
        grouped, total = self._grouped_items(location)
        # An audit-aware deep-link target: if a session is live, scanning a LOC
        # barcode still belongs in the console; surface that path from here.
        audit_active = AuditSession.active() is not None
        return {
            "location": location,
            "grouped_items": grouped,
            "item_count": total,
            "slot_maps": self._slot_maps(location),
            "move_targets": Location.assignable(),
            "audit_active": audit_active,
        }

    def get(self, request, location_id):
        location = self._get_location(location_id)
        return render(request, self.template_name, self._context(request, location))

    def post(self, request, location_id):
        location = self._get_location(location_id)
        item = get_object_or_404(InventoryItem, pk=request.POST.get("item_id") or 0)
        dest_id = (request.POST.get("dest_location") or "").strip()
        dest = (
            Location.objects.filter(pk=dest_id).first() if dest_id.isdigit() else None
        )
        if dest is None:
            messages.error(request, "Choose a valid destination location.")
            return redirect("location_detail", location_id=location.id)

        # First caller to enforce slot capacity (enforce_capacity defaults True).
        result = items.move_to(item, dest, enforce_capacity=True)
        if not result.ok:
            messages.error(request, result.message)
            return redirect("location_detail", location_id=location.id)

        if result.drying_warning:
            level, msg, _needs_ack = result.drying_warning
            if level == "warning":
                messages.warning(request, msg)
            else:  # info / error advisory — flash as info like the edit view
                messages.info(request, msg)

        messages.success(request, f"Moved {item.product.name} to {dest.name}.")
        return redirect("location_detail", location_id=location.id)


class QuickMoveView(LoginRequiredMixin, TemplateView):
    """Phone-first quick scan-to-move page. The interactive body is an HTMX
    fragment (see QuickMoveScanView); this just renders the idle shell."""

    template_name = "inventory/quick_move.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # The /edit/ "Move" button deep-links here as /move/?item=<id> to preload
        # the item as the active one (skips the first scan).
        item_id = self.request.GET.get("item")
        if item_id:
            try:
                item = quickmove.resolve_active_item(f"INV-{item_id}")
            except quickmove.QuickMoveError as exc:
                ctx["state"] = "idle"
                ctx["last_result"] = ("danger", str(exc))
                return ctx
            ctx["state"] = "item"
            ctx["active_item"] = item
            ctx["last_result"] = (
                "info",
                f"Moving {item.product.name} (INV-{item.pk}). Scan a destination.",
            )
            return ctx
        ctx["state"] = "idle"
        return ctx


class QuickMoveScanView(LoginRequiredMixin, View):
    """Input-agnostic scan/action endpoint for the quick-move flow.

    State is carried client-side via the hidden ``active_item_id`` field, so a
    typed entry, USB wedge, or camera decode all POST the same payload. Returns the
    ``quick_move_body.html`` fragment on an HX request; falls back to the full page
    otherwise.
    """

    def post(self, request):
        action = request.POST.get("action", "")
        if action == "reset":
            return self._render(request, state="idle")
        if action == "show_item":
            item = self._item(request.POST.get("active_item_id"))
            if item is None:
                return self._render(request, state="idle")
            return self._render(request, state="item", active_item=item)
        if action == "deplete_active":
            item = self._item(request.POST.get("active_item_id"))
            if item is None:
                return self._render(request, state="idle")
            items.deplete(item, reason="quick-move")
            return self._render(
                request,
                state="idle",
                last_result=("success", f"Depleted {item.product.name}."),
            )
        if action == "evict":
            return self._evict(request)

        # A scan (no action): resolve item if none active, else a destination.
        active = self._item(request.POST.get("active_item_id"))
        code = request.POST.get("code", "")
        if active is None:
            return self._scan_item(request, code)
        return self._scan_destination(request, active, code)

    # --- helpers ---------------------------------------------------------
    @staticmethod
    def _int(raw):
        """Coerce a POST value to an int pk, or None on empty/junk.

        Django does NOT map a non-numeric ``.filter(pk=...)`` to a 404 — it raises
        ValueError (a 500). Junk ids must degrade gracefully here.
        """
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    def _item(self, raw_id):
        pk = self._int(raw_id)
        if pk is None:
            return None
        # No select_related("product"): with django-polymorphic that would
        # materialize the base Product, silently disabling the drying-safety check
        # (filament_drying_warning's isinstance(self.product, Filament) guard).
        return InventoryItem.objects.filter(pk=pk).select_related("location").first()

    def _scan_item(self, request, code):
        try:
            item = quickmove.resolve_active_item(code)
        except quickmove.QuickMoveError as exc:
            return self._render(request, state="idle", last_result=("danger", str(exc)))
        return self._render(
            request,
            state="item",
            active_item=item,
            last_result=(
                "info",
                f"Moving {item.product.name} (INV-{item.pk}). Scan a destination.",
            ),
        )

    def _scan_destination(self, request, active, code):
        # Defense-in-depth: the legitimate UI only carries a non-terminal
        # active_item_id (resolve_active_item guards that up front), but a forged
        # or replayed POST could re-enter here with a DEPLETED/SOLD id. _item()
        # has no terminal guard, and move_to would no-op such an item while the
        # view still rendered a false "Moved" success. UNKNOWN stays movable.
        if active.status in items.TERMINAL_STATUSES:
            return self._render(
                request,
                state="idle",
                last_result=(
                    "danger",
                    f"INV-{active.pk} is {active.get_status_display()} — "
                    "revive it from its edit page first.",
                ),
            )
        try:
            dest = quickmove.resolve_destination(code)
        except quickmove.QuickMoveError as exc:
            return self._render(
                request,
                state="item",
                active_item=active,
                last_result=("danger", str(exc)),
            )
        if dest.needs_slot_pick:
            return self._render(
                request,
                state="container",
                active_item=active,
                dest=dest.location,
                slot_rows=_slot_map_for_unit(dest.location),
                last_result=("info", f"{dest.location.name}: pick a slot."),
            )
        # Mirror the edit view: an error-level drying warning blocks the move.
        warning = active.filament_drying_warning(dest.location)
        if warning and warning[0] == "error":
            return self._render(
                request,
                state="item",
                active_item=active,
                last_result=("danger", warning[1]),
            )
        outcome = quickmove.attempt_move(active, dest.location)
        if outcome.kind == "ok":
            return self._placed(request, active, dest.location, outcome.result)
        if outcome.kind == "full":
            return self._render(
                request,
                state="full",
                active_item=active,
                dest=dest.location,
                occupant=outcome.occupant,
                last_result=("warning", f"{dest.location.name} is full."),
            )
        return self._render(
            request,
            state="item",
            active_item=active,
            last_result=("danger", outcome.message),
        )

    def _placed(self, request, item, dest, result):
        tag, msg = "success", f"Moved {item.product.name} to {dest.name}."
        if result.drying_warning:
            level, wmsg, _ = result.drying_warning
            msg = f"{msg} — {wmsg}"
            if level in ("warning", "error"):
                tag = "warning"
        return self._render(request, state="idle", last_result=(tag, msg))

    def _evict(self, request):
        incoming = self._item(request.POST.get("active_item_id"))
        occupant = self._item(request.POST.get("occupant_id"))
        dest_pk = self._int(request.POST.get("dest_id"))
        dest = (
            Location.objects.filter(pk=dest_pk).first() if dest_pk is not None else None
        )
        deplete_old = request.POST.get("deplete_old") == "1"
        if not (incoming and occupant and dest):
            return self._render(
                request,
                state="idle",
                last_result=("danger", "Lost track of the swap — rescan the item."),
            )
        # Defense-in-depth (mirrors _scan_destination): a forged/replayed evict
        # POST could carry a terminal incoming item. _item() has no terminal
        # guard, so block it here before evict_and_place would no-op the move
        # yet render a false "Placed" success. UNKNOWN stays movable.
        if incoming.status in items.TERMINAL_STATUSES:
            return self._render(
                request,
                state="idle",
                last_result=(
                    "danger",
                    f"INV-{incoming.pk} is {incoming.get_status_display()} — "
                    "revive it from its edit page first.",
                ),
            )
        result, evicted = quickmove.evict_and_place(
            occupant, incoming, dest, deplete_old=deplete_old
        )
        if not result.ok:
            return self._render(
                request, state="idle", last_result=("danger", result.message)
            )
        if evicted is None:
            return self._render(
                request,
                state="idle",
                last_result=(
                    "success",
                    f"Depleted {occupant.product.name}; placed "
                    f"{incoming.product.name} in {dest.name}.",
                ),
            )
        return self._render(
            request,
            state="item",
            active_item=evicted,
            last_result=(
                "success",
                f"Placed {incoming.product.name} in {dest.name}. Now scan where "
                f"{evicted.product.name} (INV-{evicted.pk}) goes.",
            ),
        )

    def _render(
        self,
        request,
        *,
        state,
        active_item=None,
        dest=None,
        occupant=None,
        slot_rows=None,
        last_result=None,
    ):
        context = {
            "state": state,
            "active_item": active_item,
            "dest": dest,
            "occupant": occupant,
            "slot_rows": slot_rows,
            "last_result": last_result,
        }
        if request.headers.get("HX-Request"):
            return render(request, "inventory/partials/quick_move_body.html", context)
        return render(request, "inventory/quick_move.html", context)


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


# ---- Print jobs & utilization (Phase 15.2) --------


class PrintJobListView(LoginRequiredMixin, TemplateView):
    template_name = "inventory/print_job_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["jobs"] = (
            PrintJob.objects.select_related("printer__product")
            .prefetch_related("filaments")
            .all()
        )
        return ctx


class PrintJobCreateView(LoginRequiredMixin, View):
    """Create a PrintJob plus its filament lines, then apply consumption.

    Thin view: it owns only form/formset wiring and the redirect. The actual
    decrement/deplete logic lives in :func:`inventory.printjobs.complete_job`,
    mirroring how ``AddInventoryView`` keeps label printing in the view but
    inventory mutation in the service.
    """

    template_name = "inventory/print_job_form.html"

    def get(self, request):
        return render(
            request,
            self.template_name,
            {"form": PrintJobForm(), "formset": PrintJobFilamentFormSet()},
        )

    def post(self, request):
        form = PrintJobForm(request.POST)
        formset = PrintJobFilamentFormSet(request.POST)
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                job = form.save()
                formset.instance = job
                formset.save()
                # Manual entry is treated as a completed run: apply consumption
                # to the referenced spools (decrement + deplete at ~0).
                depleted = printjobs.complete_job(job)
            messages.success(request, f"Logged print job '{job}'.")
            for spool in depleted:
                messages.warning(
                    request, f"{spool} reached 0% and was marked depleted."
                )
            return redirect("print_job_detail", pk=job.pk)
        return render(request, self.template_name, {"form": form, "formset": formset})


class PrintJobDetailView(LoginRequiredMixin, TemplateView):
    template_name = "inventory/print_job_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["job"] = get_object_or_404(
            PrintJob.objects.select_related("printer__product").prefetch_related(
                "filaments__item__product"
            ),
            pk=kwargs["pk"],
        )
        return ctx


class UtilizationView(LoginRequiredMixin, TemplateView):
    """Fleet-wide printer utilization: hours, job count, success %, kg by material."""

    template_name = "inventory/printer_utilization.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["printers"] = printjobs.utilization_summary()
        ctx["consumption"] = printjobs.consumption_by_material()
        ctx["total_jobs"] = sum(p["jobs"] for p in ctx["printers"])
        ctx["total_hours"] = round(sum(p["hours"] for p in ctx["printers"]), 1)
        ctx["total_kg"] = round(sum(p["kg"] for p in ctx["printers"]), 2)
        return ctx


class PrinterUtilizationDetailView(LoginRequiredMixin, TemplateView):
    """Per-printer utilization, reachable from the machine's item page."""

    template_name = "inventory/printer_utilization_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        printer = get_object_or_404(
            InventoryItem.objects.select_related("product"), pk=kwargs["pk"]
        )
        ctx["printer"] = printer
        ctx["printer_name"] = str(printer.product.get_real_instance())
        ctx["stats"] = printjobs.printer_utilization(printer)
        ctx["jobs"] = (
            PrintJob.objects.filter(printer=printer).prefetch_related("filaments").all()
        )
        return ctx


# ---------------------------------------------------------------------------
# Procurement & receiving (Phase 14)
# ---------------------------------------------------------------------------


class PurchaseOrderListView(LoginRequiredMixin, TemplateView):
    """All purchase orders with received-progress at a glance (DataTables)."""

    template_name = "inventory/po_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Aggregate line counts/values in the DB rather than per-row Python.
        context["orders"] = (
            PurchaseOrder.objects.select_related("supplier")
            .annotate(
                line_count=Count("lines", distinct=True),
                qty_ordered=Sum("lines__qty_ordered"),
                qty_received=Sum("lines__qty_received"),
            )
            .order_by("-created_at")
        )
        context["statuses"] = PurchaseOrder.Status
        return context


class PurchaseOrderDetailView(LoginRequiredMixin, TemplateView):
    """A single PO: reconciliation table (ordered vs received vs outstanding)."""

    template_name = "inventory/po_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        order = get_object_or_404(
            PurchaseOrder.objects.select_related("supplier"), pk=kwargs["pk"]
        )
        context["order"] = order
        context["recon"] = procurement.reconcile(order)
        context["latest_receipt"] = order.receipts.first()
        return context


class ReceivingConsoleView(LoginRequiredMixin, TemplateView):
    """Scan-against-a-PO console.

    Opens (get_or_create) the PO's working receipt and renders the input-agnostic
    scan form. Mirrors the audit console: a USB wedge or a camera JS POST both
    deliver a ``code`` to :class:`ReceivingScanView`.
    """

    template_name = "inventory/receiving_console.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        order = get_object_or_404(
            PurchaseOrder.objects.select_related("supplier"), pk=kwargs["pk"]
        )
        receipt = self._get_or_open_receipt(order)
        context["order"] = order
        context["receipt"] = receipt
        context["recon"] = procurement.reconcile(order)
        context["rack_locations"] = Location.assignable()
        return context

    @staticmethod
    def _get_or_open_receipt(order):
        receipt = order.receipts.first()
        if receipt is None:
            receipt = PurchaseReceipt.objects.create(order=order)
        return receipt


class ReceivingScanView(LoginRequiredMixin, View):
    """Input-agnostic receiving scan: a wedge form-submit or a camera JS POST both
    deliver a ``code`` (UPC) + ``location`` here; mints/receives one unit and
    prints an ``INV-`` label (soft-fail), mirroring AddInventoryView."""

    def post(self, request, pk):
        order = get_object_or_404(PurchaseOrder, pk=pk)
        receipt = order.receipts.first() or PurchaseReceipt.objects.create(order=order)

        code = (request.POST.get("code") or "").strip()
        location = Location.objects.filter(pk=request.POST.get("location")).first()

        try:
            result = procurement.receive_scan(receipt, code, location)
        except procurement.ProcurementError as exc:
            messages.error(request, str(exc))
            return redirect("receiving_console", pk=order.pk)

        if result.item is not None:
            try:
                generate_and_print_barcode(result.item, mode="unique")
            except Exception as e:  # label print is non-fatal, like AddInventoryView
                messages.warning(request, f"Label printing failed: {e}")
                logger.error(f"Label printing failed: {e}")

        messages.success(request, result.message)
        return redirect("receiving_console", pk=order.pk)


class SpendReportView(LoginRequiredMixin, TemplateView):
    """Spend report: tracked unit_costs + cost-only line totals, per supplier."""

    template_name = "inventory/spend_report.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["summary"] = procurement.spend_summary()
        context["by_supplier"] = procurement.spend_by_supplier()
        return context


class StaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Gate a view to staff users.

    Anonymous → 302 to login; authenticated non-staff → 403. ``raise_exception``
    is computed dynamically so anonymous users fall through to
    LoginRequiredMixin's redirect instead of being 403'd.
    """

    def test_func(self):
        return self.request.user.is_staff

    @property
    def raise_exception(self):
        # Only raise (403) for authenticated users; anonymous users get the
        # login redirect from LoginRequiredMixin.
        return self.request.user.is_authenticated


class StaffUserListView(StaffRequiredMixin, View):
    """Staff-only list of all users, each linking to a password-reset page."""

    def get(self, request):
        users = get_user_model().objects.order_by("username")
        return render(request, "inventory/staff_user_list.html", {"users": users})


class StaffUserPasswordView(StaffRequiredMixin, View):
    """Staff-only: set a new password for another user via SetPasswordForm."""

    def _get_target(self, user_id):
        return get_object_or_404(get_user_model(), pk=user_id)

    def get(self, request, user_id):
        target = self._get_target(user_id)
        form = SetPasswordForm(target)
        return render(
            request,
            "inventory/staff_user_password.html",
            {"form": form, "target_user": target},
        )

    def post(self, request, user_id):
        target = self._get_target(user_id)
        form = SetPasswordForm(target, request.POST)
        if form.is_valid():
            form.save()
            logger.info(
                f"Staff user {request.user.username} reset password for "
                f"{target.username}"
            )
            messages.success(request, f"Password updated for {target.username}.")
            return redirect("staff_user_list")
        return render(
            request,
            "inventory/staff_user_password.html",
            {"form": form, "target_user": target},
        )
