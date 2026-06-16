"""GSI version management, compatibility checking, and download orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from rich.console import Console
from rich.table import Table

from phonectl.firmware.downloader import download_file

console = Console()


@dataclass
class GSIVersion:
    name: str
    build_id: str
    security_patch: str
    status: str
    download_url: str
    sha256: str
    min_vndk: int = 30
    notes: str = ""


def load_gsi_versions(config_path: str | Path | None = None) -> list[GSIVersion]:
    """Load known GSI versions, merging static config with dynamic cache."""
    static = _load_static_versions(config_path)

    from phonectl.firmware.compat_fetcher import CompatFetcher
    cached = CompatFetcher().load_cached()
    if not cached:
        return static

    return _merge_versions(static, cached)


def _load_static_versions(config_path: str | Path | None = None) -> list[GSIVersion]:
    """Load GSI versions from the bundled YAML config."""
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config" / "gsi_versions.yaml"

    config_path = Path(config_path)
    if not config_path.exists():
        return _builtin_versions()

    with open(config_path) as f:
        data = yaml.safe_load(f)

    versions = []
    for v in data.get("versions", []):
        versions.append(GSIVersion(**v))
    return versions


def _merge_versions(
    static: list[GSIVersion],
    dynamic: list[dict],
) -> list[GSIVersion]:
    """Merge dynamic cache into static baseline.

    Rules:
    - Static entries with status "broken" keep that status
    - Static entries with non-empty notes keep their notes
    - Dynamic entries update download_url, sha256, security_patch
    - New dynamic entries (unknown build_id) are appended
    """
    by_id = {v.build_id: v for v in static}
    merged = list(static)

    for d in dynamic:
        build_id = d.get("build_id", "")
        if not build_id:
            continue

        if build_id in by_id:
            existing = by_id[build_id]
            if d.get("download_url"):
                existing.download_url = d["download_url"]
            if d.get("sha256"):
                existing.sha256 = d["sha256"]
            if d.get("security_patch"):
                existing.security_patch = d["security_patch"]
            if existing.status != "broken" and d.get("status"):
                existing.status = d["status"]
        else:
            try:
                new_ver = GSIVersion(**{
                    k: v for k, v in d.items()
                    if k in GSIVersion.__dataclass_fields__
                })
                merged.append(new_ver)
                by_id[build_id] = new_ver
            except TypeError:
                continue

    return merged


def _builtin_versions() -> list[GSIVersion]:
    """Fallback hardcoded list if config file is missing."""
    return [
        GSIVersion(
            name="Android 16 (Baklava)",
            build_id="BP2A.250605.031.A3",
            security_patch="2025-06-05",
            status="stable",
            download_url=(
                "https://dl.google.com/developers/android/baklava/images/gsi/"
                "gsi_gms_arm64-exp-BP2A.250605.031.A3-13578795-38e52cb0.zip"
            ),
            sha256="38e52cb0a3331a5ee0c653a4da2401ce74598a955acbd00aa85b6326036154c5",
            min_vndk=30,
            notes="Confirmed working on Moto G71 5G (corfur) with VNDK 30",
        ),
    ]


def show_gsi_versions(config_path: str | Path | None = None) -> None:
    """Print a formatted table of available GSI versions."""
    versions = load_gsi_versions(config_path)

    table = Table(title="Available GSI Versions")
    table.add_column("Name", style="cyan")
    table.add_column("Build ID", style="green")
    table.add_column("Security Patch")
    table.add_column("Status")
    table.add_column("Min VNDK")
    table.add_column("Notes", style="dim")

    for v in versions:
        status_style = "green" if v.status == "stable" else "yellow"
        table.add_row(
            v.name,
            v.build_id,
            v.security_patch,
            f"[{status_style}]{v.status}[/]",
            str(v.min_vndk),
            v.notes,
        )
    console.print(table)


GSI_CACHE_DIR = Path.home() / ".phonectl" / "gsi_cache"


def download_gsi(
    version: GSIVersion,
    dest_dir: str | Path | None = None,
) -> Path:
    """Download a GSI zip and extract the system image.

    Downloads to ~/.phonectl/gsi_cache/<build_id>/ for persistence across reboots.
    """
    if dest_dir is None:
        dest_dir = GSI_CACHE_DIR / version.build_id
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    zip_path = dest_dir / f"gsi_{version.build_id}.zip"
    if zip_path.exists():
        console.print(f"[yellow]Using cached download:[/] {zip_path}")
    else:
        console.print(f"[bold]Downloading GSI:[/] {version.name} ({version.build_id})")
        download_file(version.download_url, zip_path, expected_sha256=version.sha256)

    # Extract system.img and vbmeta.img
    import zipfile
    with zipfile.ZipFile(zip_path) as zf:
        for name in ["system.img", "vbmeta.img"]:
            if name in zf.namelist():
                target = dest_dir / name
                if not target.exists():
                    console.print(f"Extracting {name}...")
                    zf.extract(name, dest_dir)

    system_img = dest_dir / "system.img"
    if not system_img.exists():
        raise FileNotFoundError(f"system.img not found in {zip_path}")

    console.print(f"[green]GSI ready:[/] {system_img}")
    return dest_dir


def find_compatible_version(
    vndk_version: str,
    config_path: str | Path | None = None,
) -> GSIVersion | None:
    """Find the best compatible GSI version for a given VNDK version."""
    versions = load_gsi_versions(config_path)
    vndk = int(vndk_version) if vndk_version.isdigit() else 0

    compatible = [
        v for v in versions
        if v.status == "stable" and vndk >= v.min_vndk
    ]

    return compatible[-1] if compatible else None


# ═══════════════════════════════════════════════════════════════
# Recommendation engine
# ═══════════════════════════════════════════════════════════════

@dataclass
class GSIRecommendation:
    version: GSIVersion
    verdict: str          # "recommended", "compatible", "incompatible", "broken"
    reasons: list[str]
    score: int            # 0-100, higher = better fit


def evaluate_all_versions(
    info,
    config_path: str | Path | None = None,
) -> list[GSIRecommendation]:
    """Evaluate ALL GSI versions against a device and return ranked recommendations.

    This is the core intelligence that prevents flashing an incompatible GSI.
    """
    from phonectl.core.safety import VNDK_GSI_COMPAT, MIN_KERNEL_VERSION, MIN_KERNEL_FOR_ANDROID13, GSI_ANDROID_REQUIREMENTS

    versions = load_gsi_versions(config_path)
    vndk = int(info.vndk_version) if info.vndk_version and info.vndk_version.isdigit() else 0
    ram = info.ram_total_mb or 0
    first_api = int(info.first_api_level) if info.first_api_level and info.first_api_level.isdigit() else 0
    kernel_ver = _parse_kernel(info.kernel_version) if info.kernel_version else (99, 99)
    gl_ver = int(info.opengl_version) if info.opengl_version and info.opengl_version.isdigit() else 0

    results: list[GSIRecommendation] = []

    for v in versions:
        reasons = []
        score = 50
        verdict = "compatible"

        # -- Broken status from config --
        if v.status == "broken":
            verdict = "broken"
            reasons.append(f"Marked BROKEN: {v.notes}")
            score = 0
            results.append(GSIRecommendation(v, verdict, reasons, score))
            continue

        # -- VNDKLite cross-version gate (Google Flash Tool alignment) --
        if getattr(info, 'vndk_lite', False):
            prefix = v.build_id[:4] if v.build_id else ""
            gsi_req = GSI_ANDROID_REQUIREMENTS.get(prefix, {})
            gsi_android = gsi_req.get("min_android", 0)
            device_android = int(info.android_version) if info.android_version and info.android_version.isdigit() else 0
            if gsi_android and device_android and gsi_android != device_android:
                verdict = "incompatible"
                reasons.append(
                    f"VNDKLite device (non-isolated vendor namespace) — "
                    f"can only flash same-version GSI "
                    f"(device: Android {device_android}, GSI: Android {gsi_android})"
                )
                score = 0
                results.append(GSIRecommendation(v, verdict, reasons, score))
                continue
            else:
                reasons.append("VNDKLite device — same-version GSI match OK")

        # -- VNDK compatibility (critical) --
        prefix = v.build_id[:4] if v.build_id else ""
        allowed = VNDK_GSI_COMPAT.get(str(vndk), [])
        if allowed and prefix not in allowed:
            verdict = "incompatible"
            reasons.append(f"VNDK {vndk} does not support {prefix} builds (allowed: {', '.join(allowed)})")
            score = 0
        else:
            reasons.append(f"VNDK {vndk} supports {prefix}")
            score += 15

        if verdict == "incompatible":
            results.append(GSIRecommendation(v, verdict, reasons, score))
            continue

        # -- min_vndk from GSI config --
        if vndk < v.min_vndk:
            verdict = "incompatible"
            reasons.append(f"Device VNDK {vndk} < required VNDK {v.min_vndk}")
            score = 0
            results.append(GSIRecommendation(v, verdict, reasons, score))
            continue

        # -- First API level --
        # GSI needs Treble (API 26+), but devices with API 26-27 that have
        # Treble enabled (like Nokia 6.1) can still run GSI.
        if first_api and first_api < 26:
            verdict = "incompatible"
            reasons.append(f"First API {first_api} — pre-Treble device (requires API 26+)")
            score = 0
            results.append(GSIRecommendation(v, verdict, reasons, score))
            continue
        if first_api and first_api < 28 and not info.treble_enabled:
            verdict = "incompatible"
            reasons.append(f"First API {first_api} without Treble support")
            score = 0
            results.append(GSIRecommendation(v, verdict, reasons, score))
            continue
        if first_api and first_api < 28:
            reasons.append(f"First API {first_api} — older device, Treble present")
            score -= 5

        # -- Kernel version (Android 13+ needs 4.19+, older needs 4.4+) --
        prefix = v.build_id[:4] if v.build_id else ""
        gsi_req = GSI_ANDROID_REQUIREMENTS.get(prefix, {})
        target_android = gsi_req.get("min_android", 16)
        required_kernel = MIN_KERNEL_FOR_ANDROID13 if target_android >= 13 else MIN_KERNEL_VERSION
        if kernel_ver < required_kernel:
            verdict = "incompatible"
            reasons.append(
                f"Kernel {info.kernel_version} too old for Android {target_android} "
                f"(needs {required_kernel[0]}.{required_kernel[1]}+)"
            )
            score = 0
            results.append(GSIRecommendation(v, verdict, reasons, score))
            continue

        # -- RAM --
        if ram > 0:
            if ram >= 4096:
                reasons.append(f"RAM {ram} MB — excellent")
                score += 10
            elif ram >= 2048:
                reasons.append(f"RAM {ram} MB — adequate")
                score += 5
            else:
                reasons.append(f"RAM {ram} MB — low, may be sluggish")
                score -= 10

        # -- OpenGL --
        if gl_ver > 0:
            if gl_ver >= 0x00030002:
                score += 5
            elif gl_ver < 0x00030000:
                reasons.append("OpenGL ES < 3.0 — some UI features may not work")
                score -= 5

        # -- Treble --
        if not info.treble_enabled:
            verdict = "incompatible"
            reasons.append("Device does not support Project Treble")
            score = 0
            results.append(GSIRecommendation(v, verdict, reasons, score))
            continue

        # -- Stable bonus --
        if v.status == "stable":
            score += 10
            reasons.append("Stable release")
        elif v.status == "beta":
            score -= 10
            reasons.append("Beta release — not recommended for daily use")

        # -- Download available --
        if v.download_url:
            score += 5
        else:
            reasons.append("No download URL available")
            score -= 15

        # -- Newer security patch = higher score --
        if v.security_patch:
            try:
                from datetime import datetime
                patch_date = datetime.strptime(v.security_patch, "%Y-%m-%d")
                age_days = (datetime.now() - patch_date).days
                if age_days < 180:
                    score += 10
                    reasons.append(f"Recent security patch ({v.security_patch})")
                elif age_days < 365:
                    score += 5
                else:
                    reasons.append(f"Security patch {v.security_patch} is {age_days} days old")
            except ValueError:
                pass

        score = max(0, min(100, score))

        if score >= 70:
            verdict = "recommended"
        elif score >= 40:
            verdict = "compatible"

        results.append(GSIRecommendation(v, verdict, reasons, score))

    results.sort(key=lambda r: r.score, reverse=True)
    return results


def show_recommendations(info, config_path: str | Path | None = None) -> list[GSIRecommendation]:
    """Evaluate and display ranked GSI recommendations for a device."""
    results = evaluate_all_versions(info, config_path)

    table = Table(title=f"GSI Recommendations for {info.codename or info.model or 'device'}")
    table.add_column("#", style="bold", width=3)
    table.add_column("Verdict", width=14)
    table.add_column("Name", style="cyan")
    table.add_column("Build ID", style="green")
    table.add_column("Patch")
    table.add_column("Score", width=6)
    table.add_column("Reasons", style="dim")

    for i, rec in enumerate(results, 1):
        verdict_styles = {
            "recommended": "[bold green]RECOMMENDED[/]",
            "compatible": "[yellow]COMPATIBLE[/]",
            "incompatible": "[red]INCOMPATIBLE[/]",
            "broken": "[bold red]BROKEN[/]",
        }
        verdict_str = verdict_styles.get(rec.verdict, rec.verdict)

        score_style = "green" if rec.score >= 70 else "yellow" if rec.score >= 40 else "red"

        table.add_row(
            str(i),
            verdict_str,
            rec.version.name,
            rec.version.build_id,
            rec.version.security_patch,
            f"[{score_style}]{rec.score}[/]",
            "; ".join(rec.reasons[:3]),
        )

    console.print(table)

    recommended = [r for r in results if r.verdict == "recommended"]
    compatible = [r for r in results if r.verdict == "compatible"]
    incompatible = [r for r in results if r.verdict in ("incompatible", "broken")]

    console.print(
        f"\n  [green]{len(recommended)} recommended[/]  "
        f"[yellow]{len(compatible)} compatible[/]  "
        f"[red]{len(incompatible)} incompatible[/]"
    )

    if recommended:
        best = recommended[0]
        console.print(
            f"\n[bold green]Best choice:[/] {best.version.name} "
            f"({best.version.build_id}, patch {best.version.security_patch})"
        )

    return results


def _parse_kernel(kernel_str: str) -> tuple[int, int]:
    import re
    match = re.match(r"(\d+)\.(\d+)", kernel_str)
    if match:
        return int(match.group(1)), int(match.group(2))
    return 0, 0
