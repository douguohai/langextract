# Repository Guidelines

## Project Structure & Module Organization
- `langextract/`: core library (schema, extraction, chunking, prompting, resolver, visualization) plus provider implementations under `providers/`.
- `tests/`: pytest suites; markers `live_api`/`requires_pip` gate network/install-heavy cases.
- `examples/`, `docs/`: notebooks and docs assets.
- `scripts/` and `autoformat.sh`: formatting helpers; `benchmarks/` holds performance experiments.
- Root config: `pyproject.toml` (deps + tool config), `tox.ini` (CI parity), `Dockerfile`.

## Setup, Build, and Test Commands
- Install for development (Python ≥3.10): `pip install -e ".[dev,test]"`.
- Quick format-and-hook setup: `./autoformat.sh` (isort → pyink → pre-commit run).
- Lint: `pylint --rcfile=.pylintrc langextract` and `pylint --rcfile=tests/.pylintrc tests`.
- Test fast path: `pytest -ra -m "not live_api and not requires_pip"`; full matrix/linters: `tox`.
- Live/integration (needs keys): `pytest -v tests/test_live_api.py -m live_api` with `GEMINI_API_KEY`/`OPENAI_API_KEY`/`LANGEXTRACT_API_KEY`.

## Coding Style & Naming Conventions
- Formatting: `pyink` (Google style) with 2-space indents and 80-char lines; imports sorted via `isort` (`profile=google`).
- Type hints required; `py.typed` package enforces typing for public API.
- Naming: modules/packages `snake_case`; classes `PascalCase`; functions/vars `snake_case`; constants `UPPER_SNAKE`.
- Prefer explicit dataclasses/pydantic models for schemas; keep provider modules free of back-imports per `importlinter` contracts.

## Testing Guidelines
- Tests live in `tests/` as `*_test.py`; use descriptive `TestClass` + `test_*` functions.
- Mark external deps with `@pytest.mark.live_api` or `@pytest.mark.requires_pip` so default runs stay offline.
- Add fixture-based examples that mirror real extraction calls; assert both structured outputs and grounding metadata.
- Provider changes need smoke coverage in `tests/provider_*` and, when possible, a keyed `live_api` case.

## Commit & Pull Request Guidelines
- Commit messages: short, imperative subject (≤72 chars); add a brief rationale when non-trivial.
- PRs should stay focused and typically squash to a single commit; keep scope reasonable for review.
- Include issue linkage (`Fixes #123`) and a concise summary; add screenshots or CLI output when user-visible behavior changes.
- Run `./autoformat.sh`, lint, and tests before requesting review; avoid touching infrastructure/build files unless explicitly approved.
- Respond promptly to review comments and keep PR descriptions updated as code changes.

## Provider & Security Notes
- Cloud and local model access rely on env vars: `GEMINI_API_KEY`, `OPENAI_API_KEY`, `LANGEXTRACT_API_KEY`, `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_PROJECT`.
- Never commit keys or service account files; prefer loading via `.env` (supported by `python-dotenv`) and validate with minimal-scope credentials.
- For new providers, follow the `langextract.providers` entrypoint pattern; consider publishing as an external plugin to avoid core dependency bloat.
