"""Security audit and security guard commands."""

from __future__ import annotations

import click

from phonectl.commands._helpers import (
    console, create_device_manager, _detect_device, _show_device_panel,
)


@click.command()
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

    dm = create_device_manager()
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


@click.command()
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

    dm = create_device_manager()
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
