"""Regression tests for safety and production CLI behavior."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from taco.cli import app
from taco.core import get_all_kernel_dirs, run_clean

runner = CliRunner()


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text("[project]\nname = 'project'\n\n[tool.uv]\n")
    return project


def test_no_args_shows_help_without_running_setup() -> None:
    with patch("taco.cli.run_setup") as setup:
        result = runner.invoke(app, [])

    assert result.exit_code == 0
    assert "Usage:" in result.output
    setup.assert_not_called()


def test_root_setup_option_before_subcommand_is_rejected() -> None:
    with patch("taco.cli.run_clean") as clean:
        result = runner.invoke(app, ["--dry-run", "clean"])

    assert result.exit_code == 2
    assert "No such option" in result.output
    clean.assert_not_called()


def test_missing_explicit_project_does_not_fall_back_to_parent() -> None:
    missing = Path.cwd() / "definitely-does-not-exist"
    with patch("taco.cli.run_setup") as setup:
        result = runner.invoke(app, ["setup", "--project", str(missing)])

    assert result.exit_code == 2
    assert "does not exist" in result.output
    setup.assert_not_called()


def test_invalid_kernel_name_is_a_usage_error_without_traceback(tmp_path: Path) -> None:
    project = _project(tmp_path)
    result = runner.invoke(
        app,
        ["setup", "--project", str(project), "--name", "[/cyan]oops"],
    )

    assert result.exit_code == 2
    assert "Invalid kernel name" in result.output
    assert "Traceback" not in result.output


def test_remove_rejects_path_traversal(tmp_path: Path) -> None:
    project = _project(tmp_path)
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "keep.txt").write_text("keep")

    result = runner.invoke(
        app,
        [
            "remove",
            "--project",
            str(project),
            "--name",
            "../../../../../victim",
        ],
    )

    assert result.exit_code == 2
    assert victim.is_dir()
    assert (victim / "keep.txt").read_text() == "keep"


def test_jupyter_data_dir_is_honored_on_macos(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_dir = tmp_path / "jupyter"
    monkeypatch.setenv("JUPYTER_DATA_DIR", str(data_dir))

    assert data_dir / "kernels" in get_all_kernel_dirs()


def test_clean_preserves_path_resolved_launcher(tmp_path: Path) -> None:
    kernel_dir = tmp_path / "kernels" / "python"
    kernel_dir.mkdir(parents=True)
    (kernel_dir / "kernel.json").write_text(json.dumps({"argv": ["python3"]}))
    kernel = {
        "name": "python",
        "path": str(kernel_dir),
        "display_name": "Python",
        "interpreter": "python3",
        "virtual_env": "",
        "project": "",
        "launcher": "python3",
        "managed_by_taco": False,
        "valid": True,
    }

    with (
        patch("taco.core.discover_kernels", return_value=[kernel]),
        patch("taco.core.shutil.which", return_value="/usr/bin/python3"),
    ):
        run_clean()

    assert kernel_dir.is_dir()
