"""Tests for SafetyGuard pre-flash checks and VNDK compatibility."""

from __future__ import annotations

import pytest

from phonectl.core.safety import SafetyGuard, VNDK_GSI_COMPAT


class TestVNDKCompatibility:
    def test_vndk_31_allows_bp2a(self):
        allowed = VNDK_GSI_COMPAT.get("31", [])
        assert "BP2A" in allowed

    def test_vndk_30_allows_bp2a(self):
        allowed = VNDK_GSI_COMPAT.get("30", [])
        assert "BP2A" in allowed

    def test_vndk_27_limited_to_legacy(self):
        allowed = VNDK_GSI_COMPAT.get("27", [])
        assert "BP2A" not in allowed
        assert "RP1A" in allowed

    def test_unknown_vndk_returns_empty(self):
        allowed = VNDK_GSI_COMPAT.get("99", [])
        assert allowed == []


class TestPreFlashCheck:
    def test_unlocked_bootloader_passes(self, moto_device_info):
        guard = SafetyGuard()
        report = guard.pre_flash_check(moto_device_info, "BP2A.250605.031.A3")
        bootloader_check = next(c for c in report.checks if c["name"] == "Bootloader unlocked")
        assert bootloader_check["passed"] is True

    def test_locked_bootloader_fails(self, samsung_device_info):
        guard = SafetyGuard()
        report = guard.pre_flash_check(samsung_device_info, "BP2A.250605.031.A3")
        bootloader_check = next(c for c in report.checks if c["name"] == "Bootloader unlocked")
        assert bootloader_check["passed"] is False

    def test_treble_check(self, moto_device_info):
        guard = SafetyGuard()
        report = guard.pre_flash_check(moto_device_info, "BP2A.250605.031.A3")
        treble_check = next(c for c in report.checks if c["name"] == "Project Treble")
        assert treble_check["passed"] is True

    def test_arch_check_arm64(self, moto_device_info):
        guard = SafetyGuard()
        report = guard.pre_flash_check(moto_device_info, "BP2A.250605.031.A3")
        arch_check = next(c for c in report.checks if c["name"] == "Architecture")
        assert arch_check["passed"] is True

    def test_vndk_compatibility_check(self, moto_device_info):
        guard = SafetyGuard()
        report = guard.pre_flash_check(moto_device_info, "BP2A.250605.031.A3")
        vndk_check = next(c for c in report.checks if c["name"] == "VNDK compatibility")
        assert vndk_check["passed"] is True


class TestKernelVersionCheck:
    def test_kernel_5_4_ok_for_android16(self):
        guard = SafetyGuard()
        ok, detail = guard._check_kernel_version("5.4.147-perf+", "BP2A.250605.031.A3")
        assert ok is True

    def test_kernel_4_4_fails_for_android16(self):
        guard = SafetyGuard()
        ok, detail = guard._check_kernel_version("4.4.0", "BP2A.250605.031.A3")
        assert ok is False
        assert "TOO OLD" in detail

    def test_kernel_4_19_ok_for_android13(self):
        guard = SafetyGuard()
        ok, detail = guard._check_kernel_version("4.19.191", "TQ3A.230905.001")
        assert ok is True

    def test_unparseable_kernel_passes(self):
        guard = SafetyGuard()
        ok, detail = guard._check_kernel_version("unknown-kernel", "BP2A.250605.031.A3")
        assert ok is True


class TestVNDKNamespaceIsolation:
    def test_vndklite_blocks_cross_version(self, vndklite_device_info):
        """VNDKLite device running Android 12 cannot flash Android 16 GSI."""
        guard = SafetyGuard()
        report = guard.pre_flash_check(vndklite_device_info, "BP2A.250605.031.A3")
        check = next(c for c in report.checks if c["name"] == "VNDK namespace isolation")
        assert check["passed"] is False
        assert "VNDKLite" in check["detail"]

    def test_vndklite_allows_same_version(self, vndklite_device_info):
        """VNDKLite device running Android 12 can flash Android 12L GSI."""
        guard = SafetyGuard()
        report = guard.pre_flash_check(vndklite_device_info, "SQ3A.220705.001")
        check = next(c for c in report.checks if c["name"] == "VNDK namespace isolation")
        assert check["passed"] is True

    def test_full_isolation_allows_cross_version(self, moto_device_info):
        """Fully isolated VNDK device can cross-version flash."""
        guard = SafetyGuard()
        report = guard.pre_flash_check(moto_device_info, "BP2A.250605.031.A3")
        check = next(c for c in report.checks if c["name"] == "VNDK namespace isolation")
        assert check["passed"] is True
        assert "Full VNDK isolation" in check["detail"]


class TestAVBPreFlashCheck:
    def test_orange_avb_passes(self, moto_device_info):
        """Unlocked device (orange) passes AVB check."""
        moto_device_info.verified_boot_state = "orange"
        guard = SafetyGuard()
        report = guard.pre_flash_check(moto_device_info, "BP2A.250605.031.A3")
        check = next(c for c in report.checks if c["name"] == "AVB verified boot")
        assert check["passed"] is True

    def test_green_avb_fails(self, moto_device_info):
        """Locked/verified device (green) fails AVB check."""
        moto_device_info.verified_boot_state = "green"
        guard = SafetyGuard()
        report = guard.pre_flash_check(moto_device_info, "BP2A.250605.031.A3")
        check = next(c for c in report.checks if c["name"] == "AVB verified boot")
        assert check["passed"] is False
        assert "GREEN" in check["detail"]


class TestUSBKeywords:
    def test_usb_keywords_include_nokia(self):
        guard = SafetyGuard()
        import subprocess
        from unittest.mock import patch, MagicMock

        mock_result = MagicMock()
        mock_result.stdout = "Bus 001 Device 005: ID 2e04:c026 Nokia"
        with patch.object(subprocess, "run", return_value=mock_result):
            assert guard.check_usb_connected() is True

    def test_usb_keywords_include_motorola(self):
        guard = SafetyGuard()
        import subprocess
        from unittest.mock import patch, MagicMock

        mock_result = MagicMock()
        mock_result.stdout = "Bus 001 Device 003: ID 22b8:2e81 Motorola"
        with patch.object(subprocess, "run", return_value=mock_result):
            assert guard.check_usb_connected() is True
