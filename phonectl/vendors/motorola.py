"""Motorola vendor plugin — reference implementation.

Built from real-world experience flashing a Moto G71 5G (corfur).
Encodes all Motorola-specific quirks, partition layout, and firmware sources.
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

LOLINET_BASE = "https://mirrors-obs-1.lolinet.com/firmware/lenomola"

# Known Motorola region codes
MOTO_REGIONS = {
    "RETIN": "India",
    "RETBR": "Brazil",
    "RETEU": "Europe",
    "RETGB": "United Kingdom",
    "RETAIL": "Generic Retail",
    "RETAR": "Argentina",
    "AMXMX": "Mexico (Telcel)",
    "ATTMX": "Mexico (AT&T)",
    "OPENLA": "Latin America (Open)",
}


class MotorolaPlugin(BaseVendorPlugin):
    """Motorola-specific flash logic and firmware sources."""

    @property
    def name(self) -> str:
        return "Motorola"

    @property
    def usb_vendor_ids(self) -> list[str]:
        return ["22b8"]

    def detect(self, info: DeviceInfo) -> bool:
        mfr = info.manufacturer.lower()
        if mfr in ("motorola", "motorola mobility llc", "lenovomobilecommunicationtechnology"):
            return True
        vendor_fp = info.extra.get("vendor_fingerprint", "")
        if "motorola/" in vendor_fp.lower():
            return True
        if info.hardware and info.hardware.lower() in ("qcom",) and info.codename:
            known_moto = ("corfur", "hawao", "devon", "rhode", "austin", "berlin", "corfu")
            if info.codename.lower() in known_moto:
                return True
        return False

    def get_boot_partitions(self) -> list[str]:
        return ["boot", "vendor_boot", "dtbo", "vbmeta"]

    def get_usb_quirks(self) -> dict:
        return {
            "ap_fastboot_no_usb": True,
            "requires_replug_after_mode_switch": True,
            "use_fastbootd_not_fastboot": True,
            "sparse_limit": "128M",
            "description": (
                "Motorola's low-level bootloader (AP Fastboot Flash Mode) "
                "often does not establish USB data connection. Use fastbootd "
                "(userspace fastboot) instead. Replug cable after mode switches."
            ),
        }

    def get_firmware_source(self, info: DeviceInfo) -> FirmwareSource:
        codename = info.codename or info.extra.get("codename", "")

        region = "RETIN"
        vendor_fp = info.extra.get("vendor_fingerprint", "")
        for code in MOTO_REGIONS:
            if code.lower() in vendor_fp.lower():
                region = code
                break

        return FirmwareSource(
            base_url=f"{LOLINET_BASE}/2021/{codename}/official/{region}/",
            region=region,
            codename=codename,
            filename_pattern=f"XT*_{codename.upper()}_{region}_*_CFC.xml.zip",
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
                description="Flash GSI system image (~3.2 GB, 25 chunks)",
                sparse_limit="128M",
                timeout=900,
            ),
            FlashStep(
                step_type=FlashStepType.WIPE,
                description="Wipe userdata (required for major version upgrade)",
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
                sparse_limit="128M",
                timeout=900,
            ),
            FlashStep(
                step_type=FlashStepType.REBOOT,
                description="Reboot (no data wipe — preserving user data)",
            ),
        ]

    def get_stock_flash_sequence(
        self,
        boot_imgs: dict[str, str],
        system_img: str,
    ) -> list[FlashStep]:
        """Flash stock boot partitions + GSI system (full recovery)."""
        steps = []
        for part in self.get_boot_partitions():
            if part not in boot_imgs:
                continue
            if part == "vbmeta":
                steps.append(FlashStep(
                    step_type=FlashStepType.FLASH_VBMETA,
                    partition="vbmeta",
                    image_path=boot_imgs["vbmeta"],
                    description="Flash stock vbmeta with disabled verification",
                ))
            else:
                steps.append(FlashStep(
                    step_type=FlashStepType.FLASH,
                    partition=part,
                    image_path=boot_imgs[part],
                    description=f"Flash stock {part}",
                    sparse_limit="",
                ))

        steps.append(FlashStep(
            step_type=FlashStepType.FLASH,
            partition="system",
            image_path=system_img,
            description="Flash GSI system image",
            sparse_limit="128M",
            timeout=900,
        ))
        steps.append(FlashStep(
            step_type=FlashStepType.WIPE,
            description="Wipe userdata",
        ))
        steps.append(FlashStep(
            step_type=FlashStepType.REBOOT,
            description="Reboot into system",
        ))
        return steps

    @staticmethod
    def list_firmware_regions() -> dict[str, str]:
        return dict(MOTO_REGIONS)
