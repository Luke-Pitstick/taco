"""Core logic for taco — project detection, dependency management, kernel installation."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()


@dataclass
class TacoConfig:
    """Resolved configuration for a taco run."""

    project_root: Path
    kernel_name: str
    display_name: str
    include_marimo: bool = True
    dry_run: bool = False
    venv_path: Path = field(init=False)
    interpreter: Path = field(init=False)

    def __post_init__(self) -> None:
        self.venv_path = self.project_root / ".venv"
        self.interpreter = self.venv_path / "bin" / "python"


def find_project_root(start: Path | None = None) -> Path:
    """Walk up from *start* (default: cwd) to find the nearest pyproject.toml.

    Returns the directory containing it, or raises SystemExit.
    """
    current = (start or Path.cwd()).resolve()
    for directory in [current, *current.parents]:
        if (directory / "pyproject.toml").is_file():
            return directory
    raise SystemExit(
        "[red]Error:[/red] No pyproject.toml found. "
        "Run taco from inside a uv project."
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


def compute_missing_deps(
    interpreter: Path, include_marimo: bool
) -> list[str]:
    """Return the list of packages that need to be added as dev deps."""
    packages = ["ipykernel"]
    if include_marimo:
        packages.append("marimo")
    return [p for p in packages if not _is_package_importable(interpreter, p)]


def add_dev_deps(project_root: Path, packages: list[str], dry_run: bool) -> bool:
    """Run ``uv add --dev`` for the given packages. Returns True if anything was added."""
    if not packages:
        return False
    cmd = ["uv", "add", "--dev", "--project", str(project_root), *packages]
    if dry_run:
        console.print(f"  [dim]Would run:[/dim] {' '.join(cmd)}")
        return True
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(
            f"[red]Error:[/red] uv add failed:\n{result.stderr}"
        )
    return True


def install_kernel(config: TacoConfig) -> Path:
    """Install the ipykernel kernelspec and return the kernelspec directory."""
    cmd = [
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
    if config.dry_run:
        console.print(f"  [dim]Would run:[/dim] {' '.join(cmd)}")
        return _get_kernelspec_dir(config.kernel_name)

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(
            f"[red]Error:[/red] Kernel install failed:\n{result.stderr}"
        )
    return _get_kernelspec_dir(config.kernel_name)


def _get_kernelspec_dir(kernel_name: str) -> Path:
    """Return the expected user kernelspec directory for a given kernel name."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Jupyter" / "kernels"
    else:
        base = Path(os.environ.get("JUPYTER_DATA_DIR", Path.home() / ".local" / "share" / "jupyter")) / "kernels"
    return base / kernel_name


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


def run_setup(config: TacoConfig) -> None:
    """Execute the full taco setup workflow with rich output."""
    project_name = config.project_root.name

    # Title panel
    title = Text()
    title.append("🌮 taco", style="bold magenta")
    title.append(" — uv notebook bootstrapper\n\n")
    title.append("Project:     ", style="bold")
    title.append(f"{project_name}\n")
    title.append("Interpreter: ", style="bold")
    title.append(f"{config.interpreter}\n")
    title.append("Kernel:      ", style="bold")
    title.append(f"{config.kernel_name}")
    console.print(Panel(title, border_style="magenta"))

    # Step 1: Project detection
    console.print("\n[bold]1.[/bold] Project detection")
    if config.venv_path.exists() or config.dry_run:
        console.print(f"   [green]✓[/green] Found uv project at [cyan]{config.project_root}[/cyan]")
    else:
        console.print(f"   [yellow]![/yellow] No .venv found — uv will create one during dependency sync")

    # Step 2: Dependency sync
    console.print("\n[bold]2.[/bold] Dependency sync")
    missing = compute_missing_deps(config.interpreter, config.include_marimo)
    if missing:
        console.print(f"   [yellow]→[/yellow] Adding missing deps: [cyan]{', '.join(missing)}[/cyan]")
        add_dev_deps(config.project_root, missing, config.dry_run)
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
    console.print(f"   [green]✓[/green] VIRTUAL_ENV set in [dim]{kernelspec_dir / 'kernel.json'}[/dim]")

    # Step 5: marimo readiness
    if config.include_marimo:
        console.print("\n[bold]5.[/bold] marimo readiness")
        console.print("   [green]✓[/green] marimo is available as a dev dependency")
    else:
        console.print("\n[bold]5.[/bold] marimo [dim](skipped — --no-marimo)[/dim]")

    # Success panel with next steps
    next_steps = Text()
    next_steps.append("Next steps\n\n", style="bold green")
    next_steps.append("Cursor:  ", style="bold")
    next_steps.append(f"Open an .ipynb → select kernel \"{config.display_name}\"\n")
    next_steps.append("         ", style="bold")
    next_steps.append("If missing, install the Jupyter extension (ms-toolsai.jupyter)\n\n")
    next_steps.append("Jupyter: ", style="bold")
    next_steps.append("uv run --with jupyter jupyter lab\n\n")
    if config.include_marimo:
        next_steps.append("marimo:  ", style="bold")
        next_steps.append("uv run marimo edit notebook.py")

    console.print()
    console.print(Panel(next_steps, border_style="green"))
