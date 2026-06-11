"""Migration helpers shared across data migrations.

Kept here (the migrations package ``__init__``) so a ``RunPython`` callable and
its unit test can import the same function. Helpers must accept a *model class*
(never import models directly) so they work with both the real model and the
frozen historical model handed in by ``apps.get_model`` during a migration.
"""


def _mfr_backfill_helper(FilamentModel):
    """Backfill ``Filament.manufacturer`` from the linked ``material.mfr``.

    Only touches rows where ``manufacturer`` is still blank and a material is
    set, so an explicit per-spool brand entered later is never clobbered. Pure
    ORM, so it is safe to call against the historical model inside a migration.
    Returns the number of rows updated.
    """
    updated = 0
    qs = FilamentModel.objects.filter(manufacturer="", material__isnull=False)
    for fil in qs.select_related("material"):
        mfr = (fil.material.mfr or "").strip()
        if mfr:
            fil.manufacturer = mfr
            fil.save(update_fields=["manufacturer"])
            updated += 1
    return updated
