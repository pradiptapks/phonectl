"""Samsung vendor plugin — stub for future implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from phonectl.vendors.base import BaseVendorPlugin, FirmwareSource, FlashStep

if TYPE_CHECKING:
    from phonectl.core.device import DeviceInfo


class SamsungPlugin(BaseVendorPlugin):
    """Samsung stub — contributions welcome.

    Samsung devices use Odin/Heimdall for flashing instead of fastboot.
    A full implementation would wrap heimdall or use Samsung's download mode.
    """

    @property
    def name(self) -> str:
        return "Samsung"

    @property
    def bloatware_key(self) -> str:
        return "samsung"

    @property
    def usb_vendor_ids(self) -> list[str]:
        return ["04e8"]

    def detect(self, info: DeviceInfo) -> bool:
        return info.manufacturer.lower() in ("samsung",)

    def get_boot_partitions(self) -> list[str]:
        return ["boot", "dtbo", "vbmeta"]

    def get_usb_quirks(self) -> dict:
        return {
            "uses_odin": True,
            "description": (
                "Samsung uses Odin/Heimdall protocol instead of fastboot. "
                "Flash via download mode (Power + Vol Down + USB)."
            ),
        }

    def get_firmware_source(self, info: DeviceInfo) -> FirmwareSource:
        return FirmwareSource(
            base_url="https://samfw.com",
            codename=info.codename,
        )

    def get_flash_sequence(self, info: DeviceInfo, system_img: str, vbmeta_img: str) -> list[FlashStep]:
        raise NotImplementedError("Samsung flash sequence not yet implemented. Use Odin/Heimdall.")
