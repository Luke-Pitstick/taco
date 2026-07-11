"""CLI contract tests for safe, scriptable production behavior."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from taco import __version__
from taco.cli import app

runner = CliRunner()


def _make_project(tmp_path: Path, name: str = "testproj") -> Path:
    project = tmp_path / name
    project.mkdir()
    (project / "pyproject.toml").write_text(f"[project]\nname = {name!r}\nversion = '0.1.0'\n")
    return project


def _make_managed_kernel(data_dir: Path, project: Path, name: str = "testproj") -> Path:
    kernel_dir = data_dir / "kernels" / name
    kernel_dir.mkdir(parents=True)
    environment = project / ".venv"
    (kernel_dir / "kernel.json").write_text(
        json.dumps(
            {
                "argv": ["/usr/local/bin/uv", "run", "--project", str(project)],
                "display_name": f"Python ({name})",
                "language": "python",
                "metadata": {
                    "taco": {
                        "schema": 1,
                        "version": __version__,
                        "project_root": str(project),
                        "project_type": "uv",
                        "environment": str(environment),
                        "interpreter": str(environment / "bin" / "python"),
                    }
                },
            }
        )
    )
    return kernel_dir


def test_root_help_and_short_help() -> None:
    for arguments in (["--help"], ["-h"], []):
        result = runner.invoke(app, arguments)
        assert result.exit_code == 0
        assert "Create and maintain discoverable Jupyter kernels" in result.output
        assert "setup" in result.output


@pytest.mark.parametrize("command", ["setup", "list", "info", "remove", "clean"])
def test_short_help_for_every_command(command: str) -> None:
    result = runner.invoke(app, [command, "-h"])
    assert result.exit_code == 0
    assert f"Usage: taco {command}" in result.output


def test_version_is_eager() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output == f"taco {__version__}\n"


def test_setup_dry_run_has_no_writes_or_false_success(tmp_path: Path, monkeypatch) -> None:
    project = _make_project(tmp_path)
    data_dir = tmp_path / "jupyter"
    monkeypatch.setenv("JUPYTER_DATA_DIR", str(data_dir))
    before = sorted(path.relative_to(project) for path in project.rglob("*"))

    result = runner.invoke(
        app,
        ["setup", "--project", str(project), "--dry-run"],
    )

    after = sorted(path.relative_to(project) for path in project.rglob("*"))
    assert result.exit_code == 0
    assert "PLAN" in result.output
    assert "Dry run complete — no changes made." in result.output
    assert "Kernel registered" not in result.output
    assert before == after
    assert not data_dir.exists()


def test_setup_renders_brackets_in_display_name_literally(tmp_path: Path, monkeypatch) -> None:
    project = _make_project(tmp_path)
    monkeypatch.setenv("JUPYTER_DATA_DIR", str(tmp_path / "jupyter"))
    result = runner.invoke(
        app,
        [
            "setup",
            "--project",
            str(project),
            "--display-name",
            "Python [forecast]",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "Traceback" not in result.output


def test_legacy_no_marimo_flag_remains_a_noop(tmp_path: Path, monkeypatch) -> None:
    project = _make_project(tmp_path)
    monkeypatch.setenv("JUPYTER_DATA_DIR", str(tmp_path / "jupyter"))
    result = runner.invoke(
        app,
        ["setup", "--project", str(project), "--no-marimo", "--dry-run"],
    )
    assert result.exit_code == 0
    assert "--with marimo" not in result.output


def test_runtime_error_is_concise_without_traceback(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    with (project / "pyproject.toml").open("a") as file:
        file.write("\n[tool.uv]\n")
    with patch("taco.core.shutil.which", return_value=None):
        result = runner.invoke(app, ["setup", "--project", str(project)])
    assert result.exit_code == 1
    assert "uv is required" in result.output
    assert "Traceback" not in result.output


def test_list_json_is_one_document(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JUPYTER_DATA_DIR", str(tmp_path / "jupyter"))
    result = runner.invoke(app, ["list", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload == {"count": 0, "kernels": []}


def test_list_json_explains_static_health_without_runtime_probe(
    tmp_path: Path, monkeypatch
) -> None:
    project = _make_project(tmp_path)
    data_dir = tmp_path / "jupyter"
    monkeypatch.setenv("JUPYTER_DATA_DIR", str(data_dir))
    _make_managed_kernel(data_dir, project)

    with patch("taco.core._run") as run:
        result = runner.invoke(app, ["list", "--json"])

    assert result.exit_code == 0
    record = json.loads(result.stdout)["kernels"][0]
    assert [check["name"] for check in record["checks"]] == [
        "kernelspec",
        "launcher",
        "project",
        "environment",
        "command",
    ]
    assert {check["name"] for check in record["checks"] if not check["ok"]} >= {
        "environment",
        "command",
    }
    run.assert_not_called()


def test_list_human_output_names_failed_checks_and_next_step(tmp_path: Path, monkeypatch) -> None:
    project = _make_project(tmp_path, name="forecast-project")
    data_dir = tmp_path / "jupyter"
    monkeypatch.setenv("JUPYTER_DATA_DIR", str(data_dir))
    _make_managed_kernel(data_dir, project, name="forecasting-gpu")

    result = runner.invoke(app, ["list"])

    assert result.exit_code == 0
    assert "failed:" in result.output
    assert "environment" in result.output
    assert "command" in result.output
    assert f"taco info --project {project} --name forecasting-gpu" in result.output


def test_info_missing_kernel_is_exit_one(tmp_path: Path, monkeypatch) -> None:
    project = _make_project(tmp_path)
    monkeypatch.setenv("JUPYTER_DATA_DIR", str(tmp_path / "jupyter"))
    result = runner.invoke(app, ["info", "--project", str(project)])
    assert result.exit_code == 1
    assert "not installed" in result.output


def test_info_healthy_kernel_is_exit_zero(tmp_path: Path, monkeypatch) -> None:
    project = _make_project(tmp_path)
    data_dir = tmp_path / "jupyter"
    monkeypatch.setenv("JUPYTER_DATA_DIR", str(data_dir))
    _make_managed_kernel(data_dir, project)
    health = {
        "healthy": True,
        "checks": [{"name": "runtime", "ok": True, "detail": "ready"}],
    }
    with patch("taco.core.kernel_health", return_value=health):
        result = runner.invoke(app, ["info", "--project", str(project)])
    assert result.exit_code == 0
    assert "runtime: ready" in result.output


def test_info_unhealthy_kernel_is_exit_one(tmp_path: Path, monkeypatch) -> None:
    project = _make_project(tmp_path)
    data_dir = tmp_path / "jupyter"
    monkeypatch.setenv("JUPYTER_DATA_DIR", str(data_dir))
    _make_managed_kernel(data_dir, project)
    health = {
        "healthy": False,
        "checks": [{"name": "runtime", "ok": False, "detail": "ipykernel missing"}],
    }
    with patch("taco.core.kernel_health", return_value=health):
        result = runner.invoke(app, ["info", "--project", str(project)])
    assert result.exit_code == 1
    assert "FAIL" in result.output


def test_remove_exact_managed_kernel(tmp_path: Path, monkeypatch) -> None:
    project = _make_project(tmp_path)
    data_dir = tmp_path / "jupyter"
    monkeypatch.setenv("JUPYTER_DATA_DIR", str(data_dir))
    kernel_dir = _make_managed_kernel(data_dir, project)

    result = runner.invoke(app, ["remove", "--project", str(project)])

    assert result.exit_code == 0
    assert "Removed kernel" in result.output
    assert not kernel_dir.exists()


def test_remove_missing_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    project = _make_project(tmp_path)
    monkeypatch.setenv("JUPYTER_DATA_DIR", str(tmp_path / "jupyter"))
    result = runner.invoke(app, ["remove", "--project", str(project)])
    assert result.exit_code == 0
    assert "not installed" in result.output


def test_remove_dry_run_previews_and_preserves_kernel(tmp_path: Path, monkeypatch) -> None:
    project = _make_project(tmp_path)
    data_dir = tmp_path / "jupyter"
    monkeypatch.setenv("JUPYTER_DATA_DIR", str(data_dir))
    kernel_dir = _make_managed_kernel(data_dir, project)

    result = runner.invoke(
        app,
        ["remove", "--project", str(project), "--dry-run"],
    )

    assert result.exit_code == 0
    assert "PLAN  Remove" in result.output
    assert "no changes made" in result.output
    assert kernel_dir.is_dir()


def test_clean_noop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JUPYTER_DATA_DIR", str(tmp_path / "jupyter"))
    result = runner.invoke(app, ["clean"])
    assert result.exit_code == 0
    assert "No stale Taco kernels" in result.output
