"""Storage analysis, cleanup, and bloatware commands."""

from __future__ import annotations

import click

from phonectl.commands._helpers import (
    console, create_device_manager, _detect_device,
)
from phonectl.core.safety import SafetyGuard


@click.group()
def storage():
    """Storage analysis, cleanup, and bloatware management."""


@storage.command("show")
def storage_show():
    """Show storage breakdown."""
    from phonectl.core.storage import StorageAnalyzer

    dm = create_device_manager()
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

    dm = create_device_manager()
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

    dm = create_device_manager()
    info = _detect_device(dm)
    adb = dm.get_adb()
    if not adb:
        raise SystemExit(1)
    resolved = dm.resolve_vendor(info)
    v = vendor or (resolved.bloatware_key if resolved else info.manufacturer.lower())
    StorageAnalyzer(adb).show_bloatware(v)


@bloatware.command("disable")
@click.option("--vendor", default="", help="Filter by vendor")
@click.option("--dry-run", is_flag=True, help="Preview without disabling")
def bloatware_disable(vendor: str, dry_run: bool):
    """Disable detected bloatware (SafetyGuard protected)."""
    from phonectl.core.storage import StorageAnalyzer

    dm = create_device_manager()
    info = _detect_device(dm)
    adb = dm.get_adb()
    if not adb:
        raise SystemExit(1)

    guard = SafetyGuard()
    if not dry_run:
        if not guard.confirm_destructive("Disable bloatware apps? They can be re-enabled later."):
            return

    resolved = dm.resolve_vendor(info)
    v = vendor or (resolved.bloatware_key if resolved else info.manufacturer.lower())
    StorageAnalyzer(adb).disable_bloatware(v, dry_run=dry_run)


@bloatware.command("enable")
def bloatware_enable():
    """Re-enable previously disabled bloatware."""
    from phonectl.core.storage import StorageAnalyzer

    dm = create_device_manager()
    _detect_device(dm)
    adb = dm.get_adb()
    if not adb:
        raise SystemExit(1)
    StorageAnalyzer(adb).enable_disabled()


@storage.command("apps")
def storage_apps():
    """List installed user apps."""
    from phonectl.core.storage import StorageAnalyzer

    dm = create_device_manager()
    _detect_device(dm)
    adb = dm.get_adb()
    if not adb:
        raise SystemExit(1)
    StorageAnalyzer(adb).list_apps_by_size()
