"""Anomaly detection — statistical analysis of battery, data usage, and app activity.

Identifies apps with abnormal resource consumption patterns that may indicate
malware, spyware, or misconfigured software.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from phonectl.core.adb import ADBClient
    from phonectl.core.audit import AuditCheck

console = Console()

BATTERY_THRESHOLD_PCT = 8.0
DATA_THRESHOLD_MB = 50
UNUSED_DAYS_THRESHOLD = 30

SYSTEM_BATTERY_APPS = {
    "screen", "wifi", "cell", "idle", "bluetooth", "phone", "mediaserver",
    "system", "android", "com.android.systemui", "com.google.android.gms",
    "com.android.phone",
}


@dataclass
class AppAnomaly:
    package: str
    metric: str
    value: str
    threshold: str
    description: str


class AnomalyDetector:
    """Detect anomalous app behaviour from system dumps."""

    def __init__(self, adb: ADBClient):
        self.adb = adb

    def run_all(self) -> list:
        """Run all anomaly checks and return AuditCheck-compatible results."""
        from phonectl.core.audit import AuditCheck

        checks = []
        checks.append(self._check_battery_drain())
        checks.append(self._check_data_usage())
        checks.append(self._check_unused_active_apps())
        return checks

    def _check_battery_drain(self):
        """Flag apps consuming abnormal battery."""
        from phonectl.core.audit import AuditCheck

        anomalies = []
        try:
            output = self.adb.shell("dumpsys batterystats --charged")
            current_uid = ""
            for line in output.splitlines():
                match = re.search(r'Uid\s+(\S+):\s+(\d+\.?\d*)', line)
                if not match:
                    match = re.search(r'(\S+):\s+(\d+\.?\d*)%', line)
                if match:
                    app = match.group(1).strip()
                    try:
                        pct = float(match.group(2))
                    except ValueError:
                        continue
                    if pct > BATTERY_THRESHOLD_PCT and app.lower() not in SYSTEM_BATTERY_APPS:
                        if "." in app:
                            anomalies.append(AppAnomaly(
                                package=app, metric="battery",
                                value=f"{pct:.1f}%", threshold=f">{BATTERY_THRESHOLD_PCT}%",
                                description=f"Using {pct:.1f}% battery",
                            ))
        except Exception:
            pass

        if anomalies:
            detail = f"{len(anomalies)} app(s) with high battery usage:\n"
            for a in anomalies[:10]:
                detail += f"    - {a.package}: {a.value}\n"
        else:
            detail = "No abnormal battery consumption detected"

        return AuditCheck(
            name="Battery drain anomaly",
            category="Anomaly Detection",
            passed=len(anomalies) == 0,
            severity="warning" if anomalies else "info",
            detail=detail.rstrip(),
        )

    def _check_data_usage(self):
        """Flag apps with suspicious background data transfer."""
        from phonectl.core.audit import AuditCheck

        anomalies = []
        try:
            output = self.adb.shell("dumpsys netstats --full")
            for line in output.splitlines():
                match = re.search(r'ident=.*uid=(\d+).*rb=(\d+).*tb=(\d+)', line)
                if match:
                    uid = match.group(1)
                    rx_bytes = int(match.group(2))
                    tx_bytes = int(match.group(3))
                    total_mb = (rx_bytes + tx_bytes) / (1024 * 1024)

                    if total_mb > DATA_THRESHOLD_MB:
                        try:
                            pkg_output = self.adb.shell(f"dumpsys package | grep 'userId={uid}' | head -1")
                            pkg_match = re.search(r'Package \[([^\]]+)\]', pkg_output)
                            pkg_name = pkg_match.group(1) if pkg_match else f"UID:{uid}"
                        except Exception:
                            pkg_name = f"UID:{uid}"

                        if not pkg_name.startswith(("com.android.", "com.google.")):
                            anomalies.append(AppAnomaly(
                                package=pkg_name, metric="data",
                                value=f"{total_mb:.0f} MB",
                                threshold=f">{DATA_THRESHOLD_MB} MB",
                                description=f"Transferred {total_mb:.0f} MB",
                            ))
        except Exception:
            pass

        if anomalies:
            detail = f"{len(anomalies)} app(s) with high data usage:\n"
            for a in anomalies[:10]:
                detail += f"    - {a.package}: {a.value}\n"
        else:
            detail = "No suspicious data transfer patterns detected"

        return AuditCheck(
            name="Data usage anomaly",
            category="Anomaly Detection",
            passed=len(anomalies) <= 2,
            severity="warning" if len(anomalies) > 2 else "info",
            detail=detail.rstrip(),
        )

    def _check_unused_active_apps(self):
        """Flag apps not used recently but still consuming resources."""
        from phonectl.core.audit import AuditCheck

        anomalies = []
        try:
            output = self.adb.shell("dumpsys usagestats")
            current_pkg = ""
            last_used_ms = 0
            total_time_ms = 0

            import time
            now_ms = int(time.time() * 1000)
            threshold_ms = UNUSED_DAYS_THRESHOLD * 24 * 3600 * 1000

            for line in output.splitlines():
                pkg_match = re.search(r'package=(\S+)', line)
                if pkg_match:
                    if current_pkg and (now_ms - last_used_ms) > threshold_ms and total_time_ms > 0:
                        if not current_pkg.startswith(("com.android.", "com.google.android.")):
                            days_ago = (now_ms - last_used_ms) // (24 * 3600 * 1000)
                            anomalies.append(AppAnomaly(
                                package=current_pkg, metric="unused",
                                value=f"{days_ago} days",
                                threshold=f">{UNUSED_DAYS_THRESHOLD} days",
                                description=f"Not used in {days_ago} days but has foreground time",
                            ))
                    current_pkg = pkg_match.group(1)
                    last_used_ms = 0
                    total_time_ms = 0

                time_match = re.search(r'lastTimeUsed="?(\d+)"?', line)
                if time_match:
                    last_used_ms = max(last_used_ms, int(time_match.group(1)))

                fg_match = re.search(r'totalTimeInForeground="?(\d+)"?', line)
                if fg_match:
                    total_time_ms += int(fg_match.group(1))

        except Exception:
            pass

        anomalies = anomalies[:20]

        if anomalies:
            detail = f"{len(anomalies)} unused app(s) still consuming resources:\n"
            for a in anomalies[:10]:
                detail += f"    - {a.package}: not used in {a.value}\n"
            if len(anomalies) > 10:
                detail += f"    ... and {len(anomalies) - 10} more\n"
        else:
            detail = "No resource-wasting unused apps detected"

        return AuditCheck(
            name="Unused app resource waste",
            category="Anomaly Detection",
            passed=len(anomalies) <= 5,
            severity="warning" if len(anomalies) > 5 else "info",
            detail=detail.rstrip(),
        )
