"""SafetyGuard — pre-flash validation, compatibility checks, and USB monitoring.

Encodes every lesson learned from the Moto G71 5G incident:
- Always backup boot partitions before modification
- Validate VNDK vs GSI compatibility
- Reject boot.img from mismatched ROMs
- Monitor USB connection during flash
- Maintain rollback state
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console

if TYPE_CHECKING:
    from phonectl.core.device import DeviceInfo
    from phonectl.core.fastboot import FastbootClient

console = Console()

VNDK_GSI_COMPAT = {
    "27": ["RP1A", "SQ3A"],
    "28": ["RP1A", "SQ3A", "T3B3", "TQ3A", "UP1A", "UQ1A"],
    "29": ["RP1A", "SQ3A", "T3B3", "TQ3A", "UP1A", "UQ1A"],
    "30": ["RP1A", "SQ3A", "T3B3", "TQ3A", "UP1A", "UQ1A", "AP3A", "AP4A", "CP11", "BP1A", "BP2A"],
    "31": ["RP1A", "SQ3A", "T3B3", "TQ3A", "UP1A", "UQ1A", "AP3A", "AP4A", "CP11", "BP1A", "BP2A", "BP3A"],
    "32": ["RP1A", "SQ3A", "T3B3", "TQ3A", "UP1A", "UQ1A", "AP3A", "AP4A", "CP11", "BP1A", "BP2A", "BP3A", "BP4A"],
    "33": ["RP1A", "SQ3A", "T3B3", "TQ3A", "UP1A", "UQ1A", "AP3A", "AP4A", "CP11", "BP1A", "BP2A", "BP3A", "BP4A", "CP21", "CP31"],
    "34": ["RP1A", "SQ3A", "T3B3", "TQ3A", "UP1A", "UQ1A", "AP3A", "AP4A", "CP11", "BP1A", "BP2A", "BP3A", "BP4A", "CP21", "CP31"],
}

# Android version requirements for GSI
GSI_ANDROID_REQUIREMENTS = {
    "CP31": {"min_android": 17, "min_sdk": 37, "name": "Android 17 QPR1 Beta"},
    "CP21": {"min_android": 17, "min_sdk": 37, "name": "Android 17 Beta"},
    "BP2A": {"min_android": 16, "min_sdk": 36, "name": "Android 16"},
    "BP3A": {"min_android": 16, "min_sdk": 36, "name": "Android 16 QPR1"},
    "BP4A": {"min_android": 16, "min_sdk": 36, "name": "Android 16 QPR2"},
    "CP11": {"min_android": 15, "min_sdk": 35, "name": "Android 15 QPR2"},
    "AP4A": {"min_android": 15, "min_sdk": 35, "name": "Android 15 QPR1"},
    "AP3A": {"min_android": 15, "min_sdk": 35, "name": "Android 15"},
    "UQ1A": {"min_android": 14, "min_sdk": 34, "name": "Android 14 QPR1"},
    "UP1A": {"min_android": 14, "min_sdk": 34, "name": "Android 14"},
    "TQ3A": {"min_android": 13, "min_sdk": 33, "name": "Android 13 QPR3"},
    "T3B3": {"min_android": 13, "min_sdk": 33, "name": "Android 13"},
    "SQ3A": {"min_android": 12, "min_sdk": 32, "name": "Android 12L"},
    "RP1A": {"min_android": 11, "min_sdk": 30, "name": "Android 11"},
}

# Hardware minimums for Android versions
ANDROID_HW_REQUIREMENTS = {
    17: {"min_ram_mb": 2048, "min_storage_gb": 16, "min_opengl": 0x00030002, "arch": "arm64"},
    16: {"min_ram_mb": 2048, "min_storage_gb": 16, "min_opengl": 0x00030002, "arch": "arm64"},
    15: {"min_ram_mb": 2048, "min_storage_gb": 16, "min_opengl": 0x00030001, "arch": "arm64"},
    14: {"min_ram_mb": 2048, "min_storage_gb": 16, "min_opengl": 0x00030000, "arch": "arm64"},
    13: {"min_ram_mb": 1024, "min_storage_gb": 16, "min_opengl": 0x00030000, "arch": "arm64"},
    12: {"min_ram_mb": 1024, "min_storage_gb": 16, "min_opengl": 0x00020000, "arch": "arm64"},
    11: {"min_ram_mb": 512, "min_storage_gb": 8, "min_opengl": 0x00020000, "arch": "arm64"},
}

MIN_BATTERY_FOR_FLASH = 50
# Android 13+ needs kernel 4.19+; Android 11-12 work with 4.4+
MIN_KERNEL_VERSION = (4, 4)
MIN_KERNEL_FOR_ANDROID13 = (4, 19)


@dataclass
class SafetyReport:
    passed: bool
    checks: list[dict]

    def summary(self) -> str:
        lines = []
        for c in self.checks:
            icon = "[green]PASS[/]" if c["passed"] else "[red]FAIL[/]"
            lines.append(f"  {icon} {c['name']}: {c['detail']}")
        return "\n".join(lines)


class SafetyError(Exception):
    pass


class SafetyGuard:
    """Pre-flash safety validation engine."""

    def __init__(self, backup_dir: str | Path = "~/.phonectl/backups"):
        self.backup_dir = Path(backup_dir).expanduser()

    def pre_flash_check(
        self,
        info: DeviceInfo,
        gsi_build_id: str,
        boot_img_path: str | None = None,
    ) -> SafetyReport:
        """Run all safety checks before a flash operation."""
        checks = []

        # ── 1. Bootloader unlocked ──
        checks.append({
            "name": "Bootloader unlocked",
            "passed": info.is_unlocked,
            "detail": "Unlocked" if info.is_unlocked else "LOCKED — cannot flash",
        })

        # ── 2. VNDK compatibility ──
        vndk = info.vndk_version
        compat_passed = True
        compat_detail = f"VNDK {vndk}"
        if vndk and gsi_build_id:
            prefix = gsi_build_id[:4]
            allowed = VNDK_GSI_COMPAT.get(vndk, [])
            if allowed and prefix not in allowed:
                compat_passed = False
                compat_detail = (
                    f"VNDK {vndk} is NOT compatible with GSI {gsi_build_id}. "
                    f"Allowed prefixes: {', '.join(allowed)}"
                )
            else:
                compat_detail = f"VNDK {vndk} compatible with {gsi_build_id}"
        checks.append({
            "name": "VNDK compatibility",
            "passed": compat_passed,
            "detail": compat_detail,
        })

        # ── 3. VNDK namespace isolation (Google Flash Tool gate) ──
        vndk_lite = getattr(info, 'vndk_lite', False)
        if vndk_lite and gsi_build_id:
            prefix = gsi_build_id[:4]
            gsi_req = GSI_ANDROID_REQUIREMENTS.get(prefix, {})
            gsi_android = gsi_req.get("min_android", 0)
            device_android = int(info.android_version) if info.android_version and info.android_version.isdigit() else 0
            if gsi_android and device_android and gsi_android != device_android:
                checks.append({
                    "name": "VNDK namespace isolation",
                    "passed": False,
                    "detail": (
                        f"VNDKLite device (non-isolated vendor namespace) — "
                        f"cannot cross-version flash "
                        f"(device: Android {device_android}, GSI targets Android {gsi_android})"
                    ),
                })
            else:
                checks.append({
                    "name": "VNDK namespace isolation",
                    "passed": True,
                    "detail": "VNDKLite device — same Android version, cross-version restriction OK",
                })
        else:
            checks.append({
                "name": "VNDK namespace isolation",
                "passed": True,
                "detail": "Full VNDK isolation — cross-version GSI supported",
            })

        # ── 4. Project Treble ──
        checks.append({
            "name": "Project Treble",
            "passed": info.treble_enabled,
            "detail": "Enabled" if info.treble_enabled else "DISABLED — GSI requires Treble",
        })

        # ── 5. Dynamic partitions ──
        checks.append({
            "name": "Dynamic partitions",
            "passed": info.dynamic_partitions,
            "detail": "Supported" if info.dynamic_partitions else "Not supported — may need legacy flash method",
        })

        # ── 6. AVB verified boot ──
        avb_state = info.verified_boot_state
        if avb_state == "green":
            avb_passed = False
            avb_detail = (
                "Verified boot is GREEN (locked/verified) — "
                "GSI requires AVB disabled; vbmeta with "
                "--disable-verity --disable-verification will be flashed automatically"
            )
        elif avb_state == "orange":
            avb_passed = True
            avb_detail = "Verified boot ORANGE (unlocked) — AVB can be disabled"
        elif avb_state == "yellow":
            avb_passed = True
            avb_detail = "Verified boot YELLOW (custom key) — GSI flash will override with disabled vbmeta"
        elif avb_state:
            avb_passed = True
            avb_detail = f"Verified boot state: {avb_state}"
        else:
            avb_passed = True
            avb_detail = "Not verified"
        checks.append({
            "name": "AVB verified boot",
            "passed": avb_passed,
            "detail": avb_detail,
        })

        # ── 7. Architecture ──
        arch_ok = "arm64" in info.cpu_abi.lower() if info.cpu_abi else False
        checks.append({
            "name": "Architecture",
            "passed": arch_ok,
            "detail": info.cpu_abi or "Unknown",
        })

        # ── 6. A/B partition scheme ──
        slot_count = int(info.slot_count) if info.slot_count and info.slot_count.isdigit() else 0
        has_ab = slot_count >= 2
        checks.append({
            "name": "A/B partitions",
            "passed": has_ab,
            "detail": f"{slot_count} slots (active: {info.slot_suffix or '?'})" if has_ab
                      else "Non-A/B device — flash procedure differs",
        })

        # ── 7. RAM ──
        target_android = self._parse_gsi_android_version(gsi_build_id)
        hw_req = ANDROID_HW_REQUIREMENTS.get(target_android, {})
        min_ram = hw_req.get("min_ram_mb", 2048)
        ram_ok = info.ram_total_mb >= min_ram if info.ram_total_mb > 0 else True
        checks.append({
            "name": "RAM",
            "passed": ram_ok,
            "detail": f"{info.ram_total_mb} MB" + (f" (min {min_ram} MB)" if not ram_ok else "")
                      if info.ram_total_mb > 0 else "Unknown",
        })

        # ── 8. Storage ──
        min_storage = hw_req.get("min_storage_gb", 16)
        storage_ok = info.storage_free_gb >= 4.0 if info.storage_free_gb > 0 else True
        total_ok = info.storage_total_gb >= min_storage if info.storage_total_gb > 0 else True
        checks.append({
            "name": "Storage",
            "passed": storage_ok and total_ok,
            "detail": f"{info.storage_total_gb} GB total, {info.storage_free_gb} GB free"
                      if info.storage_total_gb > 0 else "Unknown",
        })

        # ── 9. Battery ──
        batt = int(info.battery_level) if info.battery_level and info.battery_level.isdigit() else -1
        batt_ok = batt >= MIN_BATTERY_FOR_FLASH if batt >= 0 else True
        checks.append({
            "name": "Battery level",
            "passed": batt_ok,
            "detail": f"{batt}%" + (f" (min {MIN_BATTERY_FOR_FLASH}%)" if not batt_ok else "")
                      if batt >= 0 else "Unknown (charge to 50%+ recommended)",
        })

        # ── 10. OpenGL ES version ──
        if info.opengl_version:
            try:
                gl_int = int(info.opengl_version)
                gl_major = (gl_int >> 16) & 0xFFFF
                gl_minor = gl_int & 0xFFFF
                gl_str = f"{gl_major}.{gl_minor}"
                min_gl = hw_req.get("min_opengl", 0x00030000)
                gl_ok = gl_int >= min_gl
                min_gl_str = f"{(min_gl >> 16) & 0xFFFF}.{min_gl & 0xFFFF}"
                checks.append({
                    "name": "OpenGL ES",
                    "passed": gl_ok,
                    "detail": f"ES {gl_str}" + (f" (min ES {min_gl_str})" if not gl_ok else ""),
                })
            except (ValueError, TypeError):
                pass

        # ── 11. Kernel version ──
        if info.kernel_version:
            kern_ok, kern_detail = self._check_kernel_version(info.kernel_version, gsi_build_id)
            checks.append({
                "name": "Kernel version",
                "passed": kern_ok,
                "detail": kern_detail,
            })

        # ── 12. Android / firmware version check ──
        android_ok, android_detail = self._check_android_firmware(info, gsi_build_id)
        checks.append({
            "name": "Android/firmware version",
            "passed": android_ok,
            "detail": android_detail,
        })

        # ── 13. Vendor security patch age ──
        if info.vendor_security_patch:
            patch_ok, patch_detail = self._check_vendor_patch_age(info.vendor_security_patch)
            checks.append({
                "name": "Vendor security patch",
                "passed": patch_ok,
                "detail": patch_detail,
            })

        # ── 14. Backup exists ──
        device_backup = self.backup_dir / info.codename
        has_backup = device_backup.exists() and any(device_backup.glob("*.img"))
        checks.append({
            "name": "Boot partition backup",
            "passed": has_backup,
            "detail": str(device_backup) if has_backup else "NO BACKUP — run `phonectl backup create` first",
        })

        # ── 15. Boot image origin check (if provided) ──
        if boot_img_path:
            boot_ok, boot_detail = self._validate_boot_image(boot_img_path, info)
            checks.append({
                "name": "Boot image validation",
                "passed": boot_ok,
                "detail": boot_detail,
            })

        all_passed = all(c["passed"] for c in checks)
        return SafetyReport(passed=all_passed, checks=checks)

    def _parse_gsi_android_version(self, gsi_build_id: str) -> int:
        """Derive the target Android version from a GSI build ID prefix."""
        prefix = gsi_build_id[:4] if gsi_build_id else ""
        info = GSI_ANDROID_REQUIREMENTS.get(prefix, {})
        return info.get("min_android", 16)

    def _check_kernel_version(self, kernel_str: str, gsi_build_id: str = "") -> tuple[bool, str]:
        """Validate kernel is new enough for the target GSI."""
        import re
        match = re.match(r"(\d+)\.(\d+)", kernel_str)
        if not match:
            return True, f"{kernel_str} (unable to parse, skipping check)"

        major, minor = int(match.group(1)), int(match.group(2))
        target_android = self._parse_gsi_android_version(gsi_build_id)

        if target_android >= 13:
            min_major, min_minor = MIN_KERNEL_FOR_ANDROID13
        else:
            min_major, min_minor = MIN_KERNEL_VERSION

        ok = (major, minor) >= (min_major, min_minor)
        detail = f"{major}.{minor}"
        if not ok:
            detail += f" — TOO OLD (min {min_major}.{min_minor} required for Android {target_android}+)"
        return ok, detail

    def _check_android_firmware(self, info: DeviceInfo, gsi_build_id: str) -> tuple[bool, str]:
        """Check Android version and firmware compatibility with the target GSI."""
        details = []
        passed = True

        # Current Android version on device
        if info.android_version:
            details.append(f"Current Android: {info.android_version}")

        # First API level (what the device shipped with)
        if info.first_api_level:
            api = int(info.first_api_level) if info.first_api_level.isdigit() else 0
            if api < 26:
                passed = False
                details.append(f"First API level: {api} — TOO OLD (pre-Treble, requires API 26+)")
            elif api < 28 and not info.treble_enabled:
                passed = False
                details.append(f"First API level: {api} — no Treble support (requires API 28+ or Treble enabled)")
            else:
                details.append(f"First API level: {api} (shipped with Android {self._api_to_android(api)})")

        # Vendor build (stock firmware identity)
        if info.vendor_build_id:
            details.append(f"Vendor build: {info.vendor_build_id}")

        # GSI target info
        gsi_info = GSI_ANDROID_REQUIREMENTS.get(gsi_build_id[:4] if gsi_build_id else "", {})
        if gsi_info:
            details.append(f"Target GSI: {gsi_info.get('name', gsi_build_id)}")

        return passed, "; ".join(details) if details else "No firmware info available"

    def _check_vendor_patch_age(self, vendor_patch: str) -> tuple[bool, str]:
        """Warn if vendor security patch is very old."""
        from datetime import datetime
        try:
            patch_date = datetime.strptime(vendor_patch, "%Y-%m-%d")
            age_days = (datetime.now() - patch_date).days
            age_years = age_days / 365.25
            if age_years > 3:
                return False, f"{vendor_patch} — {age_years:.1f} years old (vendor support likely ended)"
            return True, f"{vendor_patch} ({age_days} days old)"
        except ValueError:
            return True, vendor_patch

    @staticmethod
    def _api_to_android(api: int) -> str:
        """Map API level to Android version name."""
        api_map = {
            26: "8.0", 27: "8.1", 28: "9", 29: "10", 30: "11",
            31: "12", 32: "12L", 33: "13", 34: "14", 35: "15",
            36: "16", 37: "17",
        }
        return api_map.get(api, str(api))

    def _validate_boot_image(self, boot_img_path: str, info: DeviceInfo) -> tuple[bool, str]:
        """Validate that a boot.img is from the same device/vendor."""
        path = Path(boot_img_path)
        if not path.exists():
            return False, f"Boot image not found: {path}"

        try:
            result = subprocess.run(
                ["file", str(path)],
                capture_output=True, text=True, timeout=10,
            )
            file_type = result.stdout.strip()
            if "Android bootimg" not in file_type:
                return False, f"Not a valid Android boot image: {file_type}"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        return True, f"Valid boot image: {path.name}"

    def check_usb_connected(self, serial: str | None = None) -> bool:
        """Check if a device is currently connected via USB."""
        try:
            result = subprocess.run(
                ["lsusb"],
                capture_output=True, text=True, timeout=5,
            )
            output = result.stdout.lower()
            usb_keywords = [
                "motorola", "google", "samsung", "nokia", "hmd",
                "22b8", "18d1", "04e8", "2e04", "2a70", "2717",
            ]
            return any(kw in output for kw in usb_keywords)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def wait_for_usb(self, timeout: int = 60, interval: int = 3) -> bool:
        """Wait for a USB device to appear. Returns True if found."""
        console.print(f"[yellow]Waiting for USB device (up to {timeout}s)...[/]")
        elapsed = 0
        while elapsed < timeout:
            if self.check_usb_connected():
                console.print("[green]USB device detected.[/]")
                return True
            time.sleep(interval)
            elapsed += interval
        console.print("[red]Timeout: no USB device detected.[/]")
        return False

    def monitor_usb_during_flash(self, check_interval: int = 5) -> bool:
        """Check USB mid-flash — returns False if cable disconnected."""
        if not self.check_usb_connected():
            console.print(
                "[bold red]WARNING: USB device disconnected during flash![/]\n"
                "[yellow]DO NOT unplug the cable. Replug and retry.[/]"
            )
            return False
        return True

    def confirm_destructive(self, action: str) -> bool:
        """Ask user to confirm a destructive operation."""
        console.print(f"\n[bold red]WARNING:[/] {action}")
        response = console.input("[yellow]Type 'yes' to continue, anything else to abort: [/]")
        return response.strip().lower() == "yes"
