from django.db import migrations


def backfill_kind(apps, schema_editor):
    """
    Set `kind` on pre-existing Location rows.

    Every row defaulted to 'shelf' when the column was added (migration 0025), so
    this only needs to correct the two specially-treated legacy locations. Printer
    takes precedence over the dry-storage name match. The name compare mirrors the
    case-insensitive check the app used before this field existed
    (`name.lower() == "dry storage"`).
    """
    Location = apps.get_model("inventory", "Location")
    for loc in Location.objects.all():
        if loc.is_printer:
            new_kind = "printer"
        elif loc.name.lower().strip() == "dry storage":
            new_kind = "dry_storage"
        else:
            continue  # leave as the 'shelf' default
        if loc.kind != new_kind:
            loc.kind = new_kind
            loc.save(update_fields=["kind"])


def reverse_backfill(apps, schema_editor):
    """No-op: 'kind' is dropped wholesale when 0025 is reversed."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0025_location_hierarchy_and_audit"),
    ]

    operations = [
        migrations.RunPython(backfill_kind, reverse_code=reverse_backfill),
    ]
