"""Fastboot subprocess wrapper for bootloader-level operations."""

from __future__ import annotations

import subprocess
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FastbootDevice:
    serial: str
    mode: str  # "fastboot" or "fastbootd"


class FastbootError(Exception):
    pass


class FastbootClient:
    """Wrapper around the `fastboot` command-line tool."""

    def __init__(self, serial: str | None = None, fastboot_path: str | None = None):
        self.serial = serial
        self.fastboot_path = fastboot_path or shutil.which("fastboot")
        if not self.fastboot_path:
            raise FastbootError(
                "fastboot not found on PATH. Install Android platform-tools."
            )

    def _build_cmd(self, *args: str) -> list[str]:
        cmd = [self.fastboot_path]
        if self.serial:
            cmd += ["-s", self.serial]
        cmd += list(args)
        return cmd

    def _run(
        self, *args: str, timeout: int = 30, check: bool = True
    ) -> str:
        cmd = self._build_cmd(*args)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise FastbootError(
                f"fastboot command timed out after {timeout}s: {' '.join(cmd)}"
            ) from exc
        except FileNotFoundError as exc:
            raise FastbootError(
                f"fastboot binary not found at {self.fastboot_path}"
            ) from exc

        combined = (result.stdout + "\n" + result.stderr).strip()
        if check and result.returncode != 0:
            raise FastbootError(f"fastboot command failed: {combined}")
        return combined

    # ── Device discovery ──

    def devices(self) -> list[FastbootDevice]:
        output = self._run("devices", check=False)
        devices = []
        for line in output.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                devices.append(FastbootDevice(serial=parts[0], mode=parts[1]))
        return devices

    def is_connected(self) -> bool:
        try:
            devs = self.devices()
            if self.serial:
                return any(d.serial == self.serial for d in devs)
            return len(devs) > 0
        except FastbootError:
            return False

    # ── Variables ──

    def getvar(self, name: str) -> str:
        output = self._run("getvar", name, check=False)
        for line in output.splitlines():
            if line.startswith(f"{name}:"):
                return line.split(":", 1)[1].strip()
        return ""

    def get_current_slot(self) -> str:
        return self.getvar("current-slot")

    def is_userspace(self) -> bool:
        return self.getvar("is-userspace").lower() == "yes"

    def is_unlocked(self) -> bool:
        return self.getvar("unlocked").lower() == "yes"

    # ── Flash operations ──

    def flash(
        self,
        partition: str,
        image_path: str | Path,
        sparse_limit: str | None = "128M",
        extra_args: list[str] | None = None,
        timeout: int = 900,
    ) -> str:
        args = ["flash", partition, str(image_path)]
        if sparse_limit:
            args += ["-S", sparse_limit]
        if extra_args:
            args += extra_args
        return self._run(*args, timeout=timeout)

    def flash_vbmeta(
        self,
        image_path: str | Path,
        disable_verity: bool = True,
        disable_verification: bool = True,
    ) -> str:
        args = ["flash", "vbmeta", str(image_path)]
        if disable_verity:
            args.append("--disable-verity")
        if disable_verification:
            args.append("--disable-verification")
        return self._run(*args, timeout=30)

    # ── Partition management ──

    def erase(self, partition: str) -> str:
        return self._run("erase", partition, timeout=30)

    def wipe(self) -> str:
        return self._run("-w", timeout=60)

    def set_active(self, slot: str) -> str:
        return self._run("set_active", slot, timeout=10)

    def delete_logical_partition(self, name: str) -> str:
        return self._run("delete-logical-partition", name, timeout=10)

    def create_logical_partition(self, name: str, size: int) -> str:
        return self._run("create-logical-partition", name, str(size), timeout=10)

    # ── Reboot ──

    def reboot(self, target: str = "") -> str:
        if target:
            return self._run("reboot", target, timeout=10, check=False)
        return self._run("reboot", timeout=10, check=False)

    def reboot_fastboot(self) -> str:
        return self.reboot("fastboot")

    def reboot_bootloader(self) -> str:
        return self.reboot("bootloader")

    def reboot_recovery(self) -> str:
        return self.reboot("recovery")
