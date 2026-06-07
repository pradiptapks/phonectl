"""Post-flash boot verification — confirms the phone actually booted after flashing.

Polls ADB/fastboot every 15 seconds for up to 5 minutes. Reports SUCCESS,
BOOT_FAILURE (phone fell back to fastboot), or TIMEOUT.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from phonectl.core.adb import ADBClient, ADBError
from phonectl.core.fastboot import FastbootClient, FastbootError

console = Console()


class BootResult(Enum):
    SUCCESS = "success"
    BOOT_FAILURE = "boot_failure"
    TIMEOUT = "timeout"


@dataclass
class BootVerification:
    result: BootResult
    android_version: str = ""
    security_patch: str = ""
    detail: str = ""


class BootVerifier:
    """Verify that a phone boots successfully after flashing."""

    def verify(
        self,
        serial: str | None = None,
        timeout: int = 300,
        poll_interval: int = 15,
    ) -> BootVerification:
        """Wait for device to boot and verify Android version.

        Returns SUCCESS if ADB detects the device, BOOT_FAILURE if the device
        falls back to fastboot, or TIMEOUT if neither happens within the timeout.
        """
        console.print(f"\n[bold]Verifying boot (up to {timeout // 60} minutes)...[/]")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Waiting for device to boot...", total=None)

            elapsed = 0
            while elapsed < timeout:
                # Check ADB (phone booted to Android)
                try:
                    adb = ADBClient(serial=serial)
                    devices = adb.devices()
                    for dev in devices:
                        if dev.state == "device":
                            if serial and dev.serial != serial:
                                continue
                            progress.update(task, description="Device detected! Reading version...")
                            time.sleep(3)

                            check_adb = ADBClient(serial=dev.serial)
                            try:
                                android_ver = check_adb.getprop("ro.build.version.release")
                                sec_patch = check_adb.getprop("ro.build.version.security_patch")
                            except ADBError:
                                android_ver = "unknown"
                                sec_patch = ""

                            console.print(
                                f"\n[bold green]Boot verified![/] "
                                f"Android {android_ver}"
                                + (f", patch {sec_patch}" if sec_patch else "")
                            )
                            return BootVerification(
                                result=BootResult.SUCCESS,
                                android_version=android_ver,
                                security_patch=sec_patch,
                                detail=f"Booted successfully to Android {android_ver}",
                            )
                except ADBError:
                    pass

                # Check fastboot (phone failed to boot and fell back)
                try:
                    fb = FastbootClient(serial=serial)
                    fb_devices = fb.devices()
                    if fb_devices and elapsed > 120:
                        console.print(
                            "\n[bold red]Boot failed![/] Device is back in fastboot mode.\n"
                            "The phone could not boot and fell back to the bootloader.\n"
                            "Run: [bold]phonectl recover[/] to restore boot partitions."
                        )
                        return BootVerification(
                            result=BootResult.BOOT_FAILURE,
                            detail="Device fell back to fastboot after 2+ minutes — boot failed",
                        )
                except FastbootError:
                    pass

                time.sleep(poll_interval)
                elapsed += poll_interval
                mins = elapsed // 60
                secs = elapsed % 60
                progress.update(task, description=f"Waiting for boot... ({mins}m {secs}s)")

        console.print(
            "\n[yellow]Boot verification timed out.[/]\n"
            "The device may still be booting (first boot can take 5+ minutes).\n"
            "Check the phone screen. If stuck at logo:\n"
            "  1. Hold Power + Volume Down for 15 seconds\n"
            "  2. Navigate to fastbootd\n"
            "  3. Run: [bold]phonectl recover[/]"
        )
        return BootVerification(
            result=BootResult.TIMEOUT,
            detail=f"No response after {timeout}s",
        )
