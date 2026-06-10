from django.apps import AppConfig


class InventoryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "inventory"

    def ready(self):
        from django.db.backends.signals import connection_created

        import inventory.signals  # noqa: F401
        from inventory.db_pragmas import enable_sqlite_pragmas

        connection_created.connect(enable_sqlite_pragmas)
