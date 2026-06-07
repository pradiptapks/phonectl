"""Performance tuning engine — apply profiles to optimize phone speed, battery, or gaming."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from phonectl.core.adb import ADBClient

console = Console()

BACKUP_FILE = Path.home() / ".phonectl" / "tune_backup.json"

SETTING_COMMANDS = {
    "window_animation_scale": ("settings get global window_animation_scale", "settings put global window_animation_scale {}"),
    "transition_animation_scale": ("settings get global transition_animation_scale", "settings put global transition_animation_scale {}"),
    "animator_duration_scale": ("settings get global animator_duration_scale", "settings put global animator_duration_scale {}"),
    "force_gpu_rendering": ("settings get global force_gpu_rendering", "settings put global force_gpu_rendering {}"),
    "always_finish_activities": ("settings get global always_finish_activities", "settings put global always_finish_activities {}"),
}

DEFAULT_PROFILES = {
    "fast": {
        "window_animation_scale": "0",
        "transition_animation_scale": "0",
        "animator_duration_scale": "0",
        "force_gpu_rendering": "1",
        "always_finish_activities": "0",
        "description": "Maximum speed — animations off, GPU forced. Best for older/slow phones.",
    },
    "balanced": {
        "window_animation_scale": "0.5",
        "transition_animation_scale": "0.5",
        "animator_duration_scale": "0.5",
        "force_gpu_rendering": "0",
        "always_finish_activities": "0",
        "description": "Balanced — reduced animations, auto GPU. Good for daily use.",
    },
    "battery": {
        "window_animation_scale": "0.5",
        "transition_animation_scale": "0.5",
        "animator_duration_scale": "0.5",
        "force_gpu_rendering": "0",
        "always_finish_activities": "1",
        "description": "Battery saver — reduced animations, aggressive background cleanup.",
    },
    "gaming": {
        "window_animation_scale": "0",
        "transition_animation_scale": "0",
        "animator_duration_scale": "0",
        "force_gpu_rendering": "1",
        "always_finish_activities": "1",
        "description": "Gaming — animations off, GPU forced, background apps killed.",
    },
}

ANDROID_DEFAULTS = {
    "window_animation_scale": "1.0",
    "transition_animation_scale": "1.0",
    "animator_duration_scale": "1.0",
    "force_gpu_rendering": "0",
    "always_finish_activities": "0",
}


@dataclass
class TuneStatus:
    current_values: dict[str, str]
    active_profile: str


class TuneEngine:
    """Apply and manage performance tuning profiles."""

    def __init__(self, adb: ADBClient, config_path: str | Path | None = None):
        self.adb = adb
        self.profiles = self._load_profiles(config_path)

    def _load_profiles(self, config_path: str | Path | None) -> dict:
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config" / "profiles.yaml"
        path = Path(config_path)
        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f) or {}
            return data.get("profiles", DEFAULT_PROFILES)
        return DEFAULT_PROFILES

    def get_current(self) -> TuneStatus:
        """Read current tuning values from device."""
        values = {}
        for key, (get_cmd, _) in SETTING_COMMANDS.items():
            try:
                val = self.adb.shell(get_cmd).strip()
                values[key] = val if val and val != "null" else ANDROID_DEFAULTS.get(key, "")
            except Exception:
                values[key] = ANDROID_DEFAULTS.get(key, "unknown")

        active = self._detect_profile(values)
        return TuneStatus(current_values=values, active_profile=active)

    def _detect_profile(self, values: dict[str, str]) -> str:
        """Detect which profile matches the current settings."""
        for name, profile in self.profiles.items():
            match = True
            for key in SETTING_COMMANDS:
                if key in profile and str(profile.get(key, "")) != str(values.get(key, "")):
                    match = False
                    break
            if match:
                return name
        if all(values.get(k) == v for k, v in ANDROID_DEFAULTS.items()):
            return "default (Android stock)"
        return "custom"

    def show_status(self) -> None:
        """Display current tuning status."""
        status = self.get_current()

        table = Table(title="Current Performance Settings")
        table.add_column("Setting", style="cyan")
        table.add_column("Value", style="green")
        table.add_column("Default")

        for key, val in status.current_values.items():
            default = ANDROID_DEFAULTS.get(key, "?")
            style = "" if val == default else "bold yellow"
            table.add_row(key, f"[{style}]{val}[/]" if style else val, default)

        console.print(table)
        console.print(f"\n[bold]Active profile:[/] {status.active_profile}")

        console.print("\n[bold]Available profiles:[/]")
        for name, profile in self.profiles.items():
            desc = profile.get("description", "")
            console.print(f"  [cyan]{name:12s}[/] {desc}")

    def apply_profile(self, profile_name: str) -> bool:
        """Apply a performance profile."""
        if profile_name not in self.profiles:
            console.print(f"[red]Unknown profile: {profile_name}[/]")
            console.print(f"Available: {', '.join(self.profiles.keys())}")
            return False

        profile = self.profiles[profile_name]
        self._backup_current()

        console.print(f"[bold]Applying profile: {profile_name}[/]")
        desc = profile.get("description", "")
        if desc:
            console.print(f"  [dim]{desc}[/]")

        for key, (_, set_cmd) in SETTING_COMMANDS.items():
            if key in profile:
                val = str(profile[key])
                try:
                    self.adb.shell(set_cmd.format(val))
                    console.print(f"  [green]SET[/] {key} = {val}")
                except Exception as exc:
                    console.print(f"  [red]FAIL[/] {key}: {exc}")

        console.print(f"\n[green]Profile '{profile_name}' applied.[/]")
        return True

    def reset_to_defaults(self) -> None:
        """Reset all settings to Android defaults, or restore from backup."""
        if BACKUP_FILE.exists():
            with open(BACKUP_FILE) as f:
                backup = json.loads(f.read())
            console.print("[bold]Restoring original settings from backup...[/]")
            source = backup
        else:
            console.print("[bold]Resetting to Android defaults...[/]")
            source = ANDROID_DEFAULTS

        for key, (_, set_cmd) in SETTING_COMMANDS.items():
            val = source.get(key, ANDROID_DEFAULTS.get(key, "1.0"))
            try:
                self.adb.shell(set_cmd.format(val))
                console.print(f"  [green]SET[/] {key} = {val}")
            except Exception as exc:
                console.print(f"  [red]FAIL[/] {key}: {exc}")

        console.print("[green]Settings restored.[/]")

    def compile_apps(self) -> None:
        """Force ART compilation for faster app launches."""
        console.print("[bold]Compiling apps (speed-profile)...[/]")
        console.print("[dim]This may take several minutes.[/]")
        try:
            result = self.adb.shell("cmd package compile -m speed-profile -a", timeout=600)
            console.print(f"[green]Compilation complete.[/]")
        except Exception as exc:
            console.print(f"[red]Compilation failed: {exc}[/]")

    def _backup_current(self) -> None:
        """Save current values before applying changes."""
        BACKUP_FILE.parent.mkdir(parents=True, exist_ok=True)
        if BACKUP_FILE.exists():
            return
        values = {}
        for key, (get_cmd, _) in SETTING_COMMANDS.items():
            try:
                val = self.adb.shell(get_cmd).strip()
                values[key] = val if val and val != "null" else ANDROID_DEFAULTS.get(key, "")
            except Exception:
                values[key] = ANDROID_DEFAULTS.get(key, "")
        BACKUP_FILE.write_text(json.dumps(values, indent=2))
        console.print(f"[dim]Original settings backed up to {BACKUP_FILE}[/]")
