"""Core behavior for Taco's environment-backed Jupyter kernel lifecycle."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib
from jupyter_core.paths import jupyter_data_dir, jupyter_path
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from taco import __version__

console = Console()

KERNEL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
RUNTIME_PROBE = (
    "import json, sys; "
    "print(json.dumps({'interpreter': sys.executable, 'environment': sys.prefix}))"
)


class TacoError(RuntimeError):
    """An expected operational failure suitable for concise CLI output."""


class ProjectType(str, Enum):
    """The environment strategy used to launch a project kernel."""

    UV = "uv"
    POETRY = "poetry"
    CONDA = "conda"
    VENV = "venv"
    PYTHON = "python"


@dataclass
class TacoConfig:
    """Resolved configuration for a Taco command."""

    project_root: Path
    kernel_name: str
    display_name: str
    project_type: ProjectType = ProjectType.UV
    dry_run: bool = False
    force: bool = False
    venv_path: Path | None = field(init=False, default=None)
    interpreter: Path | None = field(init=False, default=None)
    uv_executable: Path | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self.project_root = self.project_root.resolve()
        validate_kernel_name(self.kernel_name)


def validate_kernel_name(name: str) -> str:
    """Validate and return one safe Jupyter kernelspec basename."""
    if (
        not name
        or name in {".", ".."}
        or not KERNEL_NAME_PATTERN.fullmatch(name)
        or Path(name).name != name
    ):
        raise ValueError("Invalid kernel name. Use only ASCII letters, numbers, '.', '_', or '-'.")
    return name


def sanitize_kernel_name(name: str) -> str:
    """Convert a project name into a safe Jupyter kernelspec basename."""
    slug = re.sub(r"[^A-Za-z0-9._-]", "-", name)
    slug = re.sub(r"-+", "-", slug).strip("-")
    if not slug or slug in {".", ".."}:
        return "unnamed-kernel"
    return validate_kernel_name(slug)


def default_display_name(project_name: str) -> str:
    """Return Taco's default user-facing kernel name."""
    return f"Python ({project_name})"


def find_project_root(start: Path | None = None, *, explicit: bool = False) -> Path:
    """Find the nearest Python project root, falling back to the working directory.

    Explicit paths must already exist and be directories so a typo can never fall
    back to an unrelated ancestor project.
    """
    if start is not None and explicit:
        if not start.exists():
            raise ValueError(f"Project directory does not exist: {start}")
        if not start.is_dir():
            raise ValueError(f"Project path is not a directory: {start}")
        return start.resolve()

    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        markers = (
            "pyproject.toml",
            "uv.lock",
            "poetry.lock",
            "requirements.txt",
            "environment.yml",
            "environment.yaml",
        )
        if (
            any((directory / marker).is_file() for marker in markers)
            or (directory / ".venv").is_dir()
        ):
            return directory
    return current


def detect_project_type(project_root: Path) -> ProjectType:
    """Choose a manager-specific or generic interpreter resolution strategy."""
    data = _read_pyproject(project_root / "pyproject.toml")
    tool = data.get("tool") if isinstance(data, dict) else None
    uv = tool.get("uv") if isinstance(tool, dict) else None
    poetry = tool.get("poetry") if isinstance(tool, dict) else None

    if (
        (project_root / "uv.lock").is_file()
        or isinstance(uv, dict)
        or (
            (project_root / "pyproject.toml").is_file()
            and bool(os.environ.get("UV_PROJECT_ENVIRONMENT"))
        )
    ):
        return ProjectType.UV
    if find_uv_workspace_root(project_root) != project_root:
        return ProjectType.UV
    if (project_root / "poetry.lock").is_file() or isinstance(poetry, dict):
        return ProjectType.POETRY

    conda_prefix = os.environ.get("CONDA_PREFIX")
    if conda_prefix and venv_interpreter(Path(conda_prefix)).is_file():
        return ProjectType.CONDA
    virtual_env = os.environ.get("VIRTUAL_ENV")
    if virtual_env and venv_interpreter(Path(virtual_env)).is_file():
        return ProjectType.VENV
    if venv_interpreter(project_root / ".venv").is_file():
        return ProjectType.VENV
    return ProjectType.PYTHON


def _read_pyproject(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as file:
            return tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def find_uv_workspace_root(project_root: Path) -> Path:
    """Return the containing uv workspace root, or the project itself."""
    for directory in (project_root, *project_root.parents):
        data = _read_pyproject(directory / "pyproject.toml")
        tool = data.get("tool") if isinstance(data, dict) else None
        uv = tool.get("uv") if isinstance(tool, dict) else None
        if isinstance(uv, dict) and isinstance(uv.get("workspace"), dict):
            return directory
    return project_root


def venv_interpreter(venv_path: Path) -> Path:
    """Return the platform-correct interpreter for a virtual environment."""
    candidates = [
        venv_path / "python.exe",
        venv_path / "Scripts" / "python.exe",
        venv_path / "bin" / "python",
        venv_path / "bin" / "python3",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[1] if os.name == "nt" else candidates[2]


def predict_uv_environment(project_root: Path) -> Path:
    """Predict uv's environment location without creating or syncing it."""
    workspace_root = find_uv_workspace_root(project_root)
    configured = os.environ.get("UV_PROJECT_ENVIRONMENT")
    if configured:
        path = Path(configured).expanduser()
        return path.resolve() if path.is_absolute() else (workspace_root / path).resolve()
    return workspace_root / ".venv"


def _direct_interpreter(config: TacoConfig) -> Path:
    """Return the best concrete interpreter for a non-manager environment."""
    if config.project_type is ProjectType.CONDA:
        prefix = os.environ.get("CONDA_PREFIX")
        if prefix:
            return venv_interpreter(Path(prefix))
    if config.project_type is ProjectType.VENV:
        prefix = os.environ.get("VIRTUAL_ENV")
        if prefix and venv_interpreter(Path(prefix)).is_file():
            return venv_interpreter(Path(prefix))
        return venv_interpreter(config.project_root / ".venv")

    resolved = shutil.which("python") or shutil.which("python3")
    return _absolute_path(resolved) if resolved else Path(sys.executable).resolve()


def _predicted_environment(interpreter: Path) -> Path:
    """Predict sys.prefix from a conventional interpreter path for dry runs."""
    if interpreter.parent.name in {"bin", "Scripts"}:
        return interpreter.parent.parent
    return interpreter.parent


def _executable(name: str, install_hint: str) -> Path:
    resolved = shutil.which(name)
    if not resolved:
        raise TacoError(f"{name} is required. {install_hint}")
    return Path(resolved).resolve()


def _run(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess and translate expected failures into TacoError."""
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise TacoError(f"Command not found: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise TacoError(f"Command timed out: {shlex.join(command)}") from exc
    except OSError as exc:
        raise TacoError(f"Could not run {command[0]}: {exc}") from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        if len(detail) > 1200:
            detail = detail[-1200:]
        message = f"Command failed ({result.returncode}): {shlex.join(command)}"
        if detail:
            message = f"{message}\n{detail}"
        raise TacoError(message)
    return result


def _uv_run_prefix(config: TacoConfig, *, with_ipykernel: bool = False) -> list[str]:
    uv = config.uv_executable or _executable(
        "uv", "Install it from https://docs.astral.sh/uv/getting-started/installation/."
    )
    config.uv_executable = uv
    command = [str(uv), "run", "--project", str(config.project_root)]
    if with_ipykernel:
        command.extend(["--with", "ipykernel"])
    return command


def _runtime_payload(result: subprocess.CompletedProcess[str], source: str) -> dict[str, str]:
    """Extract the final JSON runtime probe emitted by an environment command."""
    for line in reversed(result.stdout.splitlines()):
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(candidate, dict)
            and {"interpreter", "environment"} <= candidate.keys()
            and isinstance(candidate["interpreter"], str)
            and isinstance(candidate["environment"], str)
        ):
            return candidate
    raise TacoError(f"{source} did not report its project interpreter.")


def _absolute_path(value: str) -> Path:
    """Make a reported path absolute without collapsing environment symlinks."""
    return Path(os.path.abspath(os.path.expanduser(value)))


def _resolve_uv_environment(config: TacoConfig) -> None:
    """Resolve uv's effective interpreter and environment via uv itself."""
    if config.dry_run:
        config.uv_executable = Path(shutil.which("uv") or "uv")
        config.venv_path = predict_uv_environment(config.project_root)
        config.interpreter = venv_interpreter(config.venv_path)
        return

    result = _run(
        [*_uv_run_prefix(config), "python", "-c", RUNTIME_PROBE],
        cwd=config.project_root,
    )
    payload = _runtime_payload(result, "uv")
    config.interpreter = _absolute_path(payload["interpreter"])
    config.venv_path = Path(payload["environment"]).resolve()


def resolve_environment(config: TacoConfig) -> None:
    """Resolve the effective interpreter and environment for any supported strategy."""
    if config.project_type is ProjectType.UV:
        _resolve_uv_environment(config)
        return

    if config.project_type is ProjectType.POETRY:
        poetry = Path(shutil.which("poetry") or "poetry")
        if config.dry_run:
            active = os.environ.get("VIRTUAL_ENV")
            config.venv_path = Path(active).resolve() if active else config.project_root / ".venv"
            config.interpreter = venv_interpreter(config.venv_path)
            return
        poetry = _executable(
            "poetry", "Install it from https://python-poetry.org/docs/#installation."
        )
        result = _run(
            [str(poetry), "run", "python", "-c", RUNTIME_PROBE],
            cwd=config.project_root,
        )
        payload = _runtime_payload(result, "Poetry")
    else:
        interpreter = _direct_interpreter(config)
        if config.dry_run:
            config.interpreter = interpreter
            prefix = os.environ.get("CONDA_PREFIX") or os.environ.get("VIRTUAL_ENV")
            config.venv_path = (
                Path(prefix).resolve() if prefix else _predicted_environment(interpreter)
            )
            return
        result = _run([str(interpreter), "-c", RUNTIME_PROBE], cwd=config.project_root)
        payload = _runtime_payload(result, "Python")

    config.interpreter = _absolute_path(payload["interpreter"])
    config.venv_path = Path(payload["environment"]).resolve()


def resolve_uv_environment(config: TacoConfig) -> None:
    """Compatibility wrapper for callers that explicitly resolve uv projects."""
    _resolve_uv_environment(config)


def _is_package_importable(interpreter: Path, package: str) -> bool:
    """Return whether a package imports from a concrete interpreter."""
    try:
        result = subprocess.run(
            [str(interpreter), "-c", f"import {package}"],
            capture_output=True,
            timeout=30,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def compute_missing_deps(interpreter: Path, include_marimo: bool = False) -> list[str]:
    """Compatibility helper returning missing notebook packages."""
    packages = ["ipykernel"]
    if include_marimo:
        packages.append("marimo")
    return [package for package in packages if not _is_package_importable(interpreter, package)]


def add_dev_deps(config: TacoConfig, packages: list[str]) -> bool:
    """Compatibility helper for explicitly adding uv development dependencies."""
    if not packages:
        return False
    command = [
        str(
            config.uv_executable
            or _executable(
                "uv",
                "Install it from https://docs.astral.sh/uv/getting-started/installation/.",
            )
        ),
        "add",
        "--dev",
        "--project",
        str(config.project_root),
        *packages,
    ]
    if config.dry_run:
        console.print(f"PLAN  {shlex.join(command)}", markup=False, soft_wrap=True)
        return True
    _run(command, cwd=config.project_root)
    return True


def get_user_kernel_dir() -> Path:
    """Return Jupyter's platform-aware per-user kernels directory."""
    return Path(jupyter_data_dir()) / "kernels"


def get_all_kernel_dirs() -> list[Path]:
    """Return Jupyter's configured kernelspec search path in precedence order."""
    directories: list[Path] = []
    seen: set[str] = set()
    for value in jupyter_path("kernels"):
        path = Path(value).expanduser()
        key = os.path.normcase(str(path.resolve(strict=False)))
        if key not in seen:
            directories.append(path)
            seen.add(key)
    return directories


def _safe_kernel_dir(base: Path, kernel_name: str) -> Path:
    """Join a validated kernel name and assert it cannot escape its base."""
    validate_kernel_name(kernel_name)
    base_resolved = base.resolve(strict=False)
    target = (base / kernel_name).resolve(strict=False)
    if target.parent != base_resolved:
        raise TacoError(f"Unsafe kernelspec path refused: {target}")
    return target


def _get_kernelspec_dir(config: TacoConfig) -> Path:
    """Return the user-visible kernelspec directory Taco owns for this config."""
    return _safe_kernel_dir(get_user_kernel_dir(), config.kernel_name)


def read_kernel_info(kernelspec_dir: Path) -> dict[str, Any] | None:
    """Read a kernel.json object, or return None when it is missing or malformed."""
    kernel_json = kernelspec_dir / "kernel.json"
    if not kernel_json.is_file():
        return None
    try:
        data = json.loads(kernel_json.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _taco_metadata(data: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        return None
    taco = metadata.get("taco")
    if not isinstance(taco, dict):
        return None
    if taco.get("schema") != 1 or taco.get("project_type") not in {
        project_type.value for project_type in ProjectType
    }:
        return None
    if not isinstance(taco.get("version"), str) or not taco["version"]:
        return None
    for key in ("project_root", "environment", "interpreter"):
        value = taco.get(key)
        if not isinstance(value, str) or not value or not Path(value).is_absolute():
            return None
    return taco


def is_taco_managed(data: dict[str, Any] | None) -> bool:
    """Return whether a kernelspec contains Taco ownership metadata."""
    return _taco_metadata(data) is not None


def discover_kernels(*, managed_only: bool = False) -> list[dict[str, Any]]:
    """Discover kernels without hiding duplicates or malformed specifications."""
    kernels: list[dict[str, Any]] = []
    first_by_name: set[str] = set()

    for kernel_base in get_all_kernel_dirs():
        if not kernel_base.is_dir():
            continue
        try:
            entries = sorted(kernel_base.iterdir(), key=lambda path: path.name.casefold())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir():
                continue
            kernel_json = entry / "kernel.json"
            if not kernel_json.is_file():
                continue
            error = ""
            try:
                raw = json.loads(kernel_json.read_text())
                if not isinstance(raw, dict):
                    raise ValueError("kernel.json must contain an object")
                data: dict[str, Any] | None = raw
            except (json.JSONDecodeError, OSError, ValueError) as exc:
                data = None
                error = str(exc)

            taco = _taco_metadata(data)
            managed = taco is not None
            if managed_only and not managed:
                continue
            argv_value = data.get("argv") if data else None
            argv = argv_value if isinstance(argv_value, list) else []
            env_value = data.get("env") if data else None
            spec_env = env_value if isinstance(env_value, dict) else {}
            metadata_interpreter = taco.get("interpreter") if taco else None
            interpreter = (
                str(metadata_interpreter) if metadata_interpreter else str(argv[0]) if argv else ""
            )
            folded = entry.name.casefold()
            shadowed = folded in first_by_name
            first_by_name.add(folded)
            kernels.append(
                {
                    "name": entry.name,
                    "path": str(entry),
                    "display_name": (
                        str(data.get("display_name", entry.name)) if data else entry.name
                    ),
                    "argv": [str(value) for value in argv],
                    "launcher": str(argv[0]) if argv else "",
                    "interpreter": interpreter,
                    "virtual_env": (
                        str(taco.get("environment", ""))
                        if taco
                        else str(spec_env.get("VIRTUAL_ENV", ""))
                    ),
                    "environment": str(taco.get("environment", "")) if taco else "",
                    "project": str(taco.get("project_root", "")) if taco else "",
                    "project_type": str(taco.get("project_type", "")) if taco else "",
                    "managed_by_taco": managed,
                    "valid": data is not None and bool(argv),
                    "error": error or ("missing argv" if data is not None and not argv else ""),
                    "shadowed": shadowed,
                    "data": data,
                }
            )
    return sorted(kernels, key=lambda item: (item["name"].casefold(), item["path"]))


def _same_project(record: dict[str, Any], project_root: Path) -> bool:
    value = record.get("project")
    if not value:
        return False
    try:
        return Path(str(value)).resolve() == project_root.resolve()
    except OSError:
        return False


def _valid_launcher(record: dict[str, Any]) -> bool:
    """Validate Taco's manager or direct kernel command without executing it."""
    argv = record.get("argv")
    project = record.get("project")
    project_type = record.get("project_type")
    interpreter = record.get("interpreter")
    if not isinstance(argv, list) or not project or not interpreter:
        return False
    if project_type != ProjectType.UV.value:
        return argv == [
            str(interpreter),
            "-m",
            "ipykernel_launcher",
            "-f",
            "{connection_file}",
        ]
    expected_tail = [
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
    ]
    return len(argv) == len(expected_tail) + 1 and argv[1:] == expected_tail


def _canonical_user_record(record: dict[str, Any]) -> bool:
    """Return whether a record is an owned spec at Taco's canonical write location."""
    if not record.get("managed_by_taco"):
        return False
    try:
        expected = _safe_kernel_dir(get_user_kernel_dir(), str(record["name"]))
        return Path(str(record["path"])).resolve(strict=False) == expected
    except (KeyError, OSError, TacoError, ValueError):
        return False


def _record_is_stale(record: dict[str, Any]) -> bool:
    """Return whether a validated Taco record is safe to classify as stale."""
    return (
        not record.get("valid")
        or not bool(record.get("project"))
        or not Path(str(record["project"])).is_dir()
        or not _executable_exists(str(record.get("launcher", "")))
        or not _valid_launcher(record)
    )


def _fresh_deletable_record(
    record: dict[str, Any],
    *,
    project_root: Path | None = None,
    require_stale: bool = False,
) -> dict[str, Any] | None:
    """Re-read and revalidate an exact user-level record immediately before deletion."""
    if not _canonical_user_record(record):
        return None
    kernel_dir = Path(str(record["path"]))
    data = read_kernel_info(kernel_dir)
    taco = _taco_metadata(data)
    if taco is None:
        return None
    if project_root is not None and Path(taco["project_root"]).resolve() != project_root.resolve():
        return None
    refreshed = next(
        (
            candidate
            for candidate in discover_kernels(managed_only=True)
            if Path(candidate["path"]).resolve(strict=False) == kernel_dir.resolve(strict=False)
        ),
        None,
    )
    if refreshed is None or not _canonical_user_record(refreshed):
        return None
    if require_stale and not _record_is_stale(refreshed):
        return None
    return refreshed


def _check_kernel_collision(config: TacoConfig) -> None:
    target = _get_kernelspec_dir(config).resolve(strict=False)
    for record in discover_kernels():
        if record["name"].casefold() != config.kernel_name.casefold():
            continue
        current = Path(record["path"]).resolve(strict=False)
        if (
            current == target
            and record["managed_by_taco"]
            and _same_project(record, config.project_root)
        ):
            continue
        if current == target and config.force:
            continue
        owner = record.get("project") or "another Jupyter installation"
        raise TacoError(
            f"Kernel name '{config.kernel_name}' is already used by {owner}. "
            "Choose a unique --name, or use --force only to replace the user-level spec."
        )


def install_kernel(config: TacoConfig) -> Path:
    """Prepare ipykernel and install a user-discoverable kernelspec."""
    if config.interpreter is None or config.venv_path is None:
        resolve_environment(config)
    _check_kernel_collision(config)
    if config.project_type is ProjectType.UV:
        command = [
            *_uv_run_prefix(config, with_ipykernel=True),
            "python",
            "-m",
            "ipykernel",
            "install",
            "--user",
            "--name",
            config.kernel_name,
            "--display-name",
            config.display_name,
        ]
        prepare_command: list[str] | None = None
    else:
        if config.interpreter is None:  # pragma: no cover - guarded by resolution above
            raise TacoError("Python interpreter was not resolved before kernel installation.")
        prepare_command = [str(config.interpreter), "-m", "pip", "install"]
        if config.project_type is ProjectType.PYTHON:
            prepare_command.append("--user")
        prepare_command.append("ipykernel")
        command = [
            str(config.interpreter),
            "-m",
            "ipykernel",
            "install",
            "--user",
            "--name",
            config.kernel_name,
            "--display-name",
            config.display_name,
        ]
    kernelspec_dir = _get_kernelspec_dir(config)
    if config.dry_run:
        if prepare_command is not None:
            console.print(
                f"PLAN  Ensure ipykernel is available: {shlex.join(prepare_command)}",
                markup=False,
                soft_wrap=True,
            )
        console.print(f"PLAN  {shlex.join(command)}", markup=False, soft_wrap=True)
        console.print(f"PLAN  Write kernelspec to {kernelspec_dir}", markup=False, soft_wrap=True)
        return kernelspec_dir
    if prepare_command is not None and not _is_package_importable(config.interpreter, "ipykernel"):
        _run(prepare_command, cwd=config.project_root)
    _run(command, cwd=config.project_root)
    if not (kernelspec_dir / "kernel.json").is_file():
        raise TacoError(f"ipykernel did not create {kernelspec_dir / 'kernel.json'}")
    return kernelspec_dir


def patch_kernelspec(kernelspec_dir: Path, config: TacoConfig) -> None:
    """Make a kernelspec durable and explicitly Taco-owned."""
    kernel_json = kernelspec_dir / "kernel.json"
    if config.dry_run:
        console.print(
            f"PLAN  Add Taco ownership metadata to {kernel_json}",
            markup=False,
            soft_wrap=True,
        )
        return
    data = read_kernel_info(kernelspec_dir)
    if data is None:
        raise TacoError(f"Cannot read kernelspec: {kernel_json}")
    if config.interpreter is None or config.venv_path is None:
        raise TacoError("Python environment was not resolved before kernelspec patching.")

    if config.project_type is ProjectType.UV:
        if config.uv_executable is None:
            raise TacoError("uv was not resolved before kernelspec patching.")
        data["argv"] = [
            str(config.uv_executable),
            "run",
            "--project",
            str(config.project_root),
            "--with",
            "ipykernel",
            "python",
            "-m",
            "ipykernel_launcher",
            "-f",
            "{connection_file}",
        ]
    else:
        data["argv"] = [
            str(config.interpreter),
            "-m",
            "ipykernel_launcher",
            "-f",
            "{connection_file}",
        ]
    env_value = data.get("env")
    spec_env = env_value if isinstance(env_value, dict) else {}
    spec_env.pop("VIRTUAL_ENV", None)
    spec_env.pop("UV_PROJECT_ENVIRONMENT", None)
    if config.project_type is ProjectType.UV:
        spec_env["UV_PROJECT_ENVIRONMENT"] = str(config.venv_path)
    data["env"] = spec_env
    metadata_value = data.get("metadata")
    metadata = metadata_value if isinstance(metadata_value, dict) else {}
    metadata["taco"] = {
        "schema": 1,
        "version": __version__,
        "project_root": str(config.project_root),
        "project_type": config.project_type.value,
        "environment": str(config.venv_path),
        "interpreter": str(config.interpreter or ""),
    }
    data["metadata"] = metadata
    temporary = kernel_json.with_suffix(".json.tmp")
    try:
        temporary.write_text(json.dumps(data, indent=2) + "\n")
        temporary.replace(kernel_json)
    except OSError as exc:
        raise TacoError(f"Could not update kernelspec {kernel_json}: {exc}") from exc


def _executable_exists(command: str) -> bool:
    if not command:
        return False
    path = Path(command).expanduser()
    if path.is_absolute() or path.parent != Path("."):
        return path.is_file()
    return shutil.which(command) is not None


def kernel_health(
    record: dict[str, Any],
    *,
    check_runtime: bool = True,
    trusted_interpreter: Path | None = None,
) -> dict[str, Any]:
    """Return structured static and runtime checks for one kernelspec."""
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    add("kernelspec", bool(record.get("valid")), record.get("error") or "valid JSON")
    add(
        "launcher",
        _executable_exists(str(record.get("launcher", ""))),
        str(record.get("launcher") or "missing"),
    )
    if record.get("managed_by_taco"):
        project = Path(str(record.get("project", "")))
        add("project", project.is_dir(), str(project))
        environment = Path(str(record.get("environment", "")))
        add("environment", environment.is_dir(), str(environment))
        command_valid = _valid_launcher(record)
        project_type = str(record.get("project_type", ""))
        add(
            "command",
            command_valid,
            f"valid {project_type} launcher" if command_valid else "invalid command",
        )
        trusted_uv = shutil.which("uv") if project_type == ProjectType.UV.value else None
        if check_runtime and project.is_dir() and command_valid and trusted_uv:
            env = os.environ.copy()
            if record.get("environment"):
                env["UV_PROJECT_ENVIRONMENT"] = str(record["environment"])
            command = [
                str(Path(trusted_uv).resolve()),
                "run",
                "--project",
                str(project),
                "--with",
                "ipykernel",
                "python",
                "-c",
                "import ipykernel",
            ]
            try:
                _run(command, cwd=project, env=env, timeout=180)
                add("runtime", True, "ipykernel imports through uv")
            except TacoError as exc:
                add("runtime", False, str(exc).splitlines()[-1])
        elif check_runtime and project.is_dir() and command_valid:
            recorded = _absolute_path(str(record.get("interpreter", "")))
            trusted_path = (
                Path(os.path.abspath(trusted_interpreter))
                if trusted_interpreter is not None
                else None
            )
            if trusted_path is None or trusted_path != recorded:
                add("runtime", False, "trusted project interpreter could not be resolved")
            else:
                try:
                    _run(
                        [str(trusted_path), "-c", "import ipykernel"],
                        cwd=project,
                        timeout=60,
                    )
                    add("runtime", True, "ipykernel imports through the project interpreter")
                except TacoError as exc:
                    add("runtime", False, str(exc).splitlines()[-1])

    return {"healthy": all(check["ok"] for check in checks), "checks": checks}


def _find_kernel(config: TacoConfig) -> dict[str, Any] | None:
    candidates = [
        record
        for record in discover_kernels()
        if record["name"].casefold() == config.kernel_name.casefold()
    ]
    for record in candidates:
        if record["managed_by_taco"] and _same_project(record, config.project_root):
            return record
    return None


def remove_project_kernel(config: TacoConfig) -> bool:
    """Remove only the exact Taco-owned spec for this project."""
    record = _find_kernel(config)
    if record is None:
        return False
    record = _fresh_deletable_record(record, project_root=config.project_root)
    if record is None:
        return False
    kernel_dir = Path(record["path"])
    safe_dir = _safe_kernel_dir(kernel_dir.parent, kernel_dir.name)
    if config.dry_run:
        console.print(f"PLAN  Remove {escape(str(safe_dir))}")
        return True
    try:
        shutil.rmtree(safe_dir)
    except OSError as exc:
        raise TacoError(f"Could not remove kernelspec {safe_dir}: {exc}") from exc
    return True


def remove_kernel(
    kernel_name: str,
    dry_run: bool = False,
    *,
    project_root: Path | None = None,
) -> bool:
    """Remove Taco-owned kernels matching a name and optional project."""
    validate_kernel_name(kernel_name)
    removed = False
    for record in discover_kernels(managed_only=True):
        if record["name"].casefold() != kernel_name.casefold():
            continue
        if project_root is not None and not _same_project(record, project_root):
            continue
        record = _fresh_deletable_record(record, project_root=project_root)
        if record is None:
            continue
        kernel_dir = Path(record["path"])
        safe_dir = _safe_kernel_dir(kernel_dir.parent, kernel_dir.name)
        if dry_run:
            console.print(f"PLAN  Remove {escape(str(safe_dir))}")
        else:
            try:
                shutil.rmtree(safe_dir)
            except OSError as exc:
                raise TacoError(f"Could not remove kernelspec {safe_dir}: {exc}") from exc
        removed = True
    return removed


def _plain_ui() -> bool:
    return not console.is_terminal or os.environ.get("TERM") == "dumb"


def _emit_json(payload: dict[str, Any]) -> None:
    """Write JSON without Rich highlighting or terminal-dependent ANSI codes."""
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _print_list_next_steps(records: list[dict[str, Any]]) -> None:
    commands = dict.fromkeys(
        shlex.join(
            [
                "taco",
                "info",
                "--project",
                str(record["project"]),
                "--name",
                str(record["name"]),
            ]
        )
        for record in records
        if not record["healthy"] and record["managed_by_taco"] and record["project"]
    )
    if not commands:
        return
    console.print("\nNext:")
    for command in commands:
        console.print(f"  {command}", markup=False, soft_wrap=True)


def _failed_check_names(record: dict[str, Any]) -> str:
    return ", ".join(check["name"] for check in record["checks"] if not check["ok"])


def run_setup(config: TacoConfig) -> None:
    """Create or refresh and verify a user-discoverable Python kernel."""
    _check_kernel_collision(config)
    resolve_environment(config)
    mode = "DRY RUN" if config.dry_run else "SETUP"
    console.print(f"{mode}  Taco {__version__}")
    console.print(f"Project      {escape(str(config.project_root))}")
    console.print(f"Environment  {escape(str(config.venv_path))}")
    console.print(f"Kernel       {escape(config.kernel_name)}")
    console.print()

    if config.dry_run:
        console.print(f"PLAN  Resolve the effective {config.project_type.value} environment")
        install_kernel(config)
        patch_kernelspec(_get_kernelspec_dir(config), config)
        console.print("\nDry run complete — no changes made.")
        return

    console.print(f"OK    Effective {config.project_type.value} environment resolved")
    kernelspec_dir = install_kernel(config)
    console.print("OK    ipykernel runtime prepared")
    patch_kernelspec(kernelspec_dir, config)
    console.print(f"OK    Kernel registered at {escape(str(kernelspec_dir))}")

    record = _find_kernel(config)
    if record is None:
        raise TacoError("The installed kernel is not discoverable through Jupyter.")
    health = kernel_health(
        record,
        check_runtime=True,
        trusted_interpreter=(
            config.interpreter if config.project_type is not ProjectType.UV else None
        ),
    )
    if not health["healthy"]:
        failures = ", ".join(check["name"] for check in health["checks"] if not check["ok"])
        raise TacoError(f"Kernel verification failed: {failures}")
    console.print("OK    Kernel runtime verified")
    console.print(f"\nReady  {escape(config.display_name)} is available in Jupyter and VS Code.")


def run_list(*, managed_only: bool = True, json_output: bool = False) -> None:
    """List kernels with deterministic, scriptable output."""
    kernels = discover_kernels(managed_only=managed_only)
    records: list[dict[str, Any]] = []
    for kernel in kernels:
        health = kernel_health(kernel, check_runtime=False)
        records.append(
            {
                "name": kernel["name"],
                "display_name": kernel["display_name"],
                "project": kernel["project"],
                "environment": kernel["environment"] or kernel["virtual_env"],
                "interpreter": kernel["interpreter"],
                "location": kernel["path"],
                "healthy": health["healthy"],
                "checks": health["checks"],
                "managed_by_taco": kernel["managed_by_taco"],
                "shadowed": kernel["shadowed"],
                "error": kernel["error"],
            }
        )
    if json_output:
        _emit_json({"count": len(records), "kernels": records})
        return
    if not records:
        scope = "Taco-managed " if managed_only else ""
        console.print(f"No {scope}Jupyter kernels found.")
        return
    if _plain_ui():
        for record in records:
            status = "healthy" if record["healthy"] else "unhealthy"
            failed = _failed_check_names(record)
            issue = f"\tfailed: {failed or 'unknown'}" if not record["healthy"] else ""
            console.print(
                f"{record['name']}\t{status}\t{record['project'] or record['location']}{issue}",
                markup=False,
                soft_wrap=True,
            )
        _print_list_next_steps(records)
        return
    table = Table(title="Taco kernels" if managed_only else "Jupyter kernels")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Status")
    table.add_column("Project")
    table.add_column("Environment", style="dim")
    table.add_column("Failed checks")
    for record in records:
        status = "[green]healthy[/green]" if record["healthy"] else "[red]unhealthy[/red]"
        failed = _failed_check_names(record)
        table.add_row(
            escape(record["name"]),
            status,
            escape(record["project"] or "—"),
            escape(record["environment"] or "—"),
            escape(failed or "—"),
        )
    console.print(table)
    _print_list_next_steps(records)


def run_info(config: TacoConfig, *, json_output: bool = False) -> bool:
    """Show one project's kernelspec and return whether it is healthy."""
    record = _find_kernel(config)
    if record is None:
        if json_output:
            _emit_json(
                {
                    "name": config.kernel_name,
                    "found": False,
                    "healthy": False,
                    "checks": [],
                }
            )
        else:
            console.print(f"Kernel '{escape(config.kernel_name)}' is not installed.")
            console.print("Run `taco setup` to create it.")
        return False

    trusted_interpreter: Path | None = None
    if record.get("project_type") != ProjectType.UV.value:
        try:
            if record.get("project_type") == config.project_type.value:
                resolve_environment(config)
                trusted_interpreter = config.interpreter
        except TacoError:
            pass
    health = kernel_health(
        record,
        check_runtime=True,
        trusted_interpreter=trusted_interpreter,
    )
    payload = {
        "name": record["name"],
        "display_name": record["display_name"],
        "found": True,
        "healthy": health["healthy"],
        "project": record["project"],
        "environment": record["environment"],
        "interpreter": record["interpreter"],
        "location": record["path"],
        "command": record["argv"],
        "checks": health["checks"],
    }
    if json_output:
        _emit_json(payload)
        return bool(health["healthy"])

    console.print(f"Kernel       {escape(record['name'])}")
    console.print(f"Display name {escape(record['display_name'])}")
    console.print(f"Project      {escape(record['project'])}")
    console.print(f"Environment  {escape(record['environment'])}")
    console.print(f"Location     {escape(record['path'])}")
    console.print("\nHealth checks")
    for check in health["checks"]:
        label = "OK" if check["ok"] else "FAIL"
        console.print(f"{label:<4}  {escape(check['name'])}: {escape(str(check['detail']))}")
    return bool(health["healthy"])


def run_remove(config: TacoConfig) -> bool:
    """Remove only this project's Taco-owned kernel."""
    removed = remove_project_kernel(config)
    if not removed:
        console.print(f"Kernel '{escape(config.kernel_name)}' is not installed for this project.")
        return False
    if config.dry_run:
        console.print("\nDry run complete — no changes made.")
    else:
        console.print(f"Removed kernel '{escape(config.kernel_name)}'.")
    return True


def find_stale_kernels() -> list[dict[str, Any]]:
    """Return only Taco-owned kernels whose project or launcher is gone."""
    stale: list[dict[str, Any]] = []
    for record in discover_kernels(managed_only=True):
        if not _canonical_user_record(record):
            continue
        if _record_is_stale(record):
            stale.append(record)
    return stale


def run_clean(dry_run: bool = False, *, kernels: list[dict[str, Any]] | None = None) -> int:
    """Remove stale Taco-owned kernels and return the number found."""
    stale = list(kernels) if kernels is not None else find_stale_kernels()
    validated = [
        refreshed
        for record in stale
        if (refreshed := _fresh_deletable_record(record, require_stale=True)) is not None
    ]
    if not validated:
        console.print("No stale Taco kernels found.")
        return 0
    for record in validated:
        action = "PLAN  Remove" if dry_run else "REMOVE"
        console.print(f"{action}  {escape(record['name'])} ({escape(record['path'])})")
        if not dry_run:
            kernel_dir = Path(record["path"])
            safe_dir = _safe_kernel_dir(kernel_dir.parent, kernel_dir.name)
            try:
                shutil.rmtree(safe_dir)
            except OSError as exc:
                raise TacoError(f"Could not remove kernelspec {safe_dir}: {exc}") from exc
    if dry_run:
        console.print("\nDry run complete — no changes made.")
    else:
        console.print(f"\nRemoved {len(validated)} stale Taco kernel(s).")
    return len(validated)
