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
    if info.slot_count:
        table.add_row("A/B Slots", info.slot_count)
    if info.cpu_abi:
        table.add_row("CPU ABI", info.cpu_abi)
    if info.board_platform:
        table.add_row("Platform", info.board_platform)
    if info.ram_total_mb:
        table.add_row("RAM", f"{info.ram_total_mb} MB")
    if info.storage_total_gb:
        table.add_row("Storage", f"{info.storage_total_gb} GB total, {info.storage_free_gb} GB free")
    if info.opengl_version:
        try:
            gl_int = int(info.opengl_version)
            table.add_row("OpenGL ES", f"{(gl_int >> 16) & 0xFFFF}.{gl_int & 0xFFFF}")
        except ValueError:
            table.add_row("OpenGL ES", info.opengl_version)
    if info.first_api_level:
        table.add_row("First API Level", info.first_api_level)
    if info.vendor_security_patch:
        table.add_row("Vendor Patch", info.vendor_security_patch)
    if info.battery_level:
        table.add_row("Battery", f"{info.battery_level}%")
    if info.uptime:
        table.add_row("Uptime", info.uptime)

    console.print(Panel(table, title="[bold]Device Info[/]", border_style="green"))


# ═══════════════════════════════════════════════════════════════
# CLI Group
# ═══════════════════════════════════════════════════════════════

WARRANTY_NOTICE = (
    "[bold yellow]WARNING:[/] This tool is intended for devices that are "
    "[bold]out of warranty[/] and/or no longer receiving official OEM updates. "
    "Flashing GSI or modifying boot partitions [bold red]will void your warranty[/] "
    "and may brick your device if used incorrectly. "
    "[bold]Proceed at your own risk.[/]"
)


@click.group()
@click.version_option(package_name="phonectl")
def cli():
    """phonectl — Universal Android Phone Lifecycle Manager.

    \b
    WARNING: This tool is intended for devices that are OUT OF WARRANTY
    and/or no longer receiving official OEM updates. Flashing GSI or
    modifying boot partitions WILL VOID YOUR WARRANTY and may brick
    your device if used incorrectly. Proceed at your own risk.
    """
    console.print(f"\n{WARRANTY_NOTICE}\n", highlight=False)


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
# phonectl check
# ═══════════════════════════════════════════════════════════════

@cli.command()
@click.option("--version", "build_id", default=None,
              help="GSI build ID to check compatibility against (omit to check all)")
def check(build_id: str | None):
    """Run hardware/firmware compatibility checks and show GSI recommendations."""
    from phonectl.firmware.gsi import show_recommendations, evaluate_all_versions

    dm = _create_device_manager()
    device_info = _detect_device(dm)
    vendor = dm.resolve_vendor(device_info)

    _show_device_panel(device_info, vendor.name if vendor else "Unknown")

    # If a specific version is given, run detailed checks against it
    if build_id:
        guard = SafetyGuard()
        report = guard.pre_flash_check(device_info, build_id)

        console.print(f"\n[bold]Compatibility Report for GSI {build_id}:[/]\n")
        console.print(report.summary())

        passed = sum(1 for c in report.checks if c["passed"])
        total = len(report.checks)

        if report.passed:
            console.print(f"\n[bold green]All {total} checks passed.[/] Device is ready for GSI flash.")
        else:
            failed = total - passed
            console.print(f"\n[bold yellow]{passed}/{total} checks passed, {failed} failed.[/]")
            console.print("[yellow]Fix the failed checks before flashing, or proceed at your own risk.[/]")

        console.print()

    # Always show the full recommendation table
    console.print("[bold]GSI Version Recommendations Based on Your Hardware/Firmware:[/]\n")
    results = show_recommendations(device_info)

    recommended = [r for r in results if r.verdict == "recommended"]
    if recommended:
        best = recommended[0]
        console.print(
            f"\nTo run detailed checks for the recommended version:\n"
            f"  [bold]phonectl check --version {best.version.build_id}[/]\n"
            f"To flash it:\n"
            f"  [bold]phonectl flash gsi --version {best.version.build_id}[/]"
        )
    else:
        compatible = [r for r in results if r.verdict == "compatible"]
        if compatible:
            console.print(
                "\n[yellow]No strongly recommended version. "
                "Check compatible options above.[/]"
            )
        else:
            console.print(
                "\n[red]No compatible GSI found for this device.[/]\n"
                "The hardware or firmware does not meet minimum requirements."
            )


# ═══════════════════════════════════════════════════════════════
# phonectl recommend
# ═══════════════════════════════════════════════════════════════

@cli.command()
def recommend():
    """Scan device hardware/firmware and recommend compatible GSI versions."""
    from phonectl.firmware.gsi import show_recommendations

    dm = _create_device_manager()
    device_info = _detect_device(dm)
    vendor = dm.resolve_vendor(device_info)

    _show_device_panel(device_info, vendor.name if vendor else "Unknown")
    console.print()

    results = show_recommendations(device_info)

    recommended = [r for r in results if r.verdict == "recommended"]
    if recommended:
        best = recommended[0]
        console.print(
            f"\nTo flash the recommended version:\n"
            f"  [bold]phonectl flash gsi --version {best.version.build_id}[/]"
        )
    else:
        compatible = [r for r in results if r.verdict == "compatible"]
        if compatible:
            console.print(
                "\n[yellow]No strongly recommended version, but compatible options exist.[/]"
            )
        else:
            console.print(
                "\n[red]No compatible GSI versions found for this device.[/]"
            )


# ═══════════════════════════════════════════════════════════════
# phonectl audit
# ═══════════════════════════════════════════════════════════════

@cli.command()
@click.option("--deep", is_flag=True, help="Include root-level deep scan (requires rooted device)")
@click.option("--export", "export_format", type=click.Choice(["json", "md"]),
              help="Export report to file (json or md)")
@click.option("--output", "output_path", type=click.Path(),
              help="Output file path for export (default: audit_<serial>.<ext>)")
def audit(deep: bool, export_format: str | None, output_path: str | None):
    """Run security audit and warranty estimation on connected device."""
    from phonectl.core.audit import (
        run_audit,
        display_audit_report,
        export_audit_json,
        export_audit_markdown,
    )

    dm = _create_device_manager()
    device_info = _detect_device(dm)
    vendor = dm.resolve_vendor(device_info)

    _show_device_panel(device_info, vendor.name if vendor else "Unknown")

    adb = dm.get_adb()
    if not adb:
        console.print("[red]ADB connection required for audit.[/]")
        raise SystemExit(1)

    console.print("\n[bold]Running security audit...[/]\n")

    report = run_audit(adb, device_info, deep=deep)
    display_audit_report(report)

    if export_format:
        serial = device_info.serial or "device"
        if not output_path:
            ext = "json" if export_format == "json" else "md"
            output_path = f"audit_{serial}.{ext}"
        if export_format == "json":
            export_audit_json(report, output_path)
        else:
            export_audit_markdown(report, output_path)


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

    # Find GSI version — use recommendation engine
    from phonectl.firmware.gsi import evaluate_all_versions

    versions = load_gsi_versions()
    gsi = None

    if build_id:
        gsi = next((v for v in versions if v.build_id == build_id), None)
        if not gsi:
            console.print(f"[red]Unknown GSI build ID: {build_id}[/]")
            show_gsi_versions()
            raise SystemExit(1)

        # Check if the selected version is compatible
        recommendations = evaluate_all_versions(info)
        rec = next((r for r in recommendations if r.version.build_id == build_id), None)
        if rec and rec.verdict in ("incompatible", "broken"):
            console.print(f"\n[bold red]WARNING: {gsi.name} ({build_id}) is {rec.verdict.upper()} with your device![/]")
            for reason in rec.reasons:
                console.print(f"  [red]- {reason}[/]")
            recommended = [r for r in recommendations if r.verdict == "recommended"]
            if recommended:
                best = recommended[0]
                console.print(
                    f"\n[green]Recommended instead:[/] {best.version.name} "
                    f"({best.version.build_id}, patch {best.version.security_patch})"
                )
            guard = SafetyGuard()
            if not guard.confirm_destructive("Flash this INCOMPATIBLE version anyway? HIGH RISK OF BRICK."):
                raise SystemExit(1)
    else:
        # Auto-select: use recommendation engine to find the best version
        recommendations = evaluate_all_versions(info)
        recommended = [r for r in recommendations if r.verdict == "recommended"]
        compatible = [r for r in recommendations if r.verdict == "compatible"]

        if recommended:
            gsi = recommended[0].version
            console.print(
                f"[bold green]Recommended:[/] {gsi.name} ({gsi.build_id}) "
                f"— score {recommended[0].score}/100"
            )
            for reason in recommended[0].reasons[:3]:
                console.print(f"  [dim]{reason}[/]")
        elif compatible:
            gsi = compatible[0].version
            console.print(
                f"[yellow]No strongly recommended version. Using best compatible:[/] "
                f"{gsi.name} ({gsi.build_id})"
            )
        else:
            console.print("[red]No compatible GSI version found for this device.[/]")
            console.print("Run [bold]phonectl recommend[/] to see why.")
            raise SystemExit(1)

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

    # Reboot to fastbootd (skip if already in fastbootd)
    if info.state == DeviceState.FASTBOOTD:
        console.print("[dim]Already in fastbootd — skipping reboot.[/]")
    elif info.state == DeviceState.ANDROID:
        adb = dm.get_adb()
        if adb:
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

    # Save flash state
    from phonectl.core.state import StateManager, FlashState
    sm = StateManager()
    sm.save_flash_state(FlashState(
        serial=info.serial,
        codename=info.codename,
        system_type="gsi",
        gsi_build_id=gsi.build_id,
        vbmeta_type="gsi",
        vbmeta_path=vbmeta_img,
        system_path=system_img,
        boot_source="",
        slot=info.slot_suffix.replace("_", "") if info.slot_suffix else "a",
    ))

    console.print("\n[bold green]Flash complete![/] Phone is rebooting.")

    # Boot verification
    from phonectl.core.verify import BootVerifier
    verifier = BootVerifier()
    verifier.verify(serial=info.serial, timeout=300)


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
@click.option("--no-system", is_flag=True, help="Skip system flash (boot partitions only)")
@click.option("--no-verify", is_flag=True, help="Skip post-flash boot verification")
def recover(backup_path: str | None, codename: str | None, no_system: bool, no_verify: bool):
    """Smart recovery — restore boot partitions with correct vbmeta selection."""
    from phonectl.core.state import StateManager

    bm = BackupManager()
    sm = StateManager()

    # Detect device and find backup
    serial = None
    if not backup_path:
        if not codename:
            try:
                dm = _create_device_manager()
                info = dm.detect()
                codename = info.codename
                serial = info.serial
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

    # Smart vbmeta selection based on flash state
    state = sm.load_flash_state(serial) if serial else sm.get_latest_state()
    vbmeta_type = "stock"
    backup_dir = Path(backup_path)

    if state and state.system_type == "gsi":
        gsi_vbmeta = backup_dir / "vbmeta_gsi.img"
        if gsi_vbmeta.exists():
            images["vbmeta"] = gsi_vbmeta
            vbmeta_type = "gsi"
            console.print("[bold cyan]Smart recovery:[/] Using GSI vbmeta (device was running GSI)")
        else:
            console.print("[yellow]Warning: GSI vbmeta not in backup. Using stock vbmeta.[/]")
            console.print("[yellow]If boot fails, the stock vbmeta may be incompatible with GSI system.[/]")
    elif "vbmeta_stock" in images:
        images["vbmeta"] = images.pop("vbmeta_stock")
        console.print("[dim]Using stock vbmeta (no GSI state found)[/]")

    # Remove internal backup names from flash list
    images.pop("vbmeta_stock", None)
    images.pop("vbmeta_gsi", None)

    console.print(Panel(
        "\n".join(f"  {name}: {path}" for name, path in images.items())
        + f"\n  vbmeta type: {vbmeta_type}",
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

    # Flash boot partitions
    for partition, img_path in images.items():
        console.print(f"[bold]Flashing {partition}...[/]")
        if partition == "vbmeta":
            if vbmeta_type == "gsi":
                fb.flash_vbmeta(img_path)
            else:
                fb.flash_vbmeta(img_path, disable_verity=False, disable_verification=False)
        else:
            fb.flash(partition, img_path, sparse_limit="")
        console.print(f"  [green]OK[/]")

    # Auto-flash system from GSI cache if available
    if not no_system and state and state.system_type == "gsi":
        from phonectl.firmware.gsi import GSI_CACHE_DIR
        system_candidates = [
            GSI_CACHE_DIR / state.gsi_build_id / "system.img",
            Path(state.system_path) if state.system_path else None,
        ]
        system_img = None
        for candidate in system_candidates:
            if candidate and candidate.exists():
                system_img = candidate
                break

        if system_img:
            console.print(f"\n[bold]Auto-flashing GSI system:[/] {system_img.name}")
            fb.flash("system", system_img, sparse_limit="128M", timeout=900)
            console.print(f"  [green]OK[/]")
            fb.wipe()
            console.print(f"  [green]Data wiped[/]")
        else:
            console.print(
                "\n[yellow]GSI system image not cached.[/] Run after reboot:\n"
                "  [bold]phonectl flash gsi[/]"
            )

    # Reboot and verify
    console.print("\n[bold]Rebooting...[/]")
    fb.reboot()

    if not no_verify:
        from phonectl.core.verify import BootVerifier
        verifier = BootVerifier()
        verifier.verify(serial=serial, timeout=300)


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
# phonectl diagnose
# ═══════════════════════════════════════════════════════════════

@cli.command()
def diagnose():
    """Smart diagnostics — analyze device health and generate action plan."""
    from phonectl.core.diagnose import DiagnosticEngine, display_diagnosis

    dm = _create_device_manager()
    device_info = _detect_device(dm)
    adb = dm.get_adb()
    if not adb:
        console.print("[red]ADB connection required.[/]")
        raise SystemExit(1)

    vendor = dm.resolve_vendor(device_info)
    _show_device_panel(device_info, vendor.name if vendor else "Unknown")

    console.print("\n[bold]Running diagnostics...[/]\n")
    engine = DiagnosticEngine()
    report = engine.run(adb, device_info)
    display_diagnosis(report)


# ═══════════════════════════════════════════════════════════════
# phonectl report
# ═══════════════════════════════════════════════════════════════

@cli.command()
@click.option("--export", "export_format", type=click.Choice(["md", "json"]),
              help="Export report to file")
@click.option("--output", "output_path", type=click.Path(),
              help="Output file path")
def report(export_format: str | None, output_path: str | None):
    """Generate comprehensive device health report."""
    from phonectl.core.report import ReportGenerator

    dm = _create_device_manager()
    device_info = _detect_device(dm)
    adb = dm.get_adb()
    if not adb:
        console.print("[red]ADB connection required.[/]")
        raise SystemExit(1)

    console.print("[bold]Generating health report...[/]\n")
    gen = ReportGenerator()
    health_report = gen.generate(adb, device_info)

    if export_format:
        serial = device_info.serial or "device"
        if not output_path:
            ext = "json" if export_format == "json" else "md"
            output_path = f"report_{serial}.{ext}"
        if export_format == "json":
            gen.render_json(health_report, output_path)
        else:
            gen.render_markdown(health_report, output_path)
    else:
        gen.render_text(health_report)


# ═══════════════════════════════════════════════════════════════
# phonectl tune
# ═══════════════════════════════════════════════════════════════

@cli.command()
@click.option("--profile", type=click.Choice(["fast", "balanced", "battery", "gaming"]),
              help="Apply a performance profile")
@click.option("--compile", "do_compile", is_flag=True, help="Force ART compilation for faster app launches")
@click.option("--reset", "do_reset", is_flag=True, help="Reset tuning to defaults")
def tune(profile: str | None, do_compile: bool, do_reset: bool):
    """Performance tuning — apply speed/battery/gaming profiles."""
    from phonectl.core.tune import TuneEngine

    dm = _create_device_manager()
    device_info = _detect_device(dm)
    adb = dm.get_adb()
    if not adb:
        console.print("[red]ADB connection required.[/]")
        raise SystemExit(1)

    engine = TuneEngine(adb)

    if do_reset:
        engine.reset_to_defaults()
    elif do_compile:
        engine.compile_apps()
    elif profile:
        engine.apply_profile(profile)
    else:
        engine.show_status()


# ═══════════════════════════════════════════════════════════════
# phonectl reset
# ═══════════════════════════════════════════════════════════════

@cli.command(name="reset")
@click.option("--factory", "do_factory", is_flag=True, help="Full factory reset via recovery")
@click.option("--wipe-data", "do_wipe", is_flag=True, help="Wipe userdata via fastboot")
@click.option("--clear-cache", "do_cache", is_flag=True, help="Clear all app caches (safe)")
@click.option("--app", "app_pkg", help="Clear data for a specific app package")
def reset_cmd(do_factory: bool, do_wipe: bool, do_cache: bool, app_pkg: str | None):
    """Factory reset and data management."""
    from phonectl.core.reset import ResetManager

    dm = _create_device_manager()
    adb = dm.get_adb()
    fb = dm.get_fastboot()
    manager = ResetManager(adb=adb, fastboot=fb)

    if do_factory:
        manager.factory_reset()
    elif do_wipe:
        manager.wipe_data()
    elif do_cache:
        manager.clear_all_caches()
    elif app_pkg:
        manager.clear_app_data(app_pkg)
    else:
        manager.show_options()


# ═══════════════════════════════════════════════════════════════
# phonectl storage
# ═══════════════════════════════════════════════════════════════

@cli.group()
def storage():
    """Storage analysis, cleanup, and bloatware management."""


@storage.command("show")
def storage_show():
    """Show storage breakdown."""
    from phonectl.core.storage import StorageAnalyzer

    dm = _create_device_manager()
    _detect_device(dm)
    adb = dm.get_adb()
    if not adb:
        raise SystemExit(1)
    StorageAnalyzer(adb).show_storage()


@storage.command("cleanup")
@click.option("--deep", is_flag=True, help="Deep cleanup (includes browser data, logs)")
@click.option("--dry-run", is_flag=True, help="Preview without acting")
def storage_cleanup(deep: bool, dry_run: bool):
    """Clean up caches, temp files, and leftover APKs."""
    from phonectl.core.storage import StorageAnalyzer

    dm = _create_device_manager()
    _detect_device(dm)
    adb = dm.get_adb()
    if not adb:
        raise SystemExit(1)

    analyzer = StorageAnalyzer(adb)
    if dry_run:
        console.print("[bold]Dry run — no changes will be made:[/]\n")

    if deep:
        results = analyzer.cleanup_deep(dry_run=dry_run)
    else:
        results = analyzer.cleanup_safe(dry_run=dry_run)

    for action in results["actions"]:
        console.print(f"  {action}")

    if not dry_run:
        console.print(f"\n[green]Cleanup complete.[/]")


@storage.group()
def bloatware():
    """Detect and manage pre-installed bloatware."""


@bloatware.command("list")
@click.option("--vendor", default="", help="Filter by vendor (motorola, samsung, etc.)")
def bloatware_list(vendor: str):
    """List detected bloatware apps."""
    from phonectl.core.storage import StorageAnalyzer

    dm = _create_device_manager()
    info = _detect_device(dm)
    adb = dm.get_adb()
    if not adb:
        raise SystemExit(1)
    v = vendor or info.manufacturer.lower()
    StorageAnalyzer(adb).show_bloatware(v)


@bloatware.command("disable")
@click.option("--vendor", default="", help="Filter by vendor")
@click.option("--dry-run", is_flag=True, help="Preview without disabling")
def bloatware_disable(vendor: str, dry_run: bool):
    """Disable detected bloatware (SafetyGuard protected)."""
    from phonectl.core.storage import StorageAnalyzer

    dm = _create_device_manager()
    info = _detect_device(dm)
    adb = dm.get_adb()
    if not adb:
        raise SystemExit(1)

    guard = SafetyGuard()
    if not dry_run:
        if not guard.confirm_destructive("Disable bloatware apps? They can be re-enabled later."):
            return

    v = vendor or info.manufacturer.lower()
    StorageAnalyzer(adb).disable_bloatware(v, dry_run=dry_run)


@bloatware.command("enable")
def bloatware_enable():
    """Re-enable previously disabled bloatware."""
    from phonectl.core.storage import StorageAnalyzer

    dm = _create_device_manager()
    _detect_device(dm)
    adb = dm.get_adb()
    if not adb:
        raise SystemExit(1)
    StorageAnalyzer(adb).enable_disabled()


@storage.command("apps")
def storage_apps():
    """List installed user apps."""
    from phonectl.core.storage import StorageAnalyzer

    dm = _create_device_manager()
    _detect_device(dm)
    adb = dm.get_adb()
    if not adb:
        raise SystemExit(1)
    StorageAnalyzer(adb).list_apps_by_size()


# ═══════════════════════════════════════════════════════════════
# phonectl security
# ═══════════════════════════════════════════════════════════════

@cli.command()
@click.option("--network", "cat_network", is_flag=True, help="Network security checks only")
@click.option("--lockscreen", "cat_lock", is_flag=True, help="Lock screen checks only")
@click.option("--apps", "cat_apps", is_flag=True, help="App security checks only")
@click.option("--score", "show_score", is_flag=True, help="Output security score only (0-100)")
@click.option("--harden", is_flag=True, help="Apply recommended security fixes")
@click.option("--dry-run", is_flag=True, help="Preview hardening without applying")
def security(cat_network: bool, cat_lock: bool, cat_apps: bool,
             show_score: bool, harden: bool, dry_run: bool):
    """Network and phone security assessment with optional hardening."""
    from phonectl.core.security import SecurityGuard, display_security_report

    dm = _create_device_manager()
    _detect_device(dm)
    adb = dm.get_adb()
    if not adb:
        console.print("[red]ADB connection required.[/]")
        raise SystemExit(1)

    guard = SecurityGuard(adb)

    if harden:
        console.print("[bold]Security Hardening:[/]\n")
        guard.harden(dry_run=dry_run)
        return

    categories = None
    if cat_network or cat_lock or cat_apps:
        categories = []
        if cat_network:
            categories.append("network")
        if cat_lock:
            categories.append("lockscreen")
        if cat_apps:
            categories.append("apps")

    report = guard.run_all(categories=categories)

    if show_score:
        click.echo(report.score)
        return

    display_security_report(report)


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
