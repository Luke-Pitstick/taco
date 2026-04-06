<p align="center">
  <img src="assets/taco.svg" alt="taco mascot" width="160" />
</p>

# taco

uv notebook bootstrapper — register per-project Jupyter kernels in one command.

## The problem

When you use [uv](https://docs.astral.sh/uv/) to manage Python projects, each project gets its own isolated virtual environment. That's great for reproducibility, but it creates friction with notebooks:

- **Jupyter** doesn't automatically see your project's venv or its installed packages.
- **Cursor / VS Code** need a named kernel registered on your system before the kernel picker shows it.
- **marimo** works directly from the project environment, but you still need to remember to install it.

You end up running a sequence of `uv add`, `python -m ipykernel install`, and manual `kernel.json` edits every time you start a new project. `taco` does all of that in a single command.

## What it does

Running `taco` inside a uv project will:

1. **Detect your project** — finds the nearest `pyproject.toml` and resolves the `.venv` interpreter.
2. **Sync notebook dependencies** — adds `ipykernel` and `marimo` as dev dependencies if they're missing (via `uv add --dev`).
3. **Register a Jupyter kernel** — installs a user-level kernelspec named after your project folder (e.g., `my-project`) with display name `Python (my-project)`.
4. **Patch the kernelspec** — sets `VIRTUAL_ENV` in `kernel.json` so notebook frontends launched outside the venv still resolve packages correctly.
5. **Print next steps** — copy-ready commands for Cursor, Jupyter Lab, and marimo.

If the kernel already exists, it's replaced in place — safe to rerun after changing environments.

## Installation

### System-wide (recommended)

Install as a uv tool so `taco` is available in any project:

```bash
uv tool install taco
```

Then just run `taco` from any uv project directory.

### Per-project

Add it as a dev dependency:

```bash
uv add --dev taco
uv run taco
```

### From source

```bash
uv tool install /path/to/taco
```

## Usage

```
taco [--project PATH] [--name TEXT] [--display-name TEXT] [--no-marimo] [--dry-run]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--project PATH` | Auto-detect (nearest `pyproject.toml`) | Path to the uv project root |
| `--name TEXT` | Project folder name, sanitized | Kernel name slug (must match `[a-zA-Z0-9._-]+`) |
| `--display-name TEXT` | `Python (<project>)` | Human-readable kernel display name |
| `--no-marimo` | `False` | Skip installing marimo and omit marimo guidance |
| `--dry-run` | `False` | Preview all actions without making changes |

### Examples

```bash
# Basic — auto-detect everything
taco

# Preview what would happen
taco --dry-run

# Custom kernel name
taco --name ml-env --display-name "ML Environment"

# Skip marimo
taco --no-marimo

# Target a specific project
taco --project ~/projects/my-api
```

## Using the kernel

### Cursor / VS Code

1. Make sure the [Jupyter extension](https://marketplace.visualstudio.com/items?itemName=ms-toolsai.jupyter) is installed.
2. Open or create an `.ipynb` file.
3. Click the kernel picker in the top right and select your project kernel (e.g., `Python (my-project)`).

### Jupyter Lab

taco doesn't install Jupyter Lab itself to keep your project lean. Launch it as a one-off:

```bash
uv run --with jupyter jupyter lab
```

Your project kernel will appear in the launcher and kernel picker.

### marimo

marimo runs directly from the project environment — no kernel needed:

```bash
uv run marimo edit notebook.py
```

All packages in your project's dev and runtime dependencies are available.

## How it works

Under the hood, taco runs:

```bash
# 1. Add missing deps
uv add --dev ipykernel marimo

# 2. Register the kernel using the project's own interpreter
.venv/bin/python -m ipykernel install --user --name <slug> --display-name "<display>"

# 3. Patch kernel.json to include VIRTUAL_ENV
# This ensures frontends launched outside the venv resolve packages correctly
```

The kernelspec is installed to the standard user location:
- **macOS**: `~/Library/Jupyter/kernels/<name>/`
- **Linux**: `~/.local/share/jupyter/kernels/<name>/`

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

- [uv](https://docs.astral.sh/uv/) must be installed and available on `PATH`.
- Python >= 3.10.
- The target directory must be a uv project (has a `pyproject.toml`).

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
