import colorsys
import re

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.timezone import now
from polymorphic.models import PolymorphicModel


# Polymorphic Base Product
class Product(PolymorphicModel):
    """
    Represents a product entity within the application.

    Intended to model products with attributes such as name, UPC, SKU, price,
    and additional notes. This class relies on Django's ORM to store product
    data in a relational database, while also being polymorphic to support
    product-type-specific extensions.

    Attributes:
            name: The name of the product.
            upc: The unique 13-digit barcode for the product.
            sku: A six-character internal code specific to Bambu Lab. Can be blank.
            price: The monetary value of the product stored with two decimal places.
                       Can be null or blank if not provided.
            notes: Additional free-text information about the product. Optional.
            polymorphic_ctype: A foreign key to ContentType for polymorphic
                                               behavior. Customizes the display of associated
                                               product types. Not editable by users.
    """

    name = models.CharField(max_length=255)
    upc = models.CharField(
        max_length=50, unique=True, help_text="12 or 13 digit barcode number"
    )  # the 13-digit barcode
    sku = models.CharField(
        max_length=10,
        blank=True,
        help_text="A shorter ID code within Bambu Lab",
        default="",
    )  # an internal code within Bambu Lab
    price = models.DecimalField(decimal_places=2, max_digits=6, null=True, blank=True)
    notes = models.TextField(blank=True, default="")

    class Meta:
        # abstract = True
        ordering = ["sku"]
        verbose_name = "Product"
        verbose_name_plural = "Products"

    # Override the name of the polymorphic ctype and customize it so it's more readable
    polymorphic_ctype = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        editable=False,
        verbose_name="Product Type",
        related_name="+",
        null=True,
    )

    def __str__(self):
        return f"{self.name}"


# Filament subclass
class Filament(Product):
    """
    Represents a filament product subclassed from the Product class.

    This class is intended to represent a filament with associated attributes such as material,
    color, and hexadecimal color code. It includes functionality for normalizing and validating
    hex color codes before saving the object to the database. The purpose of this class is to
    support the management and proper handling of filament-specific properties and data.

    Attributes
    ----------
    material : models.ForeignKey
            A foreign key to the Material model. Can be null or unset.
    color : models.CharField
            A human-readable color name with a max length of 50 characters.
    hex_code : models.CharField
            A hexadecimal color code string, typically in the format starting with '#' (e.g., "#FFFFFF").
    weight : models.DecimalField
            A decimal weight in kilograms with a maximum of 4 digits including 2 after the decimal point. This represents the weight of new spool of this filament.
    """

    material = models.ForeignKey(
        "Material", on_delete=models.SET_NULL, blank=True, null=True
    )

    color = models.CharField(
        max_length=50, blank=True, help_text="Human-readable color name"
    )  # The name of the color (human-readable)
    hex_code = models.CharField(
        max_length=7,
        blank=True,
        help_text="3 or 6 character hexadecimal color code string",
    )  # Color HEX code
    weight = models.DecimalField(
        decimal_places=2,
        max_digits=4,
        blank=True,
        null=True,
        help_text="Weight of the filament in kilograms",
    )
    has_spool = models.BooleanField(
        default=False, help_text="Does the filament come on a spool?"
    )  # True if the filament comes with a spool, false if it is a refill

    def normalize_hex_code(self):
        """
        Normalize and validate a hex color code.

        Removes leading and trailing whitespaces, converts the color code to lowercase,
        and ensures it starts with '#'. It validates whether the color code is in a
        proper hexadecimal format (3 or 6 characters) and updates the attribute accordingly.
        Returns the normalized hex code if valid, otherwise returns None.

        Raises
        ------
        AttributeError
                If the `hex_code` attribute is not defined.

        Returns
        -------
        str or None
                The normalized hex code if the provided code is valid, otherwise None.
        """
        rev_code = self.hex_code.strip().lower().lstrip("#")
        if re.fullmatch(r"(?:[0-9a-fA-F]{3}){1,2}", rev_code):
            self.hex_code = f"#{rev_code}"
            return self.hex_code
        else:
            return None

    COLOR_FAMILIES = [
        ("RED", "Red"),
        ("ORANGE", "Orange"),
        ("YELLOW", "Yellow"),
        ("GREEN", "Green"),
        ("BLUE", "Blue"),
        ("PURPLE", "Purple"),
        ("PINK", "Pink"),
        ("BROWN", "Brown"),
        ("BLACK", "Black"),
        ("GRAY", "Gray"),
        ("WHITE", "White"),
        ("TRANSLUCENT", "Translucent"),
    ]

    color_family = models.CharField(
        max_length=20,
        choices=COLOR_FAMILIES,
        blank=True,
        help_text="Automatically determined from hex code",
    )

    def get_color_family(self):
        """
        Determines color family from hex code by converting to HSV color space
        """
        if not self.hex_code:
            return None

        # Special case for translucent filament
        if self.hex_code.upper() in ["#FFFFFF00", "#FAFAFF"]:
            return "TRANSLUCENT"

        # Convert hex to RGB
        hex_code = self.hex_code.lstrip("#")
        if len(hex_code) == 3:
            hex_code = "".join(c * 2 for c in hex_code)
        r = int(hex_code[0:2], 16) / 255.0
        g = int(hex_code[2:4], 16) / 255.0
        b = int(hex_code[4:6], 16) / 255.0

        # Convert RGB to HSV
        h, s, v = colorsys.rgb_to_hsv(r, g, b)

        # Convert hue to degrees (0-360)
        h *= 360

        # Determine color family based on HSV values
        if s < 0.15 and v > 0.8:  # Very low saturation, high value
            return "WHITE"
        elif s < 0.15 and v < 0.3:  # Very low saturation, low value
            return "BLACK"
        elif s < 0.15:  # Low saturation
            return "GRAY"
        # Hue-based decisions
        elif h <= 15 or h > 345:
            return "RED"
        elif 15 < h <= 20:
            return "BROWN"  # Brown hues start here
        elif 20 < h <= 45 and v < 0.6:  # Include darker yellows as brown
            return "BROWN"
        elif 15 < h <= 45 and v >= 0.6:
            return "ORANGE"
        elif 45 < h <= 75:
            return "YELLOW"
        elif 75 < h <= 165:
            return "GREEN"
        elif 165 < h <= 255:
            return "BLUE"
        elif 255 < h <= 315:
            return "PURPLE"
        elif 315 < h <= 345:
            return "PINK"

        return None

    def clean(self):
        if self.hex_code:
            if self.normalize_hex_code() is None:
                raise ValidationError(
                    {
                        "hex_code": "Invalid hex color code. Use 3 or 6 hex digits (e.g. #F0F or #FF00FF)."
                    }
                )

    def save(self, *args, **kwargs):
        if self.hex_code:
            self.normalize_hex_code()
            self.color_family = self.get_color_family()
        super().save(*args, **kwargs)

    def __str__(self):
        material_name = str(self.material) if self.material else "Unknown"
        return f"{material_name} {self.color}"

    class Meta:
        # abstract = True
        verbose_name = "Filament"
        verbose_name_plural = "Filaments"


# Printer subclass
class Printer(Product):
    """
    Represents a 3D printer with attributes and functionality specific to its configuration.

    This class extends the Product class and includes attributes such as the manufacturer,
    model, number of extruders, bed dimensions, maximum height, and calculated print volume.
    It also includes methods for calculating the print volume based on bed dimensions and
    saving the instance with validation of required attributes. The class facilitates managing
    the specifications of different printer models and handling their compatible settings.

    Attributes:
            mfr (str): Manufacturer of the printer. Default is "Bambu Lab".
            model (str): Model of the printer. Default is "X1 Carbon".
            num_extruders (int): The number of extruders the printer has.
            bed_length_mm (Optional[int]): Bed length in millimeters. Can be None.
            bed_width_mm (Optional[int]): Bed width in millimeters. Can be None.
            max_height_mm (Optional[int]): Maximum printable height in millimeters. Can be None.
            print_volume_m3 (Optional[Decimal]): Calculated printable volume in cubic meters.
    """

    mfr = models.CharField(max_length=100, default="Bambu Lab")
    model = models.CharField(max_length=100, default="X1 Carbon")
    num_extruders = models.IntegerField()
    bed_length_mm = models.IntegerField(blank=True, null=True)
    bed_width_mm = models.IntegerField(blank=True, null=True)
    max_height_mm = models.IntegerField(blank=True, null=True)
    print_volume_m3 = models.DecimalField(
        decimal_places=2, max_digits=10, blank=True, null=True
    )

    # TODO Create a set of booleans on if the printer is compatible with the list of materials, enforce checks for compatibility when moving materials into the printer.

    def __str__(self):
        return f"{self.model}"

    class Meta:
        # abstract = True
        verbose_name = "Printer"
        verbose_name_plural = "Printers"

    def calculate_print_volume(self):
        """
        Calculates the print volume of a 3D printer in cubic meters based on the bed
        dimensions and maximum height provided. This method updates the
        `print_volume_m3` property of the instance if all necessary dimensions
        are available. Returns the calculated print volume or `None` if any dimension
        is missing.

        :return: The 3D printer's print volume in cubic meters or None if dimensions
                         are incomplete.
        :rtype: float or None
        """
        if self.bed_width_mm and self.bed_length_mm and self.max_height_mm:
            self.print_volume_m3 = (
                self.bed_width_mm * self.bed_length_mm * self.max_height_mm / 1e9
            )
            return self.print_volume_m3
        else:
            return None

    def clean(self):
        if not (self.bed_length_mm and self.bed_width_mm and self.max_height_mm):
            raise ValidationError(
                "Bed dimensions (length, width, height) are all required."
            )

    def save(self, *args, **kwargs):
        self.print_volume_m3 = self.calculate_print_volume()
        super().save(*args, **kwargs)


# Dryer subclass
class Dryer(Product):
    """
    Represents a machine designed for drying purposes.

    This class extends the Product class and provides additional
    information specific to dryers, such as the manufacturer, model,
    number of slots, and maximum temperature in degrees Celsius. This
    represents a catalog of dryers that may or may not be in the current
    inventory.

    Attributes:
            mfr (CharField): Manufacturer of the dryer. Stores up to 100
                    characters.
            model (CharField): Model number or name of the dryer. Stores
                    up to 100 characters.
            num_slots (IntegerField): The number of slots available in the
                    dryer. Defaults to 1.
            max_temp_degC (IntegerField | None): The maximum temperature in
                    degrees Celsius that the dryer can achieve. This value is
                    optional and can be left blank or null.
    """

    mfr = models.CharField(max_length=100)
    model = models.CharField(max_length=100)
    num_slots = models.IntegerField(default=1)
    max_temp_degC = models.IntegerField(blank=True, null=True)

    # class Meta(Product.Meta):
    # 	db_table = 'dryers'
    # db_table_comment = 'Dryers on the market; not necessarily in current inventory'

    def __str__(self):
        return f"{self.model}"

    class Meta:
        # abstract = True
        verbose_name = "Dryer"
        verbose_name_plural = "Dryers"


# AMS subclass
class AMS(Product):
    """
    Represents an AMS (Automatic Material System) product unit.

    This class inherits from Product and is used to define AMS units with specific
    attributes such as manufacturer, model, number of slots, and whether the unit
    includes a drying feature. It can also include metadata for database behavior
    and verbose names for better representation in interfaces.
    """

    mfr = models.CharField(max_length=100, default="Bambu Lab")
    model = models.CharField(max_length=100, default="AMS")
    num_slots = models.IntegerField(blank=True, default=4)
    drying = models.BooleanField(default=False)

    # class Meta(Product.Meta):
    # 	db_table = 'ams'
    # db_table_comment = 'AMS units on the market; not necessarily in current inventory'

    def __str__(self):
        return f"{self.mfr} {self.model}"

    class Meta:
        # abstract = True
        verbose_name = "AMS"
        verbose_name_plural = "AMS"


# Hardware subclass
class Hardware(Product):
    """
    Represents hardware items and their classifications in the database.

    The Hardware class extends the Product class to include additional
    information specific to hardware, accessories, spare parts, or raw materials.
    Each instance represents an item that might or might not be in current
    inventory. The class allows categorization of hardware into distinct types
    using predefined choices.

    Attributes:
            qty (int or None): The quantity of the hardware item. Can be blank or null.
            kind (int): Indicates the type of hardware using defined choices from
                    the HardwareType inner class. Default is HardwareType.HARDWARE.

    Inner Classes:
            HardwareType:
                    Enumerates the possible types of hardware as integer choices. Available
                    types include Accessory, Spare Part, Hardware, and Raw Material.

    Meta:
            verbose_name (str): A human-friendly singular name for the model, which
                    is "Hardware."
            verbose_name_plural (str): A human-friendly plural name for the model,
                    which is "Hardware."
    """

    qty = models.IntegerField(blank=True, null=True)

    class HardwareType(models.IntegerChoices):
        ACCESSORY = 1, "Accessory"
        PARTS = 2, "Spare Part"
        HARDWARE = 3, "Hardware"
        MATERIAL = 4, "Raw Material"

    kind = models.IntegerField(
        choices=HardwareType.choices, default=HardwareType.HARDWARE
    )

    # class Meta(Product.Meta):
    # 	db_table = 'hardware'
    # db_table_comment = 'Hardware, accessories, or parts on the market; not necessarily in current inventory'

    def __str__(self):
        return f"{self.name} (Part #: {self.sku})"

    class Meta:
        # abstract = True
        verbose_name = "Hardware"
        verbose_name_plural = "Hardware"


# InventoryItem with ForeignKey to polymorphic Product
class InventoryItem(models.Model):
    """
    Represents an inventory item.

    This class defines the model for an inventory item, its attributes, and management of
    its state. It includes details about shipment information, product relationships,
    statuses, and attributes to track the lifecycle of the inventory item, such as when
    it is added, sold, or depleted. The class also includes boolean indicators for
    specific states, mechanisms to update item statuses, and relevant timestamps.

    Attributes:
            shipment (str): Tracking number of the shipment, optional.
            date_added (datetime): Timestamp when the item was added, automatically set.
            product (Product): Reference to the associated product.
            serial_number (str): Serial number of the inventory item, optional.
            last_modified (datetime): Timestamp of the last modification, automatically updated.
            date_depleted (datetime or None): Timestamp when the item was marked as depleted, optional.
            date_sold (datetime or None): Timestamp when the item was marked as sold, optional.
            location (Location or None): Reference to the item's current location, optional.
            sale_price (Decimal or None): Sale price of the item, optional.
            percent_remaining (Decimal): Percentage of the item remaining,
                    defaults to 100 if not provided.
            depleted (bool): Indicates whether the item is depleted.
            in_use (bool): Indicates whether the item is currently in use.
            sold (bool): Indicates whether the item is sold.
            status (int): Current status of the inventory item, represented numerically.

            Status:
                    - NEW (int): Represents a "new" status.
                    - IN_USE (int): Represents an "in use" status.
                    - DRYING (int): Represents a "drying" status.
                    - STORED (int): Represents a "stored" status.
                    - DEPLETED (int): Represents a "depleted" status.
                    - SOLD (int): Represents a "sold" status.

    Meta:
            verbose_name (str): Human-readable name for a single inventory item.
            verbose_name_plural (str): Human-readable name for multiple inventory items.

    Example:
            To create and save a new inventory item:
                    >>> product_instance = Product.objects.get(id=1)
                    >>> item = InventoryItem(product=product_instance, sale_price=99.99)
                    >>> item.save()
    """

    # Attributes
    shipment = models.CharField(
        max_length=100, blank=True, default=""
    )  # Tracking No of the shipment
    date_added = models.DateTimeField(auto_now_add=True)
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="inventory_items"
    )
    serial_number = models.CharField(max_length=100, blank=True, default="")
    last_modified = models.DateTimeField(auto_now=True)
    date_depleted = models.DateTimeField(null=True, blank=True)
    date_sold = models.DateTimeField(null=True, blank=True)
    location = models.ForeignKey(
        "Location", on_delete=models.SET_NULL, blank=True, null=True
    )
    sale_price = models.DecimalField(
        null=True, blank=True, decimal_places=2, max_digits=8
    )
    percent_remaining = models.DecimalField(
        null=True, blank=True, decimal_places=2, max_digits=5, default=100
    )

    # Statuses of an inventory item
    class Status(models.IntegerChoices):
        NEW = 1, "new"
        IN_USE = 2, "in use"
        DRYING = 3, "drying"
        STORED = 4, "stored"
        DEPLETED = 5, "depleted"
        SOLD = 6, "sold"
        UNKNOWN = 7, "unknown"

    # Statuses that are "sticky": once set, a location change must not silently
    # recompute status from the destination's default. DEPLETED/SOLD are terminal;
    # UNKNOWN is set during an audit and must survive until explicitly resolved.
    STICKY_STATUSES = (Status.DEPLETED, Status.SOLD, Status.UNKNOWN)

    status = models.PositiveSmallIntegerField(
        choices=Status.choices, default=Status.NEW, blank=True
    )

    class Meta:
        # abstract = True
        verbose_name = "Inventory Item"
        verbose_name_plural = "Inventory Items"

    def __str__(self):
        return f"{self.product.upc} - {self.date_added.strftime('%Y-%m-%d')}"

    def save(self, *args, **kwargs):
        is_new = self.pk is None

        # Never auto-recompute status from location for sticky statuses
        # (DEPLETED/SOLD are terminal; UNKNOWN is held during an audit). This is a
        # model-level guarantee, independent of the ad-hoc _skip_status_from_location
        # flag, which does not survive a reload from the DB.
        if (
            not getattr(self, "_skip_status_from_location", False)
            and self.status not in self.STICKY_STATUSES
        ):
            if is_new:
                if self.location:
                    new_status = self.update_status()
                    if new_status:
                        self.status = new_status
            else:
                original_location_id = getattr(self, "_original_location_id", None)
                if original_location_id != self.location_id:
                    new_status = self.update_status()
                    if new_status:
                        self.status = new_status

        if self.status == self.Status.DEPLETED:
            self.mark_depleted()

        if self.status == self.Status.SOLD:
            self.mark_sold()

        self.last_modified = now()

        super().save(*args, **kwargs)

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._original_location_id = instance.location_id
        return instance

    @property
    def depleted(self):
        return self.status == self.Status.DEPLETED

    @property
    def in_use(self):
        return self.status == self.Status.IN_USE

    @property
    def sold(self):
        return self.status == self.Status.SOLD

    def update_status(self):
        """
        Determines the appropriate status based on location.
        Returns the new status value but does not save it.
        """
        if self.location and hasattr(self.location, "default_status"):
            if self.location.default_status in [
                choice[0] for choice in self.Status.choices
            ]:
                return self.location.default_status
        return None  # Return None if no valid status can be determined

    def mark_depleted(self):
        self.date_depleted = now()
        self.location = None
        self.status = self.Status.DEPLETED

    def mark_sold(self):
        self.date_sold = now()
        self.location = None
        self.status = self.Status.SOLD

    def filament_drying_warning(self, new_location):
        """
        Checks if a drying warning should be issued when moving filament to a new location.

        This method evaluates whether a warning or error message about drying the filament
        needs to be raised based on the filament's material properties and the destination
        location. It provides guidance on whether to dry the filament before use or storage.

        Attributes:
                product: Represents the product associated with the filament to be evaluated.
                status: Indicates the current status of the filament, which is used in the
                        evaluation process.

        Parameters:
                new_location (Location): The new destination where the filament is being moved.

        Returns:
                tuple: Returns a tuple containing the message type, the message itself, and
                        a boolean indicating whether skipping drying is acceptable.
                        Returns `None` if no warnings or errors need to be raised.
        """

        if not isinstance(self.product, Filament):
            return None

        # Kept tolerant of legacy rows: prefer the typed `kind`, but fall back to
        # `is_printer` so a NULL/un-backfilled kind never silently drops the drying
        # safety error.
        is_dry_storage = new_location.kind == Location.Kind.DRY_STORAGE
        is_printer = (
            new_location.kind == Location.Kind.PRINTER or new_location.is_printer
        )

        if self.status == self.Status.NEW:
            if is_dry_storage and self.product.filament.material.drying_required:
                return (
                    "error",
                    "This filament must be dried before being moved to dry storage. Skipping drying is not allowed.",
                    False,
                )
            elif is_printer and self.product.filament.material.drying_required:
                return (
                    "warning",
                    "This filament requires drying before being used. Skipping drying may lead to poor print quality or print failure.",
                    True,
                )
            elif is_printer and not self.product.filament.material.drying_required:
                return (
                    "info",
                    "This filament does not require drying before being used, but it may perform better if dried first.",
                    False,
                )
            return None

        else:
            return None


class Location(models.Model):
    """
    Represents a location that can store inventory items.

    Locations form a shallow hierarchy described by ``kind``:

    - Container kinds (``RACK``, ``AMS``, ``DRYER``) are organizational parents.
      Items are never assigned directly to them.
    - Leaf kinds (``SHELF``, ``DRY_STORAGE``, ``AMS_SLOT``, ``DRYER_SLOT``,
      ``PRINTER``) are the assignable locations and carry a ``default_status``
      that is applied to items moved into them.

    ``AMS_SLOT``/``DRYER_SLOT`` leaves may link to the physical unit's
    :class:`InventoryItem` via ``unit`` so a slot knows which tracked machine it
    belongs to.
    """

    class Kind(models.TextChoices):
        RACK = "rack", "Receiving Rack"
        SHELF = "shelf", "Shelf"
        DRY_STORAGE = "dry_storage", "Dry Storage"
        AMS = "ams", "AMS Unit"
        AMS_SLOT = "ams_slot", "AMS Slot"
        DRYER = "dryer", "Dryer"
        DRYER_SLOT = "dryer_slot", "Dryer Slot"
        PRINTER = "printer", "Printer"

    # Kinds that hold items (selectable as an item's location).
    ASSIGNABLE_KINDS = (
        Kind.SHELF,
        Kind.DRY_STORAGE,
        Kind.AMS_SLOT,
        Kind.DRYER_SLOT,
        Kind.PRINTER,
    )
    # Organizational parents; items are never assigned to these.
    CONTAINER_KINDS = (Kind.RACK, Kind.AMS, Kind.DRYER)

    name = models.CharField(max_length=200, unique=True)

    kind = models.CharField(
        max_length=20,
        choices=Kind.choices,
        default=Kind.SHELF,
        help_text="Structural type of this location.",
    )

    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
        help_text="Parent container (shelf->rack, slot->unit).",
    )

    unit = models.ForeignKey(
        "InventoryItem",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="slot_locations",
        help_text="The physical AMS/dryer unit this slot belongs to, if tracked.",
    )

    slot_index = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Slot number within an AMS/dryer (1-4)."
    )

    default_status = models.PositiveSmallIntegerField(
        choices=InventoryItem.Status.choices,
        null=True,
        blank=True,
        help_text="Default status to apply to items moved to this location.",
    )

    is_printer = models.BooleanField(
        default=False
    )  # Is the location one of the printers?

    class Meta:
        verbose_name = "Location"
        verbose_name_plural = "Locations"
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def is_container(self):
        return self.kind in self.CONTAINER_KINDS

    @classmethod
    def assignable(cls):
        """Leaf locations that an item can be assigned to, hierarchically ordered."""
        return cls.objects.filter(kind__in=cls.ASSIGNABLE_KINDS).order_by(
            "parent__name", "name"
        )


class Material(models.Model):
    """
    Represents a material for 3D printing, including its properties and characteristics.

    This class defines a model for 3D printing materials, capturing details like name,
    manufacturer, printing temperatures, drying requirements, AMS capability, and
    additional notes. Each material is uniquely identified by its name, which should include
    type and subtype designations for better clarity. The model also supports optional
    manufacturer details and various temperature-related attributes.

    Attributes:
    name (str): The name of the material, including type and subtype designations
                            (e.g., "ABS-CF" or "PLA-GF"). Must be unique.
    mfr (str): The name of the manufacturer. Default is "Bambu Lab".
    print_temp_min_degC (int, optional): Minimum recommended print temperature in degrees
                                                                             Celsius.
    print_temp_max_degC (int, optional): Maximum recommended print temperature in degrees
                                                                             Celsius.
    print_temp_ideal_degC (int, optional): Ideal print temperature in degrees Celsius.
    dry_temp_min_degC (int, optional): Minimum drying temperature for the material in degrees
                                                                       Celsius.
    dry_temp_max_degC (int, optional): Maximum drying temperature for the material in degrees
                                                                       Celsius.
    dry_temp_ideal_degC (int, optional): Ideal drying temperature for the material in degrees
                                                                             Celsius.
    dry_time_hrs (int, optional): Recommended drying time in hours.
    ams_capable (bool): Indicates if the material is compatible with AMS. Default is True.
    notes (str, optional): Additional notes or comments about the material.
    """

    name = models.CharField(max_length=100)
    material_type = models.CharField(max_length=50, blank=True, default="")
    # name = base polymer (e.g. "PETG", "PLA"); material_type = subtype modifier (e.g. "HF", "CF")
    mfr = models.CharField(max_length=100, blank=True, default="Bambu Lab")

    # Print Temperatures
    print_temp_min_degC = models.IntegerField(blank=True, null=True)
    print_temp_max_degC = models.IntegerField(blank=True, null=True)
    print_temp_ideal_degC = models.IntegerField(blank=True, null=True)

    # Drying Temperature & Time
    dry_temp_min_degC = models.IntegerField(blank=True, null=True)
    dry_temp_max_degC = models.IntegerField(blank=True, null=True)
    dry_temp_ideal_degC = models.IntegerField(blank=True, null=True)
    dry_time_hrs = models.IntegerField(blank=True, null=True)

    ams_capable = models.BooleanField(default=True)  # Is it compatible with AMS?
    drying_required = models.BooleanField(
        default=True
    )  # Does it require drying before use?

    notes = models.TextField(blank=True)

    # Filament Guide Properties (Phase 5)
    description = models.CharField(max_length=200, blank=True, default="")
    uv_resistant = models.BooleanField(default=False)
    flexible = models.BooleanField(default=False)
    high_strength = models.BooleanField(default=False)
    heat_resistant = models.BooleanField(default=False)
    food_safe = models.BooleanField(default=False)
    easy_to_print = models.BooleanField(default=False)
    budget_friendly = models.BooleanField(default=False)
    impact_resistant = models.BooleanField(default=False)
    requires_enclosure = models.BooleanField(default=False)

    class Meta:
        unique_together = [("name", "material_type")]
        ordering = ["name", "material_type"]

    def __str__(self):
        if self.material_type:
            return f"{self.name} {self.material_type}"
        return self.name


class AuditSession(models.Model):
    """
    A single physical inventory-audit run.

    The auditor walks the storage, scanning each location and then the item tags
    physically present there. Reconciliation happens live (per-location): closing a
    location flags any still-assigned-but-unscanned items as
    :attr:`InventoryItem.Status.UNKNOWN`; at finalize, items left UNKNOWN by this
    session are confirmed depleted. Only one session may be ACTIVE at a time.
    """

    class State(models.TextChoices):
        ACTIVE = "active", "Active"
        FINALIZED = "finalized", "Finalized"
        ABANDONED = "abandoned", "Abandoned"

    user = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True
    )
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    state = models.CharField(max_length=20, choices=State.choices, default=State.ACTIVE)

    class Meta:
        ordering = ["-started_at"]
        constraints = [
            # At most one active session at a time.
            models.UniqueConstraint(
                fields=["state"],
                condition=models.Q(state="active"),
                name="unique_active_audit_session",
            )
        ]

    def __str__(self):
        return f"Audit #{self.pk} ({self.state})"

    @classmethod
    def active(cls):
        return cls.objects.filter(state=cls.State.ACTIVE).first()

    def mark_finished(self, state):
        self.state = state
        self.finished_at = now()
        self.save(update_fields=["state", "finished_at"])


class AuditEvent(models.Model):
    """Append-only log of what happened to an item during an audit session."""

    class Action(models.TextChoices):
        VISITED = "visited", "Location visited"
        SCANNED_PRESENT = "scanned_present", "Scanned present"
        MOVED_IN = "moved_in", "Moved in"
        REVIVED = "revived", "Revived"
        FLAGGED_UNKNOWN = "flagged_unknown", "Flagged unknown"
        CLOSED = "closed", "Location closed"

    session = models.ForeignKey(
        AuditSession, on_delete=models.CASCADE, related_name="events"
    )
    item = models.ForeignKey(
        "InventoryItem", on_delete=models.CASCADE, null=True, blank=True
    )
    location = models.ForeignKey(
        "Location", on_delete=models.SET_NULL, null=True, blank=True
    )
    action = models.CharField(max_length=20, choices=Action.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.action} ({self.item_id}) @ {self.location_id}"
