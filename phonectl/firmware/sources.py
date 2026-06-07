"""Firmware source registry — lolinet, Google CDN, and local files."""

from __future__ import annotations

import re
from dataclasses import dataclass

import requests
from rich.console import Console

console = Console()

LOLINET_BASE = "https://mirrors-obs-1.lolinet.com/firmware/lenomola"
GOOGLE_GSI_BASE = "https://dl.google.com/developers/android/baklava/images/gsi"


@dataclass
class FirmwareFile:
    name: str
    url: str
    size: str = ""
    date: str = ""


class SourceError(Exception):
    pass


class LolinetSource:
    """Motorola firmware from lolinet mirrors — the most reliable public source."""

    def __init__(self, base_url: str = LOLINET_BASE):
        self.base_url = base_url

    def list_regions(self, codename: str) -> list[str]:
        url = f"{self.base_url}/2021/{codename}/official/"
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise SourceError(f"Cannot reach lolinet: {exc}") from exc

        regions = re.findall(r'href="/firmware/[^"]*official/(\w+)/"', resp.text)
        return regions

    def list_firmware(self, codename: str, region: str) -> list[FirmwareFile]:
        url = f"{self.base_url}/2021/{codename}/official/{region}/"
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise SourceError(f"Cannot list firmware: {exc}") from exc

        files = []
        for match in re.finditer(
            r'href="(/firmware/[^"]*\.zip)"[^>]*>([^<]+)</a>\s*</td>'
            r'\s*<td[^>]*>([^<]*)</td>\s*<td[^>]*>([^<]*)</td>',
            resp.text,
        ):
            path, name, date, size = match.groups()
            files.append(FirmwareFile(
                name=name.strip(),
                url=f"https://mirrors-obs-1.lolinet.com{path}",
                date=date.strip(),
                size=size.strip(),
            ))

        if not files:
            for match in re.finditer(r'href="(/firmware/[^"]*\.zip)"', resp.text):
                path = match.group(1)
                name = path.rsplit("/", 1)[-1]
                files.append(FirmwareFile(
                    name=name,
                    url=f"https://mirrors-obs-1.lolinet.com{path}",
                ))

        return files

    def get_download_url(self, codename: str, region: str) -> str | None:
        files = self.list_firmware(codename, region)
        if not files:
            return None
        android12 = [f for f in files if "S2R" in f.name or "12" in f.name]
        return android12[-1].url if android12 else files[-1].url


class GoogleGSISource:
    """Google GSI images from official CDN."""

    def get_download_url(self, build_id: str, file_hash: str, build_number: str) -> str:
        filename = f"gsi_gms_arm64-exp-{build_id}-{build_number}-{file_hash}.zip"
        return f"{GOOGLE_GSI_BASE}/{filename}"
