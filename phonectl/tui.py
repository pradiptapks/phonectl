"""Interactive TUI mode using Rich — guided workflows with visual feedback."""

from __future__ import annotations

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.prompt import Prompt, IntPrompt

from phonectl.core.backup import BackupManager
from phonectl.core.device import DeviceManager, DeviceState
from phonectl.core.safety import SafetyGuard
from phonectl.firmware.gsi import load_gsi_versions, show_gsi_versions
from phonectl.vendors.google import GooglePixelPlugin
from phonectl.vendors.motorola import MotorolaPlugin
from phonectl.vendors.samsung import SamsungPlugin

console = Console()

BANNER = r"""
        __                         __  __
  ___  / /  ___  ___  ___ ___  __ / /_/ /
 / _ \/ _ \/ _ \/ _ \/ -_) __/ __/ __/ /
 / .__/_//_/\___/_//_/\__/\__/\__/\__/_/
/_/
"""

WARRANTY_NOTICE = (
    "[bold yellow]WARNING:[/] This tool is for devices [bold]out of warranty[/] "
    "and/or no longer receiving OEM updates.\n"
    "Flashing or modifying partitions [bold red]will void your warranty[/] "
    "and may brick your device.\n"
    "[bold]Proceed at your own risk.[/]"
)


def _create_dm() -> DeviceManager:
    dm = DeviceManager()
    dm.register_vendor(MotorolaPlugin())
    dm.register_vendor(GooglePixelPlugin())
    dm.register_vendor(SamsungPlugin())
    return dm


def _device_status_panel(dm: DeviceManager) -> Panel:
    """Build a device info panel."""
    info = dm.detect()

    if info.state == DeviceState.DISCONNECTED:
        return Panel(
            "[red]No device connected.[/]\nConnect via USB and enable USB debugging.",
            title="[bold]Device Status[/]",
            border_style="red",
        )

    if info.state == DeviceState.UNAUTHORIZED:
        return Panel(
            f"[yellow]Device {info.serial} is unauthorized.[/]\nApprove USB debugging on your phone.",
            title="[bold]Device Status[/]",
            border_style="yellow",
        )

    vendor = dm.resolve_vendor(info)
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="cyan", width=20)
    table.add_column()

    rows = [
        ("Manufacturer", info.manufacturer),
        ("Model", info.model),
        ("Codename", info.codename),
        ("Serial", info.serial),
        ("State", info.state.value),
        ("Vendor Plugin", vendor.name if vendor else "Unknown"),
        ("Android", info.android_version),
        ("Security Patch", info.security_patch),
        ("Build ID", info.build_id),
        ("Kernel", info.kernel_version),
        ("VNDK", info.vndk_version),
        ("Slot", info.slot_suffix),
        ("Bootloader", "Unlocked" if info.is_unlocked else "Locked"),
        ("Battery", f"{info.battery_level}%" if info.battery_level else "N/A"),
    ]

    for label, value in rows:
        if value:
            table.add_row(label, value)

    return Panel(table, title="[bold green]Device Connected[/]", border_style="green")


def _main_menu() -> Panel:
    """Build the main menu panel."""
    menu = Table(show_header=False, box=None, padding=(0, 2))
    menu.add_column(style="bold cyan", width=4)
    menu.add_column()

    items = [
        ("1", "Device Info — Show connected device details"),
        ("2", "Diagnose — Smart diagnostics with prioritized action plan"),
        ("3", "Health Report — Comprehensive device health assessment"),
        ("4", "Security Audit — Warranty check, stalkerware scan, permissions"),
        ("5", "Security Guard — Network, lockscreen, app security + score"),
        ("6", "Performance Tune — Apply speed/battery/gaming profiles"),
        ("7", "Storage — Analyze storage, cleanup caches, manage bloatware"),
        ("8", "Flash GSI — Download and flash a Generic System Image"),
        ("9", "Backup / Restore — Manage boot partition backups"),
        ("r", "Reset — Factory reset, wipe data, or clear caches"),
        ("c", "Recover — Emergency recovery from boot loop"),
        ("f", "Firmware — List GSI versions or firmware regions"),
        ("0", "Exit"),
    ]

    for num, desc in items:
        menu.add_row(f"[{num}]", desc)

    return Panel(menu, title="[bold]Main Menu[/]", border_style="blue")


def _handle_info(dm: DeviceManager) -> None:
    console.print(_device_status_panel(dm))


def _handle_flash_gsi(dm: DeviceManager) -> None:
    info = dm.detect()
    if info.state == DeviceState.DISCONNECTED:
        console.print("[red]No device connected.[/]")
        return

    show_gsi_versions()
    versions = load_gsi_versions()

    if not versions:
        console.print("[red]No GSI versions available.[/]")
        return

    console.print("\nEnter the build ID to flash, or press Enter for auto-select:")
    build_id = Prompt.ask("Build ID", default="")

    no_wipe = Prompt.ask("Preserve user data? (no wipe)", choices=["y", "n"], default="n") == "y"

    from phonectl.cli import flash_gsi
    import click
    ctx = click.Context(flash_gsi)
    ctx.ensure_object(dict)
    with ctx:
        flash_gsi.invoke(ctx, build_id=build_id or None, no_wipe=no_wipe)


def _handle_update(dm: DeviceManager) -> None:
    info = dm.detect()
    if info.state == DeviceState.DISCONNECTED:
        console.print("[red]No device connected.[/]")
        return

    show_gsi_versions()
    build_id = Prompt.ask("Build ID to update to", default="")

    from phonectl.cli import flash_gsi
    import click
    ctx = click.Context(flash_gsi)
    with ctx:
        flash_gsi.invoke(ctx, build_id=build_id or None, no_wipe=True)


def _handle_backup(dm: DeviceManager) -> None:
    bm = BackupManager()

    console.print("\n[bold]Backup Options:[/]")
    console.print("  [1] Create backup from firmware directory")
    console.print("  [2] List existing backups")
    choice = Prompt.ask("Choice", choices=["1", "2"], default="2")

    if choice == "2":
        bm.show_backups()
        return

    info = dm.detect()
    codename = info.codename if info.state != DeviceState.DISCONNECTED else ""
    codename = Prompt.ask("Device codename", default=codename or "unknown")
    from_dir = Prompt.ask("Path to firmware directory with boot images")

    try:
        bm.backup_from_firmware(codename, from_dir)
    except Exception as exc:
        console.print(f"[red]Backup failed: {exc}[/]")


def _handle_restore(dm: DeviceManager) -> None:
    bm = BackupManager()
    bm.show_backups()

    backup_path = Prompt.ask("Enter backup path to restore")
    if not backup_path:
        return

    from phonectl.cli import backup_restore
    import click
    ctx = click.Context(backup_restore)
    with ctx:
        backup_restore.invoke(ctx, backup_path=backup_path)


def _handle_recover(dm: DeviceManager) -> None:
    bm = BackupManager()
    info = dm.detect()

    codename = ""
    if info.state != DeviceState.DISCONNECTED:
        codename = info.codename

    if codename:
        latest = bm.get_latest_backup(codename)
        if latest:
            console.print(f"[bold]Found backup for {codename}:[/] {latest}")
            use_latest = Prompt.ask("Use this backup?", choices=["y", "n"], default="y")
            if use_latest == "y":
                from phonectl.cli import recover
                import click
                ctx = click.Context(recover)
                with ctx:
                    recover.invoke(ctx, backup_path=str(latest), codename=codename)
                return

    console.print("[yellow]No automatic backup found.[/]")
    bm.show_backups()
    backup_path = Prompt.ask("Enter backup path (or leave empty to cancel)", default="")
    if backup_path:
        from phonectl.cli import recover
        import click
        ctx = click.Context(recover)
        with ctx:
            recover.invoke(ctx, backup_path=backup_path, codename=codename)


def _handle_firmware() -> None:
    show_gsi_versions()


def _handle_regions() -> None:
    from phonectl.firmware.sources import LolinetSource

    codename = Prompt.ask("Device codename (e.g., corfur)")
    source = LolinetSource()
    try:
        regions = source.list_regions(codename)
        console.print(f"\n[bold]Available regions for {codename}:[/]")
        for r in regions:
            console.print(f"  {r}")
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/]")


def _handle_diagnose(dm: DeviceManager) -> None:
    from phonectl.core.diagnose import DiagnosticEngine, display_diagnosis

    info = dm.detect()
    if info.state == DeviceState.DISCONNECTED:
        console.print("[red]No device connected.[/]")
        return
    adb = dm.get_adb()
    if not adb:
        return

    console.print("\n[bold]Running diagnostics...[/]\n")
    engine = DiagnosticEngine()
    report = engine.run(adb, info)
    display_diagnosis(report)


def _handle_report(dm: DeviceManager) -> None:
    from phonectl.core.report import ReportGenerator

    info = dm.detect()
    if info.state == DeviceState.DISCONNECTED:
        console.print("[red]No device connected.[/]")
        return
    adb = dm.get_adb()
    if not adb:
        return

    console.print("[bold]Generating health report...[/]\n")
    gen = ReportGenerator()
    report = gen.generate(adb, info)
    gen.render_text(report)

    export = Prompt.ask("Export report?", choices=["md", "json", "skip"], default="skip")
    if export != "skip":
        path = f"report_{info.serial or 'device'}.{export}"
        if export == "json":
            gen.render_json(report, path)
        else:
            gen.render_markdown(report, path)


def _handle_audit(dm: DeviceManager) -> None:
    from phonectl.core.audit import run_audit, display_audit_report

    info = dm.detect()
    if info.state == DeviceState.DISCONNECTED:
        console.print("[red]No device connected.[/]")
        return

    adb = dm.get_adb()
    if not adb:
        console.print("[red]ADB connection required for audit.[/]")
        return

    deep = Prompt.ask("Include root-level deep scan?", choices=["y", "n"], default="n") == "y"

    console.print("\n[bold]Running security audit...[/]\n")
    report = run_audit(adb, info, deep=deep)
    display_audit_report(report)


def _handle_security(dm: DeviceManager) -> None:
    from phonectl.core.security import SecurityGuard, display_security_report

    info = dm.detect()
    if info.state == DeviceState.DISCONNECTED:
        console.print("[red]No device connected.[/]")
        return
    adb = dm.get_adb()
    if not adb:
        return

    guard = SecurityGuard(adb)
    report = guard.run_all()
    display_security_report(report)

    if report.fixable_checks:
        fix = Prompt.ask("Apply security fixes?", choices=["y", "n"], default="n")
        if fix == "y":
            guard.harden()


def _handle_tune(dm: DeviceManager) -> None:
    from phonectl.core.tune import TuneEngine

    info = dm.detect()
    if info.state == DeviceState.DISCONNECTED:
        console.print("[red]No device connected.[/]")
        return
    adb = dm.get_adb()
    if not adb:
        return

    engine = TuneEngine(adb)
    engine.show_status()

    choice = Prompt.ask(
        "\nApply profile?",
        choices=["fast", "balanced", "battery", "gaming", "compile", "reset", "skip"],
        default="skip",
    )
    if choice == "skip":
        return
    elif choice == "compile":
        engine.compile_apps()
    elif choice == "reset":
        engine.reset_to_defaults()
    else:
        engine.apply_profile(choice)


def _handle_storage(dm: DeviceManager) -> None:
    from phonectl.core.storage import StorageAnalyzer

    info = dm.detect()
    if info.state == DeviceState.DISCONNECTED:
        console.print("[red]No device connected.[/]")
        return
    adb = dm.get_adb()
    if not adb:
        return

    analyzer = StorageAnalyzer(adb)
    analyzer.show_storage()

    console.print("\n[bold]Options:[/]")
    console.print("  [1] Safe cleanup (caches, temps, APKs)")
    console.print("  [2] Deep cleanup")
    console.print("  [3] List bloatware")
    console.print("  [4] Disable bloatware")
    console.print("  [5] Re-enable disabled apps")
    console.print("  [6] List user apps")
    console.print("  [0] Back")

    choice = Prompt.ask("Choice", default="0")
    if choice == "1":
        results = analyzer.cleanup_safe()
        for a in results["actions"]:
            console.print(f"  {a}")
    elif choice == "2":
        results = analyzer.cleanup_deep()
        for a in results["actions"]:
            console.print(f"  {a}")
    elif choice == "3":
        analyzer.show_bloatware(info.manufacturer.lower())
    elif choice == "4":
        analyzer.disable_bloatware(info.manufacturer.lower())
    elif choice == "5":
        analyzer.enable_disabled()
    elif choice == "6":
        analyzer.list_apps_by_size()


def _handle_reset_menu(dm: DeviceManager) -> None:
    from phonectl.core.reset import ResetManager

    info = dm.detect()
    adb = dm.get_adb()
    fb = dm.get_fastboot()
    manager = ResetManager(adb=adb, fastboot=fb)
    manager.show_options()

    choice = Prompt.ask("Choose option", choices=["factory", "wipe-data", "clear-cache", "app", "cancel"], default="cancel")
    if choice == "factory":
        manager.factory_reset()
    elif choice == "wipe-data":
        manager.wipe_data()
    elif choice == "clear-cache":
        manager.clear_all_caches()
    elif choice == "app":
        pkg = Prompt.ask("Package name")
        if pkg:
            manager.clear_app_data(pkg)


def _handle_backup_menu(dm: DeviceManager) -> None:
    from phonectl.core.backup import BackupManager
    bm = BackupManager()

    console.print("\n[bold]Backup Options:[/]")
    console.print("  [1] Create backup from firmware directory")
    console.print("  [2] List existing backups")
    console.print("  [3] Back")
    choice = Prompt.ask("Choice", choices=["1", "2", "3"], default="2")

    if choice == "2":
        bm.show_backups()
    elif choice == "1":
        info = dm.detect()
        codename = info.codename if info.state != DeviceState.DISCONNECTED else "unknown"
        codename = Prompt.ask("Device codename", default=codename)
        from_dir = Prompt.ask("Path to firmware directory")
        try:
            bm.backup_from_firmware(codename, from_dir)
        except Exception as exc:
            console.print(f"[red]Failed: {exc}[/]")


def run_tui() -> None:
    """Main TUI entry point — interactive menu loop."""
    dm = _create_dm()

    console.print(Text(BANNER, style="bold cyan"))
    console.print("[bold]Universal Android Phone Lifecycle Manager[/]\n")
    console.print(Panel(WARRANTY_NOTICE, border_style="yellow", title="[bold]Warranty Notice[/]"))
    console.print()

    handlers = {
        "1": lambda: _handle_info(dm),
        "2": lambda: _handle_diagnose(dm),
        "3": lambda: _handle_report(dm),
        "4": lambda: _handle_audit(dm),
        "5": lambda: _handle_security(dm),
        "6": lambda: _handle_tune(dm),
        "7": lambda: _handle_storage(dm),
        "8": lambda: _handle_flash_gsi(dm),
        "9": lambda: _handle_backup_menu(dm),
        "r": lambda: _handle_reset_menu(dm),
        "c": lambda: _handle_recover(dm),
        "f": _handle_firmware,
    }

    while True:
        console.print()
        console.print(_main_menu())

        try:
            choice = Prompt.ask("\n[bold]Select option[/]", default="0")
        except (KeyboardInterrupt, EOFError):
            break

        if choice == "0":
            console.print("[dim]Goodbye.[/]")
            break

        handler = handlers.get(choice)
        if handler:
            try:
                handler()
            except SystemExit:
                pass
            except Exception as exc:
                console.print(f"[red]Error: {exc}[/]")
        else:
            console.print("[yellow]Invalid option.[/]")
