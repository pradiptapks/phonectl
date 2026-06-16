"""Tune and reset commands."""

from __future__ import annotations

import click

from phonectl.commands._helpers import (
    console, create_device_manager, _detect_device,
)


@click.command()
@click.option("--profile", type=click.Choice(["fast", "balanced", "battery", "gaming"]),
              help="Apply a performance profile")
@click.option("--compile", "do_compile", is_flag=True, help="Force ART compilation for faster app launches")
@click.option("--reset", "do_reset", is_flag=True, help="Reset tuning to defaults")
def tune(profile: str | None, do_compile: bool, do_reset: bool):
    """Performance tuning — apply speed/battery/gaming profiles."""
    from phonectl.core.tune import TuneEngine

    dm = create_device_manager()
    _detect_device(dm)
    adb = dm.get_adb()
    if not adb:
        console.print("[red]ADB connection required.[/]")
        raise SystemExit(1)

    engine = TuneEngine(adb)

    if do_reset:
        engine.reset_to_defaults()
    elif do_compile:
        engine.compile_apps()
    elif profile:
        engine.apply_profile(profile)
    else:
        engine.show_status()


@click.command(name="reset")
@click.option("--factory", "do_factory", is_flag=True, help="Full factory reset via recovery")
@click.option("--wipe-data", "do_wipe", is_flag=True, help="Wipe userdata via fastboot")
@click.option("--clear-cache", "do_cache", is_flag=True, help="Clear all app caches (safe)")
@click.option("--app", "app_pkg", help="Clear data for a specific app package")
def reset_cmd(do_factory: bool, do_wipe: bool, do_cache: bool, app_pkg: str | None):
    """Factory reset and data management."""
    from phonectl.core.reset import ResetManager

    dm = create_device_manager()
    _detect_device(dm)
    adb = dm.get_adb()
    fb = dm.get_fastboot()
    manager = ResetManager(adb=adb, fastboot=fb)

    if do_factory:
        manager.factory_reset()
    elif do_wipe:
        manager.wipe_data()
    elif do_cache:
        manager.clear_all_caches()
    elif app_pkg:
        manager.clear_app_data(app_pkg)
    else:
        manager.show_options()
