"""Shared test fixtures — mock ADB/Fastboot clients and device info."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from phonectl.core.device import DeviceInfo, DeviceState


@pytest.fixture
def mock_adb():
    """A mock ADBClient that returns configurable shell output."""
    adb = MagicMock()
    adb.shell.return_value = ""
    return adb


@pytest.fixture
def moto_device_info() -> DeviceInfo:
    """DeviceInfo for a Motorola Moto G71 5G (corfur)."""
    return DeviceInfo(
        serial="ZY22XXXX",
        state=DeviceState.ANDROID,
        manufacturer="motorola",
        model="moto g71 5G",
        codename="corfur",
        android_version="12",
        sdk_version="32",
        security_patch="2023-01-01",
        build_id="S2SN32.73-22-3-2",
        kernel_version="5.4.147-perf+",
        vndk_version="31",
        slot_suffix="_a",
        slot_count="2",
        is_unlocked=True,
        treble_enabled=True,
        dynamic_partitions=True,
        cpu_abi="arm64-v8a",
        board_platform="lahaina",
        ram_total_mb=6144,
        storage_total_gb=128.0,
        storage_free_gb=70.0,
        opengl_version="196610",
        battery_level="85",
        first_api_level="31",
        vendor_security_patch="2023-01-01",
    )


@pytest.fixture
def samsung_device_info() -> DeviceInfo:
    """DeviceInfo for a Samsung device."""
    return DeviceInfo(
        serial="R58M12345",
        state=DeviceState.ANDROID,
        manufacturer="samsung",
        model="Galaxy A52",
        codename="a52q",
        android_version="13",
        sdk_version="33",
        vndk_version="33",
        is_unlocked=False,
        treble_enabled=True,
        dynamic_partitions=True,
        cpu_abi="arm64-v8a",
        ram_total_mb=6144,
        storage_total_gb=128.0,
        storage_free_gb=60.0,
        first_api_level="30",
    )


@pytest.fixture
def nokia_device_info() -> DeviceInfo:
    """DeviceInfo for a Nokia 6.1 (PL2)."""
    return DeviceInfo(
        serial="NOKIA12345",
        state=DeviceState.ANDROID,
        manufacturer="HMD Global",
        model="Nokia 6.1",
        codename="PL2",
        android_version="10",
        sdk_version="29",
        vndk_version="29",
        is_unlocked=True,
        treble_enabled=True,
        dynamic_partitions=False,
        cpu_abi="arm64-v8a",
        ram_total_mb=4096,
        storage_total_gb=64.0,
        storage_free_gb=30.0,
        first_api_level="27",
    )


@pytest.fixture
def vndklite_device_info() -> DeviceInfo:
    """DeviceInfo for a VNDKLite device (non-isolated vendor namespace)."""
    return DeviceInfo(
        serial="VNDKLITE123",
        state=DeviceState.ANDROID,
        manufacturer="motorola",
        model="moto g31",
        codename="cofud",
        android_version="12",
        sdk_version="32",
        vndk_version="31",
        vndk_lite=True,
        is_unlocked=True,
        treble_enabled=True,
        dynamic_partitions=True,
        cpu_abi="arm64-v8a",
        ram_total_mb=4096,
        storage_total_gb=64.0,
        storage_free_gb=30.0,
        first_api_level="31",
        kernel_version="5.4.147",
        battery_level="80",
        slot_count="2",
        slot_suffix="_a",
        opengl_version="196610",
    )


@pytest.fixture
def pixel_device_info() -> DeviceInfo:
    """DeviceInfo for a Google Pixel device."""
    return DeviceInfo(
        serial="PIXEL12345",
        state=DeviceState.ANDROID,
        manufacturer="Google",
        model="Pixel 6",
        codename="oriole",
        android_version="14",
        sdk_version="34",
        vndk_version="34",
        is_unlocked=True,
        treble_enabled=True,
        dynamic_partitions=True,
        cpu_abi="arm64-v8a",
        ram_total_mb=8192,
        storage_total_gb=128.0,
        storage_free_gb=80.0,
        first_api_level="31",
        extra={"vendor_fingerprint": "google/oriole/oriole:14/UP1A.231105.001/10817346:user/release-keys"},
    )
