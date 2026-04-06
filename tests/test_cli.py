"""CLI tests for taco — flag handling, dry-run, error paths."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from taco.cli import app

runner = CliRunner()


def _make_project(tmp_path: Path) -> Path:
    """Create a minimal uv project scaffold."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'testproj'\n")
    venv = tmp_path / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").write_text("#!/bin/sh\n")
    (venv / "python").chmod(0o755)
    return tmp_path


def test_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "uv notebook bootstrapper" in result.output


def test_dry_run(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    with patch("taco.core._is_package_importable", return_value=True):
        result = runner.invoke(app, ["--project", str(project), "--dry-run"])
    assert result.exit_code == 0
    assert "Would run" in result.output or "Would patch" in result.output


def test_no_marimo_flag(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    with patch("taco.core._is_package_importable", return_value=True), \
         patch("taco.core.install_kernel") as mock_install, \
         patch("taco.core.patch_kernelspec"):
        mock_install.return_value = tmp_path / "kernels" / "testproj"
        result = runner.invoke(app, ["--project", str(project), "--no-marimo", "--dry-run"])
    assert result.exit_code == 0
    assert "skipped" in result.output


def test_custom_name_and_display_name(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    with patch("taco.core._is_package_importable", return_value=True), \
         patch("taco.core.install_kernel") as mock_install, \
         patch("taco.core.patch_kernelspec"):
        mock_install.return_value = tmp_path / "kernels" / "custom"
        result = runner.invoke(app, [
            "--project", str(project),
            "--name", "custom",
            "--display-name", "My Custom Kernel",
            "--dry-run",
        ])
    assert result.exit_code == 0
    assert "custom" in result.output


def test_error_outside_uv_project(tmp_path: Path) -> None:
    result = runner.invoke(app, ["--project", str(tmp_path)])
    assert result.exit_code != 0
