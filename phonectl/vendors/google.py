"""Google Pixel vendor plugin — stub for future implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from phonectl.vendors.base import BaseVendorPlugin, FirmwareSource, FlashStep

if TYPE_CHECKING:
    from phonectl.core.device import DeviceInfo


class GooglePixelPlugin(BaseVendorPlugin):
    """Google Pixel stub — contributions welcome."""

    @property
    def name(self) -> str:
        return "Google Pixel"

    @property
    def usb_vendor_ids(self) -> list[str]:
        return ["18d1"]

    def detect(self, info: DeviceInfo) -> bool:
        # Avoid false positives: devices running GSI report manufacturer as "Google"
        # but their vendor fingerprint reveals the real OEM. Only match if the vendor
        # fingerprint also belongs to Google (Pixel devices).
        vendor_fp = info.extra.get("vendor_fingerprint", "")
        if vendor_fp and "google/" not in vendor_fp.lower():
            return False

        if info.manufacturer.lower() not in ("google",):
            return False

        # Known Pixel codenames for extra confidence
        pixel_codenames = (
            "sailfish", "marlin", "walleye", "taimen", "blueline", "crosshatch",
            "sargo", "bonito", "flame", "coral", "sunfish", "bramble", "redfin",
            "barbet", "oriole", "raven", "bluejay", "panther", "cheetah",
            "lynx", "tangorpro", "felix", "shiba", "husky", "akita",
            "tokay", "caiman", "komodo", "comet",
        )
        if info.codename and info.codename.lower() in pixel_codenames:
            return True

        # If vendor fingerprint confirms Google, match even without codename
        if "google/" in vendor_fp.lower():
            return True

        return False

    def get_boot_partitions(self) -> list[str]:
        return ["boot", "dtbo", "vbmeta"]

    def get_usb_quirks(self) -> dict:
        return {
            "description": "Pixel devices have good fastboot support with no known USB quirks.",
        }

    def get_firmware_source(self, info: DeviceInfo) -> FirmwareSource:
        return FirmwareSource(
            base_url="https://developers.google.com/android/images",
            codename=info.codename,
        )

    def get_flash_sequence(self, info: DeviceInfo, system_img: str, vbmeta_img: str) -> list[FlashStep]:
        raise NotImplementedError("Google Pixel flash sequence not yet implemented.")
