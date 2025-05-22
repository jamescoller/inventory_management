# Inventory Management Concept

## 1. Libraries
`django`

### Specific Imports

```python
from django.db import models
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
```

## 2. Models
We'll be using subclasses of our model classes in this case. For more information, see the [Django documentation](https://docs.djangoproject.com/en/5.2/topics/db/models/#model-inheritance).

### 1. Product

This is the structure for known "products" sold by a manufacturer. It will be matched with inventory items.
We don't want to have database entries of just 'Product' on its own, so we want to set it as an Abstract base class.
This means that the sub-classed models will pull their common properties from the base class when they are created, but
the base class on its own cannot be created.
> Note: To make this abstract, use the following syntax within the class definition:
> ```python
> class Meta:
>   abstract = True
> ```
The Product class will contain several subclasses with inherited properties from the parent product.

| **Property** | **Name** | **Field**    | **Default** | **Notes/Other**                |
|--------------|----------|--------------|-------------|--------------------------------|
| Name         | name     | CharField    |             |                                |
| UPC          | upc      | CharField    |             | unique=True                    |
| Unit Price   | price    | DecimalField | 0.00        | max_digits=6, decimal_places=2 |
| Bambu SKU    | sku      | CharField    |             | max_length=8                   |

In python, using django, this will look like the following:
```python
class Product(models.Model):
	name = models.CharField(max_length=255)
	upc = models.CharField(max_length=50, unique=True)
	price = models.DecimalField(max_digits=6, decimal_places=2, default=0)

	class Meta:
		abstract = True
```
#### Filament Sub-Class
Now, filaments will have several unique properties that are not shared with all other subclasses of products.

| **Property**               | **Name**              | **Field**    | **Default** | **Options**                    | Notes               |
|----------------------------|-----------------------|--------------|-------------|--------------------------------|---------------------|
| Plastic Material           | material              | CharField    |             |                                |                     |
| Material Sub-Type          | material_type         | CharField    |             | null=True, blank=True          |                     |
| Color (English)            | color_name            | CharField    |             |                                |                     |
| Color (HEX)                | hex_code              | CharField    |             | max_length=7                   |                     |
| Printing Temp Min (degC)   | print_temp_min_degC   | IntegerField | 0           | blank=True                     |                     |
| Printing Temp Max (degC)   | print_temp_max_degC   | IntegerField | 0           | blank=True                     |                     |
| Printing Temp Ideal (degC) | print_temp_ideal_degC | IntegerField |             | blank=True                     | Based on User Notes |
| Drying Temperature (degC)  | drying_temp_degC      | IntegerField |             | blank=True                     |                     |
| Drying Time (Hrs)          | drying_time           | IntegerField |             | blank=True                     |                     |
| Standard Size (kg)         | size_kg               | DecimalField | 1.0         | max_digits=3, decimal_places=2 |                     |

```python
class Filament(Product):
	material = models.CharField(max_length=50)
	material_type = models.CharField(max_length=50, blank=True)
	color = models.CharField(max_length=50)
	hex_code = models.CharField(max_length=7)
	print_temp_min_degC = models.IntegerField(blank=True)
	print_temp_max_degC = models.IntegerField(blank=True)
	print_temp_ideal_degC = models.IntegerField(blank=True)
	dry_temp_min_degC = models.IntegerField(blank=True)
	dry_temp_max_degC = models.IntegerField(blank=True)
	dry_temp_ideal_degC = models.IntegerField(blank=True)
	dry_time_hrs = models.IntegerField(blank=True)

	# Edit the database table that filament will be added to, and note it
	# Abstract=False by default on children classes
	class Meta(Product.Meta):
		db_table = 'filaments'
		db_table_comment = 'Filaments offered by Bambu; not necessarily in current inventory'
```

#### Printer Subclass
```python
# Printer subclass
class Printer(Product):
	mfr = models.CharField(max_length=100, default='Bambu Lab')
	model = models.CharField(max_length=100, default='X1 Carbon')
	num_extruders = models.IntegerField(max_length=1, default=1)
	bed_length_mm = models.IntegerField(max_length=3, blank=True)
	bed_width_mm = models.IntegerField(max_length=3, blank=True)
	max_height_mm = models.IntegerField(max_length=3, blank=True)
	print_volume_mm3 = models.DecimalField(decimal_places=2, max_digits=10, blank=True)

	class Meta(Product.Meta):
		db_table = 'printers'
		db_table_comment = 'Printers offered by Bambu; not necessarily in current inventory'
```
#### Dryer Subclass
```python
# Dryer subclass
class Dryer(Product):
	mfr = models.CharField(max_length=100)
	model = models.CharField(max_length=100)
	num_slots = models.IntegerField(max_length=1, default=1)
	max_temp_degC = models.IntegerField(blank=True, max_length=3)

	class Meta(Product.Meta):
		db_table = 'dryers'
		db_table_comment = 'Dryers on the market; not necessarily in current inventory'
```
#### AMS Subclass
````python
# AMS subclass
class AMS(Product):
	mfr = models.CharField(max_length=100, default='Bambu Lab')
	model = models.CharField(max_length=100, default='X1 Carbon')
	num_slots = models.IntegerField(blank=True, default=4, max_length=1)

	class Meta(Product.Meta):
		db_table = 'ams'
		db_table_comment = 'AMS units on the market; not necessarily in current inventory'
````
#### Hardware Subclass
````python
# Hardware subclass
class Hardware(Product):
	usage = models.CharField(max_length=100, blank=True)
	class HardwareType(models.IntegerChoices):
		ACCESSORY = 1, 'Accessory'
		PARTS = 2, 'Parts'
		HARDWARE = 3, 'Hardware'

	kind = models.IntegerField(choices=HardwareType.choices, default=HardwareType.HARDWARE)

	class Meta(Product.Meta):
		db_table = 'hardware'
		db_table_comment = 'Hardware, accessories, or parts on the market; not necessarily in current inventory'


````
### Inventory Item
```python
# InventoryItem with generic relation to any Product subclass
class InventoryItem(models.Model):
	product_type = models.ForeignKey('Product', on_delete=models.CASCADE)
	sku = models.CharField(max_length=120)
	shipment = models.CharField(max_length=100, blank=True)
	timestamp = models.DateTimeField(auto_now_add=True)

	class Status(models.IntegerChoices):
		NEW = 1, "new"
		IN_USE = 2, "in use"
		DRYING = 3, "drying"
		STORED = 4, "stored"
		DEPLETED = 5, "depleted"

	date_added = models.DateTimeField(auto_now_add=True)
	last_modified = models.DateTimeField(auto_now=True)
	date_depleted = models.DateTimeField(null=True, blank=True)
	user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
	location = models.ForeignKey('Location', on_delete=models.SET_NULL, blank=True, null=True)
	status = models.PositiveSmallIntegerField(choices=Status.choices, default=Status.NEW)

	def __str__(self):
		return f"{self.sku} - {self.timestamp.strftime('%Y-%m-%d')}"
```

### Location
```python
class Location(models.Model):
	name = models.CharField(max_length=200)
	class Meta:
		verbose_name_plural = 'locations'

	def __str__(self):
		return self.name
```

### Order
```python
class Order(models.Model):
	order_num = models.CharField(max_length=100)

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self._my_list = []

	@property
	def item_list(self):
		return self._item_list

	@item_list.setter
	def item_list(self, value):
		if not isinstance(value, list):
			raise ValueError("item_list must be a list")
		self._item_list = value

	def append_to_list(self, item):
		self._item_list.append(item)

	def remove_from_list(self, item):
		self._item_list.remove(item)

class Shipment(Order):
	tracking = models.CharField(max_length=200)

	class Meta:
		db_table = 'shipments'
```
