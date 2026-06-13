"""Resolve a 'View in Store' URL for a filament color/material.

Per-manufacturer store config (base + URL templates). A material's product-page
slug lives on ``Material.store_slug`` and is used only when the sheet's
manufacturer matches ``Material.mfr``; otherwise we fall back to the brand's
search URL. Unknown brand => ``None`` (caller hides the button).
"""

from urllib.parse import quote_plus

STORE_CONFIG = {
    "Bambu Lab": {
        "base": "https://us.store.bambulab.com",
        "product": "/products/{slug}",
        "search": "/search?q={query}",
    },
    "Polymaker": {
        "base": "https://us.polymaker.com",
        "search": "/search?q={query}",
    },
}


def store_url(*, manufacturer, material=None, query=""):
    cfg = STORE_CONFIG.get(manufacturer)
    if cfg is None:
        return None
    slug = getattr(material, "store_slug", "") if material is not None else ""
    mfr_match = material is not None and material.mfr == manufacturer
    if slug and mfr_match and "product" in cfg:
        return cfg["base"] + cfg["product"].format(slug=slug)
    if "search" in cfg:
        return cfg["base"] + cfg["search"].format(query=quote_plus(query))
    return cfg["base"]
