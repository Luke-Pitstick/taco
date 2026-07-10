"""End-to-end tests using real uv projects and a real Jupyter kernel."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from jupyter_client import KernelManager
from jupyter_client.kernelspec import KernelSpecManager


def _run(command: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=240,
    )


def _init_uv_project(path: Path, name: str, env: dict[str, str]) -> None:
    result = _run(
        ["uv", "init", "--bare", "--name", name, str(path)],
        cwd=path.parent,
        env=env,
    )
    assert result.returncode == 0, result.stderr


def _run_taco(
    project: Path, env: dict[str, str], *arguments: str
) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            sys.executable,
            "-m",
            "taco",
            "setup",
            "--project",
            str(project),
            "--name",
            project.name,
            *arguments,
        ],
        cwd=project,
        env=env,
    )


def _execute_kernel(kernel_name: str, project: Path) -> str:
    manager = KernelManager(kernel_name=kernel_name)
    client = None
    try:
        manager.start_kernel(cwd=str(project))
        client = manager.client()
        client.start_channels()
        client.wait_for_ready(timeout=90)
        message_id = client.execute("answer = 6 * 7; answer")
        deadline = time.monotonic() + 90
        value = ""
        while time.monotonic() < deadline:
            message = client.get_iopub_msg(timeout=10)
            if message.get("parent_header", {}).get("msg_id") != message_id:
                continue
            if message["msg_type"] == "execute_result":
                value = message["content"]["data"]["text/plain"]
            if (
                message["msg_type"] == "status"
                and message["content"].get("execution_state") == "idle"
            ):
                return value
        raise AssertionError("kernel did not return to idle")
    finally:
        if client is not None:
            client.stop_channels()
        if manager.has_kernel:
            manager.shutdown_kernel(now=True)


@pytest.fixture()
def isolated_env(tmp_path: Path, monkeypatch) -> tuple[Path, dict[str, str]]:
    data_dir = tmp_path / "jupyter"
    monkeypatch.setenv("JUPYTER_DATA_DIR", str(data_dir))
    env = {**os.environ, "JUPYTER_DATA_DIR": str(data_dir)}
    return data_dir, env


@pytest.mark.integration
def test_fresh_project_is_discoverable_and_launches(
    tmp_path: Path,
    isolated_env: tuple[Path, dict[str, str]],
) -> None:
    data_dir, env = isolated_env
    project = tmp_path / "fresh"
    _init_uv_project(project, "fresh", env)
    with (project / "pyproject.toml").open("a") as file:
        file.write("\n[tool.uv]\ndefault-groups = []\n")

    result = _run_taco(project, env)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "Kernel runtime verified" in result.stdout

    kernel_dir = data_dir / "kernels" / "fresh"
    data = json.loads((kernel_dir / "kernel.json").read_text())
    assert data["metadata"]["taco"]["project_root"] == str(project)
    assert data["argv"][0].endswith("uv")
    assert "--with" in data["argv"]
    assert "ipykernel" in data["argv"]

    specs = KernelSpecManager().find_kernel_specs()
    assert specs["fresh"] == str(kernel_dir)

    sync = _run(["uv", "sync"], cwd=project, env=env)
    assert sync.returncode == 0, sync.stderr
    assert _execute_kernel("fresh", project) == "42"


@pytest.mark.integration
def test_workspace_member_uses_workspace_environment(
    tmp_path: Path,
    isolated_env: tuple[Path, dict[str, str]],
) -> None:
    data_dir, env = isolated_env
    workspace = tmp_path / "workspace"
    member = workspace / "member"
    _init_uv_project(workspace, "workspace", env)
    _init_uv_project(member, "member", env)

    result = _run_taco(member, env)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"

    data = json.loads((data_dir / "kernels" / "member" / "kernel.json").read_text())
    metadata = data["metadata"]["taco"]
    assert Path(metadata["environment"]) == workspace / ".venv"
    assert data["argv"][data["argv"].index("--project") + 1] == str(member)


@pytest.mark.integration
def test_custom_project_environment_is_captured_for_future_launches(
    tmp_path: Path,
    isolated_env: tuple[Path, dict[str, str]],
    monkeypatch,
) -> None:
    data_dir, env = isolated_env
    project = tmp_path / "custom"
    _init_uv_project(project, "custom", env)
    custom_environment = project / ".custom-uv"
    env["UV_PROJECT_ENVIRONMENT"] = str(custom_environment)
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(custom_environment))

    result = _run_taco(project, env)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"

    kernel_json = data_dir / "kernels" / "custom" / "kernel.json"
    data = json.loads(kernel_json.read_text())
    assert data["metadata"]["taco"]["environment"] == str(custom_environment)
    assert data["env"]["UV_PROJECT_ENVIRONMENT"] == str(custom_environment)

    monkeypatch.delenv("UV_PROJECT_ENVIRONMENT")
    assert _execute_kernel("custom", project) == "42"


@pytest.mark.integration
def test_same_name_collision_is_refused_without_overwrite(
    tmp_path: Path,
    isolated_env: tuple[Path, dict[str, str]],
) -> None:
    data_dir, env = isolated_env
    first = tmp_path / "one" / "notebooks"
    second = tmp_path / "two" / "notebooks"
    first.parent.mkdir()
    second.parent.mkdir()
    _init_uv_project(first, "first", env)
    _init_uv_project(second, "second", env)

    first_result = _run_taco(first, env)
    assert first_result.returncode == 0, first_result.stderr
    original = (data_dir / "kernels" / "notebooks" / "kernel.json").read_text()
    second_before = sorted(path.relative_to(second) for path in second.rglob("*"))

    second_result = _run_taco(second, env)
    assert second_result.returncode == 1
    assert "already used" in second_result.stderr
    assert "Choose a unique --name" in second_result.stderr
    assert (data_dir / "kernels" / "notebooks" / "kernel.json").read_text() == original
    assert sorted(path.relative_to(second) for path in second.rglob("*")) == second_before
