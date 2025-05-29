import logging
import re
import subprocess
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont
from barcode import Code128
from barcode.writer import ImageWriter
from brother_ql.backends.network import BrotherQLBackendNetwork
from brother_ql.conversion import convert
from brother_ql.raster import BrotherQLRaster
from django.conf import settings
from django.http import HttpResponse

logger = logging.getLogger(__name__)


def generate_barcode(data):
    """
    Generate a barcode image from the provided data string.

    Args:
        data (str): String to be encoded into the barcode

    Returns:
        PIL.Image: Image containing the barcode with the data encoded in Code128 format

    Raises:
        ValueError: If the barcode cannot be generated
    """
    if not data:
        logger.error("Cannot generate barcode: Empty data provided")
        raise ValueError("Cannot generate barcode: Empty data provided")

    barcode_temp = BytesIO()
    try:
        barcode = Code128(data, writer=ImageWriter())
        barcode.write(
            barcode_temp,
            {
                "module_height": 10.0,
                "write_text": False,  # Disables default text rendering
            },
        )
        barcode_temp.seek(0)
        barcode_img = Image.open(barcode_temp).convert("L")
        return barcode_img
    except Exception as e:
        logger.exception("Failed to generate barcode containing %s", data)
        raise ValueError(f"Barcode generation failed: {e}")
    finally:
        # Ensure resources are properly cleaned up
        barcode_temp.close()


def format_label(barcode_img, text, label_size=(54, 17)):
    """
    Format the final label image based the barcode, text, and label size.

    Args:
        barcode_img (PIL.Image): Object containing the barcode image to be printed on the label
        text (str): the text to be printed
        label_size (tuple [int, int]): the size of the label in mm, default is (54, 17)

    Returns:
        PIL.Image object containing the formatted label image
    """
    canvas_height = None  # Printing Landscape, canvas height will be label width
    canvas_width = None  # Printing Landscape, canvas width will be label length

    # Convert mm to printable pixels at 300 dpi (including req margins)
    for dim in label_size:
        if dim == 17:
            pixels = 165
        elif dim == 23:
            pixels = 202
        elif dim == 29:
            pixels = 306
        elif dim == 38:
            pixels = 413
        elif dim == 39:
            pixels = 425
        elif dim == 42:
            pixels = 425
        elif dim == 48:
            pixels = 495
        elif dim == 52:
            pixels = 578
        elif dim == 54:
            pixels = 566
        elif dim == 62:
            pixels = 696
        elif dim == 87:
            pixels = 956
        elif dim == 90:
            pixels = 991
        elif dim == 100:
            pixels = 1109
        else:
            raise ValueError(f"Invalid label size: {dim} mm")

        if dim == label_size[0]:
            canvas_width = pixels
        else:
            canvas_height = pixels

    # IMPORTANT NOTE:
    # The Python Imaging Library uses a Cartesian pixel coordinate system, with (0,0) in the upper left corner.
    # Coordinates are usually passed to the library as 2-tuples (x, y).
    # Rectangles are represented as 4-tuples, (x1, y1, x2, y2), with the upper left corner given first.

    # === Create Label Canvas (landscape) ===
    label_img = Image.new(
        "L",  # 8-bit grayscale
        (
            canvas_width,
            canvas_height,
        ),  # 2-tuple: width and height in pixels of the image
        color=255,  # White background
    )  # White background

    # === Load Font for Text ===
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=32
        )
    except Exception as e:
        logger.warning(
            "Could not load DejaVuSans font: %s. Using default font.", str(e)
        )
        font = ImageFont.load_default(size=32)

    # === Calculate Text Dimensions ===
    draw = ImageDraw.Draw(
        label_img, mode="L"
    )  # Creates an object that can be used to draw in the given image

    bbox = draw.textbbox(
        (
            canvas_width // 2,
            canvas_height,
        ),  # anchor coordinates for the text, floating point division = bottom center
        text,  # text to be measured, can be multiline
        font=font,  # text font to be used
        anchor="md",  # anchor reference, here middle and descender (see docs)
        align="center",  # text alignment, here center
    )  # returns a 4-tuple of the bounding box coordinates (left, top, right, bottom) in pixels

    text_h = bbox[1] - bbox[3]  # Top - Bottom
    text_w = bbox[2] - bbox[0]  # Right - Left
    text_margin = 3  # margin (in pixels) around the text

    # === Resize Barcode to Fit Label ===
    max_barcode_height = canvas_height - (
        text_h + text_margin
    )  # Margin will only be on top of the text
    barcode_aspect_ratio = barcode_img.width / barcode_img.height
    new_barcode_height = min(barcode_img.height, max_barcode_height)
    new_barcode_width = int(new_barcode_height * barcode_aspect_ratio)

    barcode_resized = barcode_img.resize(
        (new_barcode_width, new_barcode_height),  # 2-tuple: width and height in pixels
        resample=Image.Resampling.LANCZOS,  # Resampling selection for resizing
    )  # returns a new PIL Image object

    # === Position and Draw Barcode ===
    barcode_x = (canvas_width - barcode_resized.width) // 2  # Centered horizontally
    barcode_y = 0  # Top of the label
    label_img.paste(
        barcode_resized, (barcode_x, barcode_y)
    )  # image, and (x,y) coordinates (upper left corner)

    # === Position and Draw Text ===
    draw.text(
        (
            canvas_width // 2,
            canvas_height,
        ),  # anchor coordinates for the text, floating point division = bottom center
        text,  # text to be measured, can be multiline
        font=font,  # text font to be used
        anchor="md",  # anchor reference, here middle and descender (see docs)
        align="center",  # text alignment, here center
        font_size=32,
    )

    # === Rotate Label to Portrait ===
    label_img = label_img.rotate(90, expand=True)

    return label_img


def print_img(img, item, mode):
    """
    Print an image using a network-connected printer.

    This function sends an image to a Brother QL-810W label printer for printing
    using the predefined configurations. The function initializes the printer
    backend, prepares the image for printing as per label printer specifications,
    and sends the image instructions to the printer. It also logs success or
    failure during the process.

    Parameters:
        img: The image to be printed on the label.
            This parameter represents the image that will be processed and printed.
        item: The inventory item object.
        mode: The barcode mode, either "upc" or "unique".

    Raises:
        Exception:
            Raised if an error occurs during the printing process, such as
            initialization failure, backend communication error, or image
            processing issues. The function continues execution even after
            the exception, logging a warning and moving forward to handle the
            scenario gracefully to avoid abrupt termination.
    """
    # Find printer on network
    # printer_mac = getattr(settings, "PRINTER_MAC", None)
    printer_ip = getattr(settings, "PRINTER_IP", None)
    # if not printer_mac:
    #     logger.error("Printer MAC address not configured in settings")
    #     raise ValueError("Printer MAC not configured")
    #
    # printer_ip = find_printer_ip_by_mac(printer_mac)
    # if not printer_ip:
    #     logger.error("Printer not found on network with MAC: %s", printer_mac)
    #     raise ValueError("Printer not found on the network")

    try:
        # Initialize printer backend
        backend = BrotherQLBackendNetwork(f"tcp://{printer_ip}:9100")

        # Configure raster
        qlr = BrotherQLRaster("QL-810W")
        qlr.exception_on_warning = True

        # Convert image to printer instructions
        instructions = convert(
            qlr=qlr,
            images=[img],
            label="17x54",
            rotate="auto",
            threshold=70.0,
            dither=False,
            compress=False,
            red=False,
            dpi_600=False,
            hq=True,
            cut=True,
        )

        # Send to printer
        backend.write(instructions)
        logger.info(
            "Successfully printed barcode label for item %s with mode %s",
            item.id,
            mode,
        )
    except Exception as e:
        logger.exception("Error printing barcode: %s", str(e))
        # Continue execution to return the image even if printing fails
        logger.warning("Continuing to generate barcode image despite printing failure")


def find_printer_ip_by_mac(target_mac, iface=None, timeout=2):
    """
    Find the IP address of a device with the specified MAC address using ARP.
    Enhanced for Docker container environments.

    Args:
        target_mac (str): MAC address of the device to find
        iface (str, optional): Network interface to use. Defaults to None.
        timeout (int, optional): Timeout in seconds. Defaults to 2.

    Returns:
        str or None: IP address as string if found, None otherwise
    """
    if not target_mac:
        logger.error("Cannot find printer: Empty MAC address provided")
        return None

    # Normalize MAC address format
    target_mac = target_mac.lower().replace("-", ":")

    # Try to populate ARP cache using multiple methods
    try:
        # Method 1: Network-wide ping scan
        try:
            subprocess.run(
                ["ping", "-c", "1", "-b", "255.255.255.255"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
            )
        except (subprocess.SubprocessError, FileNotFoundError):
            # Method 2: Alternative for systems without broadcast ping
            logger.debug("Broadcast ping failed, trying sequential ping")
            for i in range(1, 255):
                try:
                    subprocess.run(
                        ["ping", "-c", "1", f"192.168.68.{i}"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=0.1,
                    )
                except (subprocess.SubprocessError, subprocess.TimeoutExpired):
                    continue
    except Exception as e:
        logger.warning(f"ARP cache population attempts failed: {str(e)}")
        # Continue anyway as the device might already be in ARP cache

    # Try different commands to get network information
    commands = [
        ["arp", "-an"],  # Standard ARP command
        ["ip", "neigh", "show"],  # Alternative for modern Linux systems
    ]

    arp_output = ""
    for cmd in commands:
        try:
            arp_output = subprocess.check_output(cmd, timeout=timeout).decode()
            break
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            logger.debug(f"Command {cmd} failed: {str(e)}")
            continue
        except Exception as e:
            logger.debug(f"Unexpected error running {cmd}: {str(e)}")
            continue

    if not arp_output:
        logger.error("Could not get ARP information using any available command")
        return None

    # Parse ARP output to find the device
    try:
        for line in arp_output.splitlines():
            if target_mac in line.lower():
                # Try both formats: (192.168.1.1) and 192.168.1.1
                match = re.search(r"\(([\d\.]+)\)|^([\d\.]+)\s", line)
                if match:
                    ip_address = match.group(1) or match.group(2)
                    logger.info(
                        "Found printer with MAC %s at IP %s", target_mac, ip_address
                    )
                    return ip_address

        logger.warning("No device found with MAC address %s", target_mac)
    except Exception as e:
        logger.exception("Error parsing ARP output for MAC %s: %s", target_mac, str(e))

    return None


def generate_and_print_barcode(item, mode):
    """
    Generate a barcode for an inventory item and send it to the printer.

    Args:
        item: The inventory item object
        mode (str): The barcode mode, either "upc" or "unique"

    Returns:
        HttpResponse: HTTP response containing the barcode image

    Raises:
        ValueError: If there's an error generating or printing the barcode
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
    else:
        logger.error("Invalid barcode mode: %s", mode)
        raise ValueError(f"Invalid barcode mode: {mode}")

    try:
        # === Generate Barcode Image ===
        barcode_img = generate_barcode(data)

        # === Format Label Image ===
        label_img = format_label(barcode_img, data, label_size=(54, 17))

        # === Print Label if Enabled ===
        if settings.ENABLE_BARCODE_PRINTING:
            print_img(label_img, item, mode)

        else:
            logger.info("[TEST MODE] Skipping actual label print for item %s", item.id)

        # === Return Image as HTTP Response ===
        response = HttpResponse(content_type="image/png")
        label_img.save(response, format="PNG")
        return response

    except ValueError as e:
        # Re-raise ValueError exceptions
        raise
    except Exception as e:
        # Convert other exceptions to ValueError
        logger.exception("Error in generate_and_print_barcode: %s", str(e))
        raise ValueError(f"Barcode generation failed: {str(e)}")
