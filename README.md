<p align="center">
  <img src="assets/taco.jpg" alt="Taco mascot" width="320" />
</p>

# Taco

Taco creates named, discoverable Jupyter kernels backed by uv projects. It asks uv for the effective project environment, registers a user-visible kernelspec, and verifies that the kernel runtime works before reporting success.

Taco handles standalone projects, workspace members, and custom `UV_PROJECT_ENVIRONMENT` locations without assuming that every interpreter lives at `<project>/.venv/bin/python`.

## Project status

Taco is beta software and currently supports **uv projects only**. The command-line interface and kernelspec metadata are stable enough for regular use, but the package has not yet been published under a unique Python distribution name.

> [!WARNING]
> The `taco` project currently on PyPI is unrelated software. Do not run `pip install taco`, `pipx install taco`, or `uv tool install taco`. Install Taco from this repository until an official distribution is published.

## Quick start

Install Taco as an isolated uv tool:

```bash
uv tool install git+https://github.com/Luke-Pitstick/taco.git
```

Then create a kernel from any uv project:

```bash
cd ~/projects/forecasting
taco setup
```

Successful setup ends with output similar to:

```text
SETUP  Taco 0.3.0
Project      /Users/me/projects/forecasting
Environment  /Users/me/projects/forecasting/.venv
Kernel       forecasting

OK    Effective uv environment resolved
OK    ipykernel runtime prepared
OK    Kernel registered at /Users/me/Library/Jupyter/kernels/forecasting
OK    Kernel runtime verified

Ready  Python (forecasting) is available in Jupyter and VS Code.
```

Open a notebook and select `Python (forecasting)` from the kernel picker.

## What `taco setup` changes

Taco is intentionally explicit about its side effects:

1. Runs uv against the selected project to resolve its real environment. uv may create or sync the project environment and lockfile as it normally would.
2. Prepares `ipykernel` through an ephemeral `uv run --with ipykernel` overlay. Taco does **not** add `ipykernel`, JupyterLab, or marimo to `pyproject.toml`.
3. Writes a kernelspec to Jupyter's per-user data directory.
4. Replaces the temporary interpreter command with a durable uv launcher tied to the project path.
5. Adds Taco ownership metadata and the resolved uv environment to `kernel.json`.
6. Verifies Jupyter discovery and imports `ipykernel` through the final uv launch path.

Preview the complete plan without creating an environment, lockfile, or kernelspec:

```bash
taco setup --dry-run
```

## Why the kernel stays usable

A Taco-managed uv kernel launches through a command shaped like this:

```bash
/absolute/path/to/uv run \
  --project /absolute/path/to/project \
  --with ipykernel \
  python -m ipykernel_launcher -f '{connection_file}'
```

This design has three useful properties:

- uv remains the source of truth for workspace and environment selection;
- `ipykernel` does not need to remain in the project's default dependency groups;
- Jupyter and VS Code can discover the kernel even when they were launched outside the project environment.

When `UV_PROJECT_ENVIRONMENT` is active during setup, Taco resolves it to an absolute path and stores it in the kernelspec so GUI applications inherit the same environment choice later.

## Commands

Run `taco` or `taco --help` for the command overview. Setup is explicit; invoking `taco` with no subcommand never changes a project.

### `taco setup`

Create or refresh a project kernel and verify its runtime.

```text
taco setup [--project DIRECTORY] [--name NAME] [--display-name TEXT]
           [--dry-run] [--force]
```

Examples:

```bash
# Current project
taco setup

# A project elsewhere on disk
taco setup --project ~/projects/forecasting

# A custom kernelspec and display name
taco setup \
  --name forecasting-gpu \
  --display-name "Python (forecasting · GPU)"

# Preview only
taco setup --dry-run
```

Kernel names must contain only ASCII letters, numbers, `.`, `_`, and `-`. Taco refuses to replace a foreign kernel or another project's same-named kernel. Choose a unique `--name`; use `--force` only when intentionally replacing the user-level spec at that exact path.

### `taco list`

List Taco-managed kernels and their static health state:

```bash
taco list
```

Include every Jupyter kernelspec visible to the current environment:

```bash
taco list --all
```

Produce deterministic JSON for scripts:

```bash
taco list --json
```

### `taco info`

Inspect one project's kernel and run discovery, launcher, project, environment, and runtime checks:

```bash
taco info
taco info --project ~/projects/forecasting
taco info --json
```

The command exits with status `1` when the kernel is missing or unhealthy.

### `taco remove`

Remove only the Taco-owned kernelspec associated with a project:

```bash
taco remove
taco remove --project ~/projects/forecasting
taco remove --dry-run
```

Foreign kernels and Taco kernels owned by other projects are never removed by this command. Removing an already-absent kernel is an idempotent success.

### `taco clean`

Find Taco-owned kernels whose project directory or uv launcher no longer exists:

```bash
# Inspect first
taco clean --dry-run

# Confirm interactively
taco clean

# Non-interactive cleanup
taco clean --yes
```

`clean` ignores kernels that do not carry Taco ownership metadata.

### Version and completion

```bash
taco --version
taco --show-completion
taco --install-completion
```

## uv recipes

### Workspace members

Target the member directory. Taco lets uv resolve the shared workspace environment:

```bash
taco setup --project ~/work/acme/packages/analytics
```

The kernelspec records the member as its project and the workspace environment as its effective environment.

### Custom project environments

Both absolute and workspace-relative uv environment settings are supported:

```bash
UV_PROJECT_ENVIRONMENT=.venv-notebooks taco setup
```

The resolved absolute location is persisted in the kernelspec for later launches.

### Projects with non-default dependency groups

Taco does not depend on the project's `dev` group. The runtime comes from `uv run --with ipykernel`, so a later `uv sync` that excludes `dev` does not invalidate the kernel.

### Two projects with the same directory name

Jupyter kernel names are user-global. Give at least one project a unique name:

```bash
cd ~/work/client-a/notebooks
taco setup --name client-a-notebooks

cd ~/work/client-b/notebooks
taco setup --name client-b-notebooks
```

Taco detects collisions before writing anything.

## Notebook frontends

### VS Code and Cursor

Install the Jupyter extension, open an `.ipynb` file, and select the display name passed to Taco. Because the kernelspec lives in Jupyter's user data directory, the editor does not need to be launched from the project venv.

### JupyterLab

Taco does not add JupyterLab to the project. Launch it ephemerally with uv:

```bash
uv run --with jupyter jupyter lab
```

The Taco kernel is user-discoverable and appears in the launcher and kernel picker.

### marimo

marimo does not use Jupyter kernels. Run it directly through uv when needed:

```bash
uv run --with marimo marimo edit notebook.py
```

## Moving or deleting projects

A kernelspec records the project's absolute path. After moving a project, replace the old same-named spec intentionally:

```bash
cd /new/path/to/project
taco setup --force
```

After deleting a project, remove the stale spec with:

```bash
taco clean --dry-run
taco clean --yes
```

## Upgrade and uninstall

Until Taco has an official distribution, reinstall from Git to upgrade:

```bash
uv tool install --force git+https://github.com/Luke-Pitstick/taco.git
```

Remove project kernels before uninstalling the tool:

```bash
cd ~/projects/forecasting
taco remove
uv tool uninstall taco
```

## Support matrix

| Capability | Status |
|---|---|
| Standalone uv projects | Integration tested |
| uv workspace members | Integration tested |
| `UV_PROJECT_ENVIRONMENT` | Integration tested |
| Custom/default dependency groups | Integration tested |
| External Jupyter discovery | Integration tested |
| Live kernel startup and code execution | Integration tested |
| macOS | Actively tested |
| Linux | Uses uv and Jupyter's platform APIs; testing welcome |
| Windows | Uses uv and Jupyter's platform APIs; testing welcome |
| Poetry / pip-only projects | Not supported |

## Development

```bash
git clone https://github.com/Luke-Pitstick/taco.git
cd taco
uv sync

# Fast unit and CLI tests
uv run pytest -m "not integration"

# Full suite, including real uv projects and live kernels
uv run pytest

# Lint
uv run ruff check src tests
uv run ruff format --check src tests
```

The integration suite isolates `JUPYTER_DATA_DIR`, starts real kernels, executes notebook code, and verifies cleanup behavior without writing to the developer's normal Jupyter registry.

## Troubleshooting

### `uv is required`

Install uv using the [official installation instructions](https://docs.astral.sh/uv/getting-started/installation/), then confirm `uv --version` works from the same shell.

### The kernel name is already used

Jupyter names are global per user. Pass a unique `--name`, or use `--force` only when the existing user-level spec is the one you intend to replace.

### The kernel is missing or unhealthy

Run:

```bash
taco info --project /path/to/project
```

The command identifies whether discovery, the uv launcher, the project directory, the environment, or the runtime check failed. Running `taco setup` again safely refreshes a kernel already owned by the same project.

### Debug the exact launch command

Use structured output to inspect the registered command and health checks:

```bash
taco info --json
```

## Contributing

Bug reports and focused pull requests are welcome at [github.com/Luke-Pitstick/taco](https://github.com/Luke-Pitstick/taco). For kernel bugs, include `taco --version`, `uv --version`, the relevant `taco info --json` output, and whether the project is a workspace member or uses `UV_PROJECT_ENVIRONMENT`.
