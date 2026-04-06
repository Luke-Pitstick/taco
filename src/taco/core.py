"""Core logic for taco — project detection, dependency management, kernel installation."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()


class ProjectType(Enum):
    UV = "uv"
    POETRY = "poetry"
    PIP = "pip"


@dataclass
class TacoConfig:
    """Resolved configuration for a taco run."""

    project_root: Path
    kernel_name: str
    display_name: str
    project_type: ProjectType = ProjectType.UV
    include_marimo: bool = True
    dry_run: bool = False
    venv_path: Path = field(init=False)
    interpreter: Path = field(init=False)

    def __post_init__(self) -> None:
        self.venv_path = _find_venv(self.project_root, self.project_type)
        self.interpreter = self.venv_path / "bin" / "python"


def _find_venv(project_root: Path, project_type: ProjectType) -> Path:
    """Locate the virtual environment for the project."""
    # Check common venv locations
    for name in (".venv", "venv"):
        candidate = project_root / name
        if (candidate / "bin" / "python").exists() or (
            candidate / "Scripts" / "python.exe"
        ).exists():
            return candidate

    # For poetry, ask poetry where the venv is
    if project_type == ProjectType.POETRY:
        try:
            result = subprocess.run(
                ["poetry", "env", "info", "-p"],
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0:
                venv_path = Path(result.stdout.strip())
                if venv_path.exists():
                    return venv_path
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    # Default to .venv (will be created during dep sync)
    return project_root / ".venv"


def detect_project_type(project_root: Path) -> ProjectType:
    """Detect what kind of Python project this is."""
    # Check for uv markers first
    if (project_root / "uv.lock").exists():
        return ProjectType.UV
    pyproject = project_root / "pyproject.toml"
    if pyproject.exists():
        content = pyproject.read_text()
        if "[tool.uv]" in content:
            return ProjectType.UV
        # Check for poetry markers
        if (project_root / "poetry.lock").exists():
            return ProjectType.POETRY
        if "[tool.poetry]" in content:
            return ProjectType.POETRY

    # Check for pip markers
    if (project_root / "requirements.txt").exists():
        return ProjectType.PIP

    # If there's a pyproject.toml but no specific markers, check if uv is available
    if pyproject.exists():
        try:
            result = subprocess.run(["uv", "--version"], capture_output=True, timeout=5)
            if result.returncode == 0:
                return ProjectType.UV
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return ProjectType.PIP

    return ProjectType.PIP


def find_project_root(start: Path | None = None) -> Path:
    """Walk up from *start* (default: cwd) to find the nearest project root.

    Looks for pyproject.toml, setup.py, setup.cfg, or requirements.txt.
    Returns the directory containing it, or raises SystemExit.
    """
    markers = ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt")
    current = (start or Path.cwd()).resolve()
    for directory in [current, *current.parents]:
        for marker in markers:
            if (directory / marker).is_file():
                return directory
    raise SystemExit(
        "[red]Error:[/red] No Python project found. "
        "Run taco from inside a project with pyproject.toml, setup.py, or requirements.txt."
    )


def sanitize_kernel_name(name: str) -> str:
    """Sanitize a string into a Jupyter-safe kernel name slug.

    Jupyter kernel names must match [a-zA-Z0-9._-]+.
    """
    slug = re.sub(r"[^a-zA-Z0-9._-]", "-", name)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "unnamed-kernel"


def default_display_name(project_name: str) -> str:
    return f"Python ({project_name})"


def _is_package_importable(interpreter: Path, package: str) -> bool:
    """Check whether *package* is importable by *interpreter*."""
    try:
        result = subprocess.run(
            [str(interpreter), "-c", f"import {package}"],
            capture_output=True,
            timeout=30,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def compute_missing_deps(interpreter: Path, include_marimo: bool) -> list[str]:
    """Return the list of packages that need to be added as dev deps."""
    packages = ["ipykernel"]
    if include_marimo:
        packages.append("marimo")
    return [p for p in packages if not _is_package_importable(interpreter, p)]


def add_dev_deps(config: TacoConfig, packages: list[str]) -> bool:
    """Install missing packages using the appropriate package manager."""
    if not packages:
        return False

    if config.project_type == ProjectType.UV:
        cmd = ["uv", "add", "--dev", "--project", str(config.project_root), *packages]
    elif config.project_type == ProjectType.POETRY:
        cmd = ["poetry", "add", "--group", "dev", *packages]
    else:
        # pip — install into the venv directly
        cmd = [str(config.interpreter), "-m", "pip", "install", *packages]

    if config.dry_run:
        console.print(f"  [dim]Would run:[/dim] {' '.join(cmd)}")
        return True

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(config.project_root),
    )
    if result.returncode != 0:
        tool = config.project_type.value
        raise SystemExit(f"[red]Error:[/red] {tool} install failed:\n{result.stderr}")
    return True


def _ensure_venv(config: TacoConfig) -> None:
    """Create a virtual environment if one doesn't exist (pip projects only)."""
    if config.venv_path.exists():
        return
    if config.project_type != ProjectType.PIP:
        return
    if config.dry_run:
        console.print(f"  [dim]Would run:[/dim] python -m venv {config.venv_path}")
        return
    subprocess.run(
        [sys.executable, "-m", "venv", str(config.venv_path)],
        check=True,
    )


def install_kernel(config: TacoConfig) -> Path:
    """Install the ipykernel kernelspec into the project venv and return the kernelspec directory."""
    cmd = [
        str(config.interpreter),
        "-m",
        "ipykernel",
        "install",
        "--prefix",
        str(config.venv_path),
        "--name",
        config.kernel_name,
        "--display-name",
        config.display_name,
    ]
    kernelspec_dir = _get_kernelspec_dir(config)
    if config.dry_run:
        console.print(f"  [dim]Would run:[/dim] {' '.join(cmd)}")
        return kernelspec_dir

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"[red]Error:[/red] Kernel install failed:\n{result.stderr}")
    return kernelspec_dir


def _get_kernelspec_dir(config: TacoConfig) -> Path:
    """Return the project-local kernelspec directory."""
    return config.venv_path / "share" / "jupyter" / "kernels" / config.kernel_name


def get_all_kernel_dirs() -> list[Path]:
    """Return all standard kernel search directories for this platform."""
    dirs: list[Path] = []
    # User-level
    if sys.platform == "darwin":
        dirs.append(Path.home() / "Library" / "Jupyter" / "kernels")
    else:
        dirs.append(
            Path(
                os.environ.get(
                    "JUPYTER_DATA_DIR",
                    Path.home() / ".local" / "share" / "jupyter",
                )
            )
            / "kernels"
        )
    # System-level
    if sys.platform == "darwin":
        dirs.append(Path("/usr/local/share/jupyter/kernels"))
        dirs.append(Path("/usr/share/jupyter/kernels"))
    else:
        dirs.append(Path("/usr/local/share/jupyter/kernels"))
        dirs.append(Path("/usr/share/jupyter/kernels"))
    return dirs


def discover_kernels() -> list[dict]:
    """Find all installed Jupyter kernels across user and system locations.

    Returns a list of dicts with keys: name, path, display_name, interpreter, virtual_env.
    """
    kernels: list[dict] = []
    seen_names: set[str] = set()

    for kernel_base in get_all_kernel_dirs():
        if not kernel_base.is_dir():
            continue
        for entry in sorted(kernel_base.iterdir()):
            kernel_json = entry / "kernel.json"
            if not kernel_json.is_file():
                continue
            name = entry.name
            if name in seen_names:
                continue
            seen_names.add(name)
            try:
                data = json.loads(kernel_json.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            argv = data.get("argv", [])
            kernels.append(
                {
                    "name": name,
                    "path": str(entry),
                    "display_name": data.get("display_name", name),
                    "interpreter": argv[0] if argv else "unknown",
                    "virtual_env": data.get("env", {}).get("VIRTUAL_ENV", ""),
                }
            )
    return kernels


def remove_kernel(kernel_name: str, dry_run: bool = False) -> bool:
    """Remove a kernel by name from all known locations. Returns True if anything was removed."""
    removed = False
    for kernel_base in get_all_kernel_dirs():
        kernel_dir = kernel_base / kernel_name
        if kernel_dir.is_dir():
            if dry_run:
                console.print(f"  [dim]Would remove:[/dim] {kernel_dir}")
            else:
                shutil.rmtree(kernel_dir)
                console.print(f"  [green]✓[/green] Removed [cyan]{kernel_dir}[/cyan]")
            removed = True
    return removed


def remove_project_kernel(config: TacoConfig) -> bool:
    """Remove the project-local kernelspec."""
    kernelspec_dir = _get_kernelspec_dir(config)
    if not kernelspec_dir.is_dir():
        return False
    if config.dry_run:
        console.print(f"  [dim]Would remove:[/dim] {kernelspec_dir}")
        return True
    shutil.rmtree(kernelspec_dir)
    console.print(f"  [green]✓[/green] Removed [cyan]{kernelspec_dir}[/cyan]")
    return True


def patch_kernelspec(kernelspec_dir: Path, config: TacoConfig) -> None:
    """Patch kernel.json to include VIRTUAL_ENV so out-of-venv frontends work."""
    kernel_json = kernelspec_dir / "kernel.json"
    if config.dry_run:
        console.print(f"  [dim]Would patch:[/dim] {kernel_json}")
        return
    if not kernel_json.exists():
        return
    data = json.loads(kernel_json.read_text())
    env = data.get("env", {})
    env["VIRTUAL_ENV"] = str(config.venv_path)
    data["env"] = env
    kernel_json.write_text(json.dumps(data, indent=1) + "\n")


def read_kernel_info(kernelspec_dir: Path) -> dict | None:
    """Read and return the parsed kernel.json, or None if missing."""
    kernel_json = kernelspec_dir / "kernel.json"
    if not kernel_json.is_file():
        return None
    try:
        return json.loads(kernel_json.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _project_type_label(project_type: ProjectType) -> str:
    """Human-readable label for the project type."""
    return {
        ProjectType.UV: "uv",
        ProjectType.POETRY: "poetry",
        ProjectType.PIP: "pip/venv",
    }[project_type]


def _jupyter_launch_hint(config: TacoConfig) -> str:
    """Return the recommended Jupyter Lab launch command for this project type."""
    if config.project_type == ProjectType.UV:
        return "uv run --with jupyter jupyter lab"
    elif config.project_type == ProjectType.POETRY:
        return "poetry run jupyter lab"
    else:
        return "jupyter lab"


def _marimo_launch_hint(config: TacoConfig) -> str:
    """Return the recommended marimo launch command for this project type."""
    if config.project_type == ProjectType.UV:
        return "uv run marimo edit notebook.py"
    elif config.project_type == ProjectType.POETRY:
        return "poetry run marimo edit notebook.py"
    else:
        return "marimo edit notebook.py"


def run_setup(config: TacoConfig) -> None:
    """Execute the full taco setup workflow with rich output."""
    project_name = config.project_root.name
    type_label = _project_type_label(config.project_type)

    # Title panel
    title = Text()
    title.append("🌮 taco", style="bold magenta")
    title.append(" — notebook bootstrapper\n\n")
    title.append("Project:     ", style="bold")
    title.append(f"{project_name}\n")
    title.append("Type:        ", style="bold")
    title.append(f"{type_label}\n")
    title.append("Interpreter: ", style="bold")
    title.append(f"{config.interpreter}\n")
    title.append("Kernel:      ", style="bold")
    title.append(f"{config.kernel_name}")
    console.print(Panel(title, border_style="magenta"))

    # Step 1: Project detection
    console.print(f"\n[bold]1.[/bold] Project detection [dim]({type_label})[/dim]")
    if config.venv_path.exists() or config.dry_run:
        console.print(
            f"   [green]✓[/green] Found {type_label} project at [cyan]{config.project_root}[/cyan]"
        )
    else:
        if config.project_type == ProjectType.PIP:
            console.print(f"   [yellow]![/yellow] No venv found — will create one")
            _ensure_venv(config)
            if not config.dry_run:
                # Re-resolve interpreter after creating venv
                config.interpreter = config.venv_path / "bin" / "python"
        else:
            console.print(
                f"   [yellow]![/yellow] No venv found — {type_label} will create one during dependency sync"
            )

    # Step 2: Dependency sync
    console.print("\n[bold]2.[/bold] Dependency sync")
    missing = compute_missing_deps(config.interpreter, config.include_marimo)
    if missing:
        console.print(
            f"   [yellow]→[/yellow] Adding missing deps: [cyan]{', '.join(missing)}[/cyan]"
        )
        add_dev_deps(config, missing)
        console.print(f"   [green]✓[/green] Dependencies synced")
    else:
        console.print("   [green]✓[/green] All notebook dependencies already present")

    # Step 3: Kernel install
    console.print("\n[bold]3.[/bold] Kernel installation")
    kernelspec_dir = install_kernel(config)
    console.print(
        f"   [green]✓[/green] Kernel [cyan]{config.kernel_name}[/cyan] installed"
    )

    # Step 4: Kernelspec patch
    console.print("\n[bold]4.[/bold] Kernelspec patch")
    patch_kernelspec(kernelspec_dir, config)
    console.print(
        f"   [green]✓[/green] VIRTUAL_ENV set in [dim]{kernelspec_dir / 'kernel.json'}[/dim]"
    )

    # Step 5: marimo readiness
    if config.include_marimo:
        console.print("\n[bold]5.[/bold] marimo readiness")
        console.print("   [green]✓[/green] marimo is available as a dev dependency")
    else:
        console.print("\n[bold]5.[/bold] marimo [dim](skipped — --no-marimo)[/dim]")

    # Success panel with next steps
    next_steps = Text()
    next_steps.append("Next steps\n\n", style="bold green")
    next_steps.append("VS Code: ", style="bold")
    next_steps.append(f'Open an .ipynb → select kernel "{config.display_name}"\n')
    next_steps.append("         ", style="bold")
    next_steps.append(
        "If missing, install the Jupyter extension (ms-toolsai.jupyter)\n\n"
    )
    next_steps.append("Jupyter: ", style="bold")
    next_steps.append(f"{_jupyter_launch_hint(config)}\n\n")
    if config.include_marimo:
        next_steps.append("marimo:  ", style="bold")
        next_steps.append(_marimo_launch_hint(config))

    console.print()
    console.print(Panel(next_steps, border_style="green"))

    console.print(f"\n[bold]Kernel name:[/bold] [cyan]{config.kernel_name}[/cyan]")


def run_list() -> None:
    """List all installed Jupyter kernels in a table."""
    kernels = discover_kernels()
    if not kernels:
        console.print("[yellow]No Jupyter kernels found.[/yellow]")
        return

    table = Table(title="🌮 Installed Jupyter Kernels", border_style="magenta")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Display Name", style="white")
    table.add_column("Interpreter", style="dim")
    table.add_column("VIRTUAL_ENV", style="dim")

    for k in kernels:
        table.add_row(
            k["name"],
            k["display_name"],
            k["interpreter"],
            k["virtual_env"] or "—",
        )

    console.print(table)


def run_info(config: TacoConfig) -> None:
    """Show detailed info about the project's kernel."""
    kernelspec_dir = _get_kernelspec_dir(config)
    data = read_kernel_info(kernelspec_dir)

    console.print(
        Panel(
            f"[bold magenta]🌮 Kernel info:[/bold magenta] [cyan]{config.kernel_name}[/cyan]",
            border_style="magenta",
        )
    )

    if data is None:
        # Check user-level too
        for base in get_all_kernel_dirs():
            alt = base / config.kernel_name
            data = read_kernel_info(alt)
            if data is not None:
                kernelspec_dir = alt
                break

    if data is None:
        console.print(
            f"\n[yellow]Kernel [cyan]{config.kernel_name}[/cyan] is not installed.[/yellow]"
        )
        console.print("Run [bold]taco[/bold] to create it.")
        return

    argv = data.get("argv", [])
    env = data.get("env", {})

    console.print(f"\n[bold]Location:[/bold]     {kernelspec_dir}")
    console.print(f"[bold]Display name:[/bold] {data.get('display_name', '—')}")
    console.print(f"[bold]Language:[/bold]     {data.get('language', '—')}")
    console.print(f"[bold]Interpreter:[/bold]  {argv[0] if argv else '—'}")
    console.print(f"[bold]Command:[/bold]      {' '.join(argv)}")
    if env.get("VIRTUAL_ENV"):
        console.print(f"[bold]VIRTUAL_ENV:[/bold]  {env['VIRTUAL_ENV']}")

    # Health checks
    console.print("\n[bold]Health checks:[/bold]")
    interpreter = Path(argv[0]) if argv else None
    if interpreter and interpreter.exists():
        console.print(f"  [green]✓[/green] Interpreter exists")
    else:
        console.print(
            f"  [red]✗[/red] Interpreter not found: {argv[0] if argv else 'none'}"
        )

    venv = env.get("VIRTUAL_ENV")
    if venv and Path(venv).exists():
        console.print(f"  [green]✓[/green] VIRTUAL_ENV exists")
    elif venv:
        console.print(f"  [red]✗[/red] VIRTUAL_ENV path missing: {venv}")
    else:
        console.print(f"  [yellow]![/yellow] No VIRTUAL_ENV set")


def run_remove(config: TacoConfig) -> None:
    """Remove the kernel for the current project."""
    console.print(f"[bold]Removing kernel:[/bold] [cyan]{config.kernel_name}[/cyan]\n")

    removed = remove_project_kernel(config)

    # Also check user-level locations
    if not config.dry_run:
        removed = remove_kernel(config.kernel_name) or removed

    if not removed:
        console.print(
            f"[yellow]Kernel [cyan]{config.kernel_name}[/cyan] not found — nothing to remove.[/yellow]"
        )
    else:
        console.print(
            f"\n[green]Done.[/green] Kernel [cyan]{config.kernel_name}[/cyan] removed."
        )


def run_clean(dry_run: bool = False) -> None:
    """Find and remove kernels whose interpreters no longer exist."""
    kernels = discover_kernels()
    stale: list[dict] = []

    for k in kernels:
        interpreter = Path(k["interpreter"])
        if not interpreter.exists():
            stale.append(k)

    if not stale:
        console.print(
            "[green]All kernels are healthy — no stale kernels found.[/green]"
        )
        return

    console.print(f"[bold]Found {len(stale)} stale kernel(s):[/bold]\n")
    for k in stale:
        console.print(
            f"  [red]✗[/red] [cyan]{k['name']}[/cyan] — interpreter missing: [dim]{k['interpreter']}[/dim]"
        )

    console.print()
    for k in stale:
        kernel_dir = Path(k["path"])
        if dry_run:
            console.print(f"  [dim]Would remove:[/dim] {kernel_dir}")
        else:
            shutil.rmtree(kernel_dir)
            console.print(f"  [green]✓[/green] Removed [cyan]{k['name']}[/cyan]")

    if not dry_run:
        console.print(f"\n[green]Done.[/green] Removed {len(stale)} stale kernel(s).")
