"""Tests for stalkerware scanner."""

from __future__ import annotations

from phonectl.core.stalkerware import scan_for_stalkerware


class TestStalkerwareScanner:
    def test_no_match_on_clean_device(self):
        packages = ["com.google.android.gms", "com.whatsapp", "org.mozilla.firefox"]
        results = scan_for_stalkerware(packages)
        assert results == []

    def test_detect_known_stalkerware(self):
        packages = ["com.google.android.gms", "com.flexispy.app"]
        results = scan_for_stalkerware(packages)
        assert len(results) >= 1
        assert any(r["name"] == "FlexiSpy" for r in results)

    def test_empty_package_list(self):
        results = scan_for_stalkerware([])
        assert results == []

    def test_cerberus_detection(self):
        packages = ["com.lsdroid.cerberus"]
        results = scan_for_stalkerware(packages)
        assert len(results) >= 1
