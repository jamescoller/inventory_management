from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0020_phase2_dead_code_removal'),
    ]

    operations = [
        migrations.AddField(
            model_name='material',
            name='material_type',
            field=models.CharField(blank=True, default='', max_length=50),
        ),
        migrations.AlterField(
            model_name='material',
            name='name',
            field=models.CharField(max_length=100),
        ),
        migrations.AlterUniqueTogether(
            name='material',
            unique_together={('name', 'material_type')},
        ),
    ]
