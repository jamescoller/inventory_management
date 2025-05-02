from django.db import models
from django.contrib.auth.models import User

class InventoryItem(models.Model):
	class Status(models.IntegerChoices):
		NEW = 1, "new"
		IN_USE = 2, "in use"
		DRYING = 3, "drying"
		STORED = 4, "stored"
		DEPLEATED = 5, "depleted"

	sku = models.CharField(max_length=120)
	category = models.ForeignKey('Category', on_delete=models.SET_NULL, blank=True, null=True)
	date_created = models.DateTimeField(auto_now_add=True)
	last_modified = models.DateTimeField(auto_now=True)
	date_depleated = models.DateTimeField(null=True, blank=True)
	user = models.ForeignKey(User, on_delete=models.CASCADE)
	location = models.ForeignKey('Location', on_delete=models.SET_NULL, blank=True, null=True)
	shipment = models.CharField(max_length=120)
	status = models.PositiveSmallIntegerField(choices=Status.choices, default=Status.NEW)


	def __str__(self):
		return self.sku

class Category(models.Model):
	name = models.CharField(max_length=200)

	class Meta:
		verbose_name_plural = 'categories'

	def __str__(self):
		return self.name

class Location(models.Model):
	name = models.CharField(max_length=200)
	class Meta:
		verbose_name_plural = 'locations'

	def __str__(self):
		return self.name