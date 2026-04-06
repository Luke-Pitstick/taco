# taco

uv notebook bootstrapper — register per-project Jupyter kernels in one command.

## Usage

Add `taco` as a dev dependency in your uv project, then run it:

```bash
uv add --dev taco
uv run taco
```

This will:

1. Detect your uv project root.
2. Ensure `ipykernel` and `marimo` are installed as dev dependencies.
3. Register a dedicated Jupyter kernel pointing at your project's virtual environment.
4. Print next-step commands for Cursor, Jupyter, and marimo.

## Options

```
uv run taco [--project PATH] [--name TEXT] [--display-name TEXT] [--no-marimo] [--dry-run]
```

| Flag | Description |
|------|-------------|
| `--project` | Path to the uv project root (default: auto-detect) |
| `--name` | Kernel name slug (default: project folder name) |
| `--display-name` | Kernel display name (default: `Python (<project>)`) |
| `--no-marimo` | Skip marimo dependency and guidance |
| `--dry-run` | Show what would happen without making changes |
