"""CLI entrypoint for taco."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from taco.core import (
    TacoConfig,
    default_display_name,
    find_project_root,
    run_clean,
    run_info,
    run_list,
    run_remove,
    run_setup,
    sanitize_kernel_name,
)

app = typer.Typer(
    name="taco",
    help="🌮 uv notebook bootstrapper — register per-project Jupyter kernels in one command.",
    add_completion=False,
    invoke_without_command=True,
)


def _resolve_config(
    project: Path | None,
    name: str | None,
    display_name: str | None,
    no_marimo: bool = False,
    dry_run: bool = False,
) -> TacoConfig:
    """Build a TacoConfig from CLI args."""
    project_root = find_project_root(project)
    project_name = project_root.name
    kernel_name = name if name else sanitize_kernel_name(project_name)
    kernel_display = display_name if display_name else default_display_name(project_name)
    return TacoConfig(
        project_root=project_root,
        kernel_name=kernel_name,
        display_name=kernel_display,
        include_marimo=not no_marimo,
        dry_run=dry_run,
    )


@app.callback()
def main(ctx: typer.Context) -> None:
    """🌮 uv notebook bootstrapper."""
    if ctx.invoked_subcommand is None:
        # Default to setup when no subcommand is given
        ctx.invoke(setup)


@app.command()
def setup(
    project: Optional[Path] = typer.Option(
        None,
        help="Path to the uv project root (default: auto-detect).",
    ),
    name: Optional[str] = typer.Option(
        None,
        help="Kernel name slug (default: project folder name).",
    ),
    display_name: Optional[str] = typer.Option(
        None,
        "--display-name",
        help="Kernel display name (default: 'Python (<project>)').",
    ),
    no_marimo: bool = typer.Option(
        False,
        "--no-marimo",
        help="Skip marimo dependency and guidance.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would happen without making changes.",
    ),
) -> None:
    """Set up Jupyter kernels for the current uv project (default command)."""
    config = _resolve_config(project, name, display_name, no_marimo, dry_run)
    run_setup(config)


@app.command()
def remove(
    project: Optional[Path] = typer.Option(
        None,
        help="Path to the uv project root (default: auto-detect).",
    ),
    name: Optional[str] = typer.Option(
        None,
        help="Kernel name to remove (default: project folder name).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be removed without deleting.",
    ),
) -> None:
    """Remove the Jupyter kernel for a project."""
    config = _resolve_config(project, name, None, dry_run=dry_run)
    run_remove(config)


@app.command(name="list")
def list_kernels() -> None:
    """List all installed Jupyter kernels."""
    run_list()


@app.command()
def info(
    project: Optional[Path] = typer.Option(
        None,
        help="Path to the uv project root (default: auto-detect).",
    ),
    name: Optional[str] = typer.Option(
        None,
        help="Kernel name to inspect (default: project folder name).",
    ),
) -> None:
    """Show detailed info and health checks for a project's kernel."""
    config = _resolve_config(project, name, None)
    run_info(config)


@app.command()
def clean(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show stale kernels without removing them.",
    ),
) -> None:
    """Find and remove stale kernels whose interpreters no longer exist."""
    run_clean(dry_run)
