import subprocess
import re
from barcode import Code128
from barcode.writer import ImageWriter
from PIL import Image, ImageDraw, ImageFont
from brother_ql.backends.network import BrotherQLBackendNetwork
from brother_ql.raster import BrotherQLRaster
from brother_ql.conversion import convert
from django.conf import settings
from django.http import HttpResponse
import io
from warnings import filterwarnings


def find_printer_ip_by_mac(target_mac, iface=None, timeout=2):
    """
    Use `arp -a` to find the IP of a device with the specified MAC address.
    Returns IP as string if found, otherwise None.
    """
    target_mac = target_mac.lower()
    arp_output = subprocess.check_output("arp -a", shell=True).decode()

    for line in arp_output.splitlines():
        if target_mac in line.lower():
            # Extract the IP from parentheses
            match = re.search(r"\(([\d\.]+)\)", line)
            if match:
                return match.group(1)
    return None


def generate_and_print_barcode(item, mode):
    filterwarnings(
        "ignore", category=DeprecationWarning, module="brother_ql.devicedependent"
    )

    if mode == "upc":
        data = item.product.upc
        label_name = f"UPC-{data}"
    elif mode == "unique":
        data = f"INV-{item.id}"
        label_name = f"INV-{item.id}"
    else:
        return HttpResponse("Invalid mode", status=400)

    # === Barcode Image ===
    barcode_img_io = io.BytesIO()
    barcode = Code128(data, writer=ImageWriter())
    barcode.write(
        barcode_img_io,
        {
            "module_height": 10.0,
            "write_text": False,  # ✅ disables default text rendering
        },
    )
    barcode_img_io.seek(0)
    barcode_img = Image.open(barcode_img_io).convert("L")

    # === Final label dimensions (landscape) ===
    canvas_width, canvas_height = 566, 165
    label_img = Image.new("L", (canvas_width, canvas_height), 255)

    # === Text ===
    text = data
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
    except:
        font = ImageFont.load_default()

    draw = ImageDraw.Draw(label_img)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_h = bbox[3] - bbox[1]
    text_margin = 5

    # === Shrink barcode if needed ===
    max_barcode_height = canvas_height - (text_h + text_margin * 2)
    barcode_aspect_ratio = barcode_img.width / barcode_img.height
    new_barcode_height = min(barcode_img.height, max_barcode_height)
    new_barcode_width = int(new_barcode_height * barcode_aspect_ratio)

    barcode_resized = barcode_img.resize(
        (new_barcode_width, new_barcode_height), Image.Resampling.LANCZOS
    )

    # === Draw barcode ===
    barcode_x = (canvas_width - barcode_resized.width) // 2
    barcode_y = text_margin
    label_img.paste(barcode_resized, (barcode_x, barcode_y))

    # === Draw text centered below ===
    text_x = (canvas_width - bbox[2]) // 2
    text_y = barcode_y + new_barcode_height + text_margin
    draw.text((text_x, text_y), text, font=font, fill=0)

    # === Final: Rotate full label to portrait ===
    label_img = label_img.rotate(90, expand=True)

    # === Send to printer ===
    # Find the printer on the network and gather its IP address
    printer_mac = getattr(settings, "PRINTER_MAC", None)
    if not printer_mac:
        return HttpResponse("Printer MAC not configured", status=500)

    printer_ip = find_printer_ip_by_mac(printer_mac)
    if not printer_ip:
        return HttpResponse("Printer not found on the network.", status=503)

    # Use IP to initialize backend
    # printer_ip = "192.168.68.98"
    backend = BrotherQLBackendNetwork(f"tcp://{printer_ip}:9100")

    qlr = BrotherQLRaster("QL-810W")
    qlr.exception_on_warning = True

    # Convert the image(s) to printer instructions
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

    # Send the instructions to the printer
    # send(instructions=instructions, printer_identifier=f'tcp://{printer_ip}', backend_identifier='network')

    img_io = io.BytesIO()
    label_img.save(img_io, format="PNG")
    img_io.seek(0)

    if getattr(settings, "ENABLE_BARCODE_PRINTING", True):
        backend.write(instructions)
    else:
        print(f"[TEST MODE] Skipping actual label print for item {item.id}")

    return label_img  # return for preview & download
