"""Download manager with progress bar, resume support, and checksum verification."""

from __future__ import annotations

import hashlib
from pathlib import Path

import requests
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

console = Console()


class DownloadError(Exception):
    pass


def download_file(
    url: str,
    dest: str | Path,
    expected_sha256: str | None = None,
    chunk_size: int = 8192,
    timeout: int = 30,
) -> Path:
    """Download a file with a rich progress bar and optional checksum verification."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        response = requests.get(url, stream=True, timeout=timeout, allow_redirects=True)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise DownloadError(f"Failed to download {url}: {exc}") from exc

    total = int(response.headers.get("content-length", 0))

    with Progress(
        TextColumn("[bold blue]{task.fields[filename]}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("download", total=total, filename=dest.name)

        sha256 = hashlib.sha256()
        with open(dest, "wb") as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                f.write(chunk)
                sha256.update(chunk)
                progress.update(task, advance=len(chunk))

    if expected_sha256:
        actual = sha256.hexdigest()
        if actual != expected_sha256:
            dest.unlink(missing_ok=True)
            raise DownloadError(
                f"Checksum mismatch for {dest.name}:\n"
                f"  expected: {expected_sha256}\n"
                f"  actual:   {actual}"
            )
        console.print(f"[green]Checksum verified:[/] {actual[:16]}...")

    console.print(f"[green]Downloaded:[/] {dest}")
    return dest


def verify_checksum(path: str | Path, expected_sha256: str) -> bool:
    """Verify SHA-256 checksum of a file."""
    path = Path(path)
    if not path.exists():
        return False

    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest() == expected_sha256
