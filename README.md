<p align="center">
  <img src="assets/taco.jpg" alt="Taco mascot" width="320" />
</p>

<h1 align="center">Taco</h1>

<p align="center">
  <strong>Durable Jupyter kernels for the Python environment you actually selected.</strong><br />
  Resolve it, register it, verify it, and keep it manageable from one CLI.
</p>

<p align="center">
  <img alt="Project status: beta" src="https://img.shields.io/badge/status-beta-f59e0b" />
  <img alt="Python 3.10 or newer" src="https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white" />
  <img alt="Install from Git" src="https://img.shields.io/badge/package-install%20from%20Git-6f42c1" />
</p>

<p align="center">
  <a href="#install-taco">Install</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#commands">Commands</a> ·
  <a href="#automation-and-exit-codes">Automation</a> ·
  <a href="#troubleshooting">Troubleshooting</a>
</p>

Taco creates named, discoverable Jupyter kernels for Python environments. It resolves the
interpreter selected by uv, Poetry, Conda, a standard virtual environment, or your shell; registers
a user-visible kernelspec; and verifies the kernel before reporting success.

## Why Taco

Notebook frontends discover kernels globally, while Python environments are usually project-local.
Taco bridges that gap without asking an editor or Jupyter process to inherit an activated shell:

- **Manager-aware resolution** — follows uv workspaces, Poetry, `CONDA_PREFIX`, `VIRTUAL_ENV`, a
  project-local `.venv`, or Python on `PATH`.
- **Durable launchers** — records an absolute project and environment so GUI applications can start
  the same runtime later.
- **Safe lifecycle commands** — previews setup, refuses ambiguous collisions, and removes only
  kernels carrying valid Taco ownership metadata.
- **Useful diagnostics** — separates fast static inventory from active runtime checks and provides
  machine-readable JSON for automation.

## Project status

Taco is beta software. It is useful for regular local workflows, but its CLI and metadata may still
evolve. The package has not yet been published under a unique Python distribution name.

> [!WARNING]
> The `taco` project currently on PyPI is unrelated software. Do not run `pip install taco`,
> `pipx install taco`, or `uv tool install taco`. Install Taco from this repository until an
> official distribution is published.

## Requirements

- Python 3.10 or newer to run Taco.
- uv when Taco detects a uv project. For other environments uv is optional, but Taco uses it as a
  fallback installer when the selected Python does not provide `pip`.
- Poetry when Taco detects a Poetry project.
- A Jupyter-compatible notebook frontend, installed separately. Taco registers kernels but does not
  install JupyterLab or an editor extension.
- Network access when the selected environment or `ipykernel` must be created or installed.

Taco has no configuration file. Its inputs are CLI options plus the standard environment variables
`UV_PROJECT_ENVIRONMENT`, `CONDA_PREFIX`, `VIRTUAL_ENV`, and `JUPYTER_DATA_DIR`.

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
source .venv/bin/activate  # On Windows, use your shell's standard activation command.
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

By default, both the kernelspec name and display name come from the project directory. Use
`--name` for a globally unique kernelspec name and `--display-name` for the label shown by notebook
frontends.

## Configuration

Taco deliberately has no configuration file. These inputs control discovery and placement:

| Input | Effect |
|---|---|
| `--project`, `-p` | Select a project or working directory explicitly |
| `--name`, `-n` | Set the global Jupyter kernelspec name |
| `--display-name` | Set the label shown in kernel pickers during setup |
| `UV_PROJECT_ENVIRONMENT` | Select a custom uv environment location |
| `CONDA_PREFIX` | Select the active Conda-family environment |
| `VIRTUAL_ENV` | Select the active standard virtual environment |
| `JUPYTER_DATA_DIR` | Override Jupyter's per-user data directory using Jupyter's standard behavior |

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

Normal setup is not read-only: it can access the network and create or synchronize the selected
environment. In particular, `uv run` may create or sync an environment and resolve lock state under
uv's normal rules, while `poetry run` may create a Poetry environment. Taco then:

1. Resolves the selected environment's real `sys.executable` and `sys.prefix`.
2. Ensures `ipykernel` is available.
   - uv uses an ephemeral `uv run --with ipykernel` overlay; Taco does not add `ipykernel` to the
     project's declared dependencies.
   - Other environments keep using their resolved interpreter. If `ipykernel` is missing, Taco uses
     that interpreter's `pip` module when available (`--user` for plain base Python). If the
     interpreter has no `pip`, Taco uses `uv pip install --python <interpreter> ipykernel` when uv is
     available.
3. Writes a kernelspec to Jupyter's per-user data directory.
4. Replaces the temporary command with a durable launcher.
5. Adds Taco ownership metadata, including the project, environment, interpreter, and strategy.
6. Verifies Jupyter discovery and imports `ipykernel` through the final runtime.

For Poetry and non-uv environments, Taco's fallback installation changes the selected Python
environment but does not add `ipykernel` to `pyproject.toml`, `requirements.txt`, or Conda YAML
files. Add it through your manager first if you want it recorded as a declared dependency.

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

| Command | Purpose |
|---|---|
| `taco setup` | Create or refresh a project kernel, then verify its runtime |
| `taco list` | Inventory kernels using fast, static checks only |
| `taco info` | Diagnose one project kernel, including an active runtime import |
| `taco remove` | Remove one exact Taco-owned project kernel |
| `taco clean` | Preview, confirm, or remove stale Taco-owned kernels |

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

If setup uses a custom `--name`, pass that same name to later `taco info` and `taco remove`
commands. `taco list` includes it in the diagnostic command printed for an unhealthy kernel.

### `taco list`

List Taco-managed kernels and their static health state:

```bash
taco list
taco list --all
taco list --json
```

`list` never launches a kernel. It checks the kernelspec, launcher, project, environment, and
command shape; unhealthy human-readable rows name the failed checks and print a project-specific
`taco info` command for the active runtime diagnosis. `--all` also includes kernels not managed by
Taco.

### `taco info`

Inspect one project's kernel and run discovery, launcher, project, environment, and runtime checks:

```text
taco info [--project DIRECTORY] [--name NAME] [--json]
```

```bash
taco info
taco info --project ~/projects/forecasting
taco info --project ~/projects/forecasting --name forecasting-gpu
taco info --json
```

The command exits with status `1` when the kernel is missing or unhealthy.

### `taco remove`

Remove only the Taco-owned kernelspec associated with a project:

```text
taco remove [--project DIRECTORY] [--name NAME] [--dry-run]
```

```bash
taco remove
taco remove --project ~/projects/forecasting
taco remove --project ~/projects/forecasting --name forecasting-gpu
taco remove --dry-run
```

Foreign kernels and Taco kernels owned by other projects are never removed. Removing an absent
kernel is an idempotent success.

### `taco clean`

Find Taco-owned kernels whose project, launcher, or validated launch command is no longer usable:

```bash
taco clean --dry-run
taco clean
taco clean --yes
```

`clean` ignores kernels that do not carry valid Taco ownership metadata. It prompts before deletion
on a terminal; scripts must pass `--yes` to remove or `--dry-run` to preview stale kernels.

### Version and completion

```bash
taco --version
taco --show-completion
taco --install-completion
```

## Automation and exit codes

`taco list --json` and `taco info --json` each write one JSON document to stdout. List records keep
their existing inventory fields and include a `checks` array of `{name, ok, detail}` objects. The
list checks are static; `info` performs the active runtime check. The JSON format is useful for
scripts but is not yet declared a versioned compatibility contract while Taco is beta.

| Outcome | Exit status |
|---|---:|
| Successful command, including idempotent remove and clean no-op | `0` |
| Missing or unhealthy `taco info` target | `1` |
| Expected operational failure | `1` |
| Invalid option, argument, or usage | `2` |
| Operation interrupted with <kbd>Ctrl</kbd>+<kbd>C</kbd> | `130` |

`taco list` exits `0` even when it reports unhealthy kernels so automation can inspect every record.
In a non-interactive session, `taco clean` exits `1` when stale kernels exist and neither `--yes` nor
`--dry-run` was supplied.

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

This table describes coverage in the repository, not a hosted cross-platform CI guarantee.

| Capability | Repository coverage |
|---|---|
| uv projects and workspace members | Covered by end-to-end tests |
| `UV_PROJECT_ENVIRONMENT` | Covered by end-to-end tests |
| Standard `venv` / `virtualenv` | Covered by end-to-end tests |
| Poetry | Unit coverage; uses Poetry's reported interpreter |
| Anaconda / Miniconda / Conda / Mamba | Unit coverage through `CONDA_PREFIX` |
| Plain/base Python | Unit coverage through `PATH` |
| Other `.venv` / `VIRTUAL_ENV` managers | Supported through the generic interpreter path |
| External Jupyter discovery | Covered by end-to-end tests |
| Live kernel startup and code execution | Covered by end-to-end tests |
| macOS | Primary development platform |
| Linux | Designed around Python and Jupyter platform APIs; validation welcome |
| Windows | Platform-aware interpreter paths are unit covered; broader validation welcome |

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

# Build wheel and source distribution
uv build
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

Taco supports virtual environments created without `pip`: when uv is on `PATH`, it installs into the
exact selected interpreter with `uv pip install --python`. If neither `pip` nor uv is available,
install `ipykernel` with the selected environment manager, then rerun Taco:

```bash
uv add --dev ipykernel
uv pip install --python /path/to/environment/bin/python ipykernel
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
