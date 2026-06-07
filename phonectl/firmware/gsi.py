"""GSI version management, compatibility checking, and download orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from rich.console import Console
from rich.table import Table

from phonectl.firmware.downloader import download_file

console = Console()


@dataclass
class GSIVersion:
    name: str
    build_id: str
    security_patch: str
    status: str
    download_url: str
    sha256: str
    min_vndk: int = 30
    notes: str = ""


def load_gsi_versions(config_path: str | Path | None = None) -> list[GSIVersion]:
    """Load known GSI versions from the YAML config."""
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config" / "gsi_versions.yaml"

    config_path = Path(config_path)
    if not config_path.exists():
        return _builtin_versions()

    with open(config_path) as f:
        data = yaml.safe_load(f)

    versions = []
    for v in data.get("versions", []):
        versions.append(GSIVersion(**v))
    return versions


def _builtin_versions() -> list[GSIVersion]:
    """Fallback hardcoded list if config file is missing."""
    return [
        GSIVersion(
            name="Android 16 (Baklava)",
            build_id="BP2A.250605.031.A3",
            security_patch="2025-06-05",
            status="stable",
            download_url=(
                "https://dl.google.com/developers/android/baklava/images/gsi/"
                "gsi_gms_arm64-exp-BP2A.250605.031.A3-13578795-38e52cb0.zip"
            ),
            sha256="38e52cb0a3331a5ee0c653a4da2401ce74598a955acbd00aa85b6326036154c5",
            min_vndk=30,
            notes="Confirmed working on Moto G71 5G (corfur) with VNDK 30",
        ),
    ]


def show_gsi_versions(config_path: str | Path | None = None) -> None:
    """Print a formatted table of available GSI versions."""
    versions = load_gsi_versions(config_path)

    table = Table(title="Available GSI Versions")
    table.add_column("Name", style="cyan")
    table.add_column("Build ID", style="green")
    table.add_column("Security Patch")
    table.add_column("Status")
    table.add_column("Min VNDK")
    table.add_column("Notes", style="dim")

    for v in versions:
        status_style = "green" if v.status == "stable" else "yellow"
        table.add_row(
            v.name,
            v.build_id,
            v.security_patch,
            f"[{status_style}]{v.status}[/]",
            str(v.min_vndk),
            v.notes,
        )
    console.print(table)


def download_gsi(
    version: GSIVersion,
    dest_dir: str | Path = "/tmp/phonectl_gsi",
) -> Path:
    """Download a GSI zip and extract the system image."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    zip_path = dest_dir / f"gsi_{version.build_id}.zip"
    if zip_path.exists():
        console.print(f"[yellow]Using cached download:[/] {zip_path}")
    else:
        console.print(f"[bold]Downloading GSI:[/] {version.name} ({version.build_id})")
        download_file(version.download_url, zip_path, expected_sha256=version.sha256)

    # Extract system.img and vbmeta.img
    import zipfile
    with zipfile.ZipFile(zip_path) as zf:
        for name in ["system.img", "vbmeta.img"]:
            if name in zf.namelist():
                target = dest_dir / name
                if not target.exists():
                    console.print(f"Extracting {name}...")
                    zf.extract(name, dest_dir)

    system_img = dest_dir / "system.img"
    if not system_img.exists():
        raise FileNotFoundError(f"system.img not found in {zip_path}")

    console.print(f"[green]GSI ready:[/] {system_img}")
    return dest_dir


def find_compatible_version(
    vndk_version: str,
    config_path: str | Path | None = None,
) -> GSIVersion | None:
    """Find the best compatible GSI version for a given VNDK version."""
    versions = load_gsi_versions(config_path)
    vndk = int(vndk_version) if vndk_version.isdigit() else 0

    compatible = [
        v for v in versions
        if v.status == "stable" and vndk >= v.min_vndk
    ]

    return compatible[-1] if compatible else None
