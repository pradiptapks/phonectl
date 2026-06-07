"""Storage analysis, cleanup, and bloatware management with SafetyGuard protection."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

if TYPE_CHECKING:
    from phonectl.core.adb import ADBClient

console = Console()

DISABLED_APPS_LOG = Path.home() / ".phonectl" / "disabled_apps.json"
PROTECTED_APPS_PATH = Path(__file__).parent.parent / "config" / "protected_apps.yaml"
BLOATWARE_PATH = Path(__file__).parent.parent / "config" / "bloatware.yaml"


@dataclass
class StorageInfo:
    total_gb: float = 0.0
    used_gb: float = 0.0
    free_gb: float = 0.0
    cache_mb: float = 0.0
    apps_count: int = 0
    system_apps: int = 0
    user_apps: int = 0


@dataclass
class AppInfo:
    package: str
    name: str = ""
    size_mb: float = 0.0
    cache_mb: float = 0.0
    is_system: bool = False
    is_disabled: bool = False


def _load_protected_apps() -> set[str]:
    if PROTECTED_APPS_PATH.exists():
        with open(PROTECTED_APPS_PATH) as f:
            data = yaml.safe_load(f) or {}
        return set(data.get("protected", []))
    return {
        "com.android.systemui", "com.android.settings", "com.android.phone",
        "com.android.providers.contacts", "com.android.providers.media",
        "com.android.providers.telephony", "com.android.launcher3",
        "com.android.inputmethod.latin", "com.google.android.gms",
        "com.google.android.gsf", "com.android.vending",
        "com.android.bluetooth", "com.android.nfc",
    }


def _load_bloatware(vendor: str = "") -> list[dict]:
    if BLOATWARE_PATH.exists():
        with open(BLOATWARE_PATH) as f:
            data = yaml.safe_load(f) or {}
        if vendor:
            return data.get(vendor.lower(), []) + data.get("common", [])
        result = []
        for v_list in data.values():
            if isinstance(v_list, list):
                result.extend(v_list)
        return result
    return []


def _load_disabled_log() -> list[str]:
    if DISABLED_APPS_LOG.exists():
        return json.loads(DISABLED_APPS_LOG.read_text())
    return []


def _save_disabled_log(packages: list[str]) -> None:
    DISABLED_APPS_LOG.parent.mkdir(parents=True, exist_ok=True)
    DISABLED_APPS_LOG.write_text(json.dumps(packages, indent=2))


class StorageAnalyzer:
    """Analyze storage usage and manage cleanup operations."""

    def __init__(self, adb: ADBClient):
        self.adb = adb
        self.protected = _load_protected_apps()

    def get_storage_info(self) -> StorageInfo:
        """Get overall storage statistics."""
        info = StorageInfo()
        try:
            df_output = self.adb.shell("df /data")
            for line in df_output.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 4:
                    info.total_gb = round(int(parts[1]) / 1048576, 1)
                    info.used_gb = round(int(parts[2]) / 1048576, 1)
                    info.free_gb = round(int(parts[3]) / 1048576, 1)
                    break
        except Exception:
            pass

        try:
            system_pkgs = self.adb.shell("pm list packages -s")
            info.system_apps = system_pkgs.count("package:")
            all_pkgs = self.adb.shell("pm list packages")
            info.apps_count = all_pkgs.count("package:")
            info.user_apps = info.apps_count - info.system_apps
        except Exception:
            pass

        return info

    def show_storage(self) -> None:
        """Display storage breakdown."""
        info = self.get_storage_info()
        used_pct = round((info.used_gb / info.total_gb) * 100, 1) if info.total_gb else 0

        table = Table(title="Storage Overview", show_header=False, box=None, padding=(0, 2))
        table.add_column(style="cyan", width=20)
        table.add_column()

        table.add_row("Total", f"{info.total_gb} GB")
        bar_width = 30
        filled = int(bar_width * used_pct / 100)
        bar = "[red]" + "=" * filled + "[/][dim]" + "-" * (bar_width - filled) + "[/]"
        table.add_row("Used", f"{info.used_gb} GB ({used_pct}%)  {bar}")
        table.add_row("Free", f"{info.free_gb} GB")
        table.add_row("Total apps", str(info.apps_count))
        table.add_row("System apps", str(info.system_apps))
        table.add_row("User apps", str(info.user_apps))

        console.print(Panel(table, border_style="cyan"))

    def cleanup_safe(self, dry_run: bool = False) -> dict:
        """Tier 1: Safe cleanup — caches, temps, APKs."""
        results = {"freed_mb": 0, "actions": []}

        # Clear all app caches
        if dry_run:
            results["actions"].append("Would clear all app caches (pm trim-caches)")
        else:
            try:
                self.adb.shell("pm trim-caches 999G")
                results["actions"].append("Cleared all app caches")
            except Exception as exc:
                results["actions"].append(f"Cache clear failed: {exc}")

        # Delete thumbnails
        thumb_cmds = [
            ("rm -rf /sdcard/.thumbnails", "Thumbnails (.thumbnails)"),
            ("rm -rf /sdcard/DCIM/.thumbnails", "DCIM thumbnails"),
        ]
        for cmd, desc in thumb_cmds:
            if dry_run:
                results["actions"].append(f"Would delete: {desc}")
            else:
                try:
                    self.adb.shell(cmd)
                    results["actions"].append(f"Deleted: {desc}")
                except Exception:
                    pass

        # Delete temp files
        temp_patterns = ["*.tmp", "*.temp", "*.log"]
        for pattern in temp_patterns:
            if dry_run:
                results["actions"].append(f"Would delete /sdcard/**/{pattern}")
            else:
                try:
                    self.adb.shell(f"find /sdcard -name '{pattern}' -type f -delete 2>/dev/null")
                    results["actions"].append(f"Deleted /sdcard/**/{pattern}")
                except Exception:
                    pass

        # Delete downloaded APKs
        if dry_run:
            try:
                apk_list = self.adb.shell("find /sdcard -name '*.apk' -type f 2>/dev/null")
                count = len([l for l in apk_list.splitlines() if l.strip()])
                results["actions"].append(f"Would delete {count} APK files from /sdcard")
            except Exception:
                pass
        else:
            try:
                self.adb.shell("find /sdcard -name '*.apk' -type f -delete 2>/dev/null")
                results["actions"].append("Deleted leftover APK files")
            except Exception:
                pass

        # Delete empty directories
        if dry_run:
            results["actions"].append("Would remove empty directories in /sdcard")
        else:
            try:
                self.adb.shell("find /sdcard -empty -type d -delete 2>/dev/null")
                results["actions"].append("Removed empty directories")
            except Exception:
                pass

        return results

    def cleanup_deep(self, dry_run: bool = False) -> dict:
        """Tier 2+3: Deep cleanup — includes safe cleanup plus browser data and logs."""
        results = self.cleanup_safe(dry_run=dry_run)

        # Clear logcat buffer
        if dry_run:
            results["actions"].append("Would clear system log buffer")
        else:
            try:
                self.adb.shell("logcat -c")
                results["actions"].append("Cleared system log buffer")
            except Exception:
                pass

        return results

    def list_bloatware(self, vendor: str = "") -> list[dict]:
        """Detect installed bloatware based on vendor database."""
        bloatware_db = _load_bloatware(vendor)
        if not bloatware_db:
            return []

        try:
            installed = self.adb.shell("pm list packages")
            installed_set = set(
                l.replace("package:", "").strip()
                for l in installed.splitlines() if l.startswith("package:")
            )
        except Exception:
            return []

        found = []
        for entry in bloatware_db:
            pkg = entry.get("pkg", "")
            if pkg in installed_set:
                found.append(entry)
        return found

    def show_bloatware(self, vendor: str = "") -> None:
        """Display detected bloatware."""
        found = self.list_bloatware(vendor)
        if not found:
            console.print("[green]No known bloatware detected.[/]")
            return

        table = Table(title=f"Detected Bloatware ({len(found)} apps)")
        table.add_column("Package", style="cyan")
        table.add_column("Name")
        table.add_column("Safe to Disable")

        for entry in found:
            safe = "[green]Yes[/]" if entry.get("safe_to_disable", False) else "[red]No[/]"
            table.add_row(entry["pkg"], entry.get("name", ""), safe)

        console.print(table)

    def disable_bloatware(self, vendor: str = "", dry_run: bool = False) -> list[str]:
        """Disable detected bloatware with SafetyGuard protection."""
        found = self.list_bloatware(vendor)
        safe_to_disable = [e for e in found if e.get("safe_to_disable", False)]

        if not safe_to_disable:
            console.print("[green]No safely-disablable bloatware found.[/]")
            return []

        # Check against protected apps
        safe_to_disable = [
            e for e in safe_to_disable if e["pkg"] not in self.protected
        ]

        # Check default apps
        try:
            default_launcher = self.adb.shell(
                "cmd shortcut get-default-launcher 2>/dev/null || "
                "dumpsys package resolveActivity --brief -a android.intent.action.MAIN -c android.intent.category.HOME 2>/dev/null"
            )
        except Exception:
            default_launcher = ""

        console.print(f"[bold]Disabling {len(safe_to_disable)} bloatware apps:[/]")
        disabled = _load_disabled_log()
        newly_disabled = []

        for entry in safe_to_disable:
            pkg = entry["pkg"]
            name = entry.get("name", pkg)

            if pkg in default_launcher:
                console.print(f"  [yellow]SKIP[/] {name} ({pkg}) — is default launcher")
                continue

            if dry_run:
                console.print(f"  [dim]WOULD DISABLE[/] {name} ({pkg})")
                continue

            try:
                self.adb.shell(f"pm disable-user --user 0 {pkg}")
                console.print(f"  [green]DISABLED[/] {name} ({pkg})")
                newly_disabled.append(pkg)
            except Exception as exc:
                console.print(f"  [red]FAILED[/] {name} ({pkg}): {exc}")

        if newly_disabled:
            disabled.extend(newly_disabled)
            _save_disabled_log(disabled)
            console.print(f"\n[green]{len(newly_disabled)} apps disabled.[/]")
            console.print(f"[dim]Undo log: {DISABLED_APPS_LOG}[/]")

        return newly_disabled

    def enable_disabled(self) -> list[str]:
        """Re-enable previously disabled bloatware."""
        disabled = _load_disabled_log()
        if not disabled:
            console.print("[green]No previously disabled apps to re-enable.[/]")
            return []

        console.print(f"[bold]Re-enabling {len(disabled)} previously disabled apps:[/]")
        enabled = []

        for pkg in disabled:
            try:
                self.adb.shell(f"pm enable {pkg}")
                console.print(f"  [green]ENABLED[/] {pkg}")
                enabled.append(pkg)
            except Exception as exc:
                console.print(f"  [red]FAILED[/] {pkg}: {exc}")

        remaining = [p for p in disabled if p not in enabled]
        _save_disabled_log(remaining)
        console.print(f"\n[green]{len(enabled)} apps re-enabled.[/]")
        return enabled

    def list_apps_by_size(self) -> None:
        """List installed apps sorted by estimated size."""
        try:
            output = self.adb.shell("pm list packages -3")
            packages = [
                l.replace("package:", "").strip()
                for l in output.splitlines() if l.startswith("package:")
            ]
        except Exception:
            console.print("[red]Cannot list packages.[/]")
            return

        table = Table(title=f"User Apps ({len(packages)})")
        table.add_column("#", width=4)
        table.add_column("Package", style="cyan")

        for i, pkg in enumerate(sorted(packages), 1):
            table.add_row(str(i), pkg)

        console.print(table)
