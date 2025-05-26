from django.urls import path
from .views import *
from django.contrib.auth import views as auth_views

urlpatterns = [
    path("about/", AboutView.as_view(), name="about"),
    path("", Index.as_view(), name="index"),
    path("dashboard/", Dashboard.as_view(), name="dashboard"),
    # path('edit-item/<int:pk>', EditItem.as_view(), name='edit-item'),
    # path('delete-item/<int:pk>', DeleteItem.as_view(), name='delete-item'),
    # path('move-item/', MoveItem.as_view(), name='move-item'),
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
    path("addinventory/", addInventoryView.as_view(), name="add_inventory"),
    path(
        "add-product-choice/", AddProductChoiceView.as_view(), name="add_product_choice"
    ),
    path("add-filament/", AddFilamentView.as_view(), name="add_filament"),
    path("add-printer/", AddPrinterView.as_view(), name="add_printer"),
    path("add-ams/", AddAMSView.as_view(), name="add_ams"),
    path("add-hardware/", AddHardwareView.as_view(), name="add_hardware"),
    path("add-dryer/", AddDryerView.as_view(), name="add_dryer"),
    path("search/", InventorySearchView.as_view(), name="inventory_search"),
    path("edit/<int:item_id>/", inventoryEditView.as_view(), name="inventory_edit"),
    path("search/export/", InventoryExportView.as_view(), name="inventory_export"),
    path(
        "print_barcode/<int:item_id>/<str:mode>/",
        PrintBarcodeView.as_view(),
        name="print_barcode",
    ),
    path(
        "barcode/<str:value>/", BarcodeRedirectView.as_view(), name="barcode_redirect"
    ),
]
