from django.db import models
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from polymorphic.models import PolymorphicModel

# Polymorphic Base Product
class Product(PolymorphicModel):
	name = models.CharField(max_length=255)
	upc = models.CharField(max_length=50, unique=True) # the 13-digit barcode
	sku = models.CharField(max_length=8, null=True, blank=True) # a 6 character internal code within Bambu Lab
	price = models.DecimalField(decimal_places=2, max_digits=5, null=True, blank=True)
	notes = models.TextField(blank=True)
	category = models.CharField(max_length=255, null=True, blank=True)

	class Meta:
		# abstract = True
		ordering = ['sku']

	def __str__(self):
		return f"{self.name}"


# Filament subclass
class Filament(Product):
	material = models.CharField(max_length=50)
	material_type = models.CharField(max_length=50, blank=True, null=True)
	color = models.CharField(max_length=50)
	hex_code = models.CharField(max_length=7)
	print_temp_min_degC = models.IntegerField(blank=True, null=True)
	print_temp_max_degC = models.IntegerField(blank=True, null=True)
	print_temp_ideal_degC = models.IntegerField(blank=True, null=True)
	dry_temp_min_degC = models.IntegerField(blank=True, null=True)
	dry_temp_max_degC = models.IntegerField(blank=True, null=True)
	dry_temp_ideal_degC = models.IntegerField(blank=True,null=True)
	dry_time_hrs = models.IntegerField(blank=True, null=True)
	inventory_items = GenericRelation('InventoryItem')

	def __str__(self):
		return f"{self.name} ({self.color})"

	# Edit the database table that filament will be added to, and note it
	# Abstract=False by default on children classes
	# class Meta(Product.Meta):
		# db_table = 'filaments'
		# db_table_comment = 'Filaments offered by Bambu; not necessarily in current inventory'

# Printer subclass
class Printer(Product):
	mfr = models.CharField(max_length=100, default='Bambu Lab')
	model = models.CharField(max_length=100, default='X1 Carbon')
	num_extruders = models.IntegerField()
	bed_length_mm = models.IntegerField(blank=True, null=True)
	bed_width_mm = models.IntegerField(blank=True, null=True)
	max_height_mm = models.IntegerField(blank=True, null=True)
	print_volume_mm3 = models.DecimalField(decimal_places=2, max_digits=10, blank=True, null=True)
	inventory_items = GenericRelation('InventoryItem')

	def __str__(self):
		return f"{self.name} - {self.model}"
	# class Meta(Product.Meta):
	# 	db_table = 'printers'
		# db_table_comment = 'Printers offered by Bambu; not necessarily in current inventory'

# Dryer subclass
class Dryer(Product):
	mfr = models.CharField(max_length=100)
	model = models.CharField(max_length=100)
	num_slots = models.IntegerField( default=1)
	max_temp_degC = models.IntegerField(blank=True, null=True)
	inventory_items = GenericRelation('InventoryItem')

	# class Meta(Product.Meta):
	# 	db_table = 'dryers'
		# db_table_comment = 'Dryers on the market; not necessarily in current inventory'

	def __str__(self):
		return f"{self.name} (Part #: {self.model})"


# AMS subclass
class AMS(Product):
	mfr = models.CharField(max_length=100, default='Bambu Lab')
	model = models.CharField(max_length=100, default='AMS')
	num_slots = models.IntegerField(blank=True, default=4)
	inventory_items = GenericRelation('InventoryItem')
	# class Meta(Product.Meta):
	# 	db_table = 'ams'
		# db_table_comment = 'AMS units on the market; not necessarily in current inventory'

	def __str__(self):
		return f"{self.name} (Part #: {self.model})"


# Hardware subclass
class Hardware(Product):
	usage = models.CharField(max_length=100, blank=True)
	class HardwareType(models.IntegerChoices):
		ACCESSORY = 1, 'Accessory'
		PARTS = 2, 'Parts'
		HARDWARE = 3, 'Hardware'

	kind = models.IntegerField(choices=HardwareType.choices, default=HardwareType.HARDWARE)
	inventory_items = GenericRelation('InventoryItem')
	# class Meta(Product.Meta):
	# 	db_table = 'hardware'
		# db_table_comment = 'Hardware, accessories, or parts on the market; not necessarily in current inventory'

	def __str__(self):
		return f"{self.name} (Part #: {self.part_number})"

# InventoryItem with ForeignKey to polymorphic Product
class InventoryItem(models.Model):
	upc = models.CharField(max_length=120)
	shipment = models.CharField(max_length=100, blank=True, null=True)
	timestamp = models.DateTimeField(auto_now_add=True)
	date_added = models.DateTimeField(auto_now_add=True)
	product = models.ForeignKey(Product, on_delete=models.CASCADE)

	class Status(models.IntegerChoices):
		NEW = 1, "new"
		IN_USE = 2, "in use"
		DRYING = 3, "drying"
		STORED = 4, "stored"
		DEPLETED = 5, "depleted"


	last_modified = models.DateTimeField(auto_now=True)
	date_depleted = models.DateTimeField(null=True, blank=True)
	user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
	location = models.ForeignKey('Location', on_delete=models.SET_NULL, blank=True, null=True)
	status = models.PositiveSmallIntegerField(choices=Status.choices, default=Status.NEW)

	def __str__(self):
		return f"{self.upc} - {self.timestamp.strftime('%Y-%m-%d')}"


class Location(models.Model):
	name = models.CharField(max_length=200)
	class Meta:
		verbose_name_plural = 'locations'

	def __str__(self):
		return self.name

class Order(PolymorphicModel):
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

	# class Meta:
	# 	db_table = 'shipments'