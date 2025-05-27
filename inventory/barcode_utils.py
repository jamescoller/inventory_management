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

        # === Create Label Canvas (landscape) ===
        canvas_width, canvas_height = 566, 165
        label_img = Image.new(
            "L", (canvas_width, canvas_height), 255
        )  # White background

        # === Load Font for Text ===
        try:
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22
            )
        except Exception as e:
            logger.warning(
                "Could not load DejaVuSans font: %s. Using default font.", str(e)
            )
            font = ImageFont.load_default()

        # === Calculate Text Dimensions ===
        text = data
        draw = ImageDraw.Draw(label_img)
        bbox = draw.textbbox((0, 0), text, font=font)
        text_h = bbox[3] - bbox[1]
        text_margin = 5

        # === Resize Barcode to Fit Label ===
        max_barcode_height = canvas_height - (text_h + text_margin * 2)
        barcode_aspect_ratio = barcode_img.width / barcode_img.height
        new_barcode_height = min(barcode_img.height, max_barcode_height)
        new_barcode_width = int(new_barcode_height * barcode_aspect_ratio)

        barcode_resized = barcode_img.resize(
            (new_barcode_width, new_barcode_height), Image.Resampling.LANCZOS
        )

        # === Position and Draw Barcode ===
        barcode_x = (canvas_width - barcode_resized.width) // 2
        barcode_y = text_margin
        label_img.paste(barcode_resized, (barcode_x, barcode_y))

        # === Position and Draw Text ===
        text_x = (canvas_width - bbox[2]) // 2
        text_y = barcode_y + new_barcode_height + text_margin
        draw.text((text_x, text_y), text, font=font, fill=0)  # Black text

        # === Rotate Label to Portrait ===
        label_img = label_img.rotate(90, expand=True)

        # === Print Label if Enabled ===
        if settings.ENABLE_BARCODE_PRINTING:
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
                    images=[label_img],
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
                logger.warning(
                    "Continuing to generate barcode image despite printing failure"
                )
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
