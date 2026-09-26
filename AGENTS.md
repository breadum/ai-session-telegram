# Repository guide

- Make changes on a task branch. Run relevant checks, commit, and open a PR.
- Merge only after the user explicitly approves it.
- Before committing, inspect the staged diff and run the repository's secret scan. Never commit real tokens or token-derived values.
- Local checks: `uv run ruff check .` and `uv run pytest`.

## Map

- [Codebase architecture and runtime contracts](docs/codebase.md)
- [User setup and commands](README.md)
- [Operational recovery](docs/operations/README.md)
- [Windows compatibility decisions](docs/decisions/windows-compatibility.md)
