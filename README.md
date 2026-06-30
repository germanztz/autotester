# autotester

Web application for managing PDF projects. Upload PDFs, organize them into
per-project folders, and configure the application (theme, AI indexing
options) through a clean MVC interface built on Flask + Bootstrap 5. PDFs
are automatically indexed using a local Ollama embedding model into a
per-project ChromaDB vector store.

> Creates Duolingo-style tests from a document using local AI LLMs.

## Features

- **MVC architecture** (Flask blueprints + Jinja2 templates).
- **Modern responsive UI** with Bootstrap 5 (CDN) and Bootstrap Icons.
- **Fixed top navbar** with *File → Open* and *Configuration* menus.
- **Sidebar** listing all projects with rename (pencil) and delete (trash) actions.
- **PDF upload** validated by extension and magic bytes.
- **Per-project folders** stored under `./projects/<project_name>/`.
- **Async AI digest**: PDF text extraction (PyMuPDF) → chunking → embeddings
  (Ollama) → persistence (ChromaDB) running in a background thread.
- **Lazy per-page digest (#005)**: each PDF page is embedded one at a time,
  tracked via `### Page N` markers in a markdown sidecar. You can stop a
  digest mid-flight and resume it later from the sidebar.
- **Sidebar-driven progress**: live "Processing page X / Y" updates in the
  project row, with a stop button that leaves remaining markers in place.
- **Theme switcher**: Light / Dark / System, persisted in `config.yaml`.
- **AI settings**: Ollama URL, embedding model, chunk size and overlap.
- **Logging**: configurable level (DEBUG/INFO/WARNING/ERROR/CRITICAL),
  written to stderr. Every user action emits a line.
- **Toast notifications** for user feedback.
- **Comprehensive test suite** (223 tests) built with pytest.

## Project layout

```
autotester/
├── app/
│   ├── __init__.py              # Application factory
│   ├── config.py                # Flask configuration
│   ├── controllers/             # Route blueprints (MVC controllers)
│   │   ├── main_controller.py
│   │   ├── files_controller.py
│   │   ├── config_controller.py
│   │   └── ai_controller.py
│   ├── models/                  # Domain logic (MVC models)
│   │   ├── config_manager.py    # YAML configuration manager
│   │   ├── file_manager.py      # Project CRUD on disk
│   │   └── ai_manager.py        # PDF chunker, Ollama client, AI orchestrator
│   ├── services/
│   │   ├── job_runner.py        # In-process async job runner
│   │   └── page_digest.py       # Lazy per-page digest state machine
│   ├── utils/
│   │   └── validators.py        # PDF + project-name validators
│   └── views/
│       ├── static/              # CSS / JS (incl. ai_status.js poller)
│       └── templates/           # Jinja2 templates (MVC views)
├── tests/                       # pytest suite
├── projects/                    # PDF project folders (auto-created)
├── config.yaml                  # Persisted configuration (auto-created)
├── run.py                       # Entry point (port 6444)
├── requirements.txt
└── scope.md
```

## Requirements

- Python 3.10+
- pip
- An Ollama instance reachable at `SERVER` with the model pulled (or update the URL/model in  `/config`).

## Installation

```bash
# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate          # Linux / macOS
# .venv\Scripts\activate           # Windows

# Install dependencies
pip install -r requirements.txt

# Pull the default embedding model (only required once)
ollama pull model
```

## Running the app

The application always listens on port **6444**:

```bash
python run.py
```

Then open <http://localhost:6444> in your browser.

## Running tests

```bash
pytest -v
```

The suite covers validators, configuration persistence, file CRUD, AI
chunker, Ollama HTTP client (incl. retry), async job runner, lazy per-page
digest, HTTP routes, end-to-end PDF upload flows, logging setup and
integration (223 tests). All AI-touching tests run offline by
substituting a fake Ollama client.

## Usage

1. Click **File → Open** (or the *Add PDF* button) and choose a project name
   plus a PDF file from your disk.
2. The PDF is stored under `./projects/<project_name>/`. The lazy digest
   starts immediately in the background; the **sidebar** shows live
   "Processing page X / Y" updates and a stop button for each project.
3. The dashboard shows a static welcome message. There is no central
   progress widget — all digest state lives in the sidebar.
4. In the sidebar you can:
   - **Stop** an in-flight digest (stop button next to the project).
   - **Rename** a project (pencil icon) — moves the folder (and its
     ChromaDB index) atomically.
   - **Delete** a project (trash icon) — removes the folder and its PDF.
5. Click **Configuration** to:
   - Pick a **theme** (Light / Dark / System).
   - Configure **AI settings**: Ollama URL, embedding model, chunk size
     and overlap. The page shows an advisory if Ollama is unreachable.
   - Set the **log level** (DEBUG for verbose HTTP/embed diagnostics).

## Logging

Application events are logged to stderr at the level configured via the
**Configuration → Logging** card (default `INFO`). Example output:

```
2026-06-26 12:34:56 INFO     autotester | autotester starting (log level: INFO, ...)
2026-06-26 12:35:01 INFO     autotester | Uploaded PDF: project=report file=doc.pdf size_bytes=12345
2026-06-26 12:35:01 INFO     autotester | AI digest queued: project=report job_id=abc123
2026-06-26 12:35:08 INFO     autotester | AI digest finished: project=report pages=3 chunks=6 duration=7.123s
```

Set `AUTOTESTER_LOG_LEVEL=DEBUG` in the environment to override the
configured level at launch.

## Configuration file (`config.yaml`)

Created automatically on first launch:


You can edit it manually; missing keys fall back to defaults and an invalid
`theme` or `logging.level` value is corrected to the default.

## License

See [LICENSE](LICENSE).