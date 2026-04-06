"""CLI tests for taco — flag handling, subcommands, dry-run, error paths."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from taco.cli import app

runner = CliRunner()


def _make_project(tmp_path: Path, name: str = "testproj") -> Path:
    """Create a minimal project scaffold in a fixed-name subdirectory."""
    project = tmp_path / name
    project.mkdir()
    (project / "pyproject.toml").write_text(f"[project]\nname = '{name}'\n")
    venv = project / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").write_text("#!/bin/sh\n")
    (venv / "python").chmod(0o755)
    return project


def _make_poetry_project(tmp_path: Path) -> Path:
    """Create a poetry project scaffold."""
    project = tmp_path / "poetryproj"
    project.mkdir()
    (project / "pyproject.toml").write_text("[tool.poetry]\nname = 'poetryproj'\n")
    (project / "poetry.lock").write_text("")
    venv = project / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").write_text("#!/bin/sh\n")
    (venv / "python").chmod(0o755)
    return project


def _make_pip_project(tmp_path: Path) -> Path:
    """Create a pip/venv project scaffold."""
    project = tmp_path / "pipproj"
    project.mkdir()
    (project / "requirements.txt").write_text("requests\n")
    venv = project / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").write_text("#!/bin/sh\n")
    (venv / "python").chmod(0o755)
    return project


def _make_kernel(project: Path, name: str = "testproj") -> Path:
    """Create a fake kernelspec directory inside the project venv."""
    kernel_dir = project / ".venv" / "share" / "jupyter" / "kernels" / name
    kernel_dir.mkdir(parents=True)
    (kernel_dir / "kernel.json").write_text(json.dumps({
        "argv": [str(project / ".venv" / "bin" / "python"), "-m", "ipykernel_launcher", "-f", "{connection_file}"],
        "display_name": f"Python ({name})",
        "language": "python",
        "env": {"VIRTUAL_ENV": str(project / ".venv")},
    }))
    return kernel_dir


# --- help ---


def test_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "notebook bootstrapper" in result.output


def test_setup_help() -> None:
    result = runner.invoke(app, ["setup", "--help"])
    assert result.exit_code == 0
    assert "Set up Jupyter kernels" in result.output


# --- setup (explicit subcommand) ---


def test_setup_dry_run(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    with patch("taco.core._is_package_importable", return_value=True):
        result = runner.invoke(app, ["setup", "--project", str(project), "--dry-run"])
    assert result.exit_code == 0
    assert "Would run" in result.output or "Would patch" in result.output


def test_no_marimo_flag(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    with patch("taco.core._is_package_importable", return_value=True):
        result = runner.invoke(app, ["setup", "--project", str(project), "--no-marimo", "--dry-run"])
    assert result.exit_code == 0
    assert "skipped" in result.output


def test_custom_name_and_display_name(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    with patch("taco.core._is_package_importable", return_value=True):
        result = runner.invoke(app, [
            "setup", "--project", str(project),
            "--name", "custom",
            "--display-name", "My Custom Kernel",
            "--dry-run",
        ])
    assert result.exit_code == 0
    assert "custom" in result.output


def test_error_outside_project(tmp_path: Path) -> None:
    result = runner.invoke(app, ["setup", "--project", str(tmp_path)])
    assert result.exit_code != 0


# --- default command (no subcommand = setup) ---


def test_default_command_dry_run(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    with patch("taco.core._is_package_importable", return_value=True):
        result = runner.invoke(app, ["--project", str(project), "--dry-run"])
    assert result.exit_code == 0
    assert "Would run" in result.output or "Would patch" in result.output


def test_default_command_with_flags(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    with patch("taco.core._is_package_importable", return_value=True):
        result = runner.invoke(app, [
            "--project", str(project),
            "--name", "mykernel",
            "--no-marimo",
            "--dry-run",
        ])
    assert result.exit_code == 0
    assert "mykernel" in result.output
    assert "skipped" in result.output


def test_default_command_error_outside_project(tmp_path: Path) -> None:
    result = runner.invoke(app, ["--project", str(tmp_path)])
    assert result.exit_code != 0


# --- project type detection in CLI ---


def test_setup_detects_poetry(tmp_path: Path) -> None:
    project = _make_poetry_project(tmp_path)
    with patch("taco.core._is_package_importable", return_value=True):
        result = runner.invoke(app, ["setup", "--project", str(project), "--dry-run"])
    assert result.exit_code == 0
    assert "poetry" in result.output


def test_setup_detects_pip(tmp_path: Path) -> None:
    project = _make_pip_project(tmp_path)
    with patch("taco.core._is_package_importable", return_value=True):
        result = runner.invoke(app, ["setup", "--project", str(project), "--dry-run"])
    assert result.exit_code == 0
    assert "pip" in result.output


# --- list ---


def test_list_command() -> None:
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0


# --- info ---


def test_info_command(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _make_kernel(project)
    result = runner.invoke(app, ["info", "--project", str(project)])
    assert result.exit_code == 0
    assert "testproj" in result.output


def test_info_missing_kernel(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    result = runner.invoke(app, ["info", "--project", str(project)])
    assert result.exit_code == 0
    assert "not installed" in result.output


# --- remove ---


def test_remove_command(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _make_kernel(project)
    result = runner.invoke(app, ["remove", "--project", str(project)])
    assert result.exit_code == 0
    assert "Removed" in result.output


def test_remove_missing_kernel(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    result = runner.invoke(app, ["remove", "--project", str(project)])
    assert result.exit_code == 0
    assert "not found" in result.output


def test_remove_dry_run(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _make_kernel(project)
    result = runner.invoke(app, ["remove", "--project", str(project), "--dry-run"])
    assert result.exit_code == 0
    assert "Would remove" in result.output
    kernel_dir = project / ".venv" / "share" / "jupyter" / "kernels" / "testproj"
    assert kernel_dir.exists()


# --- clean ---


def test_clean_dry_run() -> None:
    result = runner.invoke(app, ["clean", "--dry-run"])
    assert result.exit_code == 0


def test_clean_help() -> None:
    result = runner.invoke(app, ["clean", "--help"])
    assert result.exit_code == 0
    assert "stale kernels" in result.output
