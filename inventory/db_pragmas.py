"""SQLite PRAGMAs applied to every new database connection.

Enables WAL so the web app and (Phase 16.1) the telemetry consumer can read and
write the same SQLite file concurrently without ``database is locked`` errors.
Connected in :meth:`InventoryConfig.ready` via the ``connection_created`` signal
so it runs identically for gunicorn workers, management commands, and the test
runner. A no-op on any non-SQLite backend.
"""


def enable_sqlite_pragmas(sender, connection, **kwargs):
    if connection.vendor != "sqlite":
        return
    cursor = connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.execute("PRAGMA busy_timeout=5000;")
    cursor.close()
