"""Device health report generator — combines all module outputs into a single report.

Produces human-readable terminal output, exportable Markdown, or JSON.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

if TYPE_CHECKING:
    from phonectl.core.adb import ADBClient
    from phonectl.core.device import DeviceInfo

console = Console()


@dataclass
class HealthReport:
    device_model: str = ""
    device_codename: str = ""
    device_serial: str = ""
    timestamp: str = ""
    # Scores
    health_score: int = 0
    security_score: int = 0
    # Sections
    device_summary: str = ""
    warranty_summary: str = ""
    security_findings: list[str] = field(default_factory=list)
    performance_assessment: str = ""
    storage_health: str = ""
    recommendations: list[dict] = field(default_factory=list)
    gsi_compatibility: str = ""


class ReportGenerator:
    """Generate comprehensive device health reports."""

    def generate(self, adb: ADBClient, info: DeviceInfo) -> HealthReport:
        """Collect all data and assemble the report."""
        report = HealthReport(
            device_model=info.model,
            device_codename=info.codename,
            device_serial=info.serial,
            timestamp=datetime.now().isoformat(),
        )

        # Device summary
        age = ""
        try:
            from phonectl.core.audit import WarrantyEstimator
            warranty = WarrantyEstimator().estimate(info)
            age_str = f"~{warranty.device_age_years} years old"
            warranty_status = "out of warranty" if warranty.warranty_expired else "under warranty"
            support = "no longer receiving updates" if warranty.software_support_ended else "still receiving updates"
            report.device_summary = (
                f"{info.manufacturer} {info.model} ({info.codename}), {age_str}, "
                f"running Android {info.android_version} with {info.ram_total_mb} MB RAM. "
                f"Device is {warranty_status} and {support}."
            )
            report.warranty_summary = warranty.summary
        except Exception:
            report.device_summary = f"{info.manufacturer} {info.model} ({info.codename})"

        # Security score
        try:
            from phonectl.core.security import SecurityGuard
            guard = SecurityGuard(adb)
            sec = guard.run_all()
            report.security_score = sec.score
            for check in sec.checks:
                if not check.passed:
                    report.security_findings.append(f"[{check.category}] {check.name}: {check.detail}")
        except Exception:
            report.security_score = -1

        # Performance
        try:
            from phonectl.core.tune import TuneEngine
            engine = TuneEngine(adb)
            status = engine.get_current()
            report.performance_assessment = (
                f"Profile: {status.active_profile}. "
                f"Animations: {status.current_values.get('window_animation_scale', '?')}x. "
                f"RAM: {info.ram_total_mb} MB."
            )
            if info.ram_total_mb < 3072:
                report.performance_assessment += " Low RAM — consider 'fast' profile."
        except Exception:
            report.performance_assessment = "Unable to assess"

        # Storage
        try:
            from phonectl.core.storage import StorageAnalyzer
            analyzer = StorageAnalyzer(adb)
            si = analyzer.get_storage_info()
            bloatware = analyzer.list_bloatware(info.manufacturer.lower())
            report.storage_health = (
                f"{si.used_gb} GB used of {si.total_gb} GB "
                f"({si.free_gb} GB free). "
                f"{si.apps_count} apps installed ({si.user_apps} user, {si.system_apps} system). "
                f"{len(bloatware)} bloatware apps detected."
            )
        except Exception:
            report.storage_health = "Unable to assess"

        # Diagnosis (recommendations)
        try:
            from phonectl.core.diagnose import DiagnosticEngine
            engine = DiagnosticEngine()
            diagnosis = engine.run(adb, info)
            for f in diagnosis.findings:
                report.recommendations.append({
                    "priority": f.priority,
                    "name": f.name,
                    "description": f.description,
                    "actions": f.actions,
                })
        except Exception:
            pass

        # GSI compatibility
        try:
            from phonectl.firmware.gsi import evaluate_all_versions
            recs = evaluate_all_versions(info)
            recommended = [r for r in recs if r.verdict == "recommended"]
            compatible = [r for r in recs if r.verdict == "compatible"]
            if recommended:
                best = recommended[0]
                report.gsi_compatibility = (
                    f"{len(recommended)} recommended, {len(compatible)} compatible. "
                    f"Best: {best.version.name} ({best.version.build_id}, "
                    f"patch {best.version.security_patch})."
                )
            elif compatible:
                report.gsi_compatibility = f"{len(compatible)} compatible GSI version(s) found."
            else:
                report.gsi_compatibility = "No compatible GSI versions for this device."
        except Exception:
            report.gsi_compatibility = "Unable to assess"

        # Health score (composite)
        scores = []
        if report.security_score >= 0:
            scores.append(report.security_score)
        storage_score = 80
        try:
            from phonectl.core.storage import StorageAnalyzer
            si = analyzer.get_storage_info()
            if si.free_gb < 2:
                storage_score = 30
            elif si.free_gb < 5:
                storage_score = 60
        except Exception:
            pass
        scores.append(storage_score)

        perf_score = 70
        if info.ram_total_mb < 2048:
            perf_score = 30
        elif info.ram_total_mb < 3072:
            perf_score = 50
        scores.append(perf_score)

        report.health_score = round(sum(scores) / len(scores)) if scores else 0

        return report

    def render_text(self, report: HealthReport) -> None:
        """Display report with rich formatting."""
        # Header
        score = report.health_score
        score_style = "green" if score >= 70 else "yellow" if score >= 50 else "red"

        console.print(Panel(
            f"  Device:       {report.device_model} ({report.device_codename})\n"
            f"  Health Score: [{score_style}]{score}/100[/]\n"
            f"  Generated:   {report.timestamp[:19]}",
            title="[bold]Device Health Report[/]",
            border_style=score_style,
        ))

        # Device summary
        console.print(f"\n[bold]Device Summary[/]")
        console.print(f"  {report.device_summary}")
        if report.warranty_summary:
            console.print(f"  [dim]{report.warranty_summary}[/]")

        # Security
        console.print(f"\n[bold]Security[/] (score: {report.security_score}/100)")
        if report.security_findings:
            for f in report.security_findings[:5]:
                console.print(f"  [yellow]![/] {f}")
            if len(report.security_findings) > 5:
                console.print(f"  [dim]... and {len(report.security_findings) - 5} more[/]")
        else:
            console.print("  [green]No security issues found.[/]")

        # Performance
        console.print(f"\n[bold]Performance[/]")
        console.print(f"  {report.performance_assessment}")

        # Storage
        console.print(f"\n[bold]Storage[/]")
        console.print(f"  {report.storage_health}")

        # GSI
        console.print(f"\n[bold]GSI Compatibility[/]")
        console.print(f"  {report.gsi_compatibility}")

        # Recommendations
        if report.recommendations:
            console.print(f"\n[bold]Recommendations[/] ({len(report.recommendations)} items)")
            priority_styles = {"critical": "bold red", "high": "red", "medium": "yellow", "low": "cyan", "info": "dim"}
            for r in report.recommendations:
                style = priority_styles.get(r["priority"], "white")
                console.print(f"\n  [{style}][{r['priority'].upper()}][/] {r['name']}")
                if r["description"]:
                    console.print(f"    {r['description']}")
                for a in r["actions"]:
                    console.print(f"    [green]Fix:[/] [bold]{a}[/]")

        console.print()

    def render_markdown(self, report: HealthReport, path: str | Path) -> Path:
        """Export report as Markdown."""
        path = Path(path)
        lines = [
            f"# Device Health Report",
            f"",
            f"**Device:** {report.device_model} ({report.device_codename})",
            f"**Health Score:** {report.health_score}/100",
            f"**Date:** {report.timestamp[:19]}",
            f"",
            f"## Device Summary",
            f"",
            f"{report.device_summary}",
            f"",
            f"## Security (Score: {report.security_score}/100)",
            f"",
        ]
        if report.security_findings:
            for f in report.security_findings:
                lines.append(f"- {f}")
        else:
            lines.append("No security issues found.")

        lines += [
            f"",
            f"## Performance",
            f"",
            f"{report.performance_assessment}",
            f"",
            f"## Storage",
            f"",
            f"{report.storage_health}",
            f"",
            f"## GSI Compatibility",
            f"",
            f"{report.gsi_compatibility}",
            f"",
        ]

        if report.recommendations:
            lines += [f"## Recommendations", ""]
            for r in report.recommendations:
                lines.append(f"### [{r['priority'].upper()}] {r['name']}")
                lines.append(f"")
                if r["description"]:
                    lines.append(f"{r['description']}")
                for a in r["actions"]:
                    lines.append(f"- `{a}`")
                lines.append("")

        path.write_text("\n".join(lines))
        console.print(f"[green]Report exported:[/] {path}")
        return path

    def render_json(self, report: HealthReport, path: str | Path) -> Path:
        """Export report as JSON."""
        path = Path(path)
        data = {
            "device": {
                "model": report.device_model,
                "codename": report.device_codename,
                "serial": report.device_serial,
            },
            "timestamp": report.timestamp,
            "health_score": report.health_score,
            "security_score": report.security_score,
            "summary": report.device_summary,
            "warranty": report.warranty_summary,
            "security_findings": report.security_findings,
            "performance": report.performance_assessment,
            "storage": report.storage_health,
            "gsi_compatibility": report.gsi_compatibility,
            "recommendations": report.recommendations,
        }
        path.write_text(json.dumps(data, indent=2))
        console.print(f"[green]Report exported:[/] {path}")
        return path
