import django_tables2 as tables
from inventory.models import InventoryItem


class InventoryItemTable(tables.Table):
    name = tables.Column(accessor='product.name', verbose_name='Product', order_by='product__name')
    sku = tables.Column(accessor='product.sku', verbose_name='SKU', order_by='product__sku')
    upc = tables.Column(accessor='product.upc', verbose_name='UPC', order_by='product__upc')
    location = tables.Column(accessor='location.name', verbose_name='Location')
    date_added = tables.DateTimeColumn(format="Y-m-d H:i:s", verbose_name='Added')

    edit = tables.TemplateColumn(
        template_code='<a href="{% url \'inventory_edit\' record.id %}" class="btn btn-sm btn-outline-secondary">Edit</a>',
        orderable=False,
        verbose_name=''
    )

    class Meta:
        model = InventoryItem
        template_name = 'django_tables2/bootstrap5.html'
        fields = ()  # We'll declare fields manually via columns