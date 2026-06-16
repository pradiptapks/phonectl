"""Flash, update, and recover commands."""

from __future__ import annotations

from pathlib import Path

import click
from rich.panel import Panel

from phonectl.commands._helpers import (
    console, create_device_manager, _detect_device, _show_device_panel,
)
from phonectl.core.backup import BackupManager
from phonectl.core.device import DeviceState
from phonectl.core.fastboot import FastbootClient, FastbootError
from phonectl.core.safety import SafetyGuard
from phonectl.firmware.gsi import download_gsi, load_gsi_versions, show_gsi_versions
from phonectl.vendors.base import FlashStepType


@click.group()
def flash():
    """Flash GSI or stock firmware."""


@flash.command("gsi")
@click.option("--version", "build_id", help="GSI build ID (e.g., BP2A.250605.031.A3)")
@click.option("--no-wipe", is_flag=True, help="Skip data wipe (same major version update)")
def flash_gsi(build_id: str | None, no_wipe: bool):
    """Download and flash a GSI image."""
    dm = create_device_manager()
    info = _detect_device(dm)
    vendor = dm.resolve_vendor(info)

    _show_device_panel(info, vendor.name if vendor else "Unknown")

    from phonectl.firmware.gsi import evaluate_all_versions

    versions = load_gsi_versions()
    gsi = None

    if build_id:
        gsi = next((v for v in versions if v.build_id == build_id), None)
        if not gsi:
            console.print(f"[red]Unknown GSI build ID: {build_id}[/]")
            show_gsi_versions()
            raise SystemExit(1)

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

    if not vendor or not vendor.supports_flash:
        vendor_name = vendor.name if vendor else "Unknown"
        quirks = vendor.get_usb_quirks() if vendor else {}
        console.print(f"[red]{vendor_name} flash is not yet supported by phonectl.[/]")
        if quirks.get("uses_odin"):
            console.print("[yellow]Samsung devices require Odin/Heimdall for flashing.[/]")
            console.print("[yellow]Enter download mode (Power + Vol Down + USB) and use Odin.[/]")
        elif quirks.get("description"):
            console.print(f"[dim]{quirks['description']}[/]")
        raise SystemExit(1)

    gsi_dir = download_gsi(gsi)
    system_img = str(gsi_dir / "system.img")
    vbmeta_img = str(gsi_dir / "vbmeta.img")

    quirks = vendor.get_usb_quirks()
    use_fastbootd = quirks.get("use_fastbootd", quirks.get("use_fastbootd_not_fastboot", True))

    if info.state == DeviceState.FASTBOOTD:
        console.print("[dim]Already in fastbootd — skipping reboot.[/]")
    elif info.state == DeviceState.ANDROID:
        adb = dm.get_adb()
        if adb:
            if use_fastbootd:
                console.print("[bold]Rebooting to fastbootd...[/]")
                adb.reboot_fastboot()
            else:
                console.print("[bold]Rebooting to bootloader (fastboot)...[/]")
                adb.reboot_bootloader()
            if quirks.get("requires_replug_after_mode_switch"):
                console.print("[yellow]Replug USB cable now if device is not detected.[/]")
            import time
            time.sleep(15)

    fb = FastbootClient()
    if not fb.is_connected():
        console.print("[yellow]Waiting for fastboot connection...[/]")
        guard.wait_for_usb(timeout=60)
        if not fb.is_connected():
            console.print("[red]Device not in fastboot. Enter fastbootd manually.[/]")
            raise SystemExit(1)

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

    from phonectl.core.verify import BootVerifier
    verifier = BootVerifier()
    verifier.verify(serial=info.serial, timeout=300)


@flash.command("stock")
@click.option("--codename", help="Device codename")
@click.option("--region", default="RETIN", help="Firmware region (default: RETIN)")
def flash_stock(codename: str | None, region: str):
    """Download and flash stock firmware boot partitions."""
    from phonectl.firmware.sources import LolinetSource

    dm = create_device_manager()
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


@click.command()
@click.option("--version", "build_id", help="Target GSI build ID")
def update(build_id: str | None):
    """Update GSI security patch without data loss."""
    ctx = click.get_current_context()
    ctx.invoke(flash_gsi, build_id=build_id, no_wipe=True)


@click.command()
@click.option("--backup-path", type=click.Path(exists=True), help="Backup directory with boot images")
@click.option("--codename", help="Device codename (for auto-finding backup)")
@click.option("--no-system", is_flag=True, help="Skip system flash (boot partitions only)")
@click.option("--no-verify", is_flag=True, help="Skip post-flash boot verification")
def recover(backup_path: str | None, codename: str | None, no_system: bool, no_verify: bool):
    """Smart recovery — restore boot partitions with correct vbmeta selection."""
    from phonectl.core.state import StateManager

    bm = BackupManager()
    sm = StateManager()

    serial = None
    if not backup_path:
        if not codename:
            try:
                dm = create_device_manager()
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

    console.print("\n[bold]Rebooting...[/]")
    fb.reboot()

    if not no_verify:
        from phonectl.core.verify import BootVerifier
        verifier = BootVerifier()
        verifier.verify(serial=serial, timeout=300)


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
