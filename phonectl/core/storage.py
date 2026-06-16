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

        # Delete temp files (*.log excluded — moved to deep tier)
        temp_patterns = ["*.tmp", "*.temp"]
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
        """Tier 2+3: Deep cleanup — includes safe cleanup plus log files and logcat."""
        results = self.cleanup_safe(dry_run=dry_run)

        # Delete log files (excluded from safe tier — could contain user-important data)
        if dry_run:
            results["actions"].append("Would delete /sdcard/**/*.log")
        else:
            try:
                self.adb.shell("find /sdcard -name '*.log' -type f -delete 2>/dev/null")
                results["actions"].append("Deleted /sdcard/**/*.log")
            except Exception:
                pass

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

    def _get_usage_stats(self) -> dict[str, dict]:
        """Parse dumpsys usagestats for last-used time and foreground duration."""
        import re, time
        stats: dict[str, dict] = {}
        now_ms = int(time.time() * 1000)

        try:
            output = self.adb.shell("dumpsys usagestats")
            current_pkg = ""

            for line in output.splitlines():
                pkg_match = re.search(r'package=(\S+)', line)
                if pkg_match:
                    current_pkg = pkg_match.group(1)
                    if current_pkg not in stats:
                        stats[current_pkg] = {"last_used_ms": 0, "foreground_ms": 0}

                if current_pkg:
                    time_match = re.search(r'lastTimeUsed="?(\d+)"?', line)
                    if time_match:
                        ts = int(time_match.group(1))
                        stats[current_pkg]["last_used_ms"] = max(stats[current_pkg]["last_used_ms"], ts)

                    fg_match = re.search(r'totalTimeInForeground="?(\d+)"?', line)
                    if fg_match:
                        stats[current_pkg]["foreground_ms"] += int(fg_match.group(1))

            for pkg, data in stats.items():
                last = data["last_used_ms"]
                if last > 0:
                    data["days_since_use"] = (now_ms - last) // (24 * 3600 * 1000)
                else:
                    data["days_since_use"] = 9999
                data["never_opened"] = data["foreground_ms"] == 0 and data["last_used_ms"] == 0
        except Exception:
            pass

        return stats

    def list_bloatware(self, vendor: str = "") -> list[dict]:
        """Detect installed bloatware with usage-based scoring."""
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

        usage = self._get_usage_stats()

        found = []
        for entry in bloatware_db:
            pkg = entry.get("pkg", "")
            if pkg not in installed_set:
                continue

            pkg_usage = usage.get(pkg, {})
            never_opened = pkg_usage.get("never_opened", True)
            days_since = pkg_usage.get("days_since_use", 9999)
            in_db = True

            score = (
                30 * (1 if never_opened else 0) +
                25 * (1 if days_since > 30 else 0) +
                min(20, int(20 * days_since / 365)) +
                10 * (1 if in_db else 0)
            )
            score = min(100, max(0, score))

            entry = dict(entry)
            entry["bloatware_score"] = score
            entry["days_since_use"] = days_since
            entry["never_opened"] = never_opened
            found.append(entry)

        found.sort(key=lambda e: e.get("bloatware_score", 0), reverse=True)
        return found

    def show_bloatware(self, vendor: str = "") -> None:
        """Display detected bloatware with usage-based scoring."""
        found = self.list_bloatware(vendor)
        if not found:
            console.print("[green]No known bloatware detected.[/]")
            return

        table = Table(title=f"Bloatware Analysis — Usage-Based Scoring ({len(found)} apps)")
        table.add_column("#", width=3)
        table.add_column("Package", style="cyan")
        table.add_column("Name")
        table.add_column("Score", width=5)
        table.add_column("Last Used")
        table.add_column("Action")

        for i, entry in enumerate(found, 1):
            score = entry.get("bloatware_score", 0)
            score_style = "green" if score < 40 else "yellow" if score < 70 else "red"

            days = entry.get("days_since_use", 9999)
            last_used = "Never" if entry.get("never_opened") else f"{days}d ago" if days < 9999 else "Unknown"

            action = "Safe to disable" if score >= 60 and entry.get("safe_to_disable") else "Review" if score >= 40 else "Keep"
            action_style = "green" if "Safe" in action else "yellow" if "Review" in action else "dim"

            table.add_row(
                str(i), entry["pkg"], entry.get("name", ""),
                f"[{score_style}]{score}[/]", last_used, f"[{action_style}]{action}[/]",
            )

        console.print(table)

    def disable_bloatware(self, vendor: str = "", dry_run: bool = False) -> list[str]:
        """Disable detected bloatware with SafetyGuard protection."""
        found = self.list_bloatware(vendor)
        safe_to_disable = [
            e for e in found
            if e.get("safe_to_disable", False) and e.get("bloatware_score", 0) >= 60
        ]

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
        """List installed user apps sorted by size (largest first)."""
        try:
            output = self.adb.shell("pm list packages -3")
            packages = [
                l.replace("package:", "").strip()
                for l in output.splitlines() if l.startswith("package:")
            ]
        except Exception:
            console.print("[red]Cannot list packages.[/]")
            return

        import re
        app_sizes: list[tuple[str, float]] = []
        for pkg in packages:
            size_kb = 0.0
            try:
                dumpsys = self.adb.shell(f"dumpsys package {pkg} | grep -i 'codePath\\|dataDir'")
                code_path = ""
                for line in dumpsys.splitlines():
                    if "codePath" in line:
                        code_path = line.split("=", 1)[-1].strip()
                        break
                if code_path:
                    du_out = self.adb.shell(f"du -sk {code_path} 2>/dev/null").strip()
                    match = re.match(r"(\d+)", du_out)
                    if match:
                        size_kb = float(match.group(1))
            except Exception:
                pass
            app_sizes.append((pkg, size_kb))

        app_sizes.sort(key=lambda x: x[1], reverse=True)

        table = Table(title=f"User Apps by Size ({len(app_sizes)})")
        table.add_column("#", width=4)
        table.add_column("Package", style="cyan")
        table.add_column("Size", justify="right", width=10)

        for i, (pkg, size_kb) in enumerate(app_sizes, 1):
            if size_kb >= 1024:
                size_str = f"{size_kb / 1024:.1f} MB"
            elif size_kb > 0:
                size_str = f"{size_kb:.0f} KB"
            else:
                size_str = "N/A"
            table.add_row(str(i), pkg, size_str)

        console.print(table)
