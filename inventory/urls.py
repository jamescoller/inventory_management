from django.contrib.auth import views as auth_views
from django.urls import path

from .views import (
    AboutView,
    AddAMSView,
    AddDryerView,
    AddFilamentView,
    AddHardwareView,
    AddInventoryView,
    AddPrinterView,
    AddProductChoiceView,
    BarcodeRedirectView,
    BulkUpdateView,
    Dashboard,
    DryStorageOverviewView,
    FilamentColorGuideView,
    FilamentGuideView,
    FilamentSummaryView,
    Index,
    InUseOverviewView,
    InventoryEditView,
    InventoryExportView,
    InventorySearchView,
    PrintBarcodeView,
    SignUpView,
)

urlpatterns = [
    path("about/", AboutView.as_view(), name="about"),
    path("", Index.as_view(), name="index"),
    path("dashboard/", Dashboard.as_view(), name="dashboard"),
    path("signup/", SignUpView.as_view(), name="signup"),
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="inventory/login.html"),
        name="login",
    ),
    path(
        "logout/",
        auth_views.LogoutView.as_view(template_name="inventory/logout.html"),
        name="logout",
    ),
    path("addinventory/", AddInventoryView.as_view(), name="add_inventory"),
    path(
        "add-product-choice/", AddProductChoiceView.as_view(), name="add_product_choice"
    ),
    path("add-filament/", AddFilamentView.as_view(), name="add_filament"),
    path("add-printer/", AddPrinterView.as_view(), name="add_printer"),
    path("add-ams/", AddAMSView.as_view(), name="add_ams"),
    path("add-hardware/", AddHardwareView.as_view(), name="add_hardware"),
    path("add-dryer/", AddDryerView.as_view(), name="add_dryer"),
    path("search/", InventorySearchView.as_view(), name="inventory_search"),
    path("bulk-update/", BulkUpdateView.as_view(), name="bulk_update"),
    path("edit/<int:item_id>/", InventoryEditView.as_view(), name="inventory_edit"),
    path("search/export/", InventoryExportView.as_view(), name="inventory_export"),
    path(
        "print_barcode/<int:item_id>/<str:mode>/",
        PrintBarcodeView.as_view(),
        name="print_barcode",
    ),
    path(
        "barcode/<str:value>/", BarcodeRedirectView.as_view(), name="barcode_redirect"
    ),
    path("in-use-overview/", InUseOverviewView.as_view(), name="in_use_overview"),
    path(
        "filament-color-guide/",
        FilamentColorGuideView.as_view(),
        name="filament_color_guide",
    ),
    path("filament-guide/", FilamentGuideView.as_view(), name="filament_guide"),
    path("filament-summary/", FilamentSummaryView.as_view(), name="filament_summary"),
    path(
        "dry-storage-overview/",
        DryStorageOverviewView.as_view(),
        name="dry_storage_overview",
    ),
]
