# AGENTS.md — autotester

## Stack
- Python 3.10+ / Flask 3.0.3 / PyYAML / pytest 8
- Frontend: Bootstrap 5.3 + Bootstrap Icons via CDN (no build step)
- MVC: `app/controllers` (routes) + `app/models` (logic) + `app/views` (templates + static)
- Port **6444** is hard-coded in `run.py` — do not change unless the user asks.

## Commands
```bash
# Install (use the existing venv or create one)
.venv/bin/pip install -r requirements.txt

# Tests
.venv/bin/python -m pytest tests/ -v          # all 65 tests
.venv/bin/python -m pytest tests/test_x.py    # single file
.venv/bin/python -m pytest -k pattern         # by name

# Run dev server (port 6444, debug on)
.venv/bin/python run.py
```
There is no separate lint/format/typecheck config. CI does not exist.

## Entry points
- `run.py` → `app.create_app()` (application factory; pass a config class for tests)
- `app/__init__.py` wires blueprints, managers (`app.extensions["config_manager"]`, `app.extensions["file_manager"]`), and a context processor exposing `app_config`, `current_theme`, `projects` to every template.

## Routes
| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Dashboard |
| GET/POST | `/config/` | View/save settings (theme) |
| POST | `/files/upload` | Upload PDF (multipart, field `pdf`, optional `project_name`) |
| POST | `/files/<name>/rename` | Rename project folder |
| POST | `/files/<name>/delete` | Delete project folder |

## Conventions
- **All UI and code is in English** (per scope decision).
- One PDF per project; projects live as folders under `./projects/<safe_name>/`.
- Project names are normalized by `app.utils.validators.safe_project_name` (strips path chars, lowercases, caps length). Always run user-supplied names through it — never use `request.form` raw in filesystem paths.
- PDF validation requires both `.pdf` extension **and** `%PDF-` magic bytes (see `app.utils.validators.is_valid_pdf_bytes`).
- Theme values are restricted to `light | dark | system`; invalid values fall back to `system` on `ConfigManager.load()`.
- `ConfigManager.save()` writes atomically via `*.tmp` + `replace()`.
- File rename collisions auto-suffix `_2`, `_3`, ... (see `FileManager._unique_path`).

## Test fixtures (tests/conftest.py)
- `temp_workspace` — fresh `tmp_path` with `projects/` and `config.yaml`; auto-cleaned.
- `app` — Flask app built via `create_app(_Cfg)` with `TestConfig` pointing at the temp workspace.
- `client` — `app.test_client()`.
- `sample_pdf_bytes` — minimal valid PDF payload.

When testing filesystem-touching code, always go through these fixtures; never touch the real `./projects/` or `./config.yaml`.

## Gotchas
- `app/__init__.py` is imported during test collection and during `create_app()`. The module-level blueprint imports mean `app/controllers/*` and `app/models/*` must exist before any test runs. Don't add heavy work at import time.
- The runtime artifacts `./projects/` and `./config.yaml` are gitignored — never commit them. They are auto-created on first run.
- `.venv/` is gitignored; the existing one is committed only via local state.
- `run.py` runs with `debug=True` — never use this entry point in production.
- Bootstrap CSS/JS are loaded from jsDelivr CDN; tests do not exercise the network layer (no browser tests).

## Out of scope (verified)
- No migrations, no database, no external services, no Celery/RQ.
- No pre-commit hooks, no CI, no Docker.
- No README instructions beyond install/test/run (see `README.md`).