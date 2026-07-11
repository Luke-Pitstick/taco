"""Production command-line interface for Taco."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import typer

from taco import __version__
from taco.core import (
    TacoConfig,
    TacoError,
    default_display_name,
    detect_project_type,
    find_project_root,
    find_stale_kernels,
    run_clean,
    run_info,
    run_list,
    run_remove,
    run_setup,
    sanitize_kernel_name,
    validate_kernel_name,
)

T = TypeVar("T")

app = typer.Typer(
    name="taco",
    help="Create and maintain discoverable Jupyter kernels for Python environments.",
    add_completion=True,
    rich_markup_mode="rich",
    pretty_exceptions_enable=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"taco {__version__}")
        raise typer.Exit()


def _project_callback(value: Path | None) -> Path | None:
    if value is None:
        return None
    if not value.exists():
        raise typer.BadParameter(f"Project directory does not exist: {value}")
    if not value.is_dir():
        raise typer.BadParameter(f"Project path is not a directory: {value}")
    return value.resolve()


def _name_callback(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return validate_kernel_name(value)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _call(operation: Callable[[], T]) -> T:
    """Render expected operational failures without a traceback."""
    try:
        return operation()
    except TacoError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt as exc:
        typer.echo("Interrupted.", err=True)
        raise typer.Exit(code=130) from exc


def _resolve_config(
    project: Path | None,
    name: str | None,
    display_name: str | None,
    *,
    dry_run: bool = False,
    force: bool = False,
) -> TacoConfig:
    project_root = find_project_root(project, explicit=project is not None)
    project_type = detect_project_type(project_root)
    kernel_name = name or sanitize_kernel_name(project_root.name)
    return TacoConfig(
        project_root=project_root,
        kernel_name=kernel_name,
        display_name=display_name or default_display_name(project_root.name),
        project_type=project_type,
        dry_run=dry_run,
        force=force,
    )


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the installed version and exit.",
    ),
) -> None:
    """Create and maintain discoverable Jupyter kernels for Python environments."""
    del version
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


@app.command()
def setup(
    project: Path | None = typer.Option(
        None,
        "--project",
        "-p",
        callback=_project_callback,
        help="Python project or working directory.",
        metavar="DIRECTORY",
    ),
    name: str | None = typer.Option(
        None,
        "--name",
        "-n",
        callback=_name_callback,
        help="Unique kernelspec name (default: project directory name).",
        metavar="NAME",
    ),
    display_name: str | None = typer.Option(
        None,
        "--display-name",
        help="Name shown in notebook kernel pickers.",
        metavar="TEXT",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Preview every action without changing files or environments.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Replace a conflicting user-level kernelspec at the same path.",
    ),
    no_marimo: bool = typer.Option(
        False,
        "--no-marimo",
        hidden=True,
    ),
) -> None:
    """Create or refresh a project kernel and verify its runtime."""
    del no_marimo  # Compatibility with Taco 0.2; marimo is no longer installed.
    _call(
        lambda: run_setup(
            _resolve_config(
                project,
                name,
                display_name,
                dry_run=dry_run,
                force=force,
            )
        )
    )


@app.command(name="list")
def list_kernels(
    all_kernels: bool = typer.Option(
        False,
        "--all",
        help="Include kernels not managed by Taco.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit one machine-readable JSON document.",
    ),
) -> None:
    """List Taco kernels and their static health status."""
    _call(lambda: run_list(managed_only=not all_kernels, json_output=json_output))


@app.command()
def info(
    project: Path | None = typer.Option(
        None,
        "--project",
        "-p",
        callback=_project_callback,
        help="Python project or working directory.",
        metavar="DIRECTORY",
    ),
    name: str | None = typer.Option(
        None,
        "--name",
        "-n",
        callback=_name_callback,
        help="Kernel name (default: project directory name).",
        metavar="NAME",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit one machine-readable JSON document.",
    ),
) -> None:
    """Run discovery, path, environment, and runtime health checks."""
    healthy = _call(
        lambda: run_info(
            _resolve_config(project, name, None),
            json_output=json_output,
        )
    )
    if not healthy:
        raise typer.Exit(code=1)


@app.command()
def remove(
    project: Path | None = typer.Option(
        None,
        "--project",
        "-p",
        callback=_project_callback,
        help="Python project or working directory.",
        metavar="DIRECTORY",
    ),
    name: str | None = typer.Option(
        None,
        "--name",
        "-n",
        callback=_name_callback,
        help="Kernel name (default: project directory name).",
        metavar="NAME",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Preview the exact Taco-owned kernelspec without deleting it.",
    ),
) -> None:
    """Remove only this project's Taco-owned kernelspec."""
    _call(lambda: run_remove(_resolve_config(project, name, None, dry_run=dry_run)))


@app.command()
def clean(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="List stale Taco kernels without deleting them.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Remove stale Taco kernels without prompting.",
    ),
) -> None:
    """Remove Taco kernels whose project or interpreter no longer exists."""
    stale = _call(find_stale_kernels)
    if not stale or dry_run:
        _call(lambda: run_clean(dry_run=dry_run, kernels=stale))
        return
    if not yes:
        typer.echo(f"Found {len(stale)} stale Taco kernel(s):")
        for record in stale:
            typer.echo(f"  {record['name']}  {record['path']}")
        if not sys.stdin.isatty():
            typer.echo(
                f"Error: {len(stale)} stale Taco kernel(s) found; rerun with --yes or --dry-run.",
                err=True,
            )
            raise typer.Exit(code=1)
        if not typer.confirm(f"Remove {len(stale)} stale Taco kernel(s)?", default=False):
            typer.echo("Cancelled — no changes made.")
            return
    _call(lambda: run_clean(kernels=stale))


def _flush_or_silence_broken_pipe() -> bool:
    """Flush normal output, silencing a downstream consumer that closed its pipe."""
    try:
        sys.stdout.flush()
        return True
    except BrokenPipeError:
        try:
            stdout_fd = sys.stdout.fileno()
            devnull_fd = os.open(os.devnull, os.O_WRONLY)
            try:
                os.dup2(devnull_fd, stdout_fd)
            finally:
                os.close(devnull_fd)
        except (AttributeError, OSError, ValueError):
            sys.stdout = open(os.devnull, "w")  # noqa: SIM115
        return False


def cli() -> None:
    """Console-script wrapper used by python -m taco and packaging entry points."""
    try:
        app()
    except SystemExit as exc:
        flushed = _flush_or_silence_broken_pipe()
        if flushed or exc.code not in (None, 0):
            raise
    except BrokenPipeError:
        _flush_or_silence_broken_pipe()
    else:
        _flush_or_silence_broken_pipe()


if __name__ == "__main__":
    cli()
