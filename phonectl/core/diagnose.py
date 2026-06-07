"""Smart diagnostics engine — rule-based expert system for device health analysis.

Collects evidence from all existing phonectl modules, evaluates diagnostic
rules, and produces a prioritized action plan.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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

PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


@dataclass
class Finding:
    rule_id: str
    name: str
    priority: str
    description: str
    evidence: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)


@dataclass
class DiagnosisReport:
    findings: list[Finding] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)

    @property
    def actionable_count(self) -> int:
        return sum(1 for f in self.findings if f.actions)

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.priority == "critical")


class DiagnosticEngine:
    """Rule-based expert system for device diagnostics."""

    def __init__(self, config_path: str | Path | None = None):
        self.rules = self._load_rules(config_path)

    def _load_rules(self, config_path: str | Path | None) -> list[dict]:
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config" / "diagnosis_rules.yaml"
        path = Path(config_path)
        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f) or {}
            return data.get("rules", [])
        return []

    def collect_evidence(self, adb: ADBClient, info: DeviceInfo) -> dict:
        """Gather diagnostic data from all existing modules."""
        evidence: dict = {
            "ram_total_mb": info.ram_total_mb,
            "storage_total_gb": info.storage_total_gb,
            "storage_free_gb": info.storage_free_gb,
            "android_version": info.android_version,
            "security_patch": info.security_patch or "",
            "vendor_security_patch": info.vendor_security_patch or "",
            "kernel_version": info.kernel_version,
            "vndk_version": info.vndk_version,
            "is_unlocked": info.is_unlocked,
            "treble_enabled": info.treble_enabled,
            "cpu_abi": info.cpu_abi,
            "manufacturer": info.manufacturer,
            "codename": info.codename,
            "battery_level": int(info.battery_level) if info.battery_level and info.battery_level.isdigit() else -1,
        }

        # Animation scale (tune status)
        try:
            anim = adb.shell("settings get global window_animation_scale").strip()
            evidence["animation_scale"] = float(anim) if anim and anim != "null" else 1.0
        except Exception:
            evidence["animation_scale"] = 1.0

        # Security score
        try:
            from phonectl.core.security import SecurityGuard
            guard = SecurityGuard(adb)
            sec_report = guard.run_all()
            evidence["security_score"] = sec_report.score
            evidence["security_fixable"] = len(sec_report.fixable_checks)
        except Exception:
            evidence["security_score"] = -1
            evidence["security_fixable"] = 0

        # Stalkerware
        try:
            from phonectl.core.stalkerware import scan_for_stalkerware
            installed = adb.shell("pm list packages")
            pkg_list = [l.replace("package:", "").strip() for l in installed.splitlines() if l.startswith("package:")]
            found = scan_for_stalkerware(pkg_list)
            evidence["stalkerware_found"] = len(found)
            evidence["stalkerware_names"] = [f["name"] for f in found]
            evidence["total_packages"] = len(pkg_list)
        except Exception:
            evidence["stalkerware_found"] = 0
            evidence["stalkerware_names"] = []
            evidence["total_packages"] = 0

        # Bloatware count
        try:
            from phonectl.core.storage import StorageAnalyzer
            analyzer = StorageAnalyzer(adb)
            bloat = analyzer.list_bloatware(info.manufacturer.lower())
            evidence["bloatware_count"] = len(bloat)
        except Exception:
            evidence["bloatware_count"] = 0

        # Warranty
        try:
            from phonectl.core.audit import WarrantyEstimator
            warranty = WarrantyEstimator().estimate(info)
            evidence["warranty_expired"] = warranty.warranty_expired
            evidence["software_support_ended"] = warranty.software_support_ended
            evidence["device_age_years"] = warranty.device_age_years
        except Exception:
            evidence["warranty_expired"] = True
            evidence["software_support_ended"] = True
            evidence["device_age_years"] = 0

        # GSI compatibility
        try:
            from phonectl.firmware.gsi import evaluate_all_versions
            recommendations = evaluate_all_versions(info)
            compatible = [r for r in recommendations if r.verdict in ("recommended", "compatible")]
            evidence["gsi_compatible_count"] = len(compatible)
            if compatible:
                evidence["gsi_best_name"] = compatible[0].version.name
                evidence["gsi_best_id"] = compatible[0].version.build_id
        except Exception:
            evidence["gsi_compatible_count"] = 0

        # Background services count
        try:
            services = adb.shell("dumpsys activity services")
            evidence["services_count"] = services.count("ServiceRecord{")
        except Exception:
            evidence["services_count"] = 0

        # Sideloading
        try:
            sideload = adb.shell("settings get secure install_non_market_apps").strip()
            evidence["sideloading_enabled"] = sideload == "1"
        except Exception:
            evidence["sideloading_enabled"] = False

        # Screen lock
        try:
            lock_type = adb.shell("settings get secure lockscreen.password_type").strip()
            evidence["has_screen_lock"] = lock_type not in ("", "65536", "-1", "null")
        except Exception:
            evidence["has_screen_lock"] = True

        return evidence

    def evaluate_rules(self, evidence: dict) -> list[Finding]:
        """Evaluate diagnostic rules against collected evidence."""
        findings = []

        for rule in self.rules:
            conditions = rule.get("conditions", [])
            if not conditions:
                continue

            matched = True
            matched_evidence = []

            for cond in conditions:
                result, detail = self._eval_condition(cond, evidence)
                if not result:
                    matched = False
                    break
                matched_evidence.append(detail)

            if matched:
                desc = rule.get("description", rule.get("name", ""))
                desc = self._interpolate(desc, evidence)
                actions = [self._interpolate(a, evidence) for a in rule.get("actions", [])]

                findings.append(Finding(
                    rule_id=rule.get("id", "unknown"),
                    name=rule.get("name", "Unknown issue"),
                    priority=rule.get("priority", "medium"),
                    description=desc,
                    evidence=matched_evidence,
                    actions=actions,
                ))

        return findings

    def _eval_condition(self, condition: str, evidence: dict) -> tuple[bool, str]:
        """Evaluate a single condition string like 'ram_total_mb < 3072'."""
        import re

        operators = {
            "==": lambda a, b: str(a).lower() == str(b).lower(),
            "!=": lambda a, b: str(a).lower() != str(b).lower(),
            ">=": lambda a, b: float(a) >= float(b),
            "<=": lambda a, b: float(a) <= float(b),
            ">": lambda a, b: float(a) > float(b),
            "<": lambda a, b: float(a) < float(b),
        }

        for op_str, op_fn in sorted(operators.items(), key=lambda x: -len(x[0])):
            if op_str in condition:
                parts = condition.split(op_str, 1)
                key = parts[0].strip()
                expected = parts[1].strip()

                actual = evidence.get(key)
                if actual is None:
                    return False, f"{key}: unknown"

                try:
                    if expected.lower() in ("true", "false"):
                        actual_bool = bool(actual) if not isinstance(actual, str) else actual.lower() == "true"
                        expected_bool = expected.lower() == "true"
                        result = actual_bool == expected_bool if op_str == "==" else actual_bool != expected_bool
                    else:
                        result = op_fn(actual, expected)

                    detail = f"{key} = {actual} ({op_str} {expected})"
                    return result, detail
                except (ValueError, TypeError):
                    return False, f"{key}: cannot evaluate"

        return False, f"Invalid condition: {condition}"

    def _interpolate(self, template: str, evidence: dict) -> str:
        """Replace {key} placeholders in strings with evidence values."""
        import re
        def replacer(match):
            key = match.group(1)
            return str(evidence.get(key, f"{{{key}}}"))
        return re.sub(r'\{(\w+)\}', replacer, template)

    def prioritize(self, findings: list[Finding]) -> list[Finding]:
        """Sort findings by priority (critical first)."""
        return sorted(findings, key=lambda f: PRIORITY_ORDER.get(f.priority, 99))

    def run(self, adb: ADBClient, info: DeviceInfo) -> DiagnosisReport:
        """Execute full diagnosis pipeline."""
        evidence = self.collect_evidence(adb, info)
        findings = self.evaluate_rules(evidence)
        findings = self.prioritize(findings)
        return DiagnosisReport(findings=findings, evidence=evidence)


def display_diagnosis(report: DiagnosisReport) -> None:
    """Render diagnosis report with rich formatting."""
    if not report.findings:
        console.print(Panel(
            "[green]No issues found. Device appears healthy.[/]",
            title="[bold]Diagnosis[/]",
            border_style="green",
        ))
        return

    console.print(Panel(
        f"  Issues found:  {len(report.findings)}\n"
        f"  Actionable:    {report.actionable_count}\n"
        f"  Critical:      {report.critical_count}",
        title="[bold]Diagnosis Summary[/]",
        border_style="yellow" if report.critical_count == 0 else "red",
    ))

    priority_styles = {
        "critical": "bold red",
        "high": "red",
        "medium": "yellow",
        "low": "cyan",
        "info": "dim",
    }

    for finding in report.findings:
        style = priority_styles.get(finding.priority, "white")
        console.print(f"\n  [{style}][{finding.priority.upper()}][/] {finding.name}")
        if finding.description:
            console.print(f"    {finding.description}")
        for ev in finding.evidence:
            console.print(f"    [dim]{ev}[/]")
        for action in finding.actions:
            console.print(f"    [green]Fix:[/] [bold]{action}[/]")

    console.print()
