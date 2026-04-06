<p align="center">
  <img src="assets/taco.jpg" alt="taco mascot" width="350" />
</p>

# taco

Notebook bootstrapper — register per-project Jupyter kernels in one command.

Works with **uv**, **poetry**, and **plain pip/venv** projects.

## The problem

Python projects use isolated virtual environments, but notebooks don't play nicely with them out of the box:

- **Jupyter** doesn't automatically see your project's venv or its installed packages.
- **Cursor / VS Code** need a named kernel registered on your system before the kernel picker shows it.
- **marimo** works directly from the project environment, but you still need to remember to install it.

You end up running a sequence of dependency installs, `python -m ipykernel install`, and manual `kernel.json` edits every time you start a new project. `taco` does all of that in a single command.

## What it does

Running `taco` inside any Python project will:

1. **Detect your project** — finds the nearest `pyproject.toml`, `setup.py`, or `requirements.txt` and auto-detects whether you're using uv, poetry, or pip.
2. **Sync notebook dependencies** — adds `ipykernel` and `marimo` using the right tool for your project (`uv add --dev`, `poetry add --group dev`, or `pip install`).
3. **Register a Jupyter kernel** — installs a per-project kernelspec named after your project folder (e.g., `my-project`) with display name `Python (my-project)`.
4. **Patch the kernelspec** — sets `VIRTUAL_ENV` in `kernel.json` so notebook frontends launched outside the venv still resolve packages correctly.
5. **Print next steps** — copy-ready commands tailored to your project type for Cursor, Jupyter Lab, and marimo.

If the kernel already exists, it's replaced in place — safe to rerun after changing environments.

## Supported project types

| Project type | Detected by | Dep install command |
|-------------|-------------|-------------------|
| **uv** | `uv.lock` or `[tool.uv]` in pyproject.toml | `uv add --dev` |
| **poetry** | `poetry.lock` or `[tool.poetry]` in pyproject.toml | `poetry add --group dev` |
| **pip/venv** | `requirements.txt`, `setup.py`, or fallback | `pip install` (into the venv) |

taco auto-detects the project type — no configuration needed. It also finds your virtualenv automatically (`.venv`, `venv`, or poetry's external venv location).

## Installation

### With uv (recommended)

```bash
uv tool install taco
```

Then run `taco` from any project directory.

### With pipx

```bash
pipx install taco
```

### With pip

```bash
pip install taco
```

### From source

```bash
uv tool install /path/to/taco
# or
pipx install /path/to/taco
```

## Commands

### `taco` / `taco setup`

Set up Jupyter kernels for the current project. This is the default command — running `taco` with no subcommand does the same thing as `taco setup`.

```
taco setup [--project PATH] [--name TEXT] [--display-name TEXT] [--no-marimo] [--dry-run]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--project PATH` | Auto-detect (nearest project root) | Path to the project root |
| `--name TEXT` | Project folder name, sanitized | Kernel name slug (must match `[a-zA-Z0-9._-]+`) |
| `--display-name TEXT` | `Python (<project>)` | Human-readable kernel display name |
| `--no-marimo` | `False` | Skip installing marimo and omit marimo guidance |
| `--dry-run` | `False` | Preview all actions without making changes |

### `taco remove`

Remove the Jupyter kernel for a project. Checks both the project-local venv and user-level kernel directories.

```
taco remove [--project PATH] [--name TEXT] [--dry-run]
```

### `taco list`

List all installed Jupyter kernels in a table showing name, display name, interpreter path, and VIRTUAL_ENV.

```
taco list
```

### `taco info`

Show detailed info and health checks for a project's kernel — whether the interpreter exists, whether the VIRTUAL_ENV path is valid, the full command used to launch the kernel, etc.

```
taco info [--project PATH] [--name TEXT]
```

### `taco clean`

Find and remove stale kernels whose Python interpreters no longer exist (e.g., from deleted venvs or old projects).

```
taco clean [--dry-run]
```

### Examples

```bash
# Basic — auto-detect everything (works in uv, poetry, or pip projects)
taco

# Preview what would happen
taco --dry-run

# Custom kernel name
taco setup --name ml-env --display-name "ML Environment"

# Skip marimo
taco setup --no-marimo

# Target a specific project
taco setup --project ~/projects/my-api

# See all kernels on your system
taco list

# Check health of current project's kernel
taco info

# Delete the kernel for the current project
taco remove

# Clean up stale kernels from deleted projects
taco clean

# Preview what clean would remove
taco clean --dry-run
```

## Using the kernel

### Cursor / VS Code

1. Make sure the [Jupyter extension](https://marketplace.visualstudio.com/items?itemName=ms-toolsai.jupyter) is installed.
2. Open or create an `.ipynb` file.
3. Click the kernel picker in the top right and select your project kernel (e.g., `Python (my-project)`).

### Jupyter Lab

taco doesn't install Jupyter Lab itself to keep your project lean. Launch it with:

```bash
# uv projects
uv run --with jupyter jupyter lab

# poetry projects
poetry run jupyter lab

# pip/venv projects
jupyter lab
```

Your project kernel will appear in the launcher and kernel picker.

### marimo

marimo runs directly from the project environment — no kernel needed:

```bash
# uv projects
uv run marimo edit notebook.py

# poetry projects
poetry run marimo edit notebook.py

# pip/venv projects
marimo edit notebook.py
```

All packages in your project's dependencies are available.

## How it works

taco detects your project type and runs the equivalent of:

```bash
# 1. Add missing deps (adapts to your package manager)
uv add --dev ipykernel marimo          # uv
poetry add --group dev ipykernel marimo # poetry
pip install ipykernel marimo            # pip/venv

# 2. Register the kernel inside the project venv
.venv/bin/python -m ipykernel install --prefix .venv --name <slug> --display-name "<display>"

# 3. Patch kernel.json to include VIRTUAL_ENV
# This ensures frontends launched outside the venv resolve packages correctly
```

The kernelspec is installed per-project inside the venv:

```
<project>/.venv/share/jupyter/kernels/<name>/
```

This keeps kernels scoped to each project — no global pollution. Jupyter and Cursor discover them automatically when running from the project's environment.

The patched `kernel.json` looks like:

```json
{
 "argv": ["/path/to/project/.venv/bin/python", "-m", "ipykernel_launcher", "-f", "{connection_file}"],
 "display_name": "Python (my-project)",
 "language": "python",
 "env": {
  "VIRTUAL_ENV": "/path/to/project/.venv"
 }
}
```

## Requirements

- Python >= 3.10.
- One of: [uv](https://docs.astral.sh/uv/), [poetry](https://python-poetry.org/), or pip (comes with Python).
- The target directory must be a Python project (has a `pyproject.toml`, `setup.py`, `setup.cfg`, or `requirements.txt`).

## Development

```bash
git clone https://github.com/Luke-Pitstick/taco.git
cd taco
uv sync

# Run tests
uv run pytest

# Run integration tests (creates real temp uv projects)
uv run pytest -m integration
```
