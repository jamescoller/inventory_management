from django.db import migrations

KNOWN_BASE_TYPES = {
    'ABS', 'ASA', 'PA6', 'PAHT', 'PC', 'PET', 'PETG',
    'PLA', 'PPS', 'PVA', 'Support', 'TPU',
}


def split_material_names(apps, schema_editor):
    Material = apps.get_model('inventory', 'Material')
    for mat in Material.objects.all():
        name = mat.name
        # Rule 1: "Support for X" (must come before space-split to avoid "Support" matching X Y)
        if name.startswith('Support for '):
            mat.name = 'Support'
            mat.material_type = name[len('Support '):]   # "for X"
        # Rule 2: hyphen — "X-Y"
        elif '-' in name:
            base, modifier = name.split('-', 1)
            mat.name = base
            mat.material_type = modifier
        # Rule 3: space — "X Y" where X is a known base
        elif ' ' in name:
            base, modifier = name.split(' ', 1)
            if base in KNOWN_BASE_TYPES:
                mat.name = base
                mat.material_type = modifier
            # else: unknown pattern, leave name unchanged, material_type stays ''
        # Rule 4: single word — nothing to do
        mat.save()


def reverse_split(apps, schema_editor):
    Material = apps.get_model('inventory', 'Material')
    for mat in Material.objects.all():
        if mat.material_type:
            mat.name = f'{mat.name} {mat.material_type}'
            mat.material_type = ''
            mat.save()


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0021_material_type'),
    ]

    operations = [
        migrations.RunPython(split_material_names, reverse_code=reverse_split),
    ]
