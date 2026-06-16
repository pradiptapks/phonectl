"""Device info, compatibility check, and recommend commands."""

from __future__ import annotations

import click

from phonectl.commands._helpers import (
    console, create_device_manager, _detect_device, _show_device_panel,
)
from phonectl.core.safety import SafetyGuard


@click.command()
def info():
    """Show connected device information."""
    dm = create_device_manager()
    device_info = _detect_device(dm)
    vendor = dm.resolve_vendor(device_info)
    _show_device_panel(device_info, vendor.name if vendor else "Unknown")

    if vendor:
        quirks = vendor.get_usb_quirks()
        if quirks.get("description"):
            console.print(f"\n[dim]Vendor note: {quirks['description']}[/]")


@click.command()
@click.option("--version", "build_id", default=None,
              help="GSI build ID to check compatibility against (omit to check all)")
def check(build_id: str | None):
    """Run hardware/firmware compatibility checks and show GSI recommendations."""
    from phonectl.firmware.gsi import show_recommendations, evaluate_all_versions

    dm = create_device_manager()
    device_info = _detect_device(dm)
    vendor = dm.resolve_vendor(device_info)

    _show_device_panel(device_info, vendor.name if vendor else "Unknown")

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

    _show_staleness_hint()


@click.command()
def recommend():
    """Scan device hardware/firmware and recommend compatible GSI versions."""
    from phonectl.firmware.gsi import show_recommendations

    dm = create_device_manager()
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

    _show_staleness_hint()


def _show_staleness_hint():
    """Show a hint if the GSI version cache is missing or expired."""
    try:
        from phonectl.firmware.compat_fetcher import CompatFetcher
        if CompatFetcher().is_stale():
            console.print(
                "\n[dim]Hint: run [bold]phonectl update-gsi-db[/bold] "
                "to check for newer GSI versions[/]"
            )
    except Exception:
        pass
