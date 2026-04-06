"""CLI entrypoint for taco."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from taco.core import (
    TacoConfig,
    default_display_name,
    find_project_root,
    run_setup,
    sanitize_kernel_name,
)

app = typer.Typer(
    name="taco",
    help="uv notebook bootstrapper — register per-project Jupyter kernels in one command.",
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def main(
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
    """Set up Jupyter kernels for the current uv project."""
    project_root = find_project_root(project)
    project_name = project_root.name

    kernel_name = name if name else sanitize_kernel_name(project_name)
    kernel_display = display_name if display_name else default_display_name(project_name)

    config = TacoConfig(
        project_root=project_root,
        kernel_name=kernel_name,
        display_name=kernel_display,
        include_marimo=not no_marimo,
        dry_run=dry_run,
    )

    run_setup(config)
