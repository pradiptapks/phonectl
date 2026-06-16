"""Centralized vendor plugin registration.

Single source of truth for vendor plugin order and registration,
used by both CLI and TUI entry points.
"""

from __future__ import annotations

from phonectl.core.device import DeviceManager
from phonectl.vendors.google import GooglePixelPlugin
from phonectl.vendors.motorola import MotorolaPlugin
from phonectl.vendors.nokia import NokiaPlugin
from phonectl.vendors.samsung import SamsungPlugin


def create_device_manager() -> DeviceManager:
    """Create a DeviceManager with all vendor plugins registered.

    Plugin order matters: first match in resolve_vendor() wins.
    Motorola is first because its fingerprint check catches GSI-on-Motorola
    devices that report manufacturer as 'Google'.
    """
    dm = DeviceManager()
    dm.register_vendor(MotorolaPlugin())
    dm.register_vendor(GooglePixelPlugin())
    dm.register_vendor(NokiaPlugin())
    dm.register_vendor(SamsungPlugin())
    return dm
