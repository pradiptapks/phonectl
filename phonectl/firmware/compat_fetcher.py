"""Dynamic GSI compatibility fetcher — scrapes Google's GSI releases page.

Hybrid design: fetches fresh GSI version data on explicit user request
(phonectl update-gsi-db), caches locally, and merges with the static
gsi_versions.yaml at load time. Static entries are never removed and
status:"broken" annotations are preserved.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml
from rich.console import Console

console = Console()

RELEASES_URL = "https://developer.android.com/topic/generic-system-image/releases"
GSI_CACHE_DIR = Path.home() / ".phonectl" / "gsi_cache"
CACHE_FILE = "gsi_remote.yaml"
META_FILE = "gsi_remote.meta.json"
TTL_HOURS = 24

# Build ID prefix → reasonable min_vndk default (for newly discovered versions)
_PREFIX_MIN_VNDK = {
    17: 33, 16: 30, 15: 30, 14: 28, 13: 28, 12: 27, 11: 27,
}


class CompatFetcher:
    """Fetch and cache GSI version data from Google's releases page."""

    def __init__(self, cache_dir: str | Path | None = None):
        self.cache_dir = Path(cache_dir) if cache_dir else GSI_CACHE_DIR
        self.cache_path = self.cache_dir / CACHE_FILE
        self.meta_path = self.cache_dir / META_FILE

    def fetch(self) -> list[dict]:
        """Fetch latest GSI releases from Google. Returns parsed entries."""
        try:
            resp = requests.get(RELEASES_URL, timeout=20)
            resp.raise_for_status()
        except Exception as exc:
            console.print(f"[red]Failed to fetch GSI releases: {exc}[/]")
            return []

        entries = self._parse_releases(resp.text)
        if not entries:
            console.print("[yellow]No GSI versions parsed from releases page.[/]")
            return []

        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.cache_path.write_text(yaml.dump(
            {"versions": entries},
            default_flow_style=False,
            sort_keys=False,
        ))

        self.meta_path.write_text(json.dumps({
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source": RELEASES_URL,
            "count": len(entries),
        }, indent=2))

        return entries

    def _parse_releases(self, html: str) -> list[dict]:
        """Parse GSI release entries from the HTML page."""
        from phonectl.core.safety import GSI_ANDROID_REQUIREMENTS

        entries = []
        seen_build_ids = set()

        # Pattern 1: Extract from metadata blocks (Date/Build/Security patch)
        # These appear as structured text blocks on the page
        meta_pattern = re.compile(
            r'Date:\s*(.+?)\n.*?'
            r'Build:\s*(\S+).*?'
            r'Security patch level:\s*(.+?)(?:\n|$)',
            re.DOTALL,
        )

        # Pattern 2: ARM64+GMS download filename → build_id + sha256
        file_pattern = re.compile(
            r'(gsi_gms_arm64-exp-([A-Z0-9]+\.\d+\.\d+(?:\.\S+)?)-(\d+)-([a-f0-9]{8}))\.zip'
        )

        # Pattern 3: SHA-256 checksums (64-char hex near filenames)
        sha_pattern = re.compile(r'\b([a-f0-9]{64})\b')

        # Pattern 4: Download URLs from dl.google.com
        url_pattern = re.compile(
            r'https://dl\.google\.com/developers/android/[^"\'>\s]+\.zip'
        )

        # Pattern 5: Section headers to determine version name and status
        header_pattern = re.compile(
            r'Android\s+(\d+)\s*(QPR\d+)?\s*(?:\(([^)]+)\))?\s*(?:GSI)?'
        )

        # Collect all download URLs for lookup
        all_urls = url_pattern.findall(html)
        url_by_build = {}
        for url in all_urls:
            fm = file_pattern.search(url)
            if fm:
                url_by_build[fm.group(2)] = url

        # Collect all SHA-256 hashes near each filename
        sha_by_build: dict[str, str] = {}
        for fm in file_pattern.finditer(html):
            build_id = fm.group(2)
            context_start = max(0, fm.start() - 200)
            context_end = min(len(html), fm.end() + 500)
            context = html[context_start:context_end]
            sha_matches = sha_pattern.findall(context)
            if sha_matches:
                sha_by_build[build_id] = sha_matches[-1]

        # Extract from metadata blocks
        for match in meta_pattern.finditer(html):
            date_str, build_id, patch_level = match.groups()
            if build_id in seen_build_ids:
                continue
            seen_build_ids.add(build_id)

            # Determine name and status from surrounding context
            context_start = max(0, match.start() - 500)
            context = html[context_start:match.start()]

            name = f"Android GSI {build_id[:4]}"
            status = "stable"
            for hm in header_pattern.finditer(context):
                ver, qpr, extra = hm.groups()
                name_parts = [f"Android {ver}"]
                if qpr:
                    name_parts.append(qpr)
                if extra:
                    name_parts.append(f"({extra})")
                name = " ".join(name_parts)

            if "beta" in context.lower() or "preview" in context.lower():
                status = "beta"

            # Determine min_vndk from build ID prefix
            prefix = build_id[:4]
            gsi_req = GSI_ANDROID_REQUIREMENTS.get(prefix, {})
            android_ver = gsi_req.get("min_android", 16)
            min_vndk = _PREFIX_MIN_VNDK.get(android_ver, 30)

            # Normalize security patch to YYYY-MM-DD
            security_patch = _normalize_patch_date(patch_level.strip(), date_str.strip())

            entry = {
                "name": name,
                "build_id": build_id,
                "security_patch": security_patch,
                "status": status,
                "download_url": url_by_build.get(build_id, ""),
                "sha256": sha_by_build.get(build_id, ""),
                "min_vndk": min_vndk,
                "notes": "Fetched from developer.android.com",
            }
            entries.append(entry)

        # Fallback: extract from filenames if metadata blocks missed them
        for fm in file_pattern.finditer(html):
            build_id = fm.group(2)
            if build_id in seen_build_ids:
                continue
            seen_build_ids.add(build_id)

            prefix = build_id[:4]
            gsi_req = GSI_ANDROID_REQUIREMENTS.get(prefix, {})
            android_ver = gsi_req.get("min_android", 16)
            name = gsi_req.get("name", f"Android {android_ver}")

            entries.append({
                "name": name,
                "build_id": build_id,
                "security_patch": "",
                "status": "stable",
                "download_url": url_by_build.get(build_id, ""),
                "sha256": sha_by_build.get(build_id, ""),
                "min_vndk": _PREFIX_MIN_VNDK.get(android_ver, 30),
                "notes": "Fetched from developer.android.com (filename only)",
            })

        return entries

    def load_cached(self) -> list[dict] | None:
        """Load cached GSI data if it exists and hasn't expired."""
        if not self.meta_path.exists() or not self.cache_path.exists():
            return None

        try:
            meta = json.loads(self.meta_path.read_text())
            fetched_at = datetime.fromisoformat(meta["fetched_at"])
            age_hours = (datetime.now(timezone.utc) - fetched_at).total_seconds() / 3600
            if age_hours > TTL_HOURS:
                return None

            data = yaml.safe_load(self.cache_path.read_text())
            return data.get("versions", []) if data else None
        except (json.JSONDecodeError, yaml.YAMLError, KeyError, ValueError, TypeError):
            return None

    def is_stale(self) -> bool:
        """Check if cache is missing or expired."""
        return self.load_cached() is None


def _normalize_patch_date(patch_str: str, date_str: str = "") -> str:
    """Try to normalize a patch level string to YYYY-MM-DD format."""
    # Already in YYYY-MM-DD format
    if re.match(r"\d{4}-\d{2}-\d{2}", patch_str):
        return patch_str[:10]

    # "June 2026" or "May 2025" → approximate to YYYY-MM-05
    month_match = re.match(r"(\w+)\s+(\d{4})", patch_str)
    if month_match:
        try:
            dt = datetime.strptime(f"{month_match.group(1)} {month_match.group(2)}", "%B %Y")
            return dt.strftime("%Y-%m-05")
        except ValueError:
            pass

    # Try parsing the release date instead
    for fmt in ("%B %d, %Y", "%Y-%m-%d", "%b %d, %Y"):
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.strftime("%Y-%m-05")
        except ValueError:
            continue

    return patch_str
