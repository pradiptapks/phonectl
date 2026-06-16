"""Backup and restore commands."""

from __future__ import annotations

import click

from phonectl.commands._helpers import (
    console, create_device_manager, _detect_device,
)
from phonectl.core.backup import BackupManager
from phonectl.core.fastboot import FastbootClient
from phonectl.core.safety import SafetyGuard


@click.group()
def backup():
    """Backup and restore boot partition images."""


@backup.command("create")
@click.option("--from-dir", type=click.Path(exists=True), help="Directory containing boot images")
@click.option("--codename", help="Device codename (auto-detected if omitted)")
def backup_create(from_dir: str | None, codename: str | None):
    """Create a backup of boot partition images."""
    bm = BackupManager()

    if not codename:
        dm = create_device_manager()
        info = _detect_device(dm)
        codename = info.codename or "unknown"

    if from_dir:
        bm.backup_from_firmware(codename, from_dir)
    else:
        console.print(
            "[yellow]No source directory specified.[/]\n"
            "Use --from-dir to point to a directory with boot.img, vendor_boot.img, etc.\n"
            "Example: phonectl backup create --from-dir /tmp/moto_recovery/"
        )


@backup.command("list")
@click.option("--codename", help="Filter by device codename")
def backup_list(codename: str | None):
    """List all available backups."""
    bm = BackupManager()
    bm.show_backups(codename)


@backup.command("restore")
@click.argument("backup_path", type=click.Path(exists=True))
def backup_restore(backup_path: str):
    """Restore boot partitions from a backup (device must be in fastbootd)."""
    bm = BackupManager()
    images = bm.get_backup_images(backup_path)

    if not images:
        console.print(f"[red]No images found in {backup_path}[/]")
        raise SystemExit(1)

    console.print(f"[bold]Restoring from:[/] {backup_path}")
    for name, path in images.items():
        console.print(f"  {name}: {path}")

    guard = SafetyGuard()
    if not guard.confirm_destructive("This will overwrite boot partitions on the device."):
        console.print("[yellow]Aborted.[/]")
        return

    fb = FastbootClient()
    if not fb.is_connected():
        console.print("[red]Device not in fastboot mode.[/] Run: adb reboot fastboot")
        raise SystemExit(1)

    for partition, img_path in images.items():
        console.print(f"[bold]Flashing {partition}...[/]")
        if partition == "vbmeta":
            fb.flash_vbmeta(img_path)
        else:
            fb.flash(partition, img_path, sparse_limit="")
        console.print(f"  [green]Done[/]")

    console.print("[green]Restore complete.[/] Reboot with: fastboot reboot")
