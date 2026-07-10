"""Unit coverage for uv environment and kernelspec lifecycle behavior."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from taco import __version__
from taco.core import (
    ProjectType,
    TacoConfig,
    _get_kernelspec_dir,
    _safe_kernel_dir,
    compute_missing_deps,
    default_display_name,
    detect_project_type,
    discover_kernels,
    find_project_root,
    find_stale_kernels,
    find_uv_workspace_root,
    get_all_kernel_dirs,
    get_user_kernel_dir,
    install_kernel,
    is_taco_managed,
    kernel_health,
    patch_kernelspec,
    predict_uv_environment,
    remove_project_kernel,
    resolve_environment,
    resolve_uv_environment,
    run_clean,
    sanitize_kernel_name,
    validate_kernel_name,
    venv_interpreter,
)


def _pyproject(path: Path, name: str = "example", extra: str = "") -> None:
    path.write_text(f"[project]\nname = {name!r}\nversion = '0.1.0'\n{extra}")


def _config(project: Path, name: str = "example", **kwargs) -> TacoConfig:
    return TacoConfig(
        project_root=project,
        kernel_name=name,
        display_name=f"Python ({name})",
        **kwargs,
    )


def _managed_spec(
    project: Path, name: str = "example", launcher: str = "/usr/local/bin/uv"
) -> dict:
    environment = project / ".venv"
    return {
        "argv": [
            launcher,
            "run",
            "--project",
            str(project),
            "--with",
            "ipykernel",
            "python",
            "-m",
            "ipykernel_launcher",
            "-f",
            "{connection_file}",
        ],
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


def test_find_project_root_from_subdirectory(tmp_path: Path) -> None:
    _pyproject(tmp_path / "pyproject.toml")
    subdirectory = tmp_path / "src" / "package"
    subdirectory.mkdir(parents=True)
    assert find_project_root(subdirectory) == tmp_path


def test_find_project_root_does_not_treat_requirements_as_uv(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("requests\n")
    assert find_project_root(tmp_path) == tmp_path


def test_find_project_root_rejects_missing_explicit_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        find_project_root(tmp_path / "missing", explicit=True)


def test_find_project_root_does_not_climb_from_explicit_directory(tmp_path: Path) -> None:
    _pyproject(tmp_path / "pyproject.toml")
    child = tmp_path / "existing-but-not-a-project"
    child.mkdir()
    assert find_project_root(child, explicit=True) == child


def test_detect_project_type_detects_uv_configuration(tmp_path: Path) -> None:
    _pyproject(tmp_path / "pyproject.toml", extra="\n[tool.uv]\n")
    assert detect_project_type(tmp_path) is ProjectType.UV


def test_detect_project_type_detects_poetry_configuration(tmp_path: Path) -> None:
    _pyproject(tmp_path / "pyproject.toml", extra="\n[tool.poetry]\n")
    assert detect_project_type(tmp_path) is ProjectType.POETRY


def test_detect_project_type_uses_active_conda_environment(tmp_path: Path, monkeypatch) -> None:
    environment = tmp_path / "conda"
    interpreter = environment / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text("")
    monkeypatch.setenv("CONDA_PREFIX", str(environment))
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)

    assert detect_project_type(tmp_path) is ProjectType.CONDA


def test_detect_project_type_uses_local_virtual_environment(tmp_path: Path, monkeypatch) -> None:
    interpreter = tmp_path / ".venv" / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text("")
    monkeypatch.delenv("CONDA_PREFIX", raising=False)
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)

    assert detect_project_type(tmp_path) is ProjectType.VENV


def test_detect_project_type_falls_back_to_python(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CONDA_PREFIX", raising=False)
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    assert detect_project_type(tmp_path) is ProjectType.PYTHON


def test_uv_environment_variable_does_not_turn_plain_directory_into_uv(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(tmp_path / ".custom"))
    monkeypatch.delenv("CONDA_PREFIX", raising=False)
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    assert detect_project_type(tmp_path) is ProjectType.PYTHON


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("my-project", "my-project"),
        ("my project!", "my-project"),
        ("a---b", "a-b"),
        ("", "unnamed-kernel"),
        ("..", "unnamed-kernel"),
        ("my_project.v2", "my_project.v2"),
    ],
)
def test_sanitize_kernel_name(value: str, expected: str) -> None:
    assert sanitize_kernel_name(value) == expected


@pytest.mark.parametrize(
    "value",
    ["", ".", "..", "bad name", "../escape", "a/b", "[/red]", "café"],
)
def test_validate_kernel_name_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(ValueError, match="Invalid kernel name"):
        validate_kernel_name(value)


def test_default_display_name() -> None:
    assert default_display_name("forecasting") == "Python (forecasting)"


def test_workspace_root_and_relative_custom_environment(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "workspace"
    member = root / "packages" / "member"
    member.mkdir(parents=True)
    _pyproject(root / "pyproject.toml", extra="\n[tool.uv.workspace]\nmembers = ['packages/*']\n")
    _pyproject(member / "pyproject.toml", name="member")
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", ".custom")

    assert find_uv_workspace_root(member) == root
    assert predict_uv_environment(member) == root / ".custom"


def test_venv_interpreter_uses_windows_scripts_when_present(tmp_path: Path) -> None:
    interpreter = tmp_path / "Scripts" / "python.exe"
    interpreter.parent.mkdir()
    interpreter.write_text("")
    assert venv_interpreter(tmp_path) == interpreter


def test_venv_interpreter_supports_conda_windows_layout(tmp_path: Path) -> None:
    interpreter = tmp_path / "python.exe"
    interpreter.write_text("")
    assert venv_interpreter(tmp_path) == interpreter


def test_resolve_uv_environment_uses_uv_reported_paths(tmp_path: Path) -> None:
    _pyproject(tmp_path / "pyproject.toml")
    config = _config(tmp_path)
    payload = json.dumps(
        {
            "interpreter": str(tmp_path / ".custom" / "bin" / "python"),
            "environment": str(tmp_path / ".custom"),
        }
    )
    completed = subprocess.CompletedProcess([], 0, stdout=f"{payload}\n", stderr="")

    with (
        patch("taco.core._executable", return_value=Path("/usr/local/bin/uv")),
        patch("taco.core._run", return_value=completed),
    ):
        resolve_uv_environment(config)

    assert config.venv_path == tmp_path / ".custom"
    assert config.interpreter == tmp_path / ".custom" / "bin" / "python"


def test_resolve_poetry_environment_uses_poetry_reported_paths(tmp_path: Path) -> None:
    _pyproject(tmp_path / "pyproject.toml", extra="\n[tool.poetry]\n")
    config = _config(tmp_path, project_type=ProjectType.POETRY)
    payload = json.dumps(
        {
            "interpreter": str(tmp_path / ".poetry" / "bin" / "python"),
            "environment": str(tmp_path / ".poetry"),
        }
    )
    completed = subprocess.CompletedProcess([], 0, stdout=f"{payload}\n", stderr="")

    with (
        patch("taco.core._executable", return_value=Path("/usr/local/bin/poetry")),
        patch("taco.core._run", return_value=completed) as run,
    ):
        resolve_environment(config)

    assert run.call_args.args[0][:3] == ["/usr/local/bin/poetry", "run", "python"]
    assert config.venv_path == tmp_path / ".poetry"
    assert config.interpreter == tmp_path / ".poetry" / "bin" / "python"


def test_resolve_base_python_uses_path_interpreter(tmp_path: Path) -> None:
    config = _config(tmp_path, project_type=ProjectType.PYTHON)
    payload = json.dumps({"interpreter": "/usr/local/bin/python3", "environment": "/usr/local"})
    completed = subprocess.CompletedProcess([], 0, stdout=f"{payload}\n", stderr="")

    with (
        patch("taco.core.shutil.which", side_effect=lambda name: "/usr/local/bin/python3"),
        patch("taco.core._run", return_value=completed) as run,
    ):
        resolve_environment(config)

    assert run.call_args.args[0][0] == "/usr/local/bin/python3"
    assert config.interpreter == Path("/usr/local/bin/python3")
    assert config.venv_path == Path("/usr/local")


def test_resolve_environment_preserves_virtualenv_interpreter_symlink(tmp_path: Path) -> None:
    environment = tmp_path / ".venv"
    interpreter = environment / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.symlink_to(sys.executable)
    config = _config(tmp_path, project_type=ProjectType.VENV)
    payload = json.dumps({"interpreter": str(interpreter), "environment": str(environment)})
    completed = subprocess.CompletedProcess([], 0, stdout=f"{payload}\n", stderr="")

    with patch("taco.core._run", return_value=completed):
        resolve_environment(config)

    assert config.interpreter == interpreter
    assert config.interpreter != interpreter.resolve()


def test_health_check_executes_virtualenv_symlink_not_base_python(tmp_path: Path) -> None:
    project = tmp_path / "project"
    environment = project / ".venv"
    interpreter = environment / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.symlink_to(sys.executable)
    record = {
        "argv": [
            str(interpreter),
            "-m",
            "ipykernel_launcher",
            "-f",
            "{connection_file}",
        ],
        "launcher": str(interpreter),
        "interpreter": str(interpreter),
        "project_type": "venv",
        "project": str(project),
        "environment": str(environment),
        "managed_by_taco": True,
        "valid": True,
        "error": "",
    }
    completed = subprocess.CompletedProcess([], 0, stdout="", stderr="")

    with patch("taco.core._run", return_value=completed) as run:
        health = kernel_health(record, trusted_interpreter=interpreter)

    assert run.call_args.args[0][0] == str(interpreter)
    assert health["healthy"]

    other_interpreter = tmp_path / "other-venv" / "bin" / "python"
    other_interpreter.parent.mkdir(parents=True)
    other_interpreter.symlink_to(sys.executable)
    with patch("taco.core._run") as run:
        mismatched_health = kernel_health(
            record,
            trusted_interpreter=other_interpreter,
        )
    run.assert_not_called()
    assert not mismatched_health["healthy"]


def test_compute_missing_deps() -> None:
    with patch("taco.core._is_package_importable", side_effect=[False, True]):
        assert compute_missing_deps(Path("python"), include_marimo=True) == ["ipykernel"]


def test_jupyter_paths_use_jupyter_core(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("taco.core.jupyter_data_dir", lambda: str(tmp_path / "data"))
    monkeypatch.setattr(
        "taco.core.jupyter_path",
        lambda kind: [str(tmp_path / "custom"), str(tmp_path / "system")],
    )
    assert get_user_kernel_dir() == tmp_path / "data" / "kernels"
    assert get_all_kernel_dirs() == [tmp_path / "custom", tmp_path / "system"]


def test_safe_kernel_dir_refuses_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        _safe_kernel_dir(tmp_path, "../../victim")


def test_patch_kernelspec_writes_uv_launcher_and_ownership(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    kernel_dir = tmp_path / "kernels" / "example"
    kernel_dir.mkdir(parents=True)
    (kernel_dir / "kernel.json").write_text(
        json.dumps(
            {
                "argv": ["temporary-python"],
                "display_name": "Python (example)",
                "language": "python",
                "env": {"FOO": "bar", "VIRTUAL_ENV": "/old"},
            }
        )
    )
    config = _config(project)
    config.uv_executable = Path("/usr/local/bin/uv")
    config.venv_path = project / ".venv"
    config.interpreter = project / ".venv" / "bin" / "python"

    patch_kernelspec(kernel_dir, config)
    data = json.loads((kernel_dir / "kernel.json").read_text())

    assert data["argv"][:4] == [
        "/usr/local/bin/uv",
        "run",
        "--project",
        str(project),
    ]
    assert data["env"]["FOO"] == "bar"
    assert "VIRTUAL_ENV" not in data["env"]
    assert data["env"]["UV_PROJECT_ENVIRONMENT"] == str(project / ".venv")
    assert data["metadata"]["taco"]["project_root"] == str(project)
    assert is_taco_managed(data)


def test_patch_kernelspec_writes_direct_interpreter_launcher(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    environment = tmp_path / "conda" / "envs" / "science"
    interpreter = environment / "bin" / "python"
    kernel_dir = tmp_path / "kernels" / "science"
    kernel_dir.mkdir(parents=True)
    (kernel_dir / "kernel.json").write_text(
        json.dumps(
            {
                "argv": ["temporary-python"],
                "display_name": "Python (science)",
                "language": "python",
                "env": {"VIRTUAL_ENV": "/old", "UV_PROJECT_ENVIRONMENT": "/old-uv"},
            }
        )
    )
    config = _config(project, name="science", project_type=ProjectType.CONDA)
    config.venv_path = environment
    config.interpreter = interpreter

    patch_kernelspec(kernel_dir, config)
    data = json.loads((kernel_dir / "kernel.json").read_text())

    assert data["argv"] == [
        str(interpreter),
        "-m",
        "ipykernel_launcher",
        "-f",
        "{connection_file}",
    ]
    assert "VIRTUAL_ENV" not in data["env"]
    assert "UV_PROJECT_ENVIRONMENT" not in data["env"]
    assert data["metadata"]["taco"]["project_type"] == "conda"
    assert is_taco_managed(data)


def test_install_kernel_uses_user_registration(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _pyproject(project / "pyproject.toml")
    user_dir = tmp_path / "jupyter" / "kernels"
    monkeypatch.setattr("taco.core.get_user_kernel_dir", lambda: user_dir)
    monkeypatch.setattr("taco.core.get_all_kernel_dirs", lambda: [user_dir])
    config = _config(project)
    config.uv_executable = Path("/usr/local/bin/uv")
    config.venv_path = project / ".venv"
    config.interpreter = project / ".venv" / "bin" / "python"
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs):
        commands.append(command)
        kernel_dir = user_dir / "example"
        kernel_dir.mkdir(parents=True)
        (kernel_dir / "kernel.json").write_text(
            json.dumps({"argv": ["python"], "display_name": "Example"})
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    with patch("taco.core._run", side_effect=fake_run):
        result = install_kernel(config)

    assert result == user_dir / "example"
    assert "--user" in commands[0]
    assert "--prefix" not in commands[0]


def test_install_kernel_prepares_ipykernel_in_direct_environment(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    environment = tmp_path / "venv"
    interpreter = environment / "bin" / "python"
    user_dir = tmp_path / "jupyter" / "kernels"
    monkeypatch.setattr("taco.core.get_user_kernel_dir", lambda: user_dir)
    monkeypatch.setattr("taco.core.get_all_kernel_dirs", lambda: [user_dir])
    config = _config(project, project_type=ProjectType.VENV)
    config.venv_path = environment
    config.interpreter = interpreter
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs):
        commands.append(command)
        if "install" in command and "--name" in command:
            kernel_dir = user_dir / "example"
            kernel_dir.mkdir(parents=True)
            (kernel_dir / "kernel.json").write_text(
                json.dumps({"argv": [str(interpreter)], "display_name": "Example"})
            )
        return subprocess.CompletedProcess(command, 0, "", "")

    with (
        patch("taco.core._is_package_importable", return_value=False),
        patch("taco.core._run", side_effect=fake_run),
    ):
        result = install_kernel(config)

    assert result == user_dir / "example"
    assert commands[0] == [str(interpreter), "-m", "pip", "install", "ipykernel"]
    assert commands[1][:4] == [str(interpreter), "-m", "ipykernel", "install"]


def test_discovery_surfaces_invalid_and_null_env_specs(tmp_path: Path, monkeypatch) -> None:
    base = tmp_path / "kernels"
    invalid = base / "invalid"
    null_env = base / "null-env"
    invalid.mkdir(parents=True)
    null_env.mkdir()
    (invalid / "kernel.json").write_text("{")
    (null_env / "kernel.json").write_text(
        json.dumps({"argv": ["python3"], "display_name": "Python", "env": None})
    )
    monkeypatch.setattr("taco.core.get_all_kernel_dirs", lambda: [base])

    records = {record["name"]: record for record in discover_kernels()}

    assert not records["invalid"]["valid"]
    assert records["invalid"]["error"]
    assert records["null-env"]["valid"]
    assert records["null-env"]["virtual_env"] == ""


def test_incomplete_taco_metadata_does_not_grant_ownership() -> None:
    assert not is_taco_managed({"metadata": {"taco": {}}})
    assert not is_taco_managed(
        {
            "metadata": {
                "taco": {
                    "schema": 1,
                    "project_type": "uv",
                    "project_root": "relative/path",
                }
            }
        }
    )


def test_health_check_never_executes_stored_launcher(tmp_path: Path) -> None:
    project = tmp_path / "project"
    environment = project / ".venv"
    environment.mkdir(parents=True)
    data = _managed_spec(project, launcher="/tmp/untrusted-launcher")
    record = {
        "name": "example",
        "path": str(tmp_path / "kernels" / "example"),
        "argv": data["argv"],
        "launcher": data["argv"][0],
        "project": str(project),
        "environment": str(environment),
        "interpreter": data["metadata"]["taco"]["interpreter"],
        "project_type": "uv",
        "managed_by_taco": True,
        "valid": True,
        "error": "",
    }
    completed = subprocess.CompletedProcess([], 0, stdout="", stderr="")

    with (
        patch("taco.core.shutil.which", return_value="/trusted/uv"),
        patch("taco.core._run", return_value=completed) as run,
    ):
        kernel_health(record)

    assert run.call_args.args[0][0] == str(Path("/trusted/uv").resolve())


def test_health_check_does_not_execute_invalid_command_shape(tmp_path: Path) -> None:
    project = tmp_path / "project"
    environment = project / ".venv"
    environment.mkdir(parents=True)
    record = {
        "name": "example",
        "path": str(tmp_path / "kernels" / "example"),
        "argv": ["/tmp/untrusted", "--do-something-else"],
        "launcher": "/tmp/untrusted",
        "project": str(project),
        "environment": str(environment),
        "managed_by_taco": True,
        "valid": True,
        "error": "",
    }

    with patch("taco.core._run") as run:
        health = kernel_health(record)

    run.assert_not_called()
    assert not health["healthy"]


def test_health_check_only_executes_a_resolved_direct_interpreter(tmp_path: Path) -> None:
    project = tmp_path / "project"
    environment = project / ".venv"
    interpreter = environment / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text("")
    record = {
        "name": "example",
        "path": str(tmp_path / "kernels" / "example"),
        "argv": [
            str(interpreter),
            "-m",
            "ipykernel_launcher",
            "-f",
            "{connection_file}",
        ],
        "launcher": str(interpreter),
        "interpreter": str(interpreter),
        "project_type": "venv",
        "project": str(project),
        "environment": str(environment),
        "managed_by_taco": True,
        "valid": True,
        "error": "",
    }

    with patch("taco.core._run") as run:
        untrusted_health = kernel_health(record)
    run.assert_not_called()
    assert not untrusted_health["healthy"]

    completed = subprocess.CompletedProcess([], 0, stdout="", stderr="")
    with patch("taco.core._run", return_value=completed) as run:
        trusted_health = kernel_health(record, trusted_interpreter=interpreter)
    assert run.call_args.args[0][0] == str(interpreter)
    assert trusted_health["healthy"]


def test_remove_project_kernel_preserves_foreign_collision(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    base = tmp_path / "kernels"
    foreign = base / "example"
    foreign.mkdir(parents=True)
    (foreign / "kernel.json").write_text(
        json.dumps({"argv": ["python3"], "display_name": "Foreign"})
    )
    monkeypatch.setattr("taco.core.get_all_kernel_dirs", lambda: [base])
    monkeypatch.setattr("taco.core.get_user_kernel_dir", lambda: base)

    assert not remove_project_kernel(_config(project))
    assert foreign.is_dir()


def test_remove_project_kernel_deletes_exact_managed_spec(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    base = tmp_path / "kernels"
    managed = base / "example"
    managed.mkdir(parents=True)
    (managed / "kernel.json").write_text(json.dumps(_managed_spec(project)))
    monkeypatch.setattr("taco.core.get_all_kernel_dirs", lambda: [base])
    monkeypatch.setattr("taco.core.get_user_kernel_dir", lambda: base)

    assert remove_project_kernel(_config(project))
    assert not managed.exists()


def test_stale_discovery_ignores_foreign_path_launcher(tmp_path: Path, monkeypatch) -> None:
    base = tmp_path / "kernels"
    foreign = base / "python"
    foreign.mkdir(parents=True)
    (foreign / "kernel.json").write_text(
        json.dumps({"argv": ["python3"], "display_name": "Python"})
    )
    monkeypatch.setattr("taco.core.get_all_kernel_dirs", lambda: [base])
    monkeypatch.setattr("taco.core.shutil.which", lambda name: "/usr/bin/python3")

    assert find_stale_kernels() == []


def test_clean_never_deletes_managed_metadata_outside_user_dir(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "missing-project"
    external_base = tmp_path / "external" / "kernels"
    user_base = tmp_path / "user" / "kernels"
    external = external_base / "example"
    external.mkdir(parents=True)
    (external / "kernel.json").write_text(json.dumps(_managed_spec(project)))
    monkeypatch.setattr("taco.core.get_all_kernel_dirs", lambda: [external_base])
    monkeypatch.setattr("taco.core.get_user_kernel_dir", lambda: user_base)

    assert find_stale_kernels() == []
    assert run_clean() == 0
    assert external.is_dir()


def test_clean_revalidates_snapshot_before_delete(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    user_base = tmp_path / "user" / "kernels"
    kernel = user_base / "example"
    kernel.mkdir(parents=True)
    (kernel / "kernel.json").write_text(json.dumps(_managed_spec(project, launcher=sys.executable)))
    monkeypatch.setattr("taco.core.get_all_kernel_dirs", lambda: [user_base])
    monkeypatch.setattr("taco.core.get_user_kernel_dir", lambda: user_base)

    stale_snapshot = find_stale_kernels()
    assert len(stale_snapshot) == 1
    project.mkdir()
    (project / ".venv").mkdir()

    assert run_clean(kernels=stale_snapshot) == 0
    assert kernel.is_dir()


def test_user_kernelspec_path_is_not_project_local(tmp_path: Path, monkeypatch) -> None:
    user_dir = tmp_path / "jupyter" / "kernels"
    monkeypatch.setattr("taco.core.get_user_kernel_dir", lambda: user_dir)
    assert _get_kernelspec_dir(_config(tmp_path)) == user_dir / "example"
