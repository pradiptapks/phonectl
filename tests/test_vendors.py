"""Tests for vendor plugin detection, properties, and flash support."""

from __future__ import annotations

import pytest

from phonectl.core.device import DeviceInfo, DeviceState
from phonectl.vendors.motorola import MotorolaPlugin
from phonectl.vendors.google import GooglePixelPlugin
from phonectl.vendors.nokia import NokiaPlugin
from phonectl.vendors.samsung import SamsungPlugin


class TestMotorolaPlugin:
    def setup_method(self):
        self.plugin = MotorolaPlugin()

    def test_detect_by_manufacturer(self, moto_device_info):
        assert self.plugin.detect(moto_device_info) is True

    def test_detect_motorola_mobility(self):
        info = DeviceInfo(manufacturer="Motorola Mobility LLC")
        assert self.plugin.detect(info) is True

    def test_no_detect_samsung(self, samsung_device_info):
        assert self.plugin.detect(samsung_device_info) is False

    def test_supports_flash(self):
        assert self.plugin.supports_flash is True

    def test_bloatware_key(self):
        assert self.plugin.bloatware_key == "motorola"

    def test_flash_sequence_returns_steps(self, moto_device_info):
        steps = self.plugin.get_flash_sequence(moto_device_info, "/sys.img", "/vb.img")
        assert len(steps) == 4
        assert steps[0].partition == "vbmeta"
        assert steps[1].partition == "system"

    def test_update_sequence_no_wipe(self, moto_device_info):
        steps = self.plugin.get_update_sequence(moto_device_info, "/sys.img", "/vb.img")
        step_types = [s.step_type.value for s in steps]
        assert "wipe" not in step_types

    def test_usb_quirks_fastbootd(self):
        quirks = self.plugin.get_usb_quirks()
        assert quirks["use_fastbootd_not_fastboot"] is True

    def test_boot_partitions_include_vendor_boot(self):
        parts = self.plugin.get_boot_partitions()
        assert "vendor_boot" in parts
        assert "boot" in parts


class TestGooglePixelPlugin:
    def setup_method(self):
        self.plugin = GooglePixelPlugin()

    def test_detect_pixel_with_fingerprint(self, pixel_device_info):
        assert self.plugin.detect(pixel_device_info) is True

    def test_no_detect_gsi_on_motorola(self):
        info = DeviceInfo(
            manufacturer="Google",
            codename="corfur",
            extra={"vendor_fingerprint": "motorola/corfur/corfur:12"},
        )
        assert self.plugin.detect(info) is False

    def test_supports_flash_false(self):
        assert self.plugin.supports_flash is False

    def test_flash_sequence_raises(self, pixel_device_info):
        with pytest.raises(NotImplementedError):
            self.plugin.get_flash_sequence(pixel_device_info, "/s.img", "/v.img")

    def test_bloatware_key(self):
        assert self.plugin.bloatware_key == "google"


class TestNokiaPlugin:
    def setup_method(self):
        self.plugin = NokiaPlugin()

    def test_detect_hmd_global(self, nokia_device_info):
        assert self.plugin.detect(nokia_device_info) is True

    def test_detect_nokia_manufacturer(self):
        info = DeviceInfo(manufacturer="Nokia")
        assert self.plugin.detect(info) is True

    def test_detect_by_codename(self):
        info = DeviceInfo(manufacturer="unknown", codename="PL2")
        assert self.plugin.detect(info) is True

    def test_supports_flash(self):
        assert self.plugin.supports_flash is True

    def test_bloatware_key(self):
        assert self.plugin.bloatware_key == "nokia"

    def test_flash_sequence(self, nokia_device_info):
        steps = self.plugin.get_flash_sequence(nokia_device_info, "/sys.img", "/vb.img")
        assert len(steps) == 4

    def test_update_sequence(self, nokia_device_info):
        steps = self.plugin.get_update_sequence(nokia_device_info, "/sys.img", "/vb.img")
        step_types = [s.step_type.value for s in steps]
        assert "wipe" not in step_types

    def test_usb_quirks_no_fastbootd(self):
        quirks = self.plugin.get_usb_quirks()
        assert quirks["use_fastbootd"] is False


class TestSamsungPlugin:
    def setup_method(self):
        self.plugin = SamsungPlugin()

    def test_detect_samsung(self, samsung_device_info):
        assert self.plugin.detect(samsung_device_info) is True

    def test_supports_flash_false(self):
        assert self.plugin.supports_flash is False

    def test_flash_sequence_raises(self, samsung_device_info):
        with pytest.raises(NotImplementedError):
            self.plugin.get_flash_sequence(samsung_device_info, "/s.img", "/v.img")

    def test_uses_odin_quirk(self):
        quirks = self.plugin.get_usb_quirks()
        assert quirks["uses_odin"] is True

    def test_bloatware_key(self):
        assert self.plugin.bloatware_key == "samsung"
