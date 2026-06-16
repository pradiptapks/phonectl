"""Firmware management commands."""

from __future__ import annotations

import click

from phonectl.commands._helpers import console
from phonectl.firmware.gsi import download_gsi, load_gsi_versions, show_gsi_versions


@click.group()
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


@click.command("update-gsi-db")
def update_gsi_db():
    """Fetch latest GSI versions from Google and update local cache."""
    from phonectl.firmware.compat_fetcher import CompatFetcher

    fetcher = CompatFetcher()

    cached = fetcher.load_cached()
    if cached:
        console.print(f"[dim]Current cache: {len(cached)} versions[/]")
    else:
        console.print("[dim]No valid cache — fetching fresh data[/]")

    console.print(f"[bold]Fetching from:[/] {fetcher.meta_path.parent / 'releases'}")
    entries = fetcher.fetch()

    if not entries:
        console.print("[red]No versions fetched. Static config will be used.[/]")
        raise SystemExit(1)

    console.print(f"[green]Cached {len(entries)} GSI versions to:[/] {fetcher.cache_path}")

    # Show what was found
    new_ids = set()
    if cached:
        old_ids = {e["build_id"] for e in cached}
        new_ids = {e["build_id"] for e in entries} - old_ids

    for entry in entries:
        marker = "[green]NEW[/] " if entry["build_id"] in new_ids else "     "
        status_style = "green" if entry["status"] == "stable" else "yellow"
        console.print(
            f"  {marker}[{status_style}]{entry['status']:6}[/] "
            f"{entry['build_id']:24} {entry['name']}"
        )
