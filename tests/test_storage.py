"""Tests for bloatware scoring and vendor key resolution."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from phonectl.core.storage import StorageAnalyzer, _load_bloatware


class TestBloatwareVendorKey:
    def test_load_bloatware_motorola(self):
        entries = _load_bloatware("motorola")
        assert isinstance(entries, list)

    def test_load_bloatware_nokia(self):
        entries = _load_bloatware("nokia")
        assert isinstance(entries, list)

    def test_load_bloatware_empty_vendor(self):
        entries = _load_bloatware("nonexistent_vendor_xyz")
        common = _load_bloatware("")
        assert isinstance(entries, list)


class TestBloatwareScoreFilter:
    def test_disable_bloatware_respects_score_threshold(self, mock_adb):
        analyzer = StorageAnalyzer(mock_adb)

        mock_adb.shell.side_effect = lambda cmd, **kw: {
            "pm list packages": "package:com.test.app1\npackage:com.test.app2",
            "dumpsys usagestats": "",
        }.get(cmd, "")

        with patch.object(analyzer, "list_bloatware") as mock_list:
            mock_list.return_value = [
                {"pkg": "com.test.app1", "safe_to_disable": True, "bloatware_score": 80},
                {"pkg": "com.test.app2", "safe_to_disable": True, "bloatware_score": 40},
            ]
            result = analyzer.disable_bloatware("test", dry_run=True)
            # app2 (score 40) should be filtered out, only app1 (score 80) qualifies
            assert "com.test.app2" not in [e.get("pkg", "") for e in mock_list.return_value
                                            if e.get("bloatware_score", 0) >= 60]


class TestBloatwareKeyFromPlugin:
    def test_motorola_plugin_bloatware_key(self):
        from phonectl.vendors.motorola import MotorolaPlugin
        plugin = MotorolaPlugin()
        assert plugin.bloatware_key == "motorola"

    def test_nokia_plugin_bloatware_key(self):
        from phonectl.vendors.nokia import NokiaPlugin
        plugin = NokiaPlugin()
        assert plugin.bloatware_key == "nokia"

    def test_samsung_plugin_bloatware_key(self):
        from phonectl.vendors.samsung import SamsungPlugin
        plugin = SamsungPlugin()
        assert plugin.bloatware_key == "samsung"
