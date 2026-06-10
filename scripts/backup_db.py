#!/usr/bin/env python3
"""Consistent, rotated backup of the inventory SQLite DB to the NAS.

Runs on the app LXC host as the ``jcoller`` cron user. Uses only the Python
standard library (no Django, no ``sqlite3`` CLI, no root) so it mirrors the
deployment model of ``ha_stats_export.py``: the file ships in the repo and runs
from the Actions-runner checkout on the host.

The snapshot is taken with SQLite's online-backup API
(``Connection.backup``), which is safe against a live writer and stays correct
under WAL — so it must never be a plain ``cp`` of the live file.

Cron (after this is deployed and ``/mnt/nas-backup`` is mounted)::

    0 2 * * * /usr/bin/python3 ~/actions-runner/_work/inventory_management/inventory_management/scripts/backup_db.py >> ~/inventory_backup.log 2>&1

Safety:
  * Refuses to run unless the destination is a live mountpoint, so a dead NFS
    mount can't silently write a "backup" onto the LXC root filesystem. Use
    ``--skip-mount-check`` for local testing only.
  * Verifies the snapshot with ``PRAGMA integrity_check`` before keeping it.
  * Writes to a temp name on the destination, then atomically renames.

Retention (GFS-lite): keep the newest ``--keep`` backups, and additionally never
prune a first-of-month snapshot within ``--keep-monthly`` months.
"""

from __future__ import annotations

import argparse
import datetime
import gzip
import os
import shutil
import sqlite3
import sys
import tempfile
import time

HOME = os.path.expanduser("~")
DEFAULT_SRC = os.path.join(HOME, "inventory_db_dir", "inventory_db.sqlite3")
DEFAULT_DEST = "/mnt/nas-backup"
PREFIX = "inventory_db-"
SUFFIX = ".sqlite3.gz"


def log(msg: str) -> None:
    print(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}", flush=True)


def make_snapshot(src: str, dest: str) -> str:
    """Write a consistent snapshot of ``src`` to ``dest`` and integrity-check it."""
    src_uri = f"file:{src}?mode=ro"
    srccon = sqlite3.connect(src_uri, uri=True)
    try:
        bck = sqlite3.connect(dest)
        try:
            srccon.backup(bck)
        finally:
            bck.close()
    finally:
        srccon.close()

    chk = sqlite3.connect(dest)
    try:
        result = chk.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        chk.close()
    if result != "ok":
        raise RuntimeError(f"integrity_check failed: {result!r}")
    return result


def rotate(dest: str, keep: int, keep_monthly: int) -> tuple[int, int]:
    """Prune old backups; keep newest ``keep`` plus monthly snapshots."""
    backups = sorted(
        (f for f in os.listdir(dest) if f.startswith(PREFIX) and f.endswith(SUFFIX)),
        reverse=True,
    )
    today = datetime.date.today()
    kept = 0
    for i, name in enumerate(backups):
        keep_it = i < keep
        datestr = name[len(PREFIX) : len(PREFIX) + 10]  # YYYY-MM-DD
        try:
            d = datetime.date.fromisoformat(datestr)
            if d.day == 1 and (today - d).days <= keep_monthly * 31:
                keep_it = True
        except ValueError:
            pass
        if keep_it:
            kept += 1
        else:
            os.remove(os.path.join(dest, name))
            log(f"pruned old backup: {name}")
    return kept, len(backups)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--src", default=DEFAULT_SRC, help="path to the live DB")
    parser.add_argument("--dest", default=DEFAULT_DEST, help="backup directory")
    parser.add_argument(
        "--keep", type=int, default=30, help="most-recent backups to retain"
    )
    parser.add_argument(
        "--keep-monthly",
        type=int,
        default=12,
        help="months to retain first-of-month snapshots",
    )
    parser.add_argument(
        "--skip-mount-check",
        action="store_true",
        help="testing only: don't require dest to be a mountpoint",
    )
    args = parser.parse_args(argv)

    if not os.path.exists(args.src):
        log(f"ERROR: source DB not found: {args.src}")
        return 2

    if args.skip_mount_check:
        os.makedirs(args.dest, exist_ok=True)
    elif not os.path.isdir(args.dest):
        log(f"ERROR: destination missing: {args.dest} (is the NAS share mounted?)")
        return 3
    elif not os.path.ismount(args.dest):
        log(
            f"ERROR: {args.dest} is not a live mountpoint — refusing to write a "
            "backup to local disk. Mount the NAS share first."
        )
        return 3

    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    final_name = f"{PREFIX}{stamp}{SUFFIX}"
    final_path = os.path.join(args.dest, final_name)
    tmp_path = final_path + ".tmp"

    start = time.time()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            snap = os.path.join(tmpdir, "snapshot.sqlite3")
            make_snapshot(args.src, snap)
            with open(snap, "rb") as f_in, gzip.open(
                tmp_path, "wb", compresslevel=6
            ) as f_out:
                shutil.copyfileobj(f_in, f_out)
            os.replace(tmp_path, final_path)  # atomic on the same filesystem
    except Exception as exc:  # noqa: BLE001 - cron wants a non-zero exit + log line
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        log(f"ERROR: backup failed: {exc}")
        return 1

    size = os.path.getsize(final_path)
    kept, total = rotate(args.dest, args.keep, args.keep_monthly)
    log(
        f"OK  {final_name}  {size:,} bytes  {time.time() - start:.2f}s  "
        f"(retained {kept}/{total})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
