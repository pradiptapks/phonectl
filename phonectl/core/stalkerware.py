"""Stalkerware and spyware detection — scans installed packages against known threats.

Sources: Coalition Against Stalkerware, EFF, Kaspersky threat intelligence,
and community-reported package names.
"""

from __future__ import annotations

from pathlib import Path

import yaml


def _load_database(config_path: str | Path | None = None) -> list[dict]:
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config" / "stalkerware.yaml"
    path = Path(config_path)
    if path.exists():
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return data.get("stalkerware", [])
    return _builtin_database()


def _builtin_database() -> list[dict]:
    """Fallback if stalkerware.yaml is missing."""
    return [
        {"name": "FlexiSpy", "packages": ["com.flexispy.app"]},
        {"name": "mSpy", "packages": ["com.mspy.app"]},
        {"name": "Cerberus", "packages": ["com.lsdroid.cerberus"]},
    ]


def scan_for_stalkerware(
    installed_packages: list[str],
    config_path: str | Path | None = None,
) -> list[dict]:
    """Scan a list of installed package names against the stalkerware database.

    Returns a list of dicts with 'name' and 'matched_package' for each hit.
    """
    db = _load_database(config_path)
    found = []

    installed_set = set(installed_packages)
    for entry in db:
        for pkg in entry.get("packages", []):
            if pkg in installed_set:
                found.append({
                    "name": entry["name"],
                    "matched_package": pkg,
                    "category": entry.get("category", "stalkerware"),
                })
    return found


def get_database_stats(config_path: str | Path | None = None) -> dict:
    """Return database statistics."""
    db = _load_database(config_path)
    total_names = len(db)
    total_packages = sum(len(e.get("packages", [])) for e in db)
    categories = set(e.get("category", "stalkerware") for e in db)
    return {
        "threat_families": total_names,
        "package_signatures": total_packages,
        "categories": list(categories),
    }
