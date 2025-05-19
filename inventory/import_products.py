import pandas as pd
from inventory.models import Filament, Printer, Hardware, AMS, Dryer
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = 'Import products from Excel'

    def handle(self, *args, **options):
        file_path = 'path/to/your.xlsx'
        df = pd.read_excel(file_path)

        count = 0

        for index, row in df.iterrows():
            product_type = row.get('type')

            model_class = {
                'Filament': Filament,
                'Printer': Printer,
                'Hardware': Hardware,
                'AMS': AMS,
                'Dryer': Dryer
            }.get(product_type)

            if model_class is None:
                print(f"❌ Skipped unknown type: {product_type}")
                continue

            obj = model_class(
                name=row.get('name'),
                upc=row.get('upc'),
                sku=row.get('sku'),
                category=row.get('category'),
                print_temp_degC=row.get('print_temp_degC', None),
                hex_code=row.get('hex_code', None),
                # Add other fields as needed
            )
            obj.save()
            count += 1

        print(f"✅ Imported {count} products.")