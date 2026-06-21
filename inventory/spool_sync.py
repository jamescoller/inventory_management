"""Pure matcher for the Bambu spool-sync dry-run (Phase 16.3, trust gate).

Reads the AMSChannelState telemetry mirror + inventory via the ORM and produces
*proposed* writes — it never writes. The (device, ams_index) -> AMS-serial bridge
is passed in (fetched live by inventory.bambu_mqtt); see
docs/superpowers/specs/2026-06-21-spool-sync-dryrun-design.md.
"""

ALL_ZEROS = "0" * 32
_HEXDIGITS = set("0123456789abcdef")


def normalize_hex(value):
    """Return a 6-char lowercase RGB hex (drops '#' and any alpha), or None."""
    if not value:
        return None
    h = str(value).strip().lstrip("#").lower()
    if len(h) < 6:
        return None
    h = h[:6]
    if any(c not in _HEXDIGITS for c in h):
        return None
    return h


def classify_tray(tray_uuid, tray_type, color_hex):
    """BAMBU (real RFID), NON_BAMBU (roll present, no RFID), or EMPTY."""
    uuid = (tray_uuid or "").strip()
    if uuid and uuid != ALL_ZEROS:
        return "BAMBU"
    if (tray_type or "").strip() or normalize_hex(color_hex):
        return "NON_BAMBU"
    return "EMPTY"


def material_matches(tray_type, filament):
    """Advisory: is the telemetry material consistent with the spool's? None if unknown."""
    if not tray_type or filament is None or filament.material is None:
        return None
    mat = filament.material
    haystack = f"{mat.name} {mat.material_type}".lower()
    return tray_type.strip().lower() in haystack
