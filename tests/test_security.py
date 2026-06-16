"""Tests for SecurityGuard scoring and VPN check fix."""

from __future__ import annotations

from unittest.mock import MagicMock

from phonectl.core.security import SecurityGuard, SecurityReport


class TestSecurityScoring:
    def test_all_pass_gives_100(self, mock_adb):
        mock_adb.shell.side_effect = lambda cmd, **kw: {
            "dumpsys connectivity | grep -i vpn | head -5": "VpnTransport CONNECTED",
            "settings get global http_proxy": ":0",
            "settings get global private_dns_mode": "hostname",
            "getprop net.dns1": "8.8.8.8",
            "getprop net.dns2": "8.8.4.4",
            "settings get global bluetooth_on": "0",
            "dumpsys connectivity | grep -i tether | head -3": "",
            "settings get global nfc_on": "0",
            "settings get global captive_portal_mode": "1",
            "ls /data/misc/user/0/cacerts-added/ 2>/dev/null": "",
            "getprop service.adb.tcp.port": "-1",
            "settings get secure lockscreen.password_type": "327680",
            "settings get secure lock_screen_lock_after_timeout": "30000",
            "dumpsys fingerprint | head -5": "enrolled",
            "dumpsys trust | grep -c 'agent' 2>/dev/null || echo 0": "1",
            "settings get global oem_unlock_allowed": "0",
            "settings get secure location_mode": "3",
            "settings get global verifier_verify_adb_installs": "1",
            "settings get secure install_non_market_apps": "0",
            "dumpsys package | grep 'SYSTEM_ALERT_WINDOW.*granted=true' | wc -l": "1",
            "settings get secure enabled_notification_listeners": "null",
        }.get(cmd, "")

        guard = SecurityGuard(mock_adb)
        report = guard.run_all()
        assert report.score == 100

    def test_vpn_inactive_reduces_score(self, mock_adb):
        mock_adb.shell.return_value = ""
        guard = SecurityGuard(mock_adb)
        report = guard.run_all(categories=["network"])
        vpn_check = next(c for c in report.checks if c.name == "VPN active")
        assert vpn_check.passed is False

    def test_vpn_active_passes(self, mock_adb):
        def shell_mock(cmd, **kw):
            if "vpn" in cmd.lower():
                return "VpnTransport CONNECTED"
            return ""
        mock_adb.shell.side_effect = shell_mock

        guard = SecurityGuard(mock_adb)
        report = guard.run_all(categories=["network"])
        vpn_check = next(c for c in report.checks if c.name == "VPN active")
        assert vpn_check.passed is True


class TestSecurityReportRating:
    def test_excellent_rating(self):
        report = SecurityReport(score=95)
        assert report.rating == "EXCELLENT"

    def test_good_rating(self):
        report = SecurityReport(score=75)
        assert report.rating == "GOOD"

    def test_fair_rating(self):
        report = SecurityReport(score=55)
        assert report.rating == "FAIR"

    def test_poor_rating(self):
        report = SecurityReport(score=35)
        assert report.rating == "POOR"

    def test_critical_rating(self):
        report = SecurityReport(score=10)
        assert report.rating == "CRITICAL"
