from django import template
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag
def filament_spool(hex_code):
    context = {
        "fill_color": hex_code,
        "spool_color": "#303030",  # Default gray for the spool edges
    }
    return mark_safe(render_to_string("inventory/includes/filament_spool.svg", context))
