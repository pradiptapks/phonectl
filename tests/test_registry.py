"""Tests for centralized vendor registry."""

from __future__ import annotations

from phonectl.vendors.registry import create_device_manager


class TestVendorRegistry:
    def test_creates_device_manager(self):
        dm = create_device_manager()
        assert dm is not None

    def test_resolves_motorola(self, moto_device_info):
        dm = create_device_manager()
        vendor = dm.resolve_vendor(moto_device_info)
        assert vendor is not None
        assert vendor.name == "Motorola"

    def test_resolves_samsung(self, samsung_device_info):
        dm = create_device_manager()
        vendor = dm.resolve_vendor(samsung_device_info)
        assert vendor is not None
        assert vendor.name == "Samsung"

    def test_resolves_nokia(self, nokia_device_info):
        dm = create_device_manager()
        vendor = dm.resolve_vendor(nokia_device_info)
        assert vendor is not None
        assert "Nokia" in vendor.name

    def test_resolves_pixel(self, pixel_device_info):
        dm = create_device_manager()
        vendor = dm.resolve_vendor(pixel_device_info)
        assert vendor is not None
        assert "Pixel" in vendor.name
