"""Diagnose, ask, and report commands."""

from __future__ import annotations

import click
from rich.panel import Panel

from phonectl.commands._helpers import (
    console, create_device_manager, _detect_device, _show_device_panel,
)


@click.command()
@click.option("--ai", is_flag=True, help="Include Gemini AI analysis (requires GEMINI_API_KEY)")
@click.option("--fix", "do_fix", is_flag=True, help="Auto-run fix commands for found issues")
def diagnose(ai: bool, do_fix: bool):
    """Smart diagnostics — analyze device health and generate action plan."""
    from phonectl.core.diagnose import DiagnosticEngine, display_diagnosis

    dm = create_device_manager()
    device_info = _detect_device(dm)
    adb = dm.get_adb()
    if not adb:
        console.print("[red]ADB connection required.[/]")
        raise SystemExit(1)

    vendor = dm.resolve_vendor(device_info)
    _show_device_panel(device_info, vendor.name if vendor else "Unknown")

    console.print("\n[bold]Running diagnostics...[/]\n")
    engine = DiagnosticEngine()
    report = engine.run(adb, device_info)

    if ai:
        try:
            from phonectl.ai.gemini import GeminiProvider
            from phonectl.ai.base import DeviceContext
            provider = GeminiProvider()
            if provider.is_available():
                console.print("[bold blue]Running Gemini AI analysis...[/]\n")
                context = DeviceContext.from_device_info(
                    device_info,
                    security_score=report.evidence.get("security_score", 0),
                    findings=[f"{f.priority}: {f.name}" for f in report.findings],
                    recommendations=[a for f in report.findings for a in f.actions],
                )
                report.ai_analysis = provider.analyze(context)
            else:
                console.print("[yellow]Gemini not available. Set GEMINI_API_KEY environment variable.[/]")
        except Exception as exc:
            console.print(f"[yellow]AI analysis failed: {exc}[/]")

    display_diagnosis(report)

    if do_fix and report.findings:
        import shlex
        import subprocess
        SAFE_FIX_PREFIXES = (
            "phonectl tune",
            "phonectl security --harden",
            "phonectl storage bloatware disable",
            "phonectl storage bloatware enable",
            "phonectl storage cleanup",
        )
        BLOCKED_FIX_KEYWORDS = ("flash", "reset --factory", "recover", "wipe")

        actions = report.unique_actions()
        if not actions:
            console.print("[dim]No auto-fixable actions found.[/]")
            return

        console.print(f"\n[bold]Auto-fix: {len(actions)} action(s) to apply[/]\n")
        applied = set()
        for action in actions:
            if action in applied:
                continue

            if any(kw in action.lower() for kw in BLOCKED_FIX_KEYWORDS):
                console.print(f"  [red]BLOCKED[/] {action} — destructive command, run manually")
                continue

            if not any(action.startswith(prefix) for prefix in SAFE_FIX_PREFIXES):
                console.print(f"  [yellow]SKIP[/] {action} — not in safe command whitelist")
                continue

            response = console.input(f"  Apply [bold]{action}[/]? [y/n/q]: ")
            if response.strip().lower() == "q":
                console.print("[yellow]Fix stopped.[/]")
                break
            if response.strip().lower() != "y":
                continue

            console.print(f"  [dim]Running: {action}...[/]")
            try:
                parts = shlex.split(action)
                subprocess.run(parts, timeout=60, check=True)
                applied.add(action)
                console.print(f"  [green]Done[/]")
            except subprocess.CalledProcessError as exc:
                console.print(f"  [red]Failed (exit code {exc.returncode})[/]")
            except Exception as exc:
                console.print(f"  [red]Failed: {exc}[/]")


@click.command()
@click.argument("question")
def ask(question: str):
    """AI-powered troubleshooting — ask a question about your device.

    Requires GEMINI_API_KEY environment variable set.
    Uses Gemini 3.1 Pro for deep reasoning.
    Only non-PII device context is sent (no serial, IMEI, or accounts).
    """
    from phonectl.ai.gemini import GeminiProvider, PRO_MODEL
    from phonectl.ai.base import DeviceContext

    dm = create_device_manager()
    device_info = _detect_device(dm)

    provider = GeminiProvider(model=PRO_MODEL)
    if not provider.is_available():
        console.print(
            "[red]Gemini API not available.[/]\n"
            "Set your API key: [bold]export GEMINI_API_KEY=your-key[/]\n"
            "Install SDK: [bold]pip install google-genai>=1.51.0[/]"
        )
        raise SystemExit(1)

    context = DeviceContext.from_device_info(device_info)

    console.print(f"[bold]Device:[/] {device_info.manufacturer} {device_info.model} ({device_info.codename})")
    console.print(f"[bold]Question:[/] {question}")
    console.print(f"\n[bold blue]Asking Gemini 3.1 Pro...[/]\n")

    answer = provider.troubleshoot(context, question)
    console.print(Panel(answer, title="[bold]AI Response[/]", border_style="blue"))


@click.command()
@click.option("--export", "export_format", type=click.Choice(["md", "json"]),
              help="Export report to file")
@click.option("--output", "output_path", type=click.Path(),
              help="Output file path")
def report(export_format: str | None, output_path: str | None):
    """Generate comprehensive device health report."""
    from phonectl.core.report import ReportGenerator

    dm = create_device_manager()
    device_info = _detect_device(dm)
    adb = dm.get_adb()
    if not adb:
        console.print("[red]ADB connection required.[/]")
        raise SystemExit(1)

    console.print("[bold]Generating health report...[/]\n")
    gen = ReportGenerator()
    health_report = gen.generate(adb, device_info)

    if export_format:
        serial = device_info.serial or "device"
        if not output_path:
            ext = "json" if export_format == "json" else "md"
            output_path = f"report_{serial}.{ext}"
        if export_format == "json":
            gen.render_json(health_report, output_path)
        else:
            gen.render_markdown(health_report, output_path)
    else:
        gen.render_text(health_report)
