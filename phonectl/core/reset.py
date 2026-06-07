"""Factory reset and data management — safe reset flows with SafetyGuard."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel

if TYPE_CHECKING:
    from phonectl.core.adb import ADBClient
    from phonectl.core.device import DeviceInfo
    from phonectl.core.fastboot import FastbootClient

console = Console()

FRP_WARNING = (
    "[bold yellow]Google Factory Reset Protection (FRP):[/]\n"
    "If you have a Google account on this device, remove it BEFORE resetting.\n"
    "Otherwise the phone will be locked to that account after reset.\n"
    "Go to: Settings > Accounts > Google > Remove Account"
)

ENCRYPTION_WARNING = (
    "[bold red]Encrypted data is IRRECOVERABLE after factory reset.[/]\n"
    "Photos, messages, app data, and all personal files will be permanently erased."
)


class ResetManager:
    """Manage device reset operations with safety confirmations."""

    def __init__(self, adb: ADBClient | None = None, fastboot: FastbootClient | None = None):
        self.adb = adb
        self.fastboot = fastboot

    def show_options(self) -> None:
        """Display available reset options."""
        table_lines = [
            "  [cyan]--factory[/]      Full factory reset via recovery (erases ALL data)",
            "  [cyan]--wipe-data[/]    Wipe userdata partition via fastboot",
            "  [cyan]--clear-cache[/]  Clear all app caches (safe, no data loss)",
            "  [cyan]--app <pkg>[/]    Clear data for a single app",
        ]
        console.print(Panel(
            "\n".join(table_lines),
            title="[bold]Reset Options[/]",
            border_style="yellow",
        ))

    def factory_reset(self) -> bool:
        """Full factory reset via recovery mode."""
        if not self.adb:
            console.print("[red]ADB connection required.[/]")
            return False

        console.print(Panel(FRP_WARNING, border_style="yellow", title="[bold]Warning[/]"))
        console.print(Panel(ENCRYPTION_WARNING, border_style="red"))

        console.print("\n[bold]This will:[/]")
        console.print("  - Erase ALL apps, photos, messages, and personal data")
        console.print("  - Reset the phone to initial setup screen")
        console.print("  - Require Google account re-login if FRP is active")

        console.print("\n[bold]Recommendation:[/] Run [cyan]phonectl backup create[/] first.")

        response = console.input("\n[bold red]Type RESET to confirm factory reset, anything else to cancel: [/]")
        if response.strip() != "RESET":
            console.print("[yellow]Aborted.[/]")
            return False

        console.print("[bold]Rebooting to recovery for factory reset...[/]")
        try:
            self.adb.reboot_recovery()
            console.print(
                "[green]Phone rebooting to recovery.[/]\n"
                "On the recovery screen:\n"
                "  1. Select 'Wipe data/factory reset'\n"
                "  2. Confirm the wipe\n"
                "  3. Select 'Reboot system now'"
            )
            return True
        except Exception as exc:
            console.print(f"[red]Failed: {exc}[/]")
            return False

    def wipe_data(self) -> bool:
        """Wipe userdata partition via fastboot."""
        if not self.fastboot:
            console.print("[red]Device must be in fastboot mode.[/]")
            console.print("Run: [cyan]adb reboot fastboot[/]")
            return False

        console.print(Panel(ENCRYPTION_WARNING, border_style="red"))

        response = console.input("\n[bold red]Type RESET to wipe userdata, anything else to cancel: [/]")
        if response.strip() != "RESET":
            console.print("[yellow]Aborted.[/]")
            return False

        console.print("[bold]Wiping userdata...[/]")
        try:
            self.fastboot.wipe()
            console.print("[green]Userdata wiped.[/] Reboot with: [cyan]fastboot reboot[/]")
            return True
        except Exception as exc:
            console.print(f"[red]Failed: {exc}[/]")
            return False

    def clear_all_caches(self) -> bool:
        """Clear all app caches — safe, no data loss."""
        if not self.adb:
            console.print("[red]ADB connection required.[/]")
            return False

        console.print("[bold]Clearing all app caches...[/]")
        try:
            self.adb.shell("pm trim-caches 999G")
            console.print("[green]All app caches cleared.[/]")
            console.print("[dim]Apps will rebuild caches as needed — no data lost.[/]")
            return True
        except Exception as exc:
            console.print(f"[red]Failed: {exc}[/]")
            return False

    def clear_app_data(self, package: str) -> bool:
        """Clear data for a specific app."""
        if not self.adb:
            console.print("[red]ADB connection required.[/]")
            return False

        try:
            packages = self.adb.shell("pm list packages")
            if f"package:{package}" not in packages:
                console.print(f"[red]Package not found: {package}[/]")
                return False
        except Exception:
            pass

        console.print(f"[bold]Clear data for: {package}[/]")
        console.print("[yellow]This will erase the app's login, settings, and cached data.[/]")

        response = console.input("[yellow]Type 'yes' to confirm: [/]")
        if response.strip().lower() != "yes":
            console.print("[yellow]Aborted.[/]")
            return False

        try:
            self.adb.shell_safe("pm clear {}", [package])
            console.print(f"[green]Data cleared for {package}.[/]")
            return True
        except Exception as exc:
            console.print(f"[red]Failed: {exc}[/]")
            return False
