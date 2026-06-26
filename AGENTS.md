# AGENTS.md — autotester

## Stack
- Python 3.10+ / Flask 3.0.3 / PyYAML / pytest 8
- AI: PyMuPDF (extract), Ollama HTTP (`/api/embeddings`), ChromaDB (per-project vector store)
- Frontend: Bootstrap 5.3 + Bootstrap Icons via CDN (no build step)
- MVC: `app/controllers` (routes) + `app/models` (logic) + `app/views` (templates + static)
- Port **6444** is hard-coded in `run.py` — do not change unless the user asks.

## Commands
```bash
# Install (use the existing venv or create one)
.venv/bin/pip install -r requirements.txt

# Tests
.venv/bin/python -m pytest tests/ -v          # all 174 tests
.venv/bin/python -m pytest tests/test_x.py    # single file
.venv/bin/python -m pytest -k pattern         # by name

# Run dev server (port 6444, debug on)
.venv/bin/python run.py
```
There is no separate lint/format/typecheck config. CI does not exist.

## Entry points
- `run.py` → `app.create_app()` (application factory; pass a config class for tests)
- `app/__init__.py` wires blueprints, managers (`app.extensions["config_manager"]`,
  `app.extensions["file_manager"]`, `app.extensions["ai_manager"]`,
  `app.extensions["job_runner"]`), and a context processor exposing
  `app_config`, `current_theme`, `projects` to every template.

## Routes
| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Dashboard |
| GET/POST | `/config/` | View/save settings (theme + IA section) |
| POST | `/files/upload` | Upload PDF; returns 202 JSON `{job_id, project}` when `Accept: application/json` is sent, otherwise classic 302 redirect |
| POST | `/files/<name>/rename` | Rename project folder |
| POST | `/files/<name>/delete` | Delete project folder |
| GET | `/ai/status/<job_id>` | Poll async digest job state |
| POST | `/ai/validate` | JSON probe of the Ollama URL; 200 if reachable, 503 if not |

## Async ingestion pipeline
- File upload returns immediately with a `job_id`; the digest (PDF text extraction,
  chunking, embedding, ChromaDB persistence) runs on `app.services.job_runner.JobRunner`,
  a `ThreadPoolExecutor(max_workers=2)` with a thread-safe registry. Jobs older than
  60 s after completion are evicted by `cleanup()` (not yet auto-invoked — manual
  cleanup only).
- Frontend polls `/ai/status/<job_id>` every 1 s via `app/views/static/js/ai_status.js`
  and swaps the spinner for a summary card on `done`. Reloading the page loses
  the in-memory job state (intentional per #002 decision).
- Ollama is invoked via `requests` from `OllamaClient`. Key behaviors:
  - **Connection pooling** via a shared `requests.Session`.
  - **Batch endpoint**: probes the modern `/api/embed` (plural, accepts `input: [...]`)
    on first call; falls back to per-text `/api/embeddings` (singular) on 404.
    Cached per client instance. Always use the batch path when possible — a
    single 5-prompt batch takes ~7 s vs. ~50 s sequentially.
  - **Retry policy**: connection errors, read timeouts and 5xx responses are
    retried up to 3 times with exponential backoff (1s, 2s, 4s). 4xx errors
    (e.g., 404 model not found) are NOT retried.
- Tunables in `app/config.py`: `OLLAMA_PER_REQUEST_TIMEOUT` (60 s),
  `OLLAMA_BATCH_SIZE` (16), `OLLAMA_MAX_ATTEMPTS` (3),
  `OLLAMA_BACKOFF_BASE_SECONDS` (1.0).
- Tests use `test_ai_manager.FakeOllama` or `responses`; patch
  `app.models.ai_manager.time.sleep` to keep retry tests fast.

## Logging
- The `autotester` logger (in `app/utils/logging_setup.py`) is the single
  sink for application events. It writes to stderr with format
  `"%(asctime)s %(levelname)-8s %(name)s | %(message)s"`.
- Level is read from `config.yaml` (`logging.level`, default `INFO`) and
  re-applied via `setup_logging()` whenever the value is updated through
  the `/config` UI. Override at launch with
  `AUTOTESTER_LOG_LEVEL=DEBUG python run.py`.
- Levels (DEBUG, INFO, WARNING, ERROR, CRITICAL) are validated by
  `ConfigManager.update_logging()` — invalid values raise `ValueError`.
- INFO lines: every user action (upload, rename, delete, theme/IA/logging
  change), Ollama reachability probes, AI digest start/finish, job
  submission.
- WARNING lines: Ollama unreachable, invalid config payloads, upload
  rejections.
- ERROR lines: exceptions in JobRunner workers, missing files.
- DEBUG lines (verbose): HTTP method/path/status, Ollama batch endpoint
  probe result, per-batch embedding mode, retry attempts, PDF extraction
  details, job state transitions.
- The logger has `propagate=True` so libraries like pytest's `caplog`
  capture our records; production deployments should not attach handlers
  to the root logger or risk duplicate output.
- Test fixture `_quiet_logger` (autouse in `conftest.py`) clears handlers
  after each test to prevent handler accumulation across runs.

## Conventions
- **All UI and code is in English** (per scope decision).
- One PDF per project; projects live as folders under `./projects/<safe_name>/`,
  each containing the original PDF plus a `chroma.db/` directory for Chroma.
- Project names are normalized by `app.utils.validators.safe_project_name` (strips path chars, lowercases, caps length). Always run user-supplied names through it — never use `request.form` raw in filesystem paths.
- PDF validation requires both `.pdf` extension **and** `%PDF-` magic bytes (see `app.utils.validators.is_valid_pdf_bytes`).
- Theme values are restricted to `light | dark | system`; invalid values fall back to `system` on `ConfigManager.load()`.
- IA settings live under `app_config["ia"]` with keys `ollama_url`, `embedding_model`,
  `chunk_size`, `chunk_overlap`. Validation in `ConfigManager.update_ia()` enforces
  `0 <= chunk_overlap < chunk_size` and `chunk_size > 0`.
- `ConfigManager.save()` writes atomically via `*.tmp` + `replace()`.
- File rename collisions auto-suffix `_2`, `_3`, ... (see `FileManager._unique_path`).

## Test fixtures (tests/conftest.py)
- `temp_workspace` — fresh `tmp_path` with `projects/` and `config.yaml`; auto-cleaned.
- `app` — Flask app built via `create_app(_Cfg)` with `TestConfig` pointing at the temp workspace.
- `client` — `app.test_client()`.
- `sample_pdf_bytes` — minimal valid PDF payload (no extractable text).
- `tests/test_ai_manager.py::FakeOllama` — drop-in replacement for `OllamaClient`
  that returns canned embeddings; use this in any new AI-touching test so the
  suite stays offline.

When testing filesystem-touching code, always go through these fixtures; never touch the real `./projects/` or `./config.yaml`.

## Gotchas
- `app/__init__.py` is imported during test collection and during `create_app()`. The module-level blueprint imports mean `app/controllers/*` and `app/models/*` must exist before any test runs. Don't add heavy work at import time.
- The runtime artifacts `./projects/` and `./config.yaml` are gitignored — never commit them. They are auto-created on first run.
- `.venv/` is gitignored; the existing one is committed only via local state.
- `run.py` runs with `debug=True` — never use this entry point in production.
- Bootstrap CSS/JS are loaded from jsDelivr CDN; tests do not exercise the network layer (no browser tests).
- ChromaDB needs an `importlib.metadata` entry for `posthog`; the `chromadb==1.x`
  install we use is Python 3.14-compatible. Older chromadb builds (0.4.x/0.5.x)
  compile `chroma-hnswlib` from source and require `python3-dev` — avoid pinning
  to those versions on bare machines.
- `pyyaml` is pinned to 6.0.2; chromadb's transitive dep `kubernetes` wants
  `>=6.0.3`, producing a resolver warning. Ignore it.
- The `JobRunner` registry is in-memory. A Flask restart between upload and
  poll returns `state: "unknown"`. The job TTL is 60 s; the cleanup loop is not
  yet started automatically — call `runner.cleanup()` manually in long-lived
  contexts.

## Out of scope (verified)
- No migrations, no database (Chroma is per-project file storage, not a DB).
- No pre-commit hooks, no CI, no Docker.
- No README instructions beyond install/test/run (see `README.md`).

## Definition of Done
Any implementation is only considered **done** when **both** hold:

1. **Test written** — at least one pytest test exists that covers the new behavior
   (happy path + the most relevant edge/error case). Add it to the matching
   `tests/test_*.py` file or create a new one following the existing naming.
2. **Tests pass** — `.venv/bin/python -m pytest tests/ -v` exits with all tests
   green. No skipped, xfail, or `pytest.skip` shortcuts to mask failures.

Run the full suite after every change. Do not declare a feature complete on
the strength of `pytest -k` against a single keyword — always verify the full
suite still passes.