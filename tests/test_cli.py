"""Smoke tests for CLI commands using Click test runner."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

from click.testing import CliRunner

from phonectl.cli import cli


class TestCLISmoke:
    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "phonectl" in result.output

    def test_quiet_flag_suppresses_banner(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["-q", "--help"])
        assert result.exit_code == 0
        assert "WARNING" not in result.output.split("Usage:")[0]

    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0

    def test_flash_group_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["-q", "flash", "--help"])
        assert result.exit_code == 0
        assert "gsi" in result.output

    def test_storage_group_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["-q", "storage", "--help"])
        assert result.exit_code == 0
        assert "bloatware" in result.output

    def test_firmware_group_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["-q", "firmware", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output

    def test_backup_group_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["-q", "backup", "--help"])
        assert result.exit_code == 0
        assert "create" in result.output
