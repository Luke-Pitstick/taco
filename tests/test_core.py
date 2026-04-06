"""Unit tests for taco.core — project detection, name sanitization, dep diffing, patching."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from taco.core import (
    ProjectType,
    TacoConfig,
    _get_kernelspec_dir,
    compute_missing_deps,
    default_display_name,
    detect_project_type,
    find_project_root,
    patch_kernelspec,
    sanitize_kernel_name,
)


# --- find_project_root ---


def test_find_project_root_in_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    assert find_project_root(tmp_path) == tmp_path


def test_find_project_root_from_subdirectory(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    sub = tmp_path / "src" / "pkg"
    sub.mkdir(parents=True)
    assert find_project_root(sub) == tmp_path


def test_find_project_root_from_requirements_txt(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("requests\n")
    assert find_project_root(tmp_path) == tmp_path


def test_find_project_root_from_setup_py(tmp_path: Path) -> None:
    (tmp_path / "setup.py").write_text("from setuptools import setup\nsetup()\n")
    assert find_project_root(tmp_path) == tmp_path


def test_find_project_root_fails_outside_project(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        find_project_root(tmp_path)


# --- detect_project_type ---


def test_detect_uv_project_by_lock(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    (tmp_path / "uv.lock").write_text("")
    assert detect_project_type(tmp_path) == ProjectType.UV


def test_detect_uv_project_by_tool_section(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n\n[tool.uv]\n")
    assert detect_project_type(tmp_path) == ProjectType.UV


def test_detect_poetry_project_by_lock(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    (tmp_path / "poetry.lock").write_text("")
    assert detect_project_type(tmp_path) == ProjectType.POETRY


def test_detect_poetry_project_by_tool_section(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.poetry]\nname = 'x'\n")
    assert detect_project_type(tmp_path) == ProjectType.POETRY


def test_detect_pip_project_by_requirements(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("requests\n")
    assert detect_project_type(tmp_path) == ProjectType.PIP


# --- sanitize_kernel_name ---


def test_sanitize_simple_name() -> None:
    assert sanitize_kernel_name("my-project") == "my-project"


def test_sanitize_spaces_and_special_chars() -> None:
    assert sanitize_kernel_name("my project!@#") == "my-project"


def test_sanitize_collapses_dashes() -> None:
    assert sanitize_kernel_name("a---b") == "a-b"


def test_sanitize_empty_string() -> None:
    assert sanitize_kernel_name("") == "unnamed-kernel"


def test_sanitize_preserves_dots_and_underscores() -> None:
    assert sanitize_kernel_name("my_project.v2") == "my_project.v2"


# --- default_display_name ---


def test_default_display_name() -> None:
    assert default_display_name("foo") == "Python (foo)"


# --- compute_missing_deps ---


def test_compute_missing_deps_all_missing() -> None:
    with patch("taco.core._is_package_importable", return_value=False):
        result = compute_missing_deps(Path("/fake/python"), include_marimo=True)
    assert result == ["ipykernel", "marimo"]


def test_compute_missing_deps_none_missing() -> None:
    with patch("taco.core._is_package_importable", return_value=True):
        result = compute_missing_deps(Path("/fake/python"), include_marimo=True)
    assert result == []


def test_compute_missing_deps_no_marimo() -> None:
    with patch("taco.core._is_package_importable", return_value=False):
        result = compute_missing_deps(Path("/fake/python"), include_marimo=False)
    assert result == ["ipykernel"]


# --- _get_kernelspec_dir ---


def test_kernelspec_dir_is_inside_project_venv(tmp_path: Path) -> None:
    project_root = tmp_path / "my-project"
    project_root.mkdir()
    config = TacoConfig(
        project_root=project_root,
        kernel_name="my-project",
        display_name="Python (my-project)",
    )
    result = _get_kernelspec_dir(config)
    assert result == project_root / ".venv" / "share" / "jupyter" / "kernels" / "my-project"


# --- patch_kernelspec ---


def test_patch_kernelspec_adds_virtual_env(tmp_path: Path) -> None:
    kernel_dir = tmp_path / "test-kernel"
    kernel_dir.mkdir()
    kernel_json = kernel_dir / "kernel.json"
    kernel_json.write_text(json.dumps({
        "argv": ["python", "-m", "ipykernel_launcher", "-f", "{connection_file}"],
        "display_name": "Test",
        "language": "python",
    }))

    project_root = tmp_path / "myproject"
    project_root.mkdir()
    config = TacoConfig(
        project_root=project_root,
        kernel_name="test-kernel",
        display_name="Test",
    )

    patch_kernelspec(kernel_dir, config)

    patched = json.loads(kernel_json.read_text())
    assert patched["env"]["VIRTUAL_ENV"] == str(project_root / ".venv")


def test_patch_kernelspec_preserves_existing_env(tmp_path: Path) -> None:
    kernel_dir = tmp_path / "test-kernel"
    kernel_dir.mkdir()
    kernel_json = kernel_dir / "kernel.json"
    kernel_json.write_text(json.dumps({
        "argv": ["python"],
        "display_name": "Test",
        "language": "python",
        "env": {"FOO": "bar"},
    }))

    project_root = tmp_path / "myproject"
    project_root.mkdir()
    config = TacoConfig(
        project_root=project_root,
        kernel_name="test-kernel",
        display_name="Test",
    )

    patch_kernelspec(kernel_dir, config)

    patched = json.loads(kernel_json.read_text())
    assert patched["env"]["FOO"] == "bar"
    assert patched["env"]["VIRTUAL_ENV"] == str(project_root / ".venv")


def test_patch_kernelspec_dry_run_does_not_modify(tmp_path: Path) -> None:
    kernel_dir = tmp_path / "test-kernel"
    kernel_dir.mkdir()
    kernel_json = kernel_dir / "kernel.json"
    original = json.dumps({"argv": ["python"], "display_name": "Test", "language": "python"})
    kernel_json.write_text(original)

    project_root = tmp_path / "myproject"
    project_root.mkdir()
    config = TacoConfig(
        project_root=project_root,
        kernel_name="test-kernel",
        display_name="Test",
        dry_run=True,
    )

    patch_kernelspec(kernel_dir, config)

    assert kernel_json.read_text() == original
