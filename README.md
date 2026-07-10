<p align="center">
  <img src="assets/taco.jpg" alt="Taco mascot" width="320" />
</p>

# Taco

Taco creates named, discoverable Jupyter kernels for Python environments. It resolves the
interpreter selected by uv, Poetry, Conda, a standard virtual environment, or your shell; registers
a user-visible kernelspec; and verifies the kernel before reporting success.

Taco works with:

- uv projects and workspace members;
- Poetry projects;
- active Anaconda, Miniconda, Conda, and Mamba environments;
- `venv`, `virtualenv`, and tools that expose `VIRTUAL_ENV` or a project-local `.venv`;
- plain Python installations found on `PATH`.

## Project status

Taco is beta software. The command-line interface and kernelspec metadata are stable enough for
regular use, but the package has not yet been published under a unique Python distribution name.

> [!WARNING]
> The `taco` project currently on PyPI is unrelated software. Do not run `pip install taco`,
> `pipx install taco`, or `uv tool install taco`. Install Taco from this repository until an
> official distribution is published.

## Install Taco

The recommended installation is an isolated uv tool:

```bash
uv tool install git+https://github.com/Luke-Pitstick/taco.git
```

`pipx` can provide the same isolation:

```bash
pipx install git+https://github.com/Luke-Pitstick/taco.git
```

You can also install Taco into the Python environment you are already using:

```bash
# venv, virtualenv, Anaconda, Miniconda, Conda, or Mamba
python -m pip install git+https://github.com/Luke-Pitstick/taco.git

# Base Python, when user installs are appropriate
python -m pip install --user git+https://github.com/Luke-Pitstick/taco.git

# Poetry project dependency
poetry add "git+https://github.com/Luke-Pitstick/taco.git"
```

Installing Taco as an isolated tool is usually preferable: Taco can still target the active project
environment without becoming one of that project's dependencies.

## Quick start

Activate or prepare the environment you want the notebook to use, then run Taco from the project:

```bash
cd ~/projects/forecasting
taco setup
```

Examples by environment manager:

```bash
# uv (uv.lock or [tool.uv] identifies the project)
uv sync
taco setup

# Poetry
poetry install
taco setup

# venv / virtualenv
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
taco setup

# Anaconda / Miniconda / Conda / Mamba
conda activate forecasting
taco setup

# Plain Python from PATH
taco setup --project ~/projects/forecasting
```

Successful setup ends with output similar to:

```text
SETUP  Taco 0.3.0
Project      /Users/me/projects/forecasting
Environment  /Users/me/projects/forecasting/.venv
Kernel       forecasting

OK    Effective venv environment resolved
OK    ipykernel runtime prepared
OK    Kernel registered at /Users/me/Library/Jupyter/kernels/forecasting
OK    Kernel runtime verified

Ready  Python (forecasting) is available in Jupyter and VS Code.
```

Open a notebook and select `Python (forecasting)` from the kernel picker.

## How Taco chooses an environment

Taco uses the first matching strategy:

1. A uv project identified by `uv.lock`, `[tool.uv]`, a uv workspace, or
   `UV_PROJECT_ENVIRONMENT`.
2. A Poetry project identified by `poetry.lock` or `[tool.poetry]`.
3. The active Conda-family environment from `CONDA_PREFIX`.
4. The active standard virtual environment from `VIRTUAL_ENV`.
5. A project-local `.venv`.
6. `python` or `python3` from `PATH`.

An explicit `--project` may point to any existing directory; a `pyproject.toml` is not required.
Without `--project`, Taco searches upward for common Python project markers and otherwise uses the
current directory.

Because a bare PEP 621 `pyproject.toml` does not identify its package manager, create `uv.lock` with
`uv sync`/`uv lock` or add `[tool.uv]` before using Taco on a brand-new uv project. Poetry projects
are identified by their Poetry table or lockfile.

## What `taco setup` changes

Taco is explicit about its side effects:

1. Resolves the selected environment's real `sys.executable` and `sys.prefix`.
2. Ensures `ipykernel` is available.
   - uv uses an ephemeral `uv run --with ipykernel` overlay and does not edit project dependencies.
   - Other environments keep using their resolved interpreter. If `ipykernel` is missing, Taco runs
     that interpreter's `pip install ipykernel` (`--user` for plain base Python).
3. Writes a kernelspec to Jupyter's per-user data directory.
4. Replaces the temporary command with a durable launcher.
5. Adds Taco ownership metadata, including the project, environment, interpreter, and strategy.
6. Verifies Jupyter discovery and imports `ipykernel` through the final runtime.

For Poetry and non-uv environments, installing a missing `ipykernel` changes the selected Python
environment but does not edit `pyproject.toml`, `poetry.lock`, `requirements.txt`, or Conda YAML
files. Add `ipykernel` through your manager first if you want it recorded as a declared dependency.

Preview the plan without creating an environment, installing packages, or writing a kernelspec:

```bash
taco setup --dry-run
```

## Why the kernel stays usable

uv kernels retain uv as the source of truth:

```bash
/absolute/path/to/uv run \
  --project /absolute/path/to/project \
  --with ipykernel \
  python -m ipykernel_launcher -f '{connection_file}'
```

This preserves uv workspace resolution, custom `UV_PROJECT_ENVIRONMENT` locations, and ephemeral
`ipykernel` injection.

Poetry, Conda, venv, and plain-Python kernels use the exact interpreter Taco resolved:

```bash
/absolute/path/to/environment/bin/python \
  -m ipykernel_launcher -f '{connection_file}'
```

The direct launcher does not depend on shell activation, so Jupyter and VS Code can start it from a
GUI or another terminal. Moving or deleting that environment makes the kernel stale; rerun
`taco setup` after recreating it.

## Commands

Run `taco` or `taco --help` for the command overview. Setup is explicit; invoking `taco` with no
subcommand never changes a project.

### `taco setup`

Create or refresh a project kernel and verify its runtime.

```text
taco setup [--project DIRECTORY] [--name NAME] [--display-name TEXT]
           [--dry-run] [--force]
```

Examples:

```bash
# Current project or working directory
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

Kernel names may contain only ASCII letters, numbers, `.`, `_`, and `-`. Taco refuses to replace a
foreign kernel or another project's same-named kernel. Choose a unique `--name`; use `--force` only
when intentionally replacing the user-level spec at that exact path.

### `taco list`

List Taco-managed kernels and their static health state:

```bash
taco list
taco list --all
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

Foreign kernels and Taco kernels owned by other projects are never removed. Removing an absent
kernel is an idempotent success.

### `taco clean`

Find Taco-owned kernels whose project or launcher no longer exists:

```bash
taco clean --dry-run
taco clean
taco clean --yes
```

`clean` ignores kernels that do not carry valid Taco ownership metadata.

### Version and completion

```bash
taco --version
taco --show-completion
taco --install-completion
```

## Environment recipes

### uv workspaces and custom environments

Target a workspace member directly:

```bash
taco setup --project ~/work/acme/packages/analytics
```

Both absolute and workspace-relative uv environment settings are supported:

```bash
UV_PROJECT_ENVIRONMENT=.venv-notebooks taco setup
```

The resolved absolute location is persisted so a GUI launch inherits the same uv environment.

### Poetry

Taco uses `poetry run python` to resolve Poetry's actual environment, then records its absolute
interpreter:

```bash
poetry install
taco setup
```

The Poetry shell does not need to remain active after registration.

### Anaconda, Miniconda, Conda, and Mamba

Activate the desired environment before setup:

```bash
conda activate forecasting
taco setup --project ~/projects/forecasting
```

Taco follows `CONDA_PREFIX`, so this works for named environments and Conda's base environment.
Mamba and Micromamba environments work when they expose the same activation variables.

### venv, virtualenv, Hatch, PDM, and similar tools

Activate the environment or place it at `<project>/.venv`:

```bash
source .venv/bin/activate
taco setup
```

Any tool that provides a conventional interpreter through `VIRTUAL_ENV` or `.venv` can use the
direct-interpreter path without dedicated Taco integration.

### Plain or base Python

With no manager or virtual environment detected, Taco resolves `python`/`python3` from `PATH`:

```bash
python -m pip install --user ipykernel  # optional; Taco attempts this if needed
taco setup --project ~/notebooks
```

Some OS-managed Python installations reject pip writes under PEP 668. In that case, install
`ipykernel` using the operating system's package manager or create a venv rather than overriding the
protection.

## Notebook frontends

### VS Code and Cursor

Install the Jupyter extension, open an `.ipynb` file, and select Taco's display name. The editor
does not need to be launched from the project environment.

### JupyterLab

Taco does not install JupyterLab into the project. Launch your preferred Jupyter installation; the
Taco kernel is registered in the per-user Jupyter data directory and appears in its kernel picker.

For an ephemeral uv-hosted JupyterLab:

```bash
uv run --with jupyter jupyter lab
```

### marimo

marimo does not use Jupyter kernels. Run it directly through your chosen environment manager.

## Moving or deleting projects and environments

A kernelspec records absolute project, environment, and interpreter paths. After moving a project
or recreating its environment, refresh the spec:

```bash
cd /new/path/to/project
taco setup --force
```

Remove stale specs after deleting projects or environments:

```bash
taco clean --dry-run
taco clean --yes
```

## Upgrade and uninstall

Reinstall from Git to upgrade an isolated uv installation:

```bash
uv tool install --force git+https://github.com/Luke-Pitstick/taco.git
```

Remove project kernels before uninstalling Taco:

```bash
cd ~/projects/forecasting
taco remove
uv tool uninstall taco
```

## Support matrix

| Capability | Status |
|---|---|
| uv projects and workspace members | Integration tested |
| `UV_PROJECT_ENVIRONMENT` | Integration tested |
| Standard `venv` / `virtualenv` | Integration tested |
| Poetry | Unit tested; uses Poetry's reported interpreter |
| Anaconda / Miniconda / Conda / Mamba | Unit tested through `CONDA_PREFIX` |
| Plain/base Python | Unit tested through `PATH` |
| Other `.venv` / `VIRTUAL_ENV` managers | Supported through the generic interpreter path |
| External Jupyter discovery | Integration tested |
| Live kernel startup and code execution | Integration tested |
| macOS | Actively tested |
| Linux | Uses Python and Jupyter platform APIs; testing welcome |
| Windows | Uses Python and Jupyter platform APIs; testing welcome |

## Development

```bash
git clone https://github.com/Luke-Pitstick/taco.git
cd taco
uv sync

# Fast unit and CLI tests
uv run pytest -m "not integration"

# Full suite, including real uv/venv projects and live kernels
uv run pytest

# Lint and formatting
uv run ruff check src tests
uv run ruff format --check src tests
```

The integration suite isolates `JUPYTER_DATA_DIR`, starts real kernels, executes notebook code, and
verifies cleanup behavior without writing to the developer's normal Jupyter registry.

## Troubleshooting

### Taco selected the wrong environment

Run `taco setup --dry-run` and inspect the reported strategy, environment, and interpreter. Activate
the desired Conda/venv environment first. For uv, ensure the project has `uv.lock`, `[tool.uv]`, a uv
workspace declaration, or `UV_PROJECT_ENVIRONMENT`.

### `uv is required` or `poetry is required`

Taco found manager-specific project metadata but could not find that manager on `PATH`. Install the
manager or remove stale metadata if the project no longer uses it.

### `ipykernel` could not be installed

Install it with the selected environment manager, then rerun Taco:

```bash
uv add --dev ipykernel
poetry add --group dev ipykernel
conda install ipykernel
python -m pip install ipykernel
```

### The kernel name is already used

Jupyter names are global per user. Pass a unique `--name`, or use `--force` only when the existing
user-level spec is the one you intend to replace.

### The kernel is missing or unhealthy

```bash
taco info --project /path/to/project
```

The command identifies whether discovery, the launcher, project directory, environment, or runtime
check failed. Running `taco setup` again safely refreshes a kernel already owned by the same project.

### Debug the exact launch command

```bash
taco info --json
```

## Contributing

Bug reports and focused pull requests are welcome at
[github.com/Luke-Pitstick/taco](https://github.com/Luke-Pitstick/taco). For kernel bugs, include
`taco --version`, `taco info --json`, the environment manager and version, and how the environment
was activated or configured.
