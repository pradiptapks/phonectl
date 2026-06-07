"""Network and phone security checks, scoring, and hardening."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

if TYPE_CHECKING:
    from phonectl.core.adb import ADBClient
    from phonectl.core.device import DeviceInfo

console = Console()

HARDENING_BACKUP = Path.home() / ".phonectl" / "security_backup.json"

LOCK_TYPE_MAP = {
    "65536": "None",
    "131072": "PIN",
    "196608": "PIN",
    "262144": "Pattern",
    "327680": "Password",
    "393216": "Password",
    "524288": "Biometric",
}


@dataclass
class SecurityCheck:
    name: str
    category: str
    passed: bool
    score_weight: int
    detail: str
    fix_cmd: str = ""
    fix_description: str = ""


@dataclass
class SecurityReport:
    checks: list[SecurityCheck] = field(default_factory=list)
    score: int = 0
    max_score: int = 0

    def checks_by_category(self) -> dict[str, list[SecurityCheck]]:
        cats: dict[str, list[SecurityCheck]] = {}
        for c in self.checks:
            cats.setdefault(c.category, []).append(c)
        return cats

    @property
    def rating(self) -> str:
        if self.score >= 90:
            return "EXCELLENT"
        if self.score >= 70:
            return "GOOD"
        if self.score >= 50:
            return "FAIR"
        if self.score >= 30:
            return "POOR"
        return "CRITICAL"

    @property
    def fixable_checks(self) -> list[SecurityCheck]:
        return [c for c in self.checks if not c.passed and c.fix_cmd]


class SecurityGuard:
    """Comprehensive phone and network security assessment."""

    def __init__(self, adb: ADBClient):
        self.adb = adb

    def run_all(self, categories: list[str] | None = None) -> SecurityReport:
        """Run security checks, optionally filtered by category."""
        report = SecurityReport()
        all_checks = []

        checkers = {
            "network": self._check_network,
            "lockscreen": self._check_lockscreen,
            "apps": self._check_apps,
        }

        targets = categories if categories else list(checkers.keys())
        for cat in targets:
            if cat in checkers:
                all_checks.extend(checkers[cat]())

        report.checks = all_checks
        report.max_score = sum(c.score_weight for c in all_checks)
        earned = sum(c.score_weight for c in all_checks if c.passed)
        report.score = round((earned / report.max_score) * 100) if report.max_score else 0
        return report

    # ── Network Security ──

    def _check_network(self) -> list[SecurityCheck]:
        checks = []

        # 1. VPN status
        try:
            vpn_out = self.adb.shell("dumpsys connectivity | grep -i vpn | head -5")
            vpn_active = "CONNECTED" in vpn_out.upper() or "VpnTransport" in vpn_out
        except Exception:
            vpn_active = False
        checks.append(SecurityCheck(
            name="VPN active", category="Network", passed=True,
            score_weight=3,
            detail="VPN connection active" if vpn_active else "No VPN — traffic is unencrypted on public WiFi",
        ))

        # 2. HTTP proxy
        try:
            proxy = self.adb.shell("settings get global http_proxy").strip()
        except Exception:
            proxy = ""
        proxy_set = proxy and proxy != "null" and proxy != ":0"
        checks.append(SecurityCheck(
            name="HTTP proxy", category="Network",
            passed=not proxy_set, score_weight=5,
            detail=f"Proxy set: {proxy} — traffic may be intercepted" if proxy_set else "No proxy configured",
        ))

        # 3. Private DNS
        try:
            dns_mode = self.adb.shell("settings get global private_dns_mode").strip()
        except Exception:
            dns_mode = ""
        dns_ok = dns_mode in ("hostname", "opportunistic")
        checks.append(SecurityCheck(
            name="Private DNS (DNS-over-TLS)", category="Network",
            passed=dns_ok, score_weight=4,
            detail=f"Mode: {dns_mode}" + (" — DNS queries encrypted" if dns_ok else " — DNS queries visible to network"),
        ))

        # 4. Custom DNS servers
        try:
            dns1 = self.adb.shell("getprop net.dns1").strip()
            dns2 = self.adb.shell("getprop net.dns2").strip()
        except Exception:
            dns1, dns2 = "", ""
        known_dns = {"8.8.8.8", "8.8.4.4", "1.1.1.1", "1.0.0.1", "9.9.9.9", ""}
        custom_dns = (dns1 not in known_dns) or (dns2 not in known_dns)
        checks.append(SecurityCheck(
            name="DNS servers", category="Network",
            passed=not custom_dns, score_weight=3,
            detail=f"DNS1: {dns1 or 'default'}, DNS2: {dns2 or 'default'}" +
                   (" — non-standard DNS, verify these are trusted" if custom_dns else ""),
        ))

        # 5. Bluetooth
        try:
            bt = self.adb.shell("settings get global bluetooth_on").strip()
        except Exception:
            bt = "0"
        checks.append(SecurityCheck(
            name="Bluetooth", category="Network",
            passed=True, score_weight=2,
            detail="Enabled" if bt == "1" else "Disabled",
        ))

        # 6. Hotspot/tethering
        try:
            tether = self.adb.shell("dumpsys connectivity | grep -i tether | head -3")
            hotspot_on = "TETHERED" in tether.upper()
        except Exception:
            hotspot_on = False
        checks.append(SecurityCheck(
            name="Hotspot/tethering", category="Network",
            passed=not hotspot_on, score_weight=2,
            detail="ACTIVE — device sharing network" if hotspot_on else "Inactive",
        ))

        # 7. NFC
        try:
            nfc = self.adb.shell("settings get global nfc_on").strip()
        except Exception:
            nfc = "0"
        checks.append(SecurityCheck(
            name="NFC", category="Network",
            passed=True, score_weight=1,
            detail="Enabled" if nfc == "1" else "Disabled",
        ))

        # 8. Captive portal detection
        try:
            captive = self.adb.shell("settings get global captive_portal_mode").strip()
        except Exception:
            captive = "1"
        captive_ok = captive != "0"
        checks.append(SecurityCheck(
            name="Captive portal detection", category="Network",
            passed=captive_ok, score_weight=3,
            detail="Enabled — detects rogue WiFi portals" if captive_ok
                   else "DISABLED — cannot detect fake WiFi login pages",
            fix_cmd="settings put global captive_portal_mode 1",
            fix_description="Enable captive portal detection",
        ))

        # 9. User-installed CA certificates
        try:
            certs = self.adb.shell("ls /data/misc/user/0/cacerts-added/ 2>/dev/null")
            cert_count = len([l for l in certs.splitlines() if l.strip()])
        except Exception:
            cert_count = 0
        checks.append(SecurityCheck(
            name="User CA certificates", category="Network",
            passed=cert_count == 0, score_weight=8,
            detail=f"{cert_count} user-installed CA certificates — MITM interception possible"
                   if cert_count else "No user-installed certificates",
        ))

        # 10. ADB over network
        try:
            adb_tcp = self.adb.shell("getprop service.adb.tcp.port").strip()
        except Exception:
            adb_tcp = ""
        adb_exposed = adb_tcp not in ("", "-1", "0")
        checks.append(SecurityCheck(
            name="ADB over network", category="Network",
            passed=not adb_exposed, score_weight=8,
            detail=f"EXPOSED on port {adb_tcp} — remote access possible" if adb_exposed
                   else "Disabled (USB only)",
            fix_cmd="setprop service.adb.tcp.port -1",
            fix_description="Disable ADB over network",
        ))

        return checks

    # ── Lock Screen & Auth ──

    def _check_lockscreen(self) -> list[SecurityCheck]:
        checks = []

        # 1. Lock screen type
        try:
            lock_type_raw = self.adb.shell("settings get secure lockscreen.password_type").strip()
        except Exception:
            lock_type_raw = ""
        lock_name = LOCK_TYPE_MAP.get(lock_type_raw, f"Type {lock_type_raw}")
        has_lock = lock_type_raw not in ("", "65536", "-1", "null")
        checks.append(SecurityCheck(
            name="Screen lock type", category="Lock Screen",
            passed=has_lock, score_weight=10,
            detail=f"{lock_name}" + ("" if has_lock else " — NO SCREEN LOCK SET"),
        ))

        # 2. Lock timeout
        try:
            timeout = self.adb.shell("settings get secure lock_screen_lock_after_timeout").strip()
            timeout_ms = int(timeout) if timeout and timeout != "null" else 0
            timeout_sec = timeout_ms // 1000
        except Exception:
            timeout_sec = 0
            timeout_ms = 0
        timeout_ok = 0 < timeout_sec <= 60
        checks.append(SecurityCheck(
            name="Lock timeout", category="Lock Screen",
            passed=timeout_ok, score_weight=5,
            detail=f"{timeout_sec}s" + ("" if timeout_ok else " — too long, should be 30-60s"),
            fix_cmd="settings put secure lock_screen_lock_after_timeout 30000",
            fix_description="Set lock timeout to 30 seconds",
        ))

        # 3. Biometric
        try:
            fingerprint = self.adb.shell("dumpsys fingerprint | head -5")
            bio_enrolled = "enrolled" in fingerprint.lower() or "numFingerprints" in fingerprint
        except Exception:
            bio_enrolled = False
        checks.append(SecurityCheck(
            name="Biometric enrolled", category="Lock Screen",
            passed=bio_enrolled, score_weight=4,
            detail="Fingerprint enrolled" if bio_enrolled else "No biometrics — recommend setting up fingerprint",
        ))

        # 4. Smart Lock (trusted agents)
        try:
            trust = self.adb.shell("dumpsys trust | grep -c 'agent' 2>/dev/null || echo 0").strip()
            trust_count = int(trust) if trust.isdigit() else 0
        except Exception:
            trust_count = 0
        checks.append(SecurityCheck(
            name="Smart Lock agents", category="Lock Screen",
            passed=trust_count <= 2, score_weight=3,
            detail=f"{trust_count} trusted agents" +
                   (" — many agents weaken lock screen" if trust_count > 2 else ""),
        ))

        # 5. OEM unlock allowed
        try:
            oem_unlock = self.adb.shell("settings get global oem_unlock_allowed").strip()
        except Exception:
            oem_unlock = "0"
        checks.append(SecurityCheck(
            name="OEM unlock allowed", category="Lock Screen",
            passed=oem_unlock != "1", score_weight=3,
            detail="ENABLED — bootloader can be unlocked (risk if device is stolen)"
                   if oem_unlock == "1" else "Disabled",
        ))

        # 6. Location mode
        try:
            location = self.adb.shell("settings get secure location_mode").strip()
        except Exception:
            location = "0"
        loc_modes = {"0": "Off", "1": "Sensors only", "2": "Battery saving", "3": "High accuracy"}
        checks.append(SecurityCheck(
            name="Location services", category="Lock Screen",
            passed=True, score_weight=1,
            detail=f"Mode: {loc_modes.get(location, location)}",
        ))

        return checks

    # ── App Security ──

    def _check_apps(self) -> list[SecurityCheck]:
        checks = []

        # 1. App verification
        try:
            verify = self.adb.shell("settings get global verifier_verify_adb_installs").strip()
        except Exception:
            verify = "0"
        checks.append(SecurityCheck(
            name="App verification (ADB installs)", category="App Security",
            passed=verify == "1", score_weight=5,
            detail="Enabled — sideloaded apps are scanned" if verify == "1"
                   else "DISABLED — sideloaded apps are NOT scanned for malware",
            fix_cmd="settings put global verifier_verify_adb_installs 1",
            fix_description="Enable app verification for ADB installs",
        ))

        # 2. Unknown sources
        try:
            sideload = self.adb.shell("settings get secure install_non_market_apps").strip()
        except Exception:
            sideload = "0"
        checks.append(SecurityCheck(
            name="Unknown sources (sideloading)", category="App Security",
            passed=sideload != "1", score_weight=5,
            detail="ENABLED — untrusted APKs can be installed" if sideload == "1" else "Disabled",
            fix_cmd="settings put secure install_non_market_apps 0",
            fix_description="Disable unknown sources",
        ))

        # 3. Overlay (draw over other apps)
        try:
            overlay_out = self.adb.shell("dumpsys package | grep 'SYSTEM_ALERT_WINDOW.*granted=true' | wc -l").strip()
            overlay_count = int(overlay_out) if overlay_out.isdigit() else 0
        except Exception:
            overlay_count = 0
        checks.append(SecurityCheck(
            name="Overlay permission", category="App Security",
            passed=overlay_count <= 3, score_weight=4,
            detail=f"{overlay_count} apps can draw over others" +
                   (" — phishing risk" if overlay_count > 3 else ""),
        ))

        # 4. Notification listeners
        try:
            listeners = self.adb.shell("settings get secure enabled_notification_listeners").strip()
        except Exception:
            listeners = ""
        listener_ok = not listeners or listeners == "null"
        listener_apps = listeners.split(":") if listeners and listeners != "null" else []
        checks.append(SecurityCheck(
            name="Notification listeners", category="App Security",
            passed=len(listener_apps) <= 2, score_weight=5,
            detail=f"{len(listener_apps)} apps reading notifications" +
                   (" — can see OTPs, password resets" if len(listener_apps) > 2 else "")
                   if listener_apps else "None",
        ))

        # 5. SMS permission (non-messaging apps)
        try:
            sms_out = self.adb.shell(
                "dumpsys package | grep -B1 'android.permission.RECEIVE_SMS.*granted=true' | "
                "grep 'Package \\[' | head -10"
            )
            sms_apps = re.findall(r'Package \[([^\]]+)\]', sms_out)
            messaging_apps = {"com.google.android.apps.messaging", "com.android.mms",
                              "com.whatsapp", "com.samsung.android.messaging"}
            suspicious_sms = [a for a in sms_apps if a not in messaging_apps and not a.startswith("com.android.")]
        except Exception:
            suspicious_sms = []
        checks.append(SecurityCheck(
            name="SMS access", category="App Security",
            passed=len(suspicious_sms) == 0, score_weight=5,
            detail=f"{len(suspicious_sms)} non-messaging apps with SMS access"
                   + (f": {', '.join(suspicious_sms[:5])}" if suspicious_sms else ""),
        ))

        # 6. Auto-sync
        try:
            sync = self.adb.shell("settings get global auto_sync").strip()
        except Exception:
            sync = "1"
        checks.append(SecurityCheck(
            name="Auto-sync", category="App Security",
            passed=True, score_weight=1,
            detail="Enabled — data syncs to cloud" if sync == "1" else "Disabled",
        ))

        # 7. Find My Device
        try:
            fmd = self.adb.shell("pm list packages | grep -c 'com.google.android.gms'").strip()
            fmd_present = fmd != "0"
        except Exception:
            fmd_present = False
        checks.append(SecurityCheck(
            name="Find My Device (GMS)", category="App Security",
            passed=fmd_present, score_weight=3,
            detail="Available (Google Play Services present)" if fmd_present else "NOT available — device cannot be remotely located",
        ))

        return checks

    # ── Hardening ──

    def harden(self, dry_run: bool = False) -> list[dict]:
        """Apply security fixes for failed checks."""
        report = self.run_all()
        fixable = report.fixable_checks

        if not fixable:
            console.print("[green]No fixable security issues found.[/]")
            return []

        if not dry_run:
            self._backup_settings(fixable)

        actions = []
        for check in fixable:
            if dry_run:
                console.print(f"  [dim]WOULD FIX[/] {check.name}: {check.fix_description}")
                actions.append({"name": check.name, "action": "dry-run", "cmd": check.fix_cmd})
            else:
                try:
                    self.adb.shell(check.fix_cmd)
                    console.print(f"  [green]FIXED[/] {check.name}: {check.fix_description}")
                    actions.append({"name": check.name, "action": "applied", "cmd": check.fix_cmd})
                except Exception as exc:
                    console.print(f"  [red]FAILED[/] {check.name}: {exc}")
                    actions.append({"name": check.name, "action": "failed", "error": str(exc)})

        return actions

    def _backup_settings(self, checks: list[SecurityCheck]) -> None:
        """Save original values before hardening."""
        HARDENING_BACKUP.parent.mkdir(parents=True, exist_ok=True)
        if HARDENING_BACKUP.exists():
            return
        backup = {}
        for check in checks:
            if "settings put" in check.fix_cmd:
                parts = check.fix_cmd.split()
                if len(parts) >= 5:
                    namespace, key = parts[2], parts[3]
                    try:
                        val = self.adb.shell(f"settings get {namespace} {key}").strip()
                        backup[f"{namespace}.{key}"] = val
                    except Exception:
                        pass
        HARDENING_BACKUP.write_text(json.dumps(backup, indent=2))
        console.print(f"[dim]Original settings backed up to {HARDENING_BACKUP}[/]")


def display_security_report(report: SecurityReport) -> None:
    """Display a formatted security report."""
    categories = report.checks_by_category()

    for cat_name, cat_checks in categories.items():
        table = Table(title=cat_name, show_header=True, box=None, padding=(0, 1))
        table.add_column("Check", style="cyan", min_width=30)
        table.add_column("Result", width=6)
        table.add_column("Wt", width=3)
        table.add_column("Detail")

        for c in cat_checks:
            result = "[green]PASS[/]" if c.passed else "[yellow]WARN[/]"
            table.add_row(c.name, result, str(c.score_weight), c.detail)

        console.print(table)
        console.print()

    # Score
    rating_styles = {
        "EXCELLENT": "bold green", "GOOD": "green",
        "FAIR": "yellow", "POOR": "red", "CRITICAL": "bold red",
    }
    style = rating_styles.get(report.rating, "white")

    console.print(Panel(
        f"  Security Score: [{style}]{report.score}/100 ({report.rating})[/]\n"
        f"  Checks passed:  {sum(1 for c in report.checks if c.passed)}/{len(report.checks)}\n"
        f"  Fixable issues: {len(report.fixable_checks)}"
        + (f"\n  Run: [cyan]phonectl security --harden[/] to auto-fix" if report.fixable_checks else ""),
        title="[bold]Security Score[/]",
        border_style=style.replace("bold ", ""),
    ))
