"""
Barcode and label utilities for the Brother QL-810W.

Design goals:
- Treat label geometry using Brother's expected pixel dimensions.
- Generate crisp 1-bit (black/white) images for the Brother QL driver.
- Never upscale barcodes horizontally; only shrink if necessary.
- Provide a small label "profile" abstraction for future label types.
- Keep a high-level API: generate_and_print_barcode(item, mode).
"""

from __future__ import annotations

import logging
import os
import warnings
from dataclasses import dataclass
from io import BytesIO
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFont
from barcode import Code128
from barcode.writer import ImageWriter

# Suppress long-lived brother_ql devicedependent deprecation noise.
warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    message=".*brother_ql.devicedependent is deprecated.*",
)

from brother_ql.backends.network import BrotherQLBackendNetwork
from brother_ql.conversion import convert
from brother_ql.raster import BrotherQLRaster

from django.conf import settings
from django.http import HttpResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (env-overridable)
# ---------------------------------------------------------------------------

DEFAULT_DPI = int(os.environ.get("BROTHER_QL_DPI", "300"))

# Try a couple of environment variable names for the printer host.
BROTHER_QL_HOST = (
    os.environ.get("BROTHER_QL_HOST") or os.environ.get("PRINTER_IP") or "192.168.68.93"
)

BROTHER_QL_MODEL = os.environ.get("BROTHER_QL_MODEL", "QL-810W")

BARCODE_FONT_SIZE = getattr(settings, "BARCODE_FONT_SIZE", 14)

# Default label physical size (mm) – used only as metadata / fallback
DEFAULT_LABEL_WIDTH_MM = 54.0
DEFAULT_LABEL_HEIGHT_MM = 17.0

# Brother's expected pixel sizes for specific labels (width_px, height_px).
# For 17x54 labels, convert() expects 566x165.
BROTHER_LABEL_PIXEL_SIZES = {
    "17x54": (566, 165),
    # You can add more here later: "29x90": (??? , ???)
}


@dataclass
class LabelProfile:
    """
    Logical description of a label type for layout and printing.

    width_mm / height_mm: physical label dimensions (mostly informational).
    code: Brother label code string as used by brother_ql (e.g. "17x54").
    dpi: Printer resolution used if we have to fall back to mm->px.
    barcode_area_ratio: Portion of the label height reserved for the barcode.
    side_margin_mm: Left/right quiet margin in mm.
    """

    code: str
    width_mm: float
    height_mm: float
    dpi: int = DEFAULT_DPI
    barcode_area_ratio: float = 0.7
    side_margin_mm: float = 2.0

    @property
    def canvas_size_px(self) -> Tuple[int, int]:
        """
        Return (width_px, height_px) for the label.

        Prefer Brother's known pixel sizes when available; fall back to
        mm->px if not defined.
        """
        if self.code in BROTHER_LABEL_PIXEL_SIZES:
            return BROTHER_LABEL_PIXEL_SIZES[self.code]

        width_px = int(self.width_mm / 25.4 * self.dpi)
        height_px = int(self.height_mm / 25.4 * self.dpi)
        return width_px, height_px

    @property
    def side_margin_px(self) -> int:
        return int(self.side_margin_mm / 25.4 * self.dpi)


def _profile_from_mm(
    label_size_mm: Tuple[float, float],
    dpi: Optional[int] = None,
    barcode_area_ratio: float = 0.7,
    side_margin_mm: float = 2.0,
) -> LabelProfile:
    """
    Create a LabelProfile from (width_mm, height_mm).

    Brother label "code" strings are generally '{height}x{width}' in mm.
    For a 54x17 mm label_size_mm, the code will be '17x54'.
    """
    width_mm, height_mm = label_size_mm
    code = f"{int(round(height_mm))}x{int(round(width_mm))}"
    return LabelProfile(
        code=code,
        width_mm=width_mm,
        height_mm=height_mm,
        dpi=dpi or DEFAULT_DPI,
        barcode_area_ratio=barcode_area_ratio,
        side_margin_mm=side_margin_mm,
    )


# Explicit default profile for the 17x54 label you’re actually using
DEFAULT_PROFILE = LabelProfile(
    code="17x54",
    width_mm=DEFAULT_LABEL_WIDTH_MM,
    height_mm=DEFAULT_LABEL_HEIGHT_MM,
    dpi=DEFAULT_DPI,
    barcode_area_ratio=0.7,
    side_margin_mm=2.0,
)

# ---------------------------------------------------------------------------
# Core barcode rendering
# ---------------------------------------------------------------------------


def _render_code128(
    data: str,
    module_width_mm: float,
    module_height_px: int,
    dpi: int,
    quiet_zone_mm: float = 2.0,
) -> Image.Image:
    """
    Render a Code128 barcode to a PIL.Image in mode '1' (1-bit).

    - module_width_mm: physical width of one narrow bar.
    - module_height_px: desired bar height in pixels.
    """
    if not data:
        raise ValueError("Cannot generate barcode from empty data string.")

    writer = ImageWriter()
    tmp = BytesIO()

    module_height_mm = module_height_px / dpi * 25.4  # px -> mm

    code = Code128(data, writer=writer)
    code.write(
        tmp,
        {
            "module_height": module_height_mm,
            "module_width": module_width_mm,
            "quiet_zone": quiet_zone_mm,
            "dpi": dpi,
            "write_text": False,
        },
    )
    tmp.seek(0)
    img = Image.open(tmp).convert("1")  # 1-bit image
    tmp.close()
    return img


def generate_barcode_to_fit(
    data: str,
    max_width_px: int,
    target_height_px: int,
    dpi: int,
    initial_module_width_mm: float = 0.3,
    min_module_width_mm: float = 0.1,
) -> Image.Image:
    """
    Generate a Code128 barcode that fits within max_width_px (no upscaling).

    We start with a given module_width_mm and iteratively shrink it
    until the barcode fits within max_width_px, or we hit min_module_width_mm.
    """
    if max_width_px <= 0 or target_height_px <= 0:
        raise ValueError("max_width_px and target_height_px must be > 0.")

    module_width = initial_module_width_mm
    img = _render_code128(
        data=data,
        module_width_mm=module_width,
        module_height_px=target_height_px,
        dpi=dpi,
    )

    # If it's too wide, shrink modules
    while img.width > max_width_px and module_width > min_module_width_mm:
        module_width *= 0.9
        img = _render_code128(
            data=data,
            module_width_mm=module_width,
            module_height_px=target_height_px,
            dpi=dpi,
        )

    # If it's still too tall, we only scale down in height with NEAREST.
    if img.height > target_height_px:
        scale = target_height_px / img.height
        new_width = int(img.width * scale)
        new_height = target_height_px
        img = img.resize((new_width, new_height), resample=Image.NEAREST)

    return img


# ---------------------------------------------------------------------------
# Label layout
# ---------------------------------------------------------------------------


def create_label_image(
    data: str,
    text: Optional[str] = None,
    profile: Optional[LabelProfile] = None,
) -> Image.Image:
    """
    Build a full label image (barcode + optional text) in mode '1'.

    - data: exact string encoded in the barcode (e.g. "INV-739").
    - text: optional human-readable label (defaults to `data`).
    - profile: LabelProfile controlling layout and size.
    """
    if profile is None:
        profile = DEFAULT_PROFILE

    canvas_width, canvas_height = profile.canvas_size_px

    # Create base label canvas (1-bit, white)
    label_img = Image.new("1", (canvas_width, canvas_height), 1)

    # Compute barcode area
    barcode_height_px = int(canvas_height * profile.barcode_area_ratio)
    max_barcode_width_px = canvas_width - 2 * profile.side_margin_px

    # Generate barcode to fit that area
    barcode_img = generate_barcode_to_fit(
        data=data,
        max_width_px=max_barcode_width_px,
        target_height_px=barcode_height_px,
        dpi=profile.dpi,
    )

    # Center barcode horizontally at top
    barcode_x = (canvas_width - barcode_img.width) // 2
    barcode_y = 0
    label_img.paste(barcode_img, (barcode_x, barcode_y))

    # Draw text (if any) below barcode
    if text is None:
        text = data

    if text:
        draw = ImageDraw.Draw(label_img)
        font = _get_default_font()

        text_y_top = barcode_y + barcode_img.height + 2  # small gap
        if text_y_top < canvas_height:
            # Centered text
            draw.text(
                (canvas_width // 2, text_y_top),
                text,
                font=font,
                anchor="ma",  # middle, top
                fill=0,  # black
            )

    # IMPORTANT: do NOT rotate here.
    # brother_ql.convert(..., rotate="auto") will rotate as needed, and
    # it expects the raw image size to match the label spec (e.g. 566x165).
    return label_img


def _get_default_font() -> ImageFont.ImageFont:
    """
    Get the font used for label text.

    Uses BARCODE_FONT_PATH / BARCODE_FONT_SIZE from settings, falling
    back to a couple of common system fonts and finally to PIL's default
    bitmap font if no TTF is available.
    """
    # Primary source: explicit setting
    font_path = getattr(settings, "BARCODE_FONT_PATH", None)
    font_size = getattr(settings, "BARCODE_FONT_SIZE", BARCODE_FONT_SIZE)

    # 1) If a BARCODE_FONT_PATH is configured, try that first.
    if font_path:
        try:
            return ImageFont.truetype(str(font_path), size=font_size)
        except Exception as exc:
            logger.warning(
                "Could not load barcode font %s (%s), will try fallbacks.",
                font_path,
                exc,
            )

    # 2) Try a couple of common system fonts as fallbacks.
    candidate_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/Library/Fonts/Arial.ttf",  # macOS common path
    ]

    for path in candidate_paths:
        try:
            return ImageFont.truetype(path, size=font_size)
        except Exception:
            continue

    # 3) Final fallback: tiny bitmap font, so warn loudly.
    logger.warning(
        "Falling back to PIL default bitmap font for labels; "
        "text will be very small. Configure BARCODE_FONT_PATH "
        "and BARCODE_FONT_SIZE in settings for better results."
    )
    return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Brother QL integration
# ---------------------------------------------------------------------------


def _get_raster() -> BrotherQLRaster:
    """Create and configure the BrotherQLRaster object for the configured model."""
    qlr = BrotherQLRaster(BROTHER_QL_MODEL)
    qlr.exception_on_error = True
    return qlr


def _get_backend() -> BrotherQLBackendNetwork:
    """Create the network backend for the configured printer host."""
    if not BROTHER_QL_HOST:
        raise RuntimeError("BROTHER_QL_HOST / BROTHER_QL_PRINTER_IP is not set.")
    return BrotherQLBackendNetwork(BROTHER_QL_HOST)


def print_label_image(
    img: Image.Image,
    label: Optional[str] = None,
    rotate: str = "auto",
    threshold: float = 70.0,
    dither: bool = False,
    compress: bool = False,
) -> None:
    """
    Print a prepared label image to the Brother QL printer.

    Parameters map directly to brother_ql.conversion.convert():
    - label: Brother label code string (e.g. "17x54").
    - rotate: "auto", "0", "90", "180", or "270".
    """
    qlr = _get_raster()

    if label is None:
        # Allow an env override while still defaulting to the profile's code.
        default_label_code = DEFAULT_PROFILE.code
        label = os.environ.get("BROTHER_QL_LABEL", default_label_code)

    instructions = convert(
        qlr=qlr,
        images=[img],
        label=label,
        rotate=rotate,
        threshold=threshold,
        dither=dither,
        compress=compress,
    )

    backend = _get_backend()
    backend.write(instructions)
    logger.info(
        "Sent label to printer '%s' at '%s' with label type '%s'.",
        BROTHER_QL_MODEL,
        BROTHER_QL_HOST,
        label,
    )


def generate_and_print_label(
    data: str,
    text: Optional[str] = None,
    profile: Optional[LabelProfile] = None,
    **print_kwargs,
) -> HttpResponse:
    """
    Convenience: create a label for `data` and immediately print it.

    Example:
        generate_and_print_label("INV-739")
        generate_and_print_label("INV-739", text="INV-739 | PLA Black")
    """
    img = create_label_image(data=data, text=text, profile=profile)
    if settings.ENABLE_BARCODE_PRINTING:
        print_label_image(img, **print_kwargs)

    else:
        logger.info("[TEST MODE] Skipping actual label print for item %s", data)

    response = HttpResponse(content_type="image/png")
    img.save(response, format="PNG")
    return response


# ---------------------------------------------------------------------------
# High-level integration point: generate_and_print_barcode(item, mode)
# ---------------------------------------------------------------------------


def _get_upc_for_item(item) -> Optional[str]:
    """
    Extract the UPC (or equivalent) from an inventory item.

    Adjust this to match your actual models. The guesses here assume:
    - item.product.upc or
    - item.product.gtin or
    - item.product.barcode

    Returns a string or None.
    """
    # TODO: tweak this to match your actual Product fields
    for attr in ("upc", "gtin", "barcode"):
        try:
            value = getattr(item.product, attr, None)
        except AttributeError:
            continue
        if value:
            return str(value)
    return None


def _get_unique_code_for_item(item) -> str:
    """
    Derive a unique code for an inventory item.

    Adjust this to match your actual model fields. The logic here:
    - Prefer item.inventory_code
    - Then item.code
    - Otherwise fall back to f"INV-{item.id}"
    """
    # TODO: tweak this to match your InventoryItem fields
    for attr in ("inventory_code", "code"):
        if hasattr(item, attr):
            value = getattr(item, attr)
            if value:
                return str(value)

    # Last-resort fallback: deterministic numeric ID with INV prefix.
    if hasattr(item, "id") and item.id is not None:
        return f"INV-{item.id}"

    logger.warning(
        "Falling back to synthetic unique code for item %r; "
        "consider adding an 'inventory_code' field.",
        item,
    )
    return "INV-UNKNOWN"


def _get_item_display_name(item) -> str:
    """
    Get a human-readable name for the item for label text.

    Adjust this to match your models. Common patterns:
    - item.product.name
    - item.name
    - str(item)
    """
    for attr_path in ("product.name", "name"):
        try:
            obj = item
            for part in attr_path.split("."):
                obj = getattr(obj, part)
            if obj:
                return str(obj)
        except AttributeError:
            continue

    return str(item)


def generate_and_print_barcode(
    item,
    mode: str,
    profile: Optional[LabelProfile] = None,
    **print_kwargs,
) -> HttpResponse:
    """
    High-level helper used by the rest of the app.

    Parameters:
        item: InventoryItem (or similar) instance.
        mode: "upc" or "unique" (case-insensitive).
        profile: optional LabelProfile (defaults to DEFAULT_PROFILE).

    Behavior:
        - In "UPC" mode:
            * Encodes the product's UPC/GTIN/etc in the barcode.
            * Text shows "<item name> | <UPC>".
        - In "Unique" mode:
            * Encodes a unique item code (e.g. "INV-123").
            * Text shows that unique code (and optionally item name).

    Returns:
        HttpResponse: HTTP response containing the barcode image.

    Raises:
        ValueError: if there's an error generating or printing the barcode.
    """

    # Validate input parameters
    if not item:
        logger.error("Cannot generate barcode: No item provided")
        raise ValueError("Cannot generate barcode: No item provided")

        # Determine barcode data based on mode
    if mode == "upc":
        if (
            not hasattr(item, "product")
            or not item.product
            or not hasattr(item.product, "upc")
        ):
            logger.error("Cannot generate UPC barcode: Item has no product or UPC")
            raise ValueError("Cannot generate UPC barcode: Item has no product or UPC")
        data = item.product.upc
        label_name = f"UPC-{data}"
    elif mode == "unique":
        if not hasattr(item, "id"):
            logger.error("Cannot generate unique barcode: Item has no ID")
            raise ValueError("Cannot generate unique barcode: Item has no ID")
        data = f"INV-{item.id}"
        label_name = f"INV-{item.id}"

    mode_lower = (mode or "").lower()
    if profile is None:
        profile = DEFAULT_PROFILE

    item_name = _get_item_display_name(item)

    if mode_lower == "upc":
        upc = _get_upc_for_item(item)
        if not upc:
            logger.error("No UPC/GTIN/barcode found for item %r in UPC mode.", item)
            raise ValueError(f"No UPC/GTIN/barcode available for item {item!r}.")

        data = upc
        text = f"{item_name} | {upc}"

    elif mode_lower in ("unique", "inv", "inventory"):
        unique_code = _get_unique_code_for_item(item)
        data = unique_code
        # You can include the name here if you want:
        # text = f"{unique_code} | {item_name}"
        text = unique_code

    else:
        raise ValueError(
            f"Unknown barcode mode: {mode!r} (expected 'UPC' or 'Unique')."
        )

    logger.info(
        "Printing barcode for item %r in mode='%s' with data='%s'.",
        item,
        mode,
        data,
    )
    response = generate_and_print_label(
        data=data, text=text, profile=profile, **print_kwargs
    )
    return response


# ---------------------------------------------------------------------------
# Backward-compatible-ish helpers
# ---------------------------------------------------------------------------


def generate_barcode(data: str) -> Image.Image:
    """
    Legacy helper: generate a standalone barcode image (no label layout).

    This uses the DEFAULT_PROFILE's barcode area to size the barcode.
    Useful if you want to export a barcode PNG or composite your own layout.
    """
    profile = DEFAULT_PROFILE
    canvas_width, canvas_height = profile.canvas_size_px
    barcode_height_px = int(canvas_height * profile.barcode_area_ratio)
    max_barcode_width_px = canvas_width - 2 * profile.side_margin_px

    img = generate_barcode_to_fit(
        data=data,
        max_width_px=max_barcode_width_px,
        target_height_px=barcode_height_px,
        dpi=profile.dpi,
    )
    return img


def format_label(
    barcode_img: Image.Image,
    label_size: Tuple[float, float] = (DEFAULT_LABEL_WIDTH_MM, DEFAULT_LABEL_HEIGHT_MM),
    text: Optional[str] = None,
) -> Image.Image:
    """
    Legacy-ish helper compatible with older code:

        barcode_img = generate_barcode("INV-739")
        label_img = format_label(barcode_img, (54, 17), text="INV-739")

    For robustness, we *ignore* the passed-in barcode_img's geometry and
    re-generate the barcode at the right size for the requested label, using
    `text` (or data) as the encoded string.
    """
    profile = _profile_from_mm(label_size, dpi=DEFAULT_DPI)

    if text is None:
        logger.warning(
            "format_label() called without text; using placeholder data. "
            "Prefer create_label_image() or generate_and_print_label()."
        )
        data = "UNKNOWN"
    else:
        data = text

    return create_label_image(data=data, text=text, profile=profile)


__all__ = [
    "LabelProfile",
    "DEFAULT_PROFILE",
    "generate_barcode_to_fit",
    "create_label_image",
    "print_label_image",
    "generate_and_print_label",
    "generate_and_print_barcode",
    "generate_barcode",
    "format_label",
]
