"""phonectl CLI — Click-based command interface for Android phone management.

This is the entry point that assembles command groups from phonectl/commands/.
Individual command implementations live in their own modules.
"""

from __future__ import annotations

import click

from phonectl.commands._helpers import console

WARRANTY_NOTICE = (
    "[bold yellow]WARNING:[/] This tool is intended for devices that are "
    "[bold]out of warranty[/] and/or no longer receiving official OEM updates. "
    "Flashing GSI or modifying boot partitions [bold red]will void your warranty[/] "
    "and may brick your device if used incorrectly. "
    "[bold]Proceed at your own risk.[/]"
)


@click.group()
@click.version_option(package_name="phonectl")
@click.option("-q", "--quiet", is_flag=True, help="Suppress warranty banner")
@click.pass_context
def cli(ctx, quiet):
    """phonectl — Universal Android Phone Lifecycle Manager.

    \b
    WARNING: This tool is intended for devices that are OUT OF WARRANTY
    and/or no longer receiving official OEM updates. Flashing GSI or
    modifying boot partitions WILL VOID YOUR WARRANTY and may brick
    your device if used incorrectly. Proceed at your own risk.
    """
    ctx.ensure_object(dict)
    if not quiet:
        console.print(f"\n{WARRANTY_NOTICE}\n", highlight=False)


# ── Register command groups from phonectl/commands/ ──

from phonectl.commands.info import info, check, recommend  # noqa: E402
from phonectl.commands.flash import flash, flash_gsi, update, recover  # noqa: E402
from phonectl.commands.backup_cmds import backup  # noqa: E402
from phonectl.commands.firmware_cmds import firmware, update_gsi_db  # noqa: E402
from phonectl.commands.diagnose_cmds import diagnose, ask, report  # noqa: E402
from phonectl.commands.tune_cmds import tune, reset_cmd  # noqa: E402
from phonectl.commands.security_cmds import audit, security  # noqa: E402
from phonectl.commands.storage_cmds import storage  # noqa: E402

cli.add_command(info)
cli.add_command(check)
cli.add_command(recommend)
cli.add_command(flash)
cli.add_command(update)
cli.add_command(recover)
cli.add_command(backup)
cli.add_command(firmware)
cli.add_command(update_gsi_db)
cli.add_command(diagnose)
cli.add_command(ask)
cli.add_command(report)
cli.add_command(tune)
cli.add_command(reset_cmd)
cli.add_command(audit)
cli.add_command(security)
cli.add_command(storage)


@cli.command()
def tui():
    """Launch interactive TUI mode."""
    from phonectl.tui import run_tui
    run_tui()
