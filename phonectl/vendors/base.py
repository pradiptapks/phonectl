"""Base vendor plugin interface — all vendors must implement this."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from phonectl.core.adb import ADBClient
    from phonectl.core.device import DeviceInfo
    from phonectl.core.fastboot import FastbootClient


class FlashStepType(Enum):
    FLASH = "flash"
    FLASH_VBMETA = "flash_vbmeta"
    WIPE = "wipe"
    REBOOT = "reboot"
    SET_ACTIVE = "set_active"
    DELETE_PARTITION = "delete_partition"
    CREATE_PARTITION = "create_partition"
    WAIT = "wait"


@dataclass
class FlashStep:
    step_type: FlashStepType
    partition: str = ""
    image_path: str = ""
    description: str = ""
    sparse_limit: str = "128M"
    extra_args: list[str] | None = None
    timeout: int = 900
    required: bool = True


@dataclass
class FirmwareSource:
    """Describes where to find firmware for a device."""
    base_url: str
    region: str = ""
    codename: str = ""
    build_id: str = ""
    filename_pattern: str = ""


class BaseVendorPlugin(ABC):
    """Abstract base class for vendor-specific behaviour.

    Each vendor plugin encapsulates the quirks, partition layouts,
    firmware sources, and flash sequences unique to that OEM.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Vendor display name (e.g., 'Motorola')."""

    @property
    @abstractmethod
    def usb_vendor_ids(self) -> list[str]:
        """USB vendor IDs for detection (e.g., ['22b8'])."""

    @abstractmethod
    def detect(self, info: DeviceInfo) -> bool:
        """Return True if this plugin handles the given device."""

    @abstractmethod
    def get_boot_partitions(self) -> list[str]:
        """Partitions that constitute the 'boot set' (boot, vendor_boot, etc.)."""

    @abstractmethod
    def get_flash_sequence(self, info: DeviceInfo, system_img: str, vbmeta_img: str) -> list[FlashStep]:
        """Return the ordered sequence of flash steps for a GSI install."""

    @abstractmethod
    def get_firmware_source(self, info: DeviceInfo) -> FirmwareSource:
        """Return the firmware download source for this device."""

    @abstractmethod
    def get_usb_quirks(self) -> dict:
        """Return known USB/fastboot quirks for this vendor."""

    @property
    def supports_flash(self) -> bool:
        """Whether this plugin has a working flash implementation.

        Override to return True in vendors with implemented get_flash_sequence.
        """
        return False

    @property
    def bloatware_key(self) -> str:
        """Key used to look up this vendor's bloatware in bloatware.yaml.

        Override if the YAML key differs from the lowercase vendor name.
        """
        return self.name.lower()

    def get_recovery_sequence(self, info: DeviceInfo, boot_imgs: dict[str, str], system_img: str) -> list[FlashStep]:
        """Return steps to recover from a boot loop using stock boot images + GSI system.

        Default implementation flashes all boot partitions then system.
        Vendors can override for custom recovery logic.
        """
        steps = []
        for partition in self.get_boot_partitions():
            if partition == "vbmeta" and partition in boot_imgs:
                steps.append(FlashStep(
                    step_type=FlashStepType.FLASH_VBMETA,
                    partition="vbmeta",
                    image_path=boot_imgs[partition],
                    description=f"Flash stock {partition}",
                ))
            elif partition in boot_imgs:
                steps.append(FlashStep(
                    step_type=FlashStepType.FLASH,
                    partition=partition,
                    image_path=boot_imgs[partition],
                    description=f"Flash stock {partition}",
                    sparse_limit="",
                ))

        if system_img:
            steps.append(FlashStep(
                step_type=FlashStepType.FLASH,
                partition="system",
                image_path=system_img,
                description="Flash GSI system image",
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
