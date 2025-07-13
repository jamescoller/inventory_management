import colorsys
import re

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
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
        if re.fullmatch(r"^#(?:[0-9a-fA-F]{3}){1,2}$", rev_code):
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

    def save(self, *args, **kwargs):
        """
        Save the object to the database after normalizing the hex code.

        The function normalizes the hexadecimal color code and verifies its validity
        before saving the object. An exception is raised if the hex code is invalid.

        Args:
                *args: Additional positional arguments passed to the save method.
                **kwargs: Additional keyword arguments passed to the save method.

        Raises:
                ValueError: If the normalized hex code is invalid.
        """
        self.normalize_hex_code()

        if not self.hex_code:
            raise ValueError("Invalid hex code")

        # Set color family
        self.color_family = self.get_color_family()

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.material.name} {self.color}"

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

    def save(self, *args, **kwargs):
        """
        Calculates and saves the print volume in cubic meters for the object. Ensures that the calculated
        value is valid and raises an error if bed dimensions are invalid or missing.

        Parameters:
        args: tuple
                Positional arguments passed to the method.
        kwargs: dict
                Keyword arguments passed to the method.

        Raises:
        ValueError
                If the calculated print volume is invalid or the bed dimensions are
                missing or incorrect.
        """
        self.print_volume_m3 = self.calculate_print_volume()
        if not self.print_volume_m3:
            raise ValueError("Invalid or missing bed dimensions")
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

    # Boolean Status Filters
    depleted = models.BooleanField(default=False)
    in_use = models.BooleanField(default=False)
    sold = models.BooleanField(default=False)

    # Statuses of an inventory item
    class Status(models.IntegerChoices):
        NEW = 1, "new"
        IN_USE = 2, "in use"
        DRYING = 3, "drying"
        STORED = 4, "stored"
        DEPLETED = 5, "depleted"
        SOLD = 6, "sold"

    status = models.PositiveSmallIntegerField(
        choices=Status.choices, default=Status.NEW, blank=True
    )

    def __str__(self):
        return f"{self.product.upc} - {self.date_added.strftime('%Y-%m-%d')}"

    def update_status(self):
        if self.location and hasattr(self.location, "default_status"):
            if self.location.default_status in [
                choice[0] for choice in self.Status.choices
            ]:
                self.status = self.location.default_status
                self.save(update_fields=["status"])
            return self.status
        return self.Status.NEW  # Return default status instead of None

    def mark_depleted(self):
        self.depleted = True
        self.date_depleted = now()
        self.location = None
        self.status = self.Status.DEPLETED
        return self.depleted

    def mark_sold(self):
        self.sold = True
        self.date_sold = now()
        self.location = None
        self.status = self.Status.SOLD
        return self.sold

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

        if self.status == "NEW":
            if (
                new_location.name.lower() == "dry storage"
                and self.product.filament.material.drying_required
            ):
                return (
                    "error",
                    "This filament must be dried before being moved to dry storage. Skipping drying is not allowed.",
                    False,
                )
            elif (
                new_location.is_printer
                and self.product.filament.material.drying_required
            ):
                return (
                    "warning",
                    "This filament requires drying before being used. Skipping drying may lead to poor print quality or print failure.",
                    True,
                )
            elif (
                new_location.is_printer
                and not self.product.filament.material.drying_required
            ):
                return (
                    "info",
                    "This filament does not require drying before being used, but it may perform better if dried first.",
                    False,
                )
            return None

        else:
            return None

    def save(self, *args, **kwargs):
        is_new = self.pk is None  # If there is no primary key, this is a new record
        previous = None

        if not is_new:
            previous = InventoryItem.objects.get(pk=self.pk)

        # Automatically update the status as location changes or if it is new
        if previous.location != self.location:  # is it in a new place?
            self.update_status()

        # set boolean for IN_USE
        if self.status == self.Status.IN_USE:
            self.in_use = True

        # if status becomes "DEPLETED", set boolean to be true for depleted, set date, and remove location
        if self.status == self.Status.DEPLETED:
            self.mark_depleted()

        # if status becomes "SOLD", set boolean to be true for sold, set date, and remove location
        if self.status == self.Status.SOLD:
            self.mark_sold()

        # Update last modified to be now
        self.last_modified = now()

        super().save(*args, **kwargs)

    class Meta:
        # abstract = True
        verbose_name = "Inventory Item"
        verbose_name_plural = "Inventory Items"


class Location(models.Model):
    """
    Represents a location that can store inventory items.

    This class is used to model different locations where inventory items can
    be stored. Each location has a name and a default status that is applied
    to any items moved into this location. The name field is unique, ensuring
    that no two locations can have the same name. The default status is
    selected from predefined status choices available in `InventoryItem.Status`.
    """

    name = models.CharField(max_length=200, unique=True)

    default_status = models.PositiveSmallIntegerField(
        choices=InventoryItem.Status.choices,
        help_text="Default status to apply to items moved to this location.",
    )

    is_printer = models.BooleanField(
        default=False
    )  # Is the location one of the printers?

    class Meta:
        verbose_name = "Location"
        verbose_name_plural = "Locations"

    def __str__(self):
        return self.name


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

    name = models.CharField(max_length=100, unique=True)
    # The name should include the material type e.g. "ABS" or "PLA" as well as any subtype designations
    # e.g. "PLA-CF" or "ABS-GF"
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

    def __str__(self):
        return self.name


class Order(PolymorphicModel):
    """
    Represents an order with a unique order number and an item list.

    This class is designed to handle operations related to an order, such as
    managing a list of items associated with the order. It features attributes
    for an order number and provides methods for managing the item list,
    including appending and removing items. The class inherits from
    PolymorphicModel and serves as a base for creating more specific types
    of orders in a polymorphic environment.

    Attributes
    ----------
    order_num : str
            A character field storing the unique identifier for the order.

    _item_list : list
            A private attribute used to store the list of items associated
            with the order.

    Meta : class
            Internal Django class for database-specific options. Includes
            configurations such as verbose names for the model.

    Methods
    -------
    item_list
            Getter and setter properties for the `_item_list` attribute. Ensures
            that the value assigned to the `_item_list` is a list.
    append_to_list(item)
            Adds an item to the `_item_list`.
    remove_from_list(item)
            Removes an item from the `_item_list`.
    __str__()
            Returns a string representation of the order using the `order_num` attribute.
    """

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

    class Meta:
        verbose_name = "Order"
        verbose_name_plural = "Orders"

    def __str__(self):
        return self.order_num


class Shipment(Order):
    """
    Represents a shipment entity in the system, inheriting from the Order class.

    This class is primarily used to store and manage shipment-specific details,
    such as tracking information. It provides customization of verbose name for
    readability in admin interfaces and string representation for display.

    Attributes:
            tracking: A string field for storing shipment tracking information.
                    The maximum length of this field is 200 characters.
    """

    tracking = models.CharField(max_length=200)

    class Meta:
        verbose_name = "Shipment"
        verbose_name_plural = "Shipments"

    def __str__(self):
        return self.tracking
