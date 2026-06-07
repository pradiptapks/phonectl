"""Community compatibility database — crowdsourced GSI compatibility data.

Uses GitHub Pages to host a static JSON file with anonymous device+GSI
compatibility reports. No server infrastructure required.

Data flow:
    phonectl compat              → fetch data.json from GitHub Pages
    phonectl compat --submit     → create GitHub Issue with device report

Privacy: only device codename, VNDK, kernel, GSI build, and result are
submitted. Never serial numbers, IMEI, accounts, or personal data.

Status: STUB — interface defined, implementation for future use.
"""

from __future__ import annotations

from dataclasses import dataclass, field


COMPAT_DATA_URL = "https://pradiptapks.github.io/phonectl/compatibility/data.json"


@dataclass
class CompatReport:
    """A single compatibility report from a user."""
    codename: str = ""
    vndk_version: str = ""
    kernel_version: str = ""
    gsi_build_id: str = ""
    result: str = ""  # "success", "boot_loop", "partial", "fail"
    ram_mb: int = 0
    notes: str = ""


@dataclass
class CompatDatabase:
    """Aggregated compatibility data for a device."""
    codename: str = ""
    total_reports: int = 0
    success_rate: float = 0.0
    reports: list[CompatReport] = field(default_factory=list)
    best_gsi: str = ""


class CommunityCompat:
    """Community compatibility database client.

    Not yet implemented — this is a stub defining the interface.
    When implemented, will fetch/submit data via GitHub Pages + Issues.
    """

    def __init__(self, data_url: str = COMPAT_DATA_URL):
        self.data_url = data_url

    def is_available(self) -> bool:
        """Check if the community database is reachable."""
        try:
            import requests
            resp = requests.head(self.data_url, timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def lookup(self, codename: str) -> CompatDatabase | None:
        """Look up compatibility data for a device codename."""
        raise NotImplementedError(
            "Community compatibility database not yet implemented. "
            "Future: fetch from GitHub Pages JSON."
        )

    def submit(self, report: CompatReport) -> bool:
        """Submit an anonymous compatibility report."""
        raise NotImplementedError(
            "Community report submission not yet implemented. "
            "Future: create GitHub Issue via gh CLI or API."
        )

    def generate_report(self, info) -> CompatReport:
        """Generate a compatibility report from current device state.

        Only includes non-PII data: codename, VNDK, kernel, GSI build, result.
        """
        raise NotImplementedError(
            "Report generation not yet implemented."
        )


# Future GitHub Issue template for submissions
SUBMIT_TEMPLATE = """
## Compatibility Report

**Device:** {codename}
**VNDK:** {vndk_version}
**Kernel:** {kernel_version}
**GSI:** {gsi_build_id}
**Result:** {result}
**RAM:** {ram_mb} MB
**Notes:** {notes}

---
*Submitted via phonectl compat --submit*
"""
