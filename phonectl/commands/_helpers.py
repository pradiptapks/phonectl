"""Shared helpers for CLI command modules."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from phonectl.core.device import DeviceInfo, DeviceManager, DeviceState
from phonectl.vendors.registry import create_device_manager

console = Console()


def _detect_device(dm: DeviceManager) -> DeviceInfo:
    info = dm.detect()
    if info.state == DeviceState.DISCONNECTED:
        console.print("[red]No device connected.[/] Connect via USB and enable USB debugging.")
        raise SystemExit(1)
    if info.state == DeviceState.UNAUTHORIZED:
        console.print("[yellow]Device unauthorized.[/] Approve the USB debugging prompt on your phone.")
        raise SystemExit(1)
    return info


def _show_device_panel(info: DeviceInfo, vendor_name: str = "") -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="cyan")
    table.add_column()

    table.add_row("Manufacturer", info.manufacturer or "Unknown")
    table.add_row("Model", info.model or "Unknown")
    table.add_row("Codename", info.codename or "Unknown")
    table.add_row("Serial", info.serial)
    table.add_row("State", info.state.value)
    if vendor_name:
        table.add_row("Vendor Plugin", vendor_name)
    if info.android_version:
        table.add_row("Android", info.android_version)
    if info.security_patch:
        table.add_row("Security Patch", info.security_patch)
    if info.build_id:
        table.add_row("Build ID", info.build_id)
    if info.kernel_version:
        table.add_row("Kernel", info.kernel_version)
    if info.vndk_version:
        table.add_row("VNDK", info.vndk_version)
    if info.slot_suffix:
        table.add_row("Active Slot", info.slot_suffix)
    table.add_row("Bootloader", "Unlocked" if info.is_unlocked else "Locked")
    table.add_row("Treble", "Yes" if info.treble_enabled else "No")
    table.add_row("Dynamic Partitions", "Yes" if info.dynamic_partitions else "No")
    if info.slot_count:
        table.add_row("A/B Slots", info.slot_count)
    if info.cpu_abi:
        table.add_row("CPU ABI", info.cpu_abi)
    if info.board_platform:
        table.add_row("Platform", info.board_platform)
    if info.ram_total_mb:
        table.add_row("RAM", f"{info.ram_total_mb} MB")
    if info.storage_total_gb:
        table.add_row("Storage", f"{info.storage_total_gb} GB total, {info.storage_free_gb} GB free")
    if info.opengl_version:
        try:
            gl_int = int(info.opengl_version)
            table.add_row("OpenGL ES", f"{(gl_int >> 16) & 0xFFFF}.{gl_int & 0xFFFF}")
        except ValueError:
            table.add_row("OpenGL ES", info.opengl_version)
    if info.first_api_level:
        table.add_row("First API Level", info.first_api_level)
    if info.vendor_security_patch:
        table.add_row("Vendor Patch", info.vendor_security_patch)
    if info.battery_level:
        table.add_row("Battery", f"{info.battery_level}%")
    if info.uptime:
        table.add_row("Uptime", info.uptime)

    console.print(Panel(table, title="[bold]Device Info[/]", border_style="green"))
