"""Device detection, identification, and info gathering."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from phonectl.core.adb import ADBClient, ADBError
from phonectl.core.fastboot import FastbootClient, FastbootError


class DeviceState(Enum):
    ANDROID = "android"
    FASTBOOT = "fastboot"
    FASTBOOTD = "fastbootd"
    RECOVERY = "recovery"
    SIDELOAD = "sideload"
    DISCONNECTED = "disconnected"
    UNAUTHORIZED = "unauthorized"


@dataclass
class DeviceInfo:
    serial: str = ""
    state: DeviceState = DeviceState.DISCONNECTED
    manufacturer: str = ""
    model: str = ""
    codename: str = ""
    android_version: str = ""
    sdk_version: str = ""
    security_patch: str = ""
    build_id: str = ""
    build_fingerprint: str = ""
    kernel_version: str = ""
    bootloader_version: str = ""
    baseband_version: str = ""
    # Partition info
    slot_suffix: str = ""
    slot_count: str = ""
    is_unlocked: bool = False
    treble_enabled: bool = False
    dynamic_partitions: bool = False
    vndk_version: str = ""
    verified_boot_state: str = ""
    # Hardware
    cpu_abi: str = ""
    board_platform: str = ""
    hardware: str = ""
    # Runtime
    battery_level: str = ""
    uptime: str = ""
    # Extra vendor-specific properties
    extra: dict = field(default_factory=dict)


class DeviceManager:
    """Detects and identifies connected Android devices."""

    def __init__(self):
        self._adb: ADBClient | None = None
        self._fastboot: FastbootClient | None = None
        self._vendor_plugins: list = []

    def register_vendor(self, plugin) -> None:
        self._vendor_plugins.append(plugin)

    def detect(self) -> DeviceInfo:
        """Detect a connected device via ADB first, then fastboot."""
        info = DeviceInfo()

        adb = ADBClient()
        fb = FastbootClient()

        # Try ADB first
        try:
            adb_devices = adb.devices()
            for dev in adb_devices:
                if dev.state == "device":
                    info.serial = dev.serial
                    info.state = DeviceState.ANDROID
                    self._adb = ADBClient(serial=dev.serial)
                    self._fill_from_adb(info)
                    return info
                if dev.state == "recovery":
                    info.serial = dev.serial
                    info.state = DeviceState.RECOVERY
                    self._adb = ADBClient(serial=dev.serial)
                    return info
                if dev.state == "sideload":
                    info.serial = dev.serial
                    info.state = DeviceState.SIDELOAD
                    return info
                if dev.state == "unauthorized":
                    info.serial = dev.serial
                    info.state = DeviceState.UNAUTHORIZED
                    return info
        except ADBError:
            pass

        # Try fastboot
        try:
            fb_devices = fb.devices()
            if fb_devices:
                dev = fb_devices[0]
                info.serial = dev.serial
                self._fastboot = FastbootClient(serial=dev.serial)
                if self._fastboot.is_userspace():
                    info.state = DeviceState.FASTBOOTD
                else:
                    info.state = DeviceState.FASTBOOT
                self._fill_from_fastboot(info)
                return info
        except FastbootError:
            pass

        info.state = DeviceState.DISCONNECTED
        return info

    def _fill_from_adb(self, info: DeviceInfo) -> None:
        adb = self._adb
        if not adb:
            return

        prop_map = {
            "ro.product.manufacturer": "manufacturer",
            "ro.product.model": "model",
            "ro.product.vendor.device": "codename",
            "ro.build.version.release": "android_version",
            "ro.build.version.sdk": "sdk_version",
            "ro.build.version.security_patch": "security_patch",
            "ro.build.display.id": "build_id",
            "ro.build.fingerprint": "build_fingerprint",
            "ro.boot.slot_suffix": "slot_suffix",
            "ro.boot.verifiedbootstate": "verified_boot_state",
            "ro.product.cpu.abi": "cpu_abi",
            "ro.board.platform": "board_platform",
            "ro.hardware": "hardware",
            "ro.vndk.version": "vndk_version",
            "ro.bootimage.build.fingerprint": "bootloader_version",
            "gsm.version.baseband": "baseband_version",
        }

        for prop, attr in prop_map.items():
            try:
                val = adb.getprop(prop)
                if val:
                    setattr(info, attr, val)
            except ADBError:
                pass

        # Boolean properties
        try:
            info.treble_enabled = adb.getprop("ro.treble.enabled").lower() == "true"
        except ADBError:
            pass
        try:
            info.dynamic_partitions = adb.getprop("ro.dynamic_partitions").lower() == "true"
        except ADBError:
            pass
        try:
            info.is_unlocked = info.verified_boot_state == "orange"
        except (ADBError, AttributeError):
            pass

        # Kernel version
        try:
            info.kernel_version = adb.shell("uname -r")
        except ADBError:
            pass

        # Battery
        try:
            battery_output = adb.shell("dumpsys battery")
            for line in battery_output.splitlines():
                if "level:" in line:
                    info.battery_level = line.split(":", 1)[1].strip()
                    break
        except ADBError:
            pass

        # Uptime
        try:
            info.uptime = adb.shell("uptime -p") or adb.shell("uptime")
        except ADBError:
            pass

        # Vendor build fingerprint (for stock firmware identification)
        try:
            vendor_fp = adb.getprop("ro.vendor.build.fingerprint")
            if vendor_fp:
                info.extra["vendor_fingerprint"] = vendor_fp
        except ADBError:
            pass

    def _fill_from_fastboot(self, info: DeviceInfo) -> None:
        fb = self._fastboot
        if not fb:
            return

        var_map = {
            "product": "codename",
            "serialno": "serial",
            "current-slot": "slot_suffix",
            "slot-count": "slot_count",
            "version-bootloader": "bootloader_version",
            "version-baseband": "baseband_version",
        }

        for var, attr in var_map.items():
            try:
                val = fb.getvar(var)
                if val:
                    setattr(info, attr, val)
            except FastbootError:
                pass

        try:
            info.is_unlocked = fb.is_unlocked()
        except FastbootError:
            pass

    def get_adb(self) -> ADBClient | None:
        return self._adb

    def get_fastboot(self) -> FastbootClient | None:
        return self._fastboot

    def resolve_vendor(self, info: DeviceInfo):
        """Find the matching vendor plugin for a device."""
        for plugin in self._vendor_plugins:
            if plugin.detect(info):
                return plugin
        return None
