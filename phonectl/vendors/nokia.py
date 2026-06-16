"""Nokia / HMD Global vendor plugin.

Nokia Android phones (post-2017) are manufactured by HMD Global and run
Android One / stock Android.  Most models use A/B partitions.

Bootloader fastboot mode is used for flashing (not fastbootd/userspace
fastboot).  Enter fastboot via: power off, then hold Power + Volume Down.

Reference device: Nokia 6.1 (PL2) — Treble-enabled, A/B, bootloader fastboot.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from phonectl.vendors.base import (
    BaseVendorPlugin,
    FirmwareSource,
    FlashStep,
    FlashStepType,
)

if TYPE_CHECKING:
    from phonectl.core.device import DeviceInfo

KNOWN_NOKIA_CODENAMES = (
    "PL2",   # Nokia 6.1
    "B2N",   # Nokia 7 Plus
    "DRG",   # Nokia 8
    "PNX",   # Nokia 8.1
    "CTL",   # Nokia 7.2
    "DDV",   # Nokia 6.2
    "TAS",   # Nokia 8.3 5G
    "BGT",   # Nokia X20
    "CRS",   # Nokia X10
    "FOX",   # Nokia 5.3
    "DPL",   # Nokia 3.4
    "CAP",   # Nokia 2.4
    "WSP",   # Nokia G21
    "ROG",   # Nokia G50
    "SPR",   # Nokia G20
    "AGT",   # Nokia G60
    "PHR",   # Nokia G42
)


class NokiaPlugin(BaseVendorPlugin):
    """Nokia / HMD Global — fastbootd-capable Android One devices."""

    @property
    def name(self) -> str:
        return "Nokia (HMD Global)"

    @property
    def supports_flash(self) -> bool:
        return True

    @property
    def bloatware_key(self) -> str:
        return "nokia"

    @property
    def usb_vendor_ids(self) -> list[str]:
        return ["2e04"]

    def detect(self, info: DeviceInfo) -> bool:
        mfr = info.manufacturer.lower()
        if mfr in ("nokia", "hmd global"):
            return True

        vendor_fp = info.extra.get("vendor_fingerprint", "")
        if "nokia/" in vendor_fp.lower() or "hmd/" in vendor_fp.lower():
            return True

        if info.codename and info.codename.upper() in KNOWN_NOKIA_CODENAMES:
            return True

        return False

    def get_boot_partitions(self) -> list[str]:
        return ["boot", "dtbo", "vbmeta"]

    def get_usb_quirks(self) -> dict:
        return {
            "use_fastbootd": False,
            "sparse_limit": "256M",
            "description": (
                "Nokia/HMD devices use standard bootloader fastboot (not fastbootd). "
                "Enter fastboot mode via: power off, then hold Power + Volume Down."
            ),
        }

    def get_firmware_source(self, info: DeviceInfo) -> FirmwareSource:
        return FirmwareSource(
            base_url="https://nokia-updates.com",
            codename=info.codename,
        )

    def get_flash_sequence(
        self, info: DeviceInfo, system_img: str, vbmeta_img: str
    ) -> list[FlashStep]:
        return [
            FlashStep(
                step_type=FlashStepType.FLASH_VBMETA,
                partition="vbmeta",
                image_path=vbmeta_img,
                description="Disable verified boot (flash vbmeta)",
            ),
            FlashStep(
                step_type=FlashStepType.FLASH,
                partition="system",
                image_path=system_img,
                description="Flash GSI system image",
                sparse_limit="256M",
                timeout=900,
            ),
            FlashStep(
                step_type=FlashStepType.WIPE,
                description="Wipe userdata (required after GSI flash)",
            ),
            FlashStep(
                step_type=FlashStepType.REBOOT,
                description="Reboot into Android",
            ),
        ]

    def get_update_sequence(
        self, info: DeviceInfo, system_img: str, vbmeta_img: str
    ) -> list[FlashStep]:
        """Update GSI without data wipe (same major version)."""
        return [
            FlashStep(
                step_type=FlashStepType.FLASH_VBMETA,
                partition="vbmeta",
                image_path=vbmeta_img,
                description="Flash vbmeta with disabled verification",
            ),
            FlashStep(
                step_type=FlashStepType.FLASH,
                partition="system",
                image_path=system_img,
                description="Flash updated GSI system image",
                sparse_limit="256M",
                timeout=900,
            ),
            FlashStep(
                step_type=FlashStepType.REBOOT,
                description="Reboot (no data wipe — preserving user data)",
            ),
        ]
