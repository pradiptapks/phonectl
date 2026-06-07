"""ADB subprocess wrapper for device communication."""

from __future__ import annotations

import re
import subprocess
import shutil
from dataclasses import dataclass
from pathlib import Path

_SAFE_PATTERN = re.compile(r'^[a-zA-Z0-9._\-:/=+ @]+$')


def _validate_safe_string(value: str, label: str = "input") -> None:
    """Reject strings with shell metacharacters to prevent injection."""
    if not value:
        return
    if not _SAFE_PATTERN.match(value):
        raise ADBError(
            f"Unsafe {label}: '{value}' contains shell metacharacters. "
            "Only alphanumeric, dots, dashes, underscores, colons, slashes, and spaces are allowed."
        )


@dataclass
class ADBDevice:
    serial: str
    state: str  # "device", "unauthorized", "offline", "recovery", "sideload"


class ADBError(Exception):
    pass


class ADBClient:
    """Wrapper around the `adb` command-line tool."""

    def __init__(self, serial: str | None = None, adb_path: str | None = None):
        self.serial = serial
        self.adb_path = adb_path or shutil.which("adb")
        if not self.adb_path:
            raise ADBError("adb not found on PATH. Install Android platform-tools.")

    def _build_cmd(self, *args: str) -> list[str]:
        cmd = [self.adb_path]
        if self.serial:
            cmd += ["-s", self.serial]
        cmd += list(args)
        return cmd

    def _run(self, *args: str, timeout: int = 30, check: bool = True) -> str:
        cmd = self._build_cmd(*args)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise ADBError(f"adb command timed out after {timeout}s: {' '.join(cmd)}") from exc
        except FileNotFoundError as exc:
            raise ADBError(f"adb binary not found at {self.adb_path}") from exc

        if check and result.returncode != 0:
            stderr = result.stderr.strip()
            raise ADBError(f"adb command failed: {stderr or result.stdout.strip()}")
        return result.stdout.strip()

    # ── Device management ──

    def devices(self) -> list[ADBDevice]:
        output = self._run("devices", check=False)
        devices = []
        for line in output.splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) == 2:
                devices.append(ADBDevice(serial=parts[0], state=parts[1]))
        return devices

    def wait_for_device(self, timeout: int = 60) -> None:
        self._run("wait-for-device", timeout=timeout)

    def is_connected(self) -> bool:
        try:
            devs = self.devices()
            if self.serial:
                return any(d.serial == self.serial and d.state == "device" for d in devs)
            return any(d.state == "device" for d in devs)
        except ADBError:
            return False

    # ── Shell commands ──

    def shell(self, command: str, timeout: int = 30) -> str:
        return self._run("shell", command, timeout=timeout)

    def getprop(self, prop: str) -> str:
        _validate_safe_string(prop, "property name")
        return self.shell(f"getprop {prop}")

    def shell_safe(self, command: str, args: list[str] | None = None, timeout: int = 30) -> str:
        """Run a shell command with sanitized arguments.

        Use this instead of shell() when arguments come from untrusted sources
        (user input, device-reported package names, etc.).
        """
        if args:
            for arg in args:
                _validate_safe_string(arg, "shell argument")
            command = command.format(*args)
        return self._run("shell", command, timeout=timeout)

    def get_props(self, props: list[str]) -> dict[str, str]:
        return {p: self.getprop(p) for p in props}

    # ── File operations ──

    def push(self, local: str | Path, remote: str) -> str:
        return self._run("push", str(local), remote, timeout=120)

    def pull(self, remote: str, local: str | Path) -> str:
        return self._run("pull", remote, str(local), timeout=120)

    def install(self, apk_path: str | Path) -> str:
        return self._run("install", str(apk_path), timeout=120)

    # ── Reboot ──

    def reboot(self, target: str = "") -> str:
        if target:
            return self._run("reboot", target, timeout=10, check=False)
        return self._run("reboot", timeout=10, check=False)

    def reboot_bootloader(self) -> str:
        return self.reboot("bootloader")

    def reboot_fastboot(self) -> str:
        return self.reboot("fastboot")

    def reboot_recovery(self) -> str:
        return self.reboot("recovery")

    # ── Sideload ──

    def sideload(self, zip_path: str | Path, timeout: int = 600) -> str:
        return self._run("sideload", str(zip_path), timeout=timeout, check=False)

    # ── Server management ──

    def kill_server(self) -> str:
        return self._run("kill-server", check=False)

    def start_server(self) -> str:
        return self._run("start-server", check=False)

    def restart_server(self) -> None:
        self.kill_server()
        self.start_server()
