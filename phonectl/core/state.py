"""Flash state persistence, device profile caching, and flash audit log.

Tracks what's currently on the device so recovery knows what to restore,
caches device properties for fastbootd-mode operations, and logs every
flash operation for audit trail.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console

if TYPE_CHECKING:
    from phonectl.core.device import DeviceInfo

console = Console()

PHONECTL_DIR = Path.home() / ".phonectl"
STATE_FILE = PHONECTL_DIR / "state.json"
PROFILES_DIR = PHONECTL_DIR / "profiles"
FLASH_LOG_FILE = PHONECTL_DIR / "flash_log.jsonl"


@dataclass
class FlashState:
    """Records what was last flashed to a device."""
    serial: str = ""
    codename: str = ""
    system_type: str = ""       # "gsi" or "stock"
    gsi_build_id: str = ""      # e.g. "BP2A.250605.031.A3"
    vbmeta_type: str = ""       # "gsi" or "stock"
    vbmeta_path: str = ""
    system_path: str = ""
    boot_source: str = ""
    timestamp: str = ""
    slot: str = ""              # "a" or "b"


@dataclass
class DeviceProfile:
    """Cached device properties for use when phone is in fastbootd."""
    serial: str = ""
    manufacturer: str = ""
    model: str = ""
    codename: str = ""
    android_version: str = ""
    vndk_version: str = ""
    vndk_lite: bool = False
    treble_enabled: bool = False
    dynamic_partitions: bool = False
    cpu_abi: str = ""
    ram_total_mb: int = 0
    storage_total_gb: float = 0.0
    kernel_version: str = ""
    board_platform: str = ""
    hardware: str = ""
    is_unlocked: bool = False
    slot_suffix: str = ""
    slot_count: str = ""
    first_api_level: str = ""
    opengl_version: str = ""
    build_fingerprint: str = ""
    vendor_fingerprint: str = ""
    cached_at: str = ""


class StateManager:
    """Manage flash state and device profiles."""

    def __init__(self):
        PHONECTL_DIR.mkdir(parents=True, exist_ok=True)
        PROFILES_DIR.mkdir(parents=True, exist_ok=True)

    # ── Flash State ──

    def save_flash_state(self, state: FlashState) -> None:
        """Save current flash state."""
        state.timestamp = datetime.now().isoformat()
        data = asdict(state)

        all_states = self._load_all_states()
        all_states[state.serial] = data
        STATE_FILE.write_text(json.dumps(all_states, indent=2))

        self._append_flash_log(state, "flash")
        console.print(f"[dim]Flash state saved for {state.serial}[/]")

    def load_flash_state(self, serial: str) -> FlashState | None:
        """Load flash state for a specific device."""
        all_states = self._load_all_states()
        data = all_states.get(serial)
        if data:
            return FlashState(**{k: v for k, v in data.items() if k in FlashState.__dataclass_fields__})
        return None

    def get_latest_state(self) -> FlashState | None:
        """Get the most recently flashed device state."""
        all_states = self._load_all_states()
        if not all_states:
            return None
        latest = max(all_states.values(), key=lambda s: s.get("timestamp", ""))
        return FlashState(**{k: v for k, v in latest.items() if k in FlashState.__dataclass_fields__})

    def _load_all_states(self) -> dict:
        if STATE_FILE.exists():
            try:
                return json.loads(STATE_FILE.read_text())
            except (json.JSONDecodeError, ValueError):
                return {}
        return {}

    # ── Device Profile Cache ──

    def save_profile(self, info: DeviceInfo) -> None:
        """Cache device properties from ADB detection."""
        profile = DeviceProfile(
            serial=info.serial,
            manufacturer=info.manufacturer,
            model=info.model,
            codename=info.codename,
            android_version=info.android_version,
            vndk_version=info.vndk_version,
            vndk_lite=info.vndk_lite,
            treble_enabled=info.treble_enabled,
            dynamic_partitions=info.dynamic_partitions,
            cpu_abi=info.cpu_abi,
            ram_total_mb=info.ram_total_mb,
            storage_total_gb=info.storage_total_gb,
            kernel_version=info.kernel_version,
            board_platform=info.board_platform,
            hardware=info.hardware,
            is_unlocked=info.is_unlocked,
            slot_suffix=info.slot_suffix,
            slot_count=info.slot_count,
            first_api_level=info.first_api_level,
            opengl_version=info.opengl_version,
            build_fingerprint=info.build_fingerprint,
            vendor_fingerprint=info.extra.get("vendor_fingerprint", ""),
            cached_at=datetime.now().isoformat(),
        )
        path = PROFILES_DIR / f"{info.serial}.json"
        path.write_text(json.dumps(asdict(profile), indent=2))

    def load_profile(self, serial: str) -> DeviceProfile | None:
        """Load cached device profile by serial number."""
        path = PROFILES_DIR / f"{serial}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return DeviceProfile(**{k: v for k, v in data.items() if k in DeviceProfile.__dataclass_fields__})
        except (json.JSONDecodeError, ValueError, TypeError):
            return None

    def apply_profile_to_info(self, profile: DeviceProfile, info: DeviceInfo) -> None:
        """Apply cached profile data to a DeviceInfo object (for fastbootd mode)."""
        field_map = {
            "manufacturer": "manufacturer",
            "model": "model",
            "codename": "codename",
            "android_version": "android_version",
            "vndk_version": "vndk_version",
            "vndk_lite": "vndk_lite",
            "treble_enabled": "treble_enabled",
            "dynamic_partitions": "dynamic_partitions",
            "cpu_abi": "cpu_abi",
            "ram_total_mb": "ram_total_mb",
            "storage_total_gb": "storage_total_gb",
            "kernel_version": "kernel_version",
            "board_platform": "board_platform",
            "hardware": "hardware",
            "is_unlocked": "is_unlocked",
            "first_api_level": "first_api_level",
            "opengl_version": "opengl_version",
            "build_fingerprint": "build_fingerprint",
        }
        for profile_field, info_field in field_map.items():
            val = getattr(profile, profile_field, None)
            current = getattr(info, info_field, None)
            if val and (not current or current == "" or current == 0 or current == 0.0):
                setattr(info, info_field, val)

        if profile.vendor_fingerprint:
            info.extra["vendor_fingerprint"] = profile.vendor_fingerprint

        if not info.slot_count and profile.slot_count:
            info.slot_count = profile.slot_count

    # ── Flash Log ──

    def _append_flash_log(self, state: FlashState, action: str) -> None:
        """Append an entry to the flash audit log."""
        entry = {
            "timestamp": state.timestamp,
            "serial": state.serial,
            "codename": state.codename,
            "action": action,
            "system_type": state.system_type,
            "gsi_build_id": state.gsi_build_id,
            "vbmeta_type": state.vbmeta_type,
            "slot": state.slot,
        }
        with open(FLASH_LOG_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def get_flash_log(self, serial: str | None = None, limit: int = 20) -> list[dict]:
        """Read flash log entries, optionally filtered by serial."""
        if not FLASH_LOG_FILE.exists():
            return []
        entries = []
        with open(FLASH_LOG_FILE) as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if serial is None or entry.get("serial") == serial:
                        entries.append(entry)
                except json.JSONDecodeError:
                    continue
        return entries[-limit:]
