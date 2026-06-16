"""Tests for the dynamic GSI compatibility fetcher."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml

from phonectl.firmware.compat_fetcher import CompatFetcher, _normalize_patch_date
from phonectl.firmware.gsi import GSIVersion, _merge_versions

# Sample HTML that mimics the real developer.android.com/topic/generic-system-image/releases page
SAMPLE_HTML = """
<h2>Android 17 QPR1 GSIs</h2>
<h3>Android 17 QPR1 (Beta)</h3>
<p>GSI binaries for Android 17 QPR1 Beta built from the same AOSP and GMS sources.</p>
<ul>
<li>Pixel 9</li>
<li>Pixel 10</li>
</ul>
<p>
Date: June 10, 2026
Build: CP31.260522.006
Security patch level: May 2026
Google Play Services: 26.18.35
</p>
<table>
<tr><th>Type</th><th>Download and SHA-256</th></tr>
<tr>
<td>ARM64+GMS</td>
<td>
<a href="https://dl.google.com/developers/android/cinnamonbun/images/gsi/gsi_gms_arm64-exp-CP31.260522.006-15591510-d37fa437.zip">
gsi_gms_arm64-exp-CP31.260522.006-15591510-d37fa437.zip</a>
d37fa4375aea219b97fff97fea61ffb30f4cf3b9ecaa51c73036b5c9b8b757c4
</td>
</tr>
</table>

<h2>Android 16 GSIs</h2>
<h3>Android 16 (stable release)</h3>
<p>GSI binaries for Android 16 stable release.</p>
<p>
Date: June 3, 2025
Build: BP2A.250605.031.A3
Security patch level: 2025-06-05
</p>
<table>
<tr><th>Type</th><th>Download and SHA-256</th></tr>
<tr>
<td>ARM64+GMS</td>
<td>
<a href="https://dl.google.com/developers/android/baklava/images/gsi/gsi_gms_arm64-exp-BP2A.250605.031.A3-13578795-38e52cb0.zip">
gsi_gms_arm64-exp-BP2A.250605.031.A3-13578795-38e52cb0.zip</a>
38e52cb0a3331a5ee0c653a4da2401ce74598a955acbd00aa85b6326036154c5
</td>
</tr>
</table>
"""


@pytest.fixture
def tmp_cache(tmp_path):
    """Provide a temporary cache directory for CompatFetcher."""
    return tmp_path / "gsi_cache"


class TestParseReleases:
    def test_extracts_build_ids(self, tmp_cache):
        fetcher = CompatFetcher(cache_dir=tmp_cache)
        entries = fetcher._parse_releases(SAMPLE_HTML)
        build_ids = [e["build_id"] for e in entries]
        assert "CP31.260522.006" in build_ids
        assert "BP2A.250605.031.A3" in build_ids

    def test_extracts_download_urls(self, tmp_cache):
        fetcher = CompatFetcher(cache_dir=tmp_cache)
        entries = fetcher._parse_releases(SAMPLE_HTML)
        by_id = {e["build_id"]: e for e in entries}

        cp31 = by_id["CP31.260522.006"]
        assert "dl.google.com" in cp31["download_url"]
        assert "CP31.260522.006" in cp31["download_url"]

    def test_extracts_sha256(self, tmp_cache):
        fetcher = CompatFetcher(cache_dir=tmp_cache)
        entries = fetcher._parse_releases(SAMPLE_HTML)
        by_id = {e["build_id"]: e for e in entries}

        cp31 = by_id["CP31.260522.006"]
        assert cp31["sha256"] == "d37fa4375aea219b97fff97fea61ffb30f4cf3b9ecaa51c73036b5c9b8b757c4"

    def test_detects_beta_status(self, tmp_cache):
        fetcher = CompatFetcher(cache_dir=tmp_cache)
        entries = fetcher._parse_releases(SAMPLE_HTML)
        by_id = {e["build_id"]: e for e in entries}

        assert by_id["CP31.260522.006"]["status"] == "beta"
        assert by_id["BP2A.250605.031.A3"]["status"] == "stable"

    def test_sets_min_vndk(self, tmp_cache):
        fetcher = CompatFetcher(cache_dir=tmp_cache)
        entries = fetcher._parse_releases(SAMPLE_HTML)
        by_id = {e["build_id"]: e for e in entries}

        assert by_id["CP31.260522.006"]["min_vndk"] == 33
        assert by_id["BP2A.250605.031.A3"]["min_vndk"] == 30

    def test_empty_html_returns_empty(self, tmp_cache):
        fetcher = CompatFetcher(cache_dir=tmp_cache)
        entries = fetcher._parse_releases("<html><body>Nothing here</body></html>")
        assert entries == []

    def test_normalizes_security_patch(self, tmp_cache):
        fetcher = CompatFetcher(cache_dir=tmp_cache)
        entries = fetcher._parse_releases(SAMPLE_HTML)
        by_id = {e["build_id"]: e for e in entries}

        bp2a = by_id["BP2A.250605.031.A3"]
        assert bp2a["security_patch"] == "2025-06-05"

        cp31 = by_id["CP31.260522.006"]
        assert cp31["security_patch"] == "2026-05-05"


class TestMergeVersions:
    def test_new_dynamic_entry_added(self):
        static = [
            GSIVersion(name="Android 16", build_id="BP2A.250605.031.A3",
                       security_patch="2025-06-05", status="stable",
                       download_url="https://old.url", sha256="old_hash"),
        ]
        dynamic = [
            {"name": "Android 17", "build_id": "CP31.260522.006",
             "security_patch": "2026-05-05", "status": "beta",
             "download_url": "https://new.url", "sha256": "new_hash",
             "min_vndk": 33, "notes": "Fetched"},
        ]
        merged = _merge_versions(static, dynamic)
        assert len(merged) == 2
        assert merged[1].build_id == "CP31.260522.006"

    def test_existing_entry_url_updated(self):
        static = [
            GSIVersion(name="Android 16", build_id="BP2A.250605.031.A3",
                       security_patch="2025-06-05", status="stable",
                       download_url="https://old.url", sha256="old_hash"),
        ]
        dynamic = [
            {"build_id": "BP2A.250605.031.A3",
             "download_url": "https://new.url", "sha256": "new_hash",
             "security_patch": "2025-07-05"},
        ]
        merged = _merge_versions(static, dynamic)
        assert len(merged) == 1
        assert merged[0].download_url == "https://new.url"
        assert merged[0].sha256 == "new_hash"
        assert merged[0].security_patch == "2025-07-05"

    def test_broken_status_preserved(self):
        static = [
            GSIVersion(name="Android 16 QPR2", build_id="BP4A.251205.006",
                       security_patch="2025-12-05", status="broken",
                       download_url="", sha256="",
                       notes="BROKEN on VNDK 30"),
        ]
        dynamic = [
            {"build_id": "BP4A.251205.006", "status": "stable",
             "download_url": "https://new.url", "sha256": "new_hash"},
        ]
        merged = _merge_versions(static, dynamic)
        assert merged[0].status == "broken"
        assert merged[0].download_url == "https://new.url"

    def test_static_notes_preserved(self):
        static = [
            GSIVersion(name="Android 16", build_id="BP2A.250605.031.A3",
                       security_patch="2025-06-05", status="stable",
                       download_url="", sha256="",
                       notes="Confirmed on Moto G71 5G"),
        ]
        dynamic = [
            {"build_id": "BP2A.250605.031.A3",
             "notes": "Fetched from developer.android.com"},
        ]
        merged = _merge_versions(static, dynamic)
        assert merged[0].notes == "Confirmed on Moto G71 5G"

    def test_empty_dynamic_returns_static(self):
        static = [
            GSIVersion(name="Android 16", build_id="BP2A.250605.031.A3",
                       security_patch="2025-06-05", status="stable",
                       download_url="", sha256=""),
        ]
        merged = _merge_versions(static, [])
        assert len(merged) == 1
        assert merged[0].build_id == "BP2A.250605.031.A3"


class TestCacheExpiry:
    def test_load_cached_returns_none_when_missing(self, tmp_cache):
        fetcher = CompatFetcher(cache_dir=tmp_cache)
        assert fetcher.load_cached() is None

    def test_load_cached_returns_data_when_fresh(self, tmp_cache):
        tmp_cache.mkdir(parents=True)
        versions = [{"name": "Test", "build_id": "XX1A.000000.001"}]
        (tmp_cache / "gsi_remote.yaml").write_text(
            yaml.dump({"versions": versions})
        )
        (tmp_cache / "gsi_remote.meta.json").write_text(json.dumps({
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source": "test",
            "count": 1,
        }))

        fetcher = CompatFetcher(cache_dir=tmp_cache)
        result = fetcher.load_cached()
        assert result is not None
        assert len(result) == 1
        assert result[0]["build_id"] == "XX1A.000000.001"

    def test_load_cached_returns_none_when_expired(self, tmp_cache):
        tmp_cache.mkdir(parents=True)
        versions = [{"name": "Test", "build_id": "XX1A.000000.001"}]
        (tmp_cache / "gsi_remote.yaml").write_text(
            yaml.dump({"versions": versions})
        )
        expired_time = datetime.now(timezone.utc) - timedelta(hours=25)
        (tmp_cache / "gsi_remote.meta.json").write_text(json.dumps({
            "fetched_at": expired_time.isoformat(),
            "source": "test",
            "count": 1,
        }))

        fetcher = CompatFetcher(cache_dir=tmp_cache)
        assert fetcher.load_cached() is None

    def test_is_stale_when_no_cache(self, tmp_cache):
        fetcher = CompatFetcher(cache_dir=tmp_cache)
        assert fetcher.is_stale() is True


class TestFetchNetworkError:
    def test_fetch_handles_connection_error(self, tmp_cache):
        fetcher = CompatFetcher(cache_dir=tmp_cache)
        with patch("phonectl.firmware.compat_fetcher.requests.get",
                    side_effect=Exception("Network error")):
            result = fetcher.fetch()
            assert result == []

    def test_fetch_handles_http_error(self, tmp_cache):
        fetcher = CompatFetcher(cache_dir=tmp_cache)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("404")
        with patch("phonectl.firmware.compat_fetcher.requests.get",
                    return_value=mock_resp):
            result = fetcher.fetch()
            assert result == []


class TestNormalizePatchDate:
    def test_already_formatted(self):
        assert _normalize_patch_date("2025-06-05") == "2025-06-05"

    def test_month_year_format(self):
        assert _normalize_patch_date("May 2026") == "2026-05-05"

    def test_full_month_year(self):
        assert _normalize_patch_date("June 2025") == "2025-06-05"

    def test_fallback_to_date_str(self):
        result = _normalize_patch_date("unknown", "June 10, 2026")
        assert result == "2026-06-05"
