from django.db import migrations

from inventory import search_index


def populate(apps, schema_editor):
    search_index.rebuild_all()


def depopulate(apps, schema_editor):
    pass  # table is dropped by the reverse RunSQL


class Migration(migrations.Migration):
    dependencies = [("inventory", "0039_material_store_slug_filamentcolor")]
    operations = [
        migrations.RunSQL(
            sql=search_index.FTS_CREATE_SQL, reverse_sql=search_index.FTS_DROP_SQL
        ),
        migrations.RunPython(populate, depopulate),
    ]
