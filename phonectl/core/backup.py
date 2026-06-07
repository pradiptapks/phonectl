"""BackupManager — backup and restore boot partition images.

Supports:
- Backing up boot partitions from stock firmware downloads
- Restoring boot partitions to recover from boot loops
- Managing backup archives per device codename
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from phonectl.core.device import DeviceInfo

console = Console()

DEFAULT_BACKUP_DIR = Path.home() / ".phonectl" / "backups"
BOOT_PARTITIONS = ["boot.img", "vendor_boot.img", "dtbo.img", "vbmeta.img"]


class BackupError(Exception):
    pass


class BackupManager:
    """Manages boot partition backups for Android devices."""

    def __init__(self, backup_dir: str | Path = DEFAULT_BACKUP_DIR):
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def _device_dir(self, codename: str) -> Path:
        d = self.backup_dir / codename
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _timestamp_dir(self, codename: str) -> Path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        d = self._device_dir(codename) / ts
        d.mkdir(parents=True, exist_ok=True)
        return d

    def backup_from_firmware(
        self,
        codename: str,
        firmware_dir: str | Path,
        info: DeviceInfo | None = None,
        gsi_vbmeta: str | Path | None = None,
    ) -> Path:
        """Backup boot images extracted from a firmware zip.

        Args:
            gsi_vbmeta: Optional path to GSI vbmeta.img. If provided, stored as
                        vbmeta_gsi.img alongside the stock vbmeta (vbmeta_stock.img).
                        This ensures recovery can select the correct vbmeta based
                        on whether the device is running GSI or stock.
        """
        firmware_path = Path(firmware_dir)
        if not firmware_path.exists():
            raise BackupError(f"Firmware directory not found: {firmware_path}")

        backup_path = self._timestamp_dir(codename)

        copied = []
        for img_name in BOOT_PARTITIONS:
            src = firmware_path / img_name
            if src.exists():
                if img_name == "vbmeta.img":
                    shutil.copy2(src, backup_path / "vbmeta_stock.img")
                    shutil.copy2(src, backup_path / "vbmeta.img")
                    copied.append("vbmeta_stock.img")
                else:
                    shutil.copy2(src, backup_path / img_name)
                copied.append(img_name)

        if not copied:
            raise BackupError(
                f"No boot images found in {firmware_path}. "
                f"Expected: {', '.join(BOOT_PARTITIONS)}"
            )

        # Store GSI vbmeta if provided
        has_gsi_vbmeta = False
        if gsi_vbmeta:
            gsi_vbmeta_path = Path(gsi_vbmeta)
            if gsi_vbmeta_path.exists():
                shutil.copy2(gsi_vbmeta_path, backup_path / "vbmeta_gsi.img")
                copied.append("vbmeta_gsi.img")
                has_gsi_vbmeta = True
                console.print(f"[green]GSI vbmeta stored:[/] vbmeta_gsi.img")
        else:
            for candidate in [
                Path.home() / ".phonectl" / "gsi_cache" / "vbmeta.img",
                Path("/tmp/gsi_flash/vbmeta.img"),
                Path("/tmp/phonectl_gsi/vbmeta.img"),
            ]:
                if candidate.exists():
                    shutil.copy2(candidate, backup_path / "vbmeta_gsi.img")
                    copied.append("vbmeta_gsi.img")
                    has_gsi_vbmeta = True
                    console.print(f"[green]GSI vbmeta auto-detected:[/] {candidate}")
                    break

        metadata = {
            "codename": codename,
            "timestamp": datetime.now().isoformat(),
            "images": copied,
            "source": str(firmware_path),
            "has_gsi_vbmeta": has_gsi_vbmeta,
        }
        if info:
            metadata["build_id"] = info.build_id
            metadata["vendor_fingerprint"] = info.extra.get("vendor_fingerprint", "")

        meta_file = backup_path / "metadata.json"
        meta_file.write_text(json.dumps(metadata, indent=2))

        # Update "latest" symlink
        latest = self._device_dir(codename) / "latest"
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        latest.symlink_to(backup_path.name)

        console.print(f"[green]Backup saved:[/] {backup_path}")
        console.print(f"  Images: {', '.join(copied)}")
        return backup_path

    def backup_from_files(
        self, codename: str, image_files: dict[str, str | Path]
    ) -> Path:
        """Backup individual image files by path."""
        backup_path = self._timestamp_dir(codename)
        copied = []

        for name, src_path in image_files.items():
            src = Path(src_path)
            if not src.exists():
                console.print(f"[yellow]Warning: {src} not found, skipping[/]")
                continue
            dest_name = name if name.endswith(".img") else f"{name}.img"
            shutil.copy2(src, backup_path / dest_name)
            copied.append(dest_name)

        if not copied:
            raise BackupError("No valid image files provided.")

        metadata = {
            "codename": codename,
            "timestamp": datetime.now().isoformat(),
            "images": copied,
            "source": "manual",
        }
        (backup_path / "metadata.json").write_text(json.dumps(metadata, indent=2))

        latest = self._device_dir(codename) / "latest"
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        latest.symlink_to(backup_path.name)

        console.print(f"[green]Backup saved:[/] {backup_path}")
        return backup_path

    def get_latest_backup(self, codename: str) -> Path | None:
        """Get the latest backup directory for a device."""
        latest = self._device_dir(codename) / "latest"
        if latest.is_symlink() or latest.exists():
            target = latest.resolve()
            if target.exists():
                return target
        return None

    def get_backup_images(self, backup_path: str | Path) -> dict[str, Path]:
        """Get a mapping of partition name → image path from a backup."""
        bp = Path(backup_path)
        images = {}
        for img in bp.glob("*.img"):
            partition = img.stem
            images[partition] = img
        return images

    def list_backups(self, codename: str | None = None) -> list[dict]:
        """List all backups, optionally filtered by codename."""
        backups = []
        search_dirs = [self._device_dir(codename)] if codename else self.backup_dir.iterdir()

        for device_dir in search_dirs:
            if not device_dir.is_dir() or device_dir.name.startswith("."):
                continue
            for backup_dir in sorted(device_dir.iterdir(), reverse=True):
                if not backup_dir.is_dir() or backup_dir.name == "latest":
                    continue
                meta_file = backup_dir / "metadata.json"
                if meta_file.exists():
                    meta = json.loads(meta_file.read_text())
                    meta["path"] = str(backup_dir)
                    backups.append(meta)
                else:
                    images = list(backup_dir.glob("*.img"))
                    backups.append({
                        "codename": device_dir.name,
                        "timestamp": backup_dir.name,
                        "images": [i.name for i in images],
                        "path": str(backup_dir),
                    })
        return backups

    def show_backups(self, codename: str | None = None) -> None:
        """Print a formatted table of backups."""
        backups = self.list_backups(codename)
        if not backups:
            console.print("[yellow]No backups found.[/]")
            return

        table = Table(title="Boot Partition Backups")
        table.add_column("Device", style="cyan")
        table.add_column("Timestamp", style="green")
        table.add_column("Images")
        table.add_column("Path", style="dim")

        for b in backups:
            table.add_row(
                b.get("codename", "?"),
                b.get("timestamp", "?"),
                ", ".join(b.get("images", [])),
                b.get("path", ""),
            )
        console.print(table)
