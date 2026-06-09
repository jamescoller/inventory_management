# DB Backup (Phase 11.1) — status & blocker (tabled 2026-06-09)

**Status: script DONE & validated; deployment BLOCKED on getting the NAS share
reachable from inside the app LXC. Tabled during a planning session. A proven fix is now
identified — the CIFS-on-host + bind-mount pattern the Plex LXC (CT 106) already uses (see
"Proven solution" below). Apply it when resuming.**

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

## Proven solution — CIFS-on-host + bind-mount (from Plex CT 106)
The Plex LXC (**CT 106**, also an unprivileged Debian 12 container on the same Proxmox host) hit
this exact wall — *"NFS does not work cleanly into an unprivileged LXC"* — and solved it by
mounting the share over **CIFS on the Proxmox host** and bind-mounting it in, keeping the
container unprivileged. Full writeup: `~/projects/homelab/media_server.md` (§ "Access method —
SMB/CIFS, not NFS"). Replicate for CT 105:

1. **Synology:** enable **SMB** on the `inventory-backup` shared folder; give a service account
   R/W (reuse `plexnfs` (DSM uid 1026) or make a dedicated `invbackup` account). The earlier NFS export rule becomes unused — safe to remove (same as Plex).
2. **Proxmox host `/etc/fstab`** — CIFS mount with a client-side uid/gid override set to the
   **host-mapped** IDs of the container's `jcoller` (in-container uid/gid **1000/1000** → host
   **101000/101000** under the unprivileged +100000 offset):
   ```
   //10.10.20.4/inventory-backup  /mnt/inventory-backup  cifs  credentials=/root/.smbcreds-invbackup,uid=101000,gid=101000,file_mode=0664,dir_mode=0775,vers=3.1.1,iocharset=utf8,_netdev,nofail  0  0
   ```
   Credentials file `/root/.smbcreds-invbackup` (mode 600): `username=…` + `password=…`. Then
   `mkdir -p /mnt/inventory-backup && mount -a` on the host.
3. **Bind-mount into CT 105** (next free `mpN`):
   `pct set 105 -mp0 /mnt/inventory-backup,mp=/mnt/nas-backup`.
4. Remove the failed in-container NFS fstab line; `pct reboot 105`; verify
   `pct exec 105 -- mountpoint /mnt/nas-backup`.

This keeps CT 105 unprivileged, needs no idmap, and the CIFS `uid=`/`gid=` override means the
backup script (running as `jcoller`) **owns the files it writes** — no two-writer permission war.
Afterwards the script's default `--dest /mnt/nas-backup` + mountpoint check work as written —
**no code change**.

## Fallbacks — no mount needed
If the CIFS-on-host route is ever undesirable, two transports sidestep mounting entirely and need
**no script change** (the script already takes `--dest <local-dir>` + `--skip-mount-check`):

- **NAS-side pull (preferred).** Script writes the gz to a **local** staging dir in the LXC
  (e.g. `~/db-backups/`); the Synology pulls it on a schedule (Hyper Backup, or a Synology
  `rsync`/Task Scheduler job over SSH). No NAS creds on the LXC, no in-container mount, and the
  NAS owns retention/versioning. Cleanest fit given the LXC NFS restriction.
- **Push over SSH from the LXC** — `rsync`/`scp` the gz to the NAS over SSH (needs a key + the
  NAS accepting SSH). Also no mount.

## To finish (later)
Apply the **CIFS-on-host + bind-mount** template above (the proven CT 106 route) — or a no-mount
fallback if preferred. Then remove the dead in-container NFS fstab line, wire the `jcoller` cron
(`0 2 * * *`), and run a first real backup + restore test.

## Loose ends to clean up
- `nfs-common` is now installed on CT 105 (harmless; leave or remove).
- The container `/etc/fstab` still has the `…/mnt/nas-backup nfs…` line, so a mount unit
  **fails on every boot** (cosmetic log noise). Remove that line when the real transport is
  chosen.

## Pointers
- Script + PR: `scripts/backup_db.py`, PR #130. Cron model mirrors `scripts/ha_stats_export.py`
  (runs from the Actions-runner checkout). Roadmap item: Phase 11.1 in `todo.md` / PR #129.
