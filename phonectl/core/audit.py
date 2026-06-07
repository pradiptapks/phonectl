"""Security audit and warranty estimation engine.

Performs non-root security checks (17 checks) and optional root-level
deep inspection (4 checks) to assess device integrity, detect stalkerware,
audit permissions, and estimate warranty/support status.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

if TYPE_CHECKING:
    from phonectl.core.adb import ADBClient
    from phonectl.core.device import DeviceInfo

console = Console()

RISK_THRESHOLDS = {"LOW": 0, "MEDIUM": 3, "HIGH": 6, "CRITICAL": 10}


@dataclass
class AuditCheck:
    name: str
    category: str
    passed: bool
    severity: str  # "info", "warning", "critical"
    detail: str
    requires_root: bool = False


@dataclass
class WarrantyReport:
    ship_year: int = 0
    device_age_years: float = 0.0
    warranty_years: int = 1
    warranty_expired: bool = True
    warranty_expiry_year: int = 0
    software_support_years: int = 3
    software_support_ended: bool = True
    last_vendor_patch: str = ""
    vendor_patch_age_days: int = 0
    safe_to_flash: bool = True
    manufacturer: str = ""
    summary: str = ""


@dataclass
class AuditReport:
    device_serial: str = ""
    device_model: str = ""
    device_codename: str = ""
    timestamp: str = ""
    warranty: WarrantyReport = field(default_factory=WarrantyReport)
    checks: list[AuditCheck] = field(default_factory=list)
    risk_level: str = "LOW"
    root_checks_run: bool = False
    root_available: bool = False

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def failed_count(self) -> int:
        return sum(1 for c in self.checks if not c.passed)

    @property
    def total_count(self) -> int:
        return len(self.checks)

    def checks_by_category(self) -> dict[str, list[AuditCheck]]:
        cats: dict[str, list[AuditCheck]] = {}
        for c in self.checks:
            cats.setdefault(c.category, []).append(c)
        return cats


# ═══════════════════════════════════════════════════════════════
# Warranty Estimator
# ═══════════════════════════════════════════════════════════════

API_TO_YEAR = {
    21: 2014, 22: 2015, 23: 2015, 24: 2016, 25: 2016,
    26: 2017, 27: 2017, 28: 2018, 29: 2019, 30: 2020,
    31: 2021, 32: 2022, 33: 2022, 34: 2023, 35: 2024, 36: 2025,
}

DEFAULT_WARRANTY = {"warranty_years": 1, "software_support_years": 3}


class WarrantyEstimator:
    """Estimate warranty and software support status from device properties."""

    def __init__(self, config_path: str | Path | None = None):
        self.config = self._load_config(config_path)

    def _load_config(self, config_path: str | Path | None) -> dict:
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config" / "warranty.yaml"
        path = Path(config_path)
        if path.exists():
            with open(path) as f:
                return yaml.safe_load(f) or {}
        return {}

    def estimate(self, info: DeviceInfo) -> WarrantyReport:
        report = WarrantyReport()
        report.manufacturer = info.manufacturer

        # Ship year from first API level
        api = int(info.first_api_level) if info.first_api_level and info.first_api_level.isdigit() else 0
        api_years = self.config.get("api_to_year", API_TO_YEAR)
        report.ship_year = api_years.get(api, api_years.get(str(api), 0))

        if not report.ship_year and info.extra.get("build_date"):
            try:
                bd = datetime.strptime(info.extra["build_date"][:10], "%Y-%m-%d")
                report.ship_year = bd.year
            except (ValueError, TypeError):
                pass

        if not report.ship_year:
            report.ship_year = 2020
            report.summary = "Unable to determine ship year — using estimate"

        now = datetime.now()
        report.device_age_years = round((now.year - report.ship_year) + (now.month / 12), 1)

        # Vendor warranty/support periods
        mfr = info.manufacturer.lower().strip()
        vendors_cfg = self.config.get("vendors", {})
        vendor_info = vendors_cfg.get(mfr, DEFAULT_WARRANTY)
        for key in vendors_cfg:
            if key.lower() in mfr or mfr in key.lower():
                vendor_info = vendors_cfg[key]
                break

        report.warranty_years = vendor_info.get("warranty_years", 1)
        report.software_support_years = vendor_info.get("software_support_years", 3)
        report.warranty_expiry_year = report.ship_year + report.warranty_years
        report.warranty_expired = now.year > report.warranty_expiry_year

        # Vendor patch age
        report.last_vendor_patch = info.vendor_security_patch or info.security_patch or ""
        if report.last_vendor_patch:
            try:
                patch_date = datetime.strptime(report.last_vendor_patch, "%Y-%m-%d")
                report.vendor_patch_age_days = (now - patch_date).days
                support_end_year = report.ship_year + report.software_support_years
                report.software_support_ended = now.year > support_end_year or report.vendor_patch_age_days > 365
            except ValueError:
                report.software_support_ended = True
        else:
            report.software_support_ended = True

        report.safe_to_flash = report.warranty_expired
        report.summary = self._build_summary(report)
        return report

    def _build_summary(self, r: WarrantyReport) -> str:
        if r.warranty_expired and r.software_support_ended:
            return "Device is out of warranty and no longer receiving OEM updates. Safe to flash."
        if r.warranty_expired and not r.software_support_ended:
            return "Warranty expired but OEM may still provide updates. Flash with caution."
        return "Device may still be under warranty. Flashing will void it."


# ═══════════════════════════════════════════════════════════════
# Security Scanner
# ═══════════════════════════════════════════════════════════════

class SecurityScanner:
    """Run security checks against a connected Android device."""

    def __init__(self, adb: ADBClient):
        self.adb = adb

    def run_all(self, info: DeviceInfo, deep: bool = False) -> list[AuditCheck]:
        checks = []
        checks += self._check_os_integrity(info)
        checks += self._check_root_and_mods(info)
        checks += self._check_stalkerware()
        checks += self._check_permissions()
        checks += self._check_network_exposure(info)
        if deep:
            checks += self._check_deep_root_scan()
        return checks

    def has_root(self) -> bool:
        try:
            result = self.adb.shell("su -c id")
            return "uid=0" in result
        except Exception:
            return False

    # ── Category A: OS Integrity ──

    def _check_os_integrity(self, info: DeviceInfo) -> list[AuditCheck]:
        checks = []

        # 1. Build signature
        build_tags = info.extra.get("build_tags", "")
        checks.append(AuditCheck(
            name="Build signature",
            category="OS Integrity",
            passed=build_tags == "release-keys",
            severity="critical" if build_tags == "test-keys" else "info",
            detail=f"{build_tags}" + (" — unsigned/test build detected" if build_tags != "release-keys" else ""),
        ))

        # 2. Verified boot state
        vb = info.verified_boot_state
        vb_ok = vb in ("green", "")
        vb_severity = "info" if vb in ("green", "orange", "") else "critical"
        detail_map = {
            "green": "Fully verified — stock boot chain",
            "orange": "Bootloader unlocked — custom images allowed",
            "yellow": "Custom key — non-OEM signing key in use",
            "red": "FAILED verification — boot chain compromised",
        }
        checks.append(AuditCheck(
            name="Verified boot state",
            category="OS Integrity",
            passed=vb != "red",
            severity=vb_severity,
            detail=f"{vb}: {detail_map.get(vb, 'Unknown state')}",
        ))

        # 3. Build type
        build_type = info.extra.get("build_type", "user")
        checks.append(AuditCheck(
            name="Build type",
            category="OS Integrity",
            passed=build_type == "user",
            severity="warning" if build_type != "user" else "info",
            detail=f"{build_type}" + (" — debug build has elevated access" if build_type != "user" else ""),
        ))

        # 4. SELinux
        selinux = info.extra.get("selinux_status", "")
        checks.append(AuditCheck(
            name="SELinux status",
            category="OS Integrity",
            passed=selinux.lower() == "enforcing",
            severity="critical" if selinux.lower() in ("permissive", "disabled") else "info",
            detail=f"{selinux}" + (" — security policies NOT enforced" if selinux.lower() != "enforcing" else ""),
        ))

        return checks

    # ── Category B: Root and Modification Detection ──

    def _check_root_and_mods(self, info: DeviceInfo) -> list[AuditCheck]:
        checks = []

        # 5. Root access
        root_available = self.has_root()
        checks.append(AuditCheck(
            name="Root access",
            category="Root/Modifications",
            passed=not root_available,
            severity="warning" if root_available else "info",
            detail="ROOT AVAILABLE — su binary present" if root_available else "Not rooted",
        ))

        # 6. Root management apps
        root_packages = ["com.topjohnwu.magisk", "eu.chainfire.supersu",
                         "me.weishu.kernelsu", "com.koushikdutta.superuser",
                         "com.noshufou.android.su", "com.thirdparty.superuser"]
        try:
            installed = self.adb.shell("pm list packages")
            found = [p for p in root_packages if p in installed]
        except Exception:
            found = []

        checks.append(AuditCheck(
            name="Root management apps",
            category="Root/Modifications",
            passed=len(found) == 0,
            severity="warning" if found else "info",
            detail=f"Found: {', '.join(found)}" if found else "None detected",
        ))

        # 7. Encryption
        crypto = info.extra.get("crypto_state", "")
        checks.append(AuditCheck(
            name="Device encryption",
            category="Root/Modifications",
            passed=crypto == "encrypted",
            severity="critical" if crypto and crypto != "encrypted" else "info",
            detail=crypto if crypto else "Unknown",
        ))

        # 8. Custom ROM detection
        build_fp = info.build_fingerprint
        vendor_fp = info.extra.get("vendor_fingerprint", "")
        if build_fp and vendor_fp:
            build_mfr = build_fp.split("/")[0] if "/" in build_fp else ""
            vendor_mfr = vendor_fp.split("/")[0] if "/" in vendor_fp else ""
            is_custom = build_mfr != vendor_mfr
        else:
            is_custom = False
        checks.append(AuditCheck(
            name="Custom ROM / GSI detection",
            category="Root/Modifications",
            passed=True,
            severity="info",
            detail="GSI or custom ROM detected (system != vendor)" if is_custom else "Stock or matching system",
        ))

        return checks

    # ── Category C: Stalkerware Detection ──

    def _check_stalkerware(self) -> list[AuditCheck]:
        from phonectl.core.stalkerware import scan_for_stalkerware
        checks = []

        try:
            installed = self.adb.shell("pm list packages")
            package_list = [
                line.replace("package:", "").strip()
                for line in installed.splitlines()
                if line.startswith("package:")
            ]
        except Exception:
            package_list = []

        # 9. Known stalkerware
        found_stalkerware = scan_for_stalkerware(package_list)
        if found_stalkerware:
            stalker_detail = f"DETECTED ({len(found_stalkerware)} matches):\n"
            for f in found_stalkerware:
                stalker_detail += f"    - {f['name']}: {f['matched_package']} [{f.get('category', 'stalkerware')}]\n"
        else:
            stalker_detail = f"Clean — scanned {len(package_list)} packages"
        checks.append(AuditCheck(
            name="Known stalkerware/spyware",
            category="Stalkerware",
            passed=len(found_stalkerware) == 0,
            severity="critical" if found_stalkerware else "info",
            detail=stalker_detail.rstrip(),
        ))

        # 10. Device admin apps
        try:
            admin_output = self.adb.shell("dumpsys device_policy")
            admin_packages = set()
            import re
            for match in re.finditer(r'ComponentInfo\{([^/]+)/', admin_output):
                admin_packages.add(match.group(1))
            admin_apps = list(admin_packages)
        except Exception:
            admin_apps = []

        known_admins = ["com.google.android.gms", "com.android.managedprovisioning",
                        "com.android.providers.telephony", "com.android.shell",
                        "com.google.android.apps.work.clouddpc", "com.android.settings",
                        "com.google.android.devicelockcontroller"]
        suspicious_admins = [a for a in admin_apps if not any(k in a for k in known_admins)]
        if suspicious_admins:
            admin_detail = f"Suspicious admin apps ({len(suspicious_admins)}):\n"
            for a in sorted(suspicious_admins):
                admin_detail += f"    - {a}\n"
        else:
            admin_detail = f"OK ({len(admin_apps)} admin packages, all known)"
        checks.append(AuditCheck(
            name="Device admin apps",
            category="Stalkerware",
            passed=len(suspicious_admins) == 0,
            severity="warning" if suspicious_admins else "info",
            detail=admin_detail.rstrip(),
        ))

        # 11. Accessibility services abuse
        try:
            acc_services = self.adb.shell("settings get secure enabled_accessibility_services")
        except Exception:
            acc_services = ""

        acc_ok = not acc_services or acc_services.lower() == "null"
        checks.append(AuditCheck(
            name="Accessibility services",
            category="Stalkerware",
            passed=acc_ok,
            severity="warning" if not acc_ok else "info",
            detail=f"Active: {acc_services}" if not acc_ok else "None enabled",
        ))

        return checks

    # ── Category D: Permissions Audit ──

    def _check_permissions(self) -> list[AuditCheck]:
        checks = []

        # 12. Dangerous permissions (apps with camera + mic + location)
        dangerous_perms = [
            "android.permission.CAMERA",
            "android.permission.RECORD_AUDIO",
            "android.permission.ACCESS_FINE_LOCATION",
            "android.permission.READ_SMS",
        ]
        try:
            output = self.adb.shell("dumpsys package -f")
            suspicious_apps = set()
            current_pkg = ""
            current_perms = []
            for line in output.splitlines():
                if "Package [" in line:
                    if current_pkg and len([p for p in dangerous_perms if p in " ".join(current_perms)]) >= 3:
                        if not current_pkg.startswith(("com.google.", "com.android.")):
                            suspicious_apps.add(current_pkg)
                    current_pkg = line.split("[")[1].split("]")[0] if "[" in line else ""
                    current_perms = []
                elif any(p in line for p in dangerous_perms):
                    current_perms.append(line.strip())
        except Exception:
            suspicious_apps = set()

        if suspicious_apps:
            perm_detail = f"{len(suspicious_apps)} third-party apps with camera+mic+location:\n"
            for app in sorted(suspicious_apps):
                perm_detail += f"    - {app}\n"
        else:
            perm_detail = "No third-party apps with excessive permissions"
        checks.append(AuditCheck(
            name="Dangerous permissions",
            category="Permissions",
            passed=len(suspicious_apps) == 0,
            severity="warning" if suspicious_apps else "info",
            detail=perm_detail.rstrip(),
        ))

        # 13. Sideloading enabled
        try:
            sideload = self.adb.shell("settings get secure install_non_market_apps")
        except Exception:
            sideload = "0"

        checks.append(AuditCheck(
            name="Sideloading (unknown sources)",
            category="Permissions",
            passed=sideload.strip() != "1",
            severity="warning" if sideload.strip() == "1" else "info",
            detail="ENABLED — untrusted APKs can be installed" if sideload.strip() == "1" else "Disabled",
        ))

        # 14. Developer options
        try:
            dev_opts = self.adb.shell("settings get global development_settings_enabled")
        except Exception:
            dev_opts = "0"

        checks.append(AuditCheck(
            name="Developer options",
            category="Permissions",
            passed=True,
            severity="info",
            detail="Enabled" if dev_opts.strip() == "1" else "Disabled",
        ))

        return checks

    # ── Category E: Network Exposure ──

    def _check_network_exposure(self, info: DeviceInfo) -> list[AuditCheck]:
        checks = []

        # 15. ADB over network
        try:
            adb_tcp = self.adb.shell("getprop service.adb.tcp.port")
        except Exception:
            adb_tcp = ""

        adb_exposed = adb_tcp.strip() not in ("", "-1", "0")
        checks.append(AuditCheck(
            name="ADB over network",
            category="Network",
            passed=not adb_exposed,
            severity="critical" if adb_exposed else "info",
            detail=f"EXPOSED on port {adb_tcp.strip()} — remote access possible" if adb_exposed
                   else "Disabled (USB only)",
        ))

        # 16. Persistent ADB TCP
        try:
            persist_tcp = self.adb.shell("getprop persist.adb.tcp.port")
        except Exception:
            persist_tcp = ""

        persist_exposed = persist_tcp.strip() not in ("", "-1", "0")
        checks.append(AuditCheck(
            name="Persistent ADB TCP port",
            category="Network",
            passed=not persist_exposed,
            severity="critical" if persist_exposed else "info",
            detail=f"PERSISTED on port {persist_tcp.strip()} — survives reboot" if persist_exposed
                   else "Not set",
        ))

        # 17. Background services count
        try:
            services_output = self.adb.shell("dumpsys activity services")
            service_count = services_output.count("ServiceRecord{")
        except Exception:
            service_count = 0

        high_services = service_count > 100
        checks.append(AuditCheck(
            name="Running background services",
            category="Network",
            passed=not high_services,
            severity="warning" if high_services else "info",
            detail=f"{service_count} services running" +
                   (" — unusually high, check for hidden activity" if high_services else ""),
        ))

        return checks

    # ── Category F: Root-Level Deep Scan ──

    def _check_deep_root_scan(self) -> list[AuditCheck]:
        checks = []

        if not self.has_root():
            checks.append(AuditCheck(
                name="Root deep scan",
                category="Deep Scan",
                passed=True,
                severity="info",
                detail="Skipped — root access not available. Root the device and retry with --deep.",
                requires_root=True,
            ))
            return checks

        # 18. Hosts file
        try:
            hosts = self.adb.shell("su -c 'cat /etc/hosts'")
            extra_hosts = [
                l.strip() for l in hosts.splitlines()
                if l.strip() and not l.strip().startswith("#")
                and "localhost" not in l.lower()
            ]
        except Exception:
            extra_hosts = []

        checks.append(AuditCheck(
            name="Hosts file modifications",
            category="Deep Scan",
            passed=len(extra_hosts) == 0,
            severity="warning" if extra_hosts else "info",
            detail=f"{len(extra_hosts)} extra entries (DNS redirection)" if extra_hosts
                   else "Clean — only localhost",
            requires_root=True,
        ))

        # 19. System partition modifications
        try:
            modified = self.adb.shell("su -c 'find /system -newer /system/build.prop -type f 2>/dev/null'")
            mod_files = [l.strip() for l in modified.splitlines() if l.strip()]
        except Exception:
            mod_files = []

        checks.append(AuditCheck(
            name="System partition integrity",
            category="Deep Scan",
            passed=len(mod_files) <= 5,
            severity="critical" if len(mod_files) > 20 else "warning" if mod_files else "info",
            detail=f"{len(mod_files)} files modified after build" if mod_files
                   else "Intact — no post-build modifications",
            requires_root=True,
        ))

        # 20. Kernel modules
        try:
            lsmod = self.adb.shell("su -c 'lsmod 2>/dev/null || cat /proc/modules 2>/dev/null'")
            modules = [l.split()[0] for l in lsmod.splitlines() if l.strip() and not l.startswith("Module")]
        except Exception:
            modules = []

        checks.append(AuditCheck(
            name="Kernel modules",
            category="Deep Scan",
            passed=True,
            severity="info",
            detail=f"{len(modules)} modules loaded: {', '.join(modules[:5])}" +
                   ("..." if len(modules) > 5 else "") if modules else "No modules or unable to read",
            requires_root=True,
        ))

        # 21. Hidden processes (visible only to root)
        try:
            root_ps = self.adb.shell("su -c 'ps -A'")
            user_ps = self.adb.shell("ps -A")
            root_pids = set()
            user_pids = set()
            for line in root_ps.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 2:
                    root_pids.add(parts[1])
            for line in user_ps.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 2:
                    user_pids.add(parts[1])
            hidden = root_pids - user_pids
        except Exception:
            hidden = set()

        checks.append(AuditCheck(
            name="Hidden processes",
            category="Deep Scan",
            passed=len(hidden) <= 10,
            severity="warning" if len(hidden) > 10 else "info",
            detail=f"{len(hidden)} processes visible only to root" +
                   (" — excessive, may indicate hiding" if len(hidden) > 50 else ""),
            requires_root=True,
        ))

        return checks


# ═══════════════════════════════════════════════════════════════
# Full Audit Runner
# ═══════════════════════════════════════════════════════════════

def run_audit(adb: ADBClient, info: DeviceInfo, deep: bool = False) -> AuditReport:
    """Execute the full audit — warranty estimation + security scan."""
    report = AuditReport(
        device_serial=info.serial,
        device_model=info.model,
        device_codename=info.codename,
        timestamp=datetime.now().isoformat(),
    )

    # Warranty
    estimator = WarrantyEstimator()
    report.warranty = estimator.estimate(info)

    # Security scan
    scanner = SecurityScanner(adb)
    report.root_available = scanner.has_root()
    report.checks = scanner.run_all(info, deep=deep)
    report.root_checks_run = deep and report.root_available

    # Risk level
    critical_fails = sum(1 for c in report.checks if not c.passed and c.severity == "critical")
    warning_fails = sum(1 for c in report.checks if not c.passed and c.severity == "warning")
    risk_score = critical_fails * 3 + warning_fails
    if risk_score >= RISK_THRESHOLDS["CRITICAL"]:
        report.risk_level = "CRITICAL"
    elif risk_score >= RISK_THRESHOLDS["HIGH"]:
        report.risk_level = "HIGH"
    elif risk_score >= RISK_THRESHOLDS["MEDIUM"]:
        report.risk_level = "MEDIUM"
    else:
        report.risk_level = "LOW"

    return report


# ═══════════════════════════════════════════════════════════════
# Report Display
# ═══════════════════════════════════════════════════════════════

def display_audit_report(report: AuditReport) -> None:
    """Render the audit report as rich formatted output."""
    # Warranty panel
    w = report.warranty
    warranty_lines = []
    warranty_lines.append(f"  Ship year:         ~{w.ship_year} (API → Android)")
    warranty_lines.append(f"  Device age:        ~{w.device_age_years} years")
    warranty_lines.append(f"  Manufacturer:      {w.manufacturer}")
    warranty_lines.append(f"  Warranty period:   {w.warranty_years} year(s)")
    warranty_status = "[red]EXPIRED[/]" if w.warranty_expired else "[green]ACTIVE[/]"
    warranty_lines.append(f"  Warranty status:   {warranty_status} (estimated ~{w.warranty_expiry_year})")
    support_status = "[red]ENDED[/]" if w.software_support_ended else "[green]ACTIVE[/]"
    if w.last_vendor_patch:
        support_status += f" (last patch: {w.last_vendor_patch}, {w.vendor_patch_age_days} days ago)"
    warranty_lines.append(f"  Software support:  {support_status}")
    safe_style = "[green]YES[/]" if w.safe_to_flash else "[yellow]CAUTION[/]"
    warranty_lines.append(f"  Safe to flash:     {safe_style}")
    if w.summary:
        warranty_lines.append(f"  [dim]{w.summary}[/]")

    console.print(Panel("\n".join(warranty_lines), title="[bold]Warranty Estimation[/]", border_style="cyan"))

    # Security checks by category
    categories = report.checks_by_category()
    for cat_name, cat_checks in categories.items():
        table = Table(show_header=True, title=cat_name, box=None, padding=(0, 1))
        table.add_column("#", width=3)
        table.add_column("Check", style="cyan", min_width=28)
        table.add_column("Result", width=6)
        table.add_column("Detail")

        for i, c in enumerate(cat_checks, 1):
            if c.passed:
                result = "[green]PASS[/]"
            elif c.severity == "critical":
                result = "[bold red]FAIL[/]"
            else:
                result = "[yellow]WARN[/]"
            table.add_row(str(i), c.name, result, c.detail)

        console.print(table)
        console.print()

    # Findings — list all warnings and failures with details
    failed_checks = [c for c in report.checks if not c.passed]
    if failed_checks:
        console.print(Panel.fit(
            "[bold]Findings — Warnings and Failures[/]",
            border_style="yellow",
        ))
        for c in failed_checks:
            severity_tag = "[bold red]CRITICAL[/]" if c.severity == "critical" else "[yellow]WARNING[/]"
            console.print(f"\n  {severity_tag} [{c.category}] {c.name}")
            for line in c.detail.splitlines():
                console.print(f"    {line}")
        console.print()

    # Summary
    passed = report.passed_count
    total = report.total_count
    risk_style = {
        "LOW": "green", "MEDIUM": "yellow", "HIGH": "red", "CRITICAL": "bold red"
    }.get(report.risk_level, "white")

    summary_lines = [
        f"  Checks:     {passed}/{total} passed",
        f"  Risk level: [{risk_style}]{report.risk_level}[/]",
    ]
    if failed_checks:
        summary_lines.append(f"  Findings:   {len(failed_checks)} issue(s) found — see details above")
    if report.root_checks_run:
        summary_lines.append("  Deep scan:  Completed (root checks included)")
    elif report.root_available:
        summary_lines.append("  Deep scan:  Skipped (use --deep to include root checks)")
    else:
        summary_lines.append("  Deep scan:  N/A (device not rooted)")

    console.print(Panel(
        "\n".join(summary_lines),
        title="[bold]Audit Summary[/]",
        border_style=risk_style.replace("bold ", ""),
    ))


# ═══════════════════════════════════════════════════════════════
# Export
# ═══════════════════════════════════════════════════════════════

def export_audit_json(report: AuditReport, path: str | Path) -> Path:
    """Export audit report as JSON."""
    path = Path(path)
    data = {
        "device": {
            "serial": report.device_serial,
            "model": report.device_model,
            "codename": report.device_codename,
        },
        "timestamp": report.timestamp,
        "warranty": {
            "ship_year": report.warranty.ship_year,
            "device_age_years": report.warranty.device_age_years,
            "warranty_expired": report.warranty.warranty_expired,
            "warranty_expiry_year": report.warranty.warranty_expiry_year,
            "software_support_ended": report.warranty.software_support_ended,
            "last_vendor_patch": report.warranty.last_vendor_patch,
            "safe_to_flash": report.warranty.safe_to_flash,
            "summary": report.warranty.summary,
        },
        "risk_level": report.risk_level,
        "checks": [
            {
                "name": c.name,
                "category": c.category,
                "passed": c.passed,
                "severity": c.severity,
                "detail": c.detail,
            }
            for c in report.checks
        ],
        "summary": {
            "passed": report.passed_count,
            "failed": report.failed_count,
            "total": report.total_count,
        },
    }
    path.write_text(json.dumps(data, indent=2))
    console.print(f"[green]Exported JSON report:[/] {path}")
    return path


def export_audit_markdown(report: AuditReport, path: str | Path) -> Path:
    """Export audit report as Markdown."""
    path = Path(path)
    lines = [
        f"# phonectl Security Audit Report",
        f"",
        f"**Device:** {report.device_model} ({report.device_codename}) — {report.device_serial}",
        f"**Date:** {report.timestamp}",
        f"**Risk Level:** {report.risk_level}",
        f"",
        f"## Warranty Estimation",
        f"",
        f"| Property | Value |",
        f"|----------|-------|",
        f"| Ship Year | ~{report.warranty.ship_year} |",
        f"| Device Age | ~{report.warranty.device_age_years} years |",
        f"| Warranty | {'EXPIRED' if report.warranty.warranty_expired else 'ACTIVE'} (~{report.warranty.warranty_expiry_year}) |",
        f"| Software Support | {'ENDED' if report.warranty.software_support_ended else 'ACTIVE'} |",
        f"| Last Vendor Patch | {report.warranty.last_vendor_patch} ({report.warranty.vendor_patch_age_days} days ago) |",
        f"| Safe to Flash | {'Yes' if report.warranty.safe_to_flash else 'Caution'} |",
        f"",
        f"## Security Checks ({report.passed_count}/{report.total_count} passed)",
        f"",
        f"| # | Category | Check | Result | Detail |",
        f"|---|----------|-------|--------|--------|",
    ]
    for i, c in enumerate(report.checks, 1):
        result = "PASS" if c.passed else "FAIL" if c.severity == "critical" else "WARN"
        lines.append(f"| {i} | {c.category} | {c.name} | {result} | {c.detail} |")

    lines += ["", f"**Risk Level:** {report.risk_level}", ""]
    path.write_text("\n".join(lines))
    console.print(f"[green]Exported Markdown report:[/] {path}")
    return path
