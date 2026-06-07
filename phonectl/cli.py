"""phonectl CLI — Click-based command interface for Android phone management."""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from phonectl.core.adb import ADBError
from phonectl.core.backup import BackupManager
from phonectl.core.device import DeviceInfo, DeviceManager, DeviceState
from phonectl.core.fastboot import FastbootClient, FastbootError
from phonectl.core.safety import SafetyGuard
from phonectl.firmware.gsi import (
    download_gsi,
    find_compatible_version,
    load_gsi_versions,
    show_gsi_versions,
)
from phonectl.vendors.base import FlashStepType
from phonectl.vendors.google import GooglePixelPlugin
from phonectl.vendors.motorola import MotorolaPlugin
from phonectl.vendors.samsung import SamsungPlugin

console = Console()


def _create_device_manager() -> DeviceManager:
    dm = DeviceManager()
    dm.register_vendor(MotorolaPlugin())
    dm.register_vendor(GooglePixelPlugin())
    dm.register_vendor(SamsungPlugin())
    return dm


def _detect_device(dm: DeviceManager) -> DeviceInfo:
    info = dm.detect()
    if info.state == DeviceState.DISCONNECTED:
        console.print("[red]No device connected.[/] Connect via USB and enable USB debugging.")
        raise SystemExit(1)
    if info.state == DeviceState.UNAUTHORIZED:
        console.print("[yellow]Device unauthorized.[/] Approve the USB debugging prompt on your phone.")
        raise SystemExit(1)
    return info


def _show_device_panel(info: DeviceInfo, vendor_name: str = "") -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="cyan")
    table.add_column()

    table.add_row("Manufacturer", info.manufacturer or "Unknown")
    table.add_row("Model", info.model or "Unknown")
    table.add_row("Codename", info.codename or "Unknown")
    table.add_row("Serial", info.serial)
    table.add_row("State", info.state.value)
    if vendor_name:
        table.add_row("Vendor Plugin", vendor_name)
    if info.android_version:
        table.add_row("Android", info.android_version)
    if info.security_patch:
        table.add_row("Security Patch", info.security_patch)
    if info.build_id:
        table.add_row("Build ID", info.build_id)
    if info.kernel_version:
        table.add_row("Kernel", info.kernel_version)
    if info.vndk_version:
        table.add_row("VNDK", info.vndk_version)
    if info.slot_suffix:
        table.add_row("Active Slot", info.slot_suffix)
    table.add_row("Bootloader", "Unlocked" if info.is_unlocked else "Locked")
    table.add_row("Treble", "Yes" if info.treble_enabled else "No")
    table.add_row("Dynamic Partitions", "Yes" if info.dynamic_partitions else "No")
    if info.cpu_abi:
        table.add_row("CPU ABI", info.cpu_abi)
    if info.board_platform:
        table.add_row("Platform", info.board_platform)
    if info.battery_level:
        table.add_row("Battery", f"{info.battery_level}%")
    if info.uptime:
        table.add_row("Uptime", info.uptime)

    console.print(Panel(table, title="[bold]Device Info[/]", border_style="green"))


# ═══════════════════════════════════════════════════════════════
# CLI Group
# ═══════════════════════════════════════════════════════════════

@click.group()
@click.version_option(package_name="phonectl")
def cli():
    """phonectl — Universal Android Phone Lifecycle Manager."""


# ═══════════════════════════════════════════════════════════════
# phonectl info
# ═══════════════════════════════════════════════════════════════

@cli.command()
def info():
    """Show connected device information."""
    dm = _create_device_manager()
    info = _detect_device(dm)
    vendor = dm.resolve_vendor(info)
    _show_device_panel(info, vendor.name if vendor else "Unknown")

    if vendor:
        quirks = vendor.get_usb_quirks()
        if quirks.get("description"):
            console.print(f"\n[dim]Vendor note: {quirks['description']}[/]")


# ═══════════════════════════════════════════════════════════════
# phonectl backup
# ═══════════════════════════════════════════════════════════════

@cli.group()
def backup():
    """Backup and restore boot partition images."""


@backup.command("create")
@click.option("--from-dir", type=click.Path(exists=True), help="Directory containing boot images")
@click.option("--codename", help="Device codename (auto-detected if omitted)")
def backup_create(from_dir: str | None, codename: str | None):
    """Create a backup of boot partition images."""
    bm = BackupManager()

    if not codename:
        dm = _create_device_manager()
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


# ═══════════════════════════════════════════════════════════════
# phonectl flash
# ═══════════════════════════════════════════════════════════════

@cli.group()
def flash():
    """Flash GSI or stock firmware."""


@flash.command("gsi")
@click.option("--version", "build_id", help="GSI build ID (e.g., BP2A.250605.031.A3)")
@click.option("--no-wipe", is_flag=True, help="Skip data wipe (same major version update)")
def flash_gsi(build_id: str | None, no_wipe: bool):
    """Download and flash a GSI image."""
    dm = _create_device_manager()
    info = _detect_device(dm)
    vendor = dm.resolve_vendor(info)

    _show_device_panel(info, vendor.name if vendor else "Unknown")

    # Find GSI version
    versions = load_gsi_versions()
    gsi = None
    if build_id:
        gsi = next((v for v in versions if v.build_id == build_id), None)
        if not gsi:
            console.print(f"[red]Unknown GSI build ID: {build_id}[/]")
            show_gsi_versions()
            raise SystemExit(1)
    else:
        gsi = find_compatible_version(info.vndk_version or "30")
        if not gsi:
            console.print("[red]No compatible GSI version found.[/]")
            raise SystemExit(1)
        console.print(f"[bold]Auto-selected:[/] {gsi.name} ({gsi.build_id})")

    # Safety checks
    guard = SafetyGuard()
    report = guard.pre_flash_check(info, gsi.build_id)
    console.print("\n[bold]Safety Checks:[/]")
    console.print(report.summary())

    if not report.passed:
        console.print("\n[red]Safety checks failed. Fix issues above before flashing.[/]")
        if not guard.confirm_destructive("Proceed anyway? THIS IS DANGEROUS."):
            raise SystemExit(1)

    wipe_msg = "This will WIPE ALL DATA on the device." if not no_wipe else "Data will be preserved."
    if not guard.confirm_destructive(f"Flash {gsi.name} ({gsi.build_id}). {wipe_msg}"):
        console.print("[yellow]Aborted.[/]")
        return

    # Download GSI
    gsi_dir = download_gsi(gsi)
    system_img = str(gsi_dir / "system.img")
    vbmeta_img = str(gsi_dir / "vbmeta.img")

    # Reboot to fastbootd
    adb = dm.get_adb()
    if info.state == DeviceState.ANDROID and adb:
        console.print("[bold]Rebooting to fastbootd...[/]")
        adb.reboot_fastboot()
        import time
        time.sleep(15)

    fb = FastbootClient()
    if not fb.is_connected():
        console.print("[yellow]Waiting for fastboot connection...[/]")
        guard.wait_for_usb(timeout=60)
        if not fb.is_connected():
            console.print("[red]Device not in fastboot. Enter fastbootd manually.[/]")
            raise SystemExit(1)

    # Execute flash sequence
    if vendor and not no_wipe:
        steps = vendor.get_flash_sequence(info, system_img, vbmeta_img)
    elif vendor and no_wipe:
        if hasattr(vendor, "get_update_sequence"):
            steps = vendor.get_update_sequence(info, system_img, vbmeta_img)
        else:
            steps = vendor.get_flash_sequence(info, system_img, vbmeta_img)
            steps = [s for s in steps if s.step_type != FlashStepType.WIPE]
    else:
        console.print("[red]No vendor plugin found. Cannot determine flash sequence.[/]")
        raise SystemExit(1)

    _execute_flash_steps(fb, steps)
    console.print("\n[bold green]Flash complete![/] Phone is rebooting.")


@flash.command("stock")
@click.option("--codename", help="Device codename")
@click.option("--region", default="RETIN", help="Firmware region (default: RETIN)")
def flash_stock(codename: str | None, region: str):
    """Download and flash stock firmware boot partitions."""
    from phonectl.firmware.sources import LolinetSource

    dm = _create_device_manager()
    info = _detect_device(dm)
    codename = codename or info.codename

    if not codename:
        console.print("[red]Cannot determine device codename.[/] Use --codename.")
        raise SystemExit(1)

    source = LolinetSource()
    console.print(f"[bold]Fetching firmware for {codename} ({region})...[/]")

    try:
        url = source.get_download_url(codename, region)
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/]")
        raise SystemExit(1)

    if not url:
        console.print("[red]No firmware found.[/]")
        try:
            regions = source.list_regions(codename)
            console.print(f"Available regions: {', '.join(regions)}")
        except Exception:
            pass
        raise SystemExit(1)

    console.print(f"[bold]Download URL:[/] {url}")
    console.print("Download and extract the firmware, then use:")
    console.print("  phonectl backup create --from-dir /path/to/extracted/firmware/")
    console.print("  phonectl backup restore /path/to/backup/")


# ═══════════════════════════════════════════════════════════════
# phonectl update
# ═══════════════════════════════════════════════════════════════

@cli.command()
@click.option("--version", "build_id", help="Target GSI build ID")
def update(build_id: str | None):
    """Update GSI security patch without data loss."""
    ctx = click.get_current_context()
    ctx.invoke(flash_gsi, build_id=build_id, no_wipe=True)


# ═══════════════════════════════════════════════════════════════
# phonectl recover
# ═══════════════════════════════════════════════════════════════

@cli.command()
@click.option("--backup-path", type=click.Path(exists=True), help="Backup directory with boot images")
@click.option("--codename", help="Device codename (for auto-finding backup)")
def recover(backup_path: str | None, codename: str | None):
    """Emergency recovery — restore boot partitions from backup."""
    bm = BackupManager()

    if not backup_path:
        if not codename:
            console.print("[yellow]Trying to detect device...[/]")
            try:
                dm = _create_device_manager()
                info = dm.detect()
                codename = info.codename
            except Exception:
                pass

        if codename:
            latest = bm.get_latest_backup(codename)
            if latest:
                backup_path = str(latest)
                console.print(f"[bold]Using latest backup:[/] {backup_path}")

    if not backup_path:
        console.print("[red]No backup found.[/] Specify --backup-path or --codename.")
        bm.show_backups()
        raise SystemExit(1)

    images = bm.get_backup_images(backup_path)
    if not images:
        console.print(f"[red]No boot images found in {backup_path}[/]")
        raise SystemExit(1)

    console.print(Panel(
        "\n".join(f"  {name}: {path}" for name, path in images.items()),
        title="[bold]Recovery Images[/]",
        border_style="yellow",
    ))

    guard = SafetyGuard()
    if not guard.confirm_destructive("Flash these boot images to recover the device?"):
        return

    fb = FastbootClient()
    if not fb.is_connected():
        console.print(
            "[red]Device not in fastboot.[/]\n"
            "Enter fastbootd manually:\n"
            "  1. Hold Power + Volume Down for 15 seconds\n"
            "  2. Navigate to Recovery → Reboot to fastbootd\n"
            "  3. Replug USB cable"
        )
        guard.wait_for_usb(timeout=120)
        if not fb.is_connected():
            raise SystemExit(1)

    for partition, img_path in images.items():
        console.print(f"[bold]Flashing {partition}...[/]")
        if partition == "vbmeta":
            fb.flash_vbmeta(img_path)
        else:
            fb.flash(partition, img_path, sparse_limit="")
        console.print(f"  [green]OK[/]")

    console.print("\n[green]Boot partitions restored.[/]")
    console.print("To complete recovery, flash a GSI system:")
    console.print("  phonectl flash gsi")


# ═══════════════════════════════════════════════════════════════
# phonectl firmware
# ═══════════════════════════════════════════════════════════════

@cli.group()
def firmware():
    """Manage firmware and GSI versions."""


@firmware.command("list")
def firmware_list():
    """List available GSI versions."""
    show_gsi_versions()


@firmware.command("download")
@click.argument("build_id")
def firmware_download(build_id: str):
    """Download a GSI version for offline use."""
    versions = load_gsi_versions()
    gsi = next((v for v in versions if v.build_id == build_id), None)
    if not gsi:
        console.print(f"[red]Unknown build ID: {build_id}[/]")
        show_gsi_versions()
        raise SystemExit(1)

    if not gsi.download_url:
        console.print(f"[red]No download URL for {gsi.name}[/]")
        raise SystemExit(1)

    download_gsi(gsi)


@firmware.command("regions")
@click.argument("codename")
def firmware_regions(codename: str):
    """List available firmware regions for a device (from lolinet)."""
    from phonectl.firmware.sources import LolinetSource

    source = LolinetSource()
    try:
        regions = source.list_regions(codename)
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/]")
        raise SystemExit(1)

    console.print(f"[bold]Available regions for {codename}:[/]")
    for r in regions:
        console.print(f"  {r}")


# ═══════════════════════════════════════════════════════════════
# phonectl tui (launches interactive mode)
# ═══════════════════════════════════════════════════════════════

@cli.command()
def tui():
    """Launch interactive TUI mode."""
    from phonectl.tui import run_tui
    run_tui()


# ═══════════════════════════════════════════════════════════════
# Flash step executor
# ═══════════════════════════════════════════════════════════════

def _execute_flash_steps(fb: FastbootClient, steps: list) -> None:
    """Execute an ordered list of FlashStep objects."""
    guard = SafetyGuard()
    total = len(steps)

    for i, step in enumerate(steps, 1):
        console.print(f"\n[bold][{i}/{total}][/] {step.description}")

        if not guard.monitor_usb_during_flash():
            if not guard.confirm_destructive("USB disconnected. Continue anyway?"):
                raise SystemExit(1)

        try:
            if step.step_type == FlashStepType.FLASH:
                fb.flash(
                    step.partition,
                    step.image_path,
                    sparse_limit=step.sparse_limit or None,
                    timeout=step.timeout,
                )
            elif step.step_type == FlashStepType.FLASH_VBMETA:
                fb.flash_vbmeta(step.image_path)
            elif step.step_type == FlashStepType.WIPE:
                fb.wipe()
            elif step.step_type == FlashStepType.REBOOT:
                fb.reboot()
            elif step.step_type == FlashStepType.SET_ACTIVE:
                fb.set_active(step.partition)
            elif step.step_type == FlashStepType.DELETE_PARTITION:
                fb.delete_logical_partition(step.partition)
            elif step.step_type == FlashStepType.CREATE_PARTITION:
                fb.create_logical_partition(step.partition, int(step.extra_args[0]))
            elif step.step_type == FlashStepType.WAIT:
                import time
                time.sleep(step.timeout)

            console.print(f"  [green]OK[/]")

        except (FastbootError, Exception) as exc:
            console.print(f"  [red]FAILED: {exc}[/]")
            if step.required:
                console.print("[red]Aborting flash sequence.[/]")
                raise SystemExit(1)
            console.print("[yellow]Non-critical step, continuing...[/]")
