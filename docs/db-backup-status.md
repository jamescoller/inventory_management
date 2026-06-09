# DB Backup (Phase 11.1) — status & blocker (tabled 2026-06-09)

**Status: script DONE & validated; deployment BLOCKED on getting the NAS share
reachable from inside the app LXC. Tabled during a planning session — pick up later.**

## What's done
- **`scripts/backup_db.py`** (this PR, #130). Stdlib-only, no root, no `sqlite3` CLI;
  consistent snapshot via SQLite's online-backup API (live-writer-safe, WAL-correct),
  integrity-checked, gzipped, atomic-rename, GFS-lite retention. Refuses to write unless
  the dest is a live mountpoint (`--skip-mount-check` for local testing).
- **Validated on the live host:** a snapshot restores cleanly to **641 items / 107
  locations**; rotation prunes correctly; ~130 KB gz, 0.02 s; source DB untouched.
- So the *backup logic* is finished and proven. Only the **transport to the NAS** is open.

## The blocker
Target: `10.10.20.4:/volume1/inventory-backup` → `/mnt/nas-backup` on the app LXC (CT **105**).
- fstab line + Synology export are configured; NAS `:2049` is reachable from the LXC.
- `nfs-common` was missing → installed it. Then the mount fails with
  **`mount.nfs: Operation not permitted`**.
- **Root cause:** CT 105 is an **unprivileged Proxmox LXC**; Proxmox/AppArmor blocks NFS
  mounts *inside* unprivileged containers. (Same family as the existing "no sudo on the app
  LXC" constraint — privileged/host ops have to come from the Proxmox host.)

## Attempts that did NOT work (2026-06-09)
Both tried on the Proxmox host; **neither succeeded** (exact failure output not captured —
**first step next time: re-run and record the precise errors**):
1. **Host-mounts-NFS + bind-mount into CT** — `pct set 105 -mp0 <host-nfs-path>,mp=/mnt/nas-backup`.
2. **Let the container mount NFS** — `pct set 105 -features nesting=1,mount=nfs` (nesting kept so
   Docker survives) + reboot.

## Recommended next approach — avoid an in-LXC mount entirely
The friction is *mounting* the share inside the container. Two transports sidestep it and need
**no script change** (the script already takes `--dest <local-dir>` + `--skip-mount-check`):

- **NAS-side pull (preferred).** Script writes the gz to a **local** staging dir in the LXC
  (e.g. `~/db-backups/`); the Synology pulls it on a schedule (Hyper Backup, or a Synology
  `rsync`/Task Scheduler job over SSH). No NAS creds on the LXC, no in-container mount, and the
  NAS owns retention/versioning. Cleanest fit given the LXC NFS restriction.
- **Push over SSH from the LXC** — `rsync`/`scp` the gz to the NAS over SSH (needs a key + the
  NAS accepting SSH). Also no mount.

Fallback: re-attempt the host-mount+bind (capture exact errors), or try CIFS/SMB (likely the
same unprivileged-LXC restriction).

## Decision needed from James (later)
Pick the transport: **NAS-side pull** (recommended) vs **push-over-SSH** vs **fix the in-LXC
mount**. Then: choose the local staging dir, wire the cron (`0 2 * * *`), and run a first real
backup + restore test.

## Loose ends to clean up
- `nfs-common` is now installed on CT 105 (harmless; leave or remove).
- The container `/etc/fstab` still has the `…/mnt/nas-backup nfs…` line, so a mount unit
  **fails on every boot** (cosmetic log noise). Remove that line when the real transport is
  chosen.

## Pointers
- Script + PR: `scripts/backup_db.py`, PR #130. Cron model mirrors `scripts/ha_stats_export.py`
  (runs from the Actions-runner checkout). Roadmap item: Phase 11.1 in `todo.md` / PR #129.
