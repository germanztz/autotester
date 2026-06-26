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
- **Live status widget**: shows "Processing PDF... (xx s)" while indexing,
  then a summary card with pages, chunks and total time.
- **Theme switcher**: Light / Dark / System, persisted in `config.yaml`.
- **AI settings**: Ollama URL, embedding model, chunk size and overlap.
- **Toast notifications** for user feedback.
- **Comprehensive test suite** (125 tests) built with pytest.

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
│   │   └── job_runner.py        # In-process async job runner
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
- An Ollama instance reachable at `http://localhost:11434` with the
  `qwen3-embedding:4b` model pulled (or update the URL/model in
  `/config`).

## Installation

```bash
# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate          # Linux / macOS
# .venv\Scripts\activate           # Windows

# Install dependencies
pip install -r requirements.txt

# Pull the default embedding model (only required once)
ollama pull qwen3-embedding:4b
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
chunker, Ollama HTTP client, async job runner, HTTP routes and end-to-end
PDF upload flows (125 tests). All AI-touching tests run offline by
substituting a fake Ollama client.

## Usage

1. Click **File → Open** (or the *Add PDF* button) and choose a project name
   plus a PDF file from your disk.
2. The PDF is stored under `./projects/<project_name>/`. The AI digest
   starts immediately in the background; the dashboard shows a live
   "Processing PDF... (xx s)" counter and replaces it with a summary card
   (pages, chunks, total time) when done.
3. In the sidebar you can:
   - **Rename** a project (pencil icon) — moves the folder (and its
     ChromaDB index) atomically.
   - **Delete** a project (trash icon) — removes the folder and its PDF.
4. Click **Configuration** to:
   - Pick a **theme** (Light / Dark / System).
   - Configure **AI settings**: Ollama URL, embedding model, chunk size
     and overlap. The page shows an advisory if Ollama is unreachable.

## Configuration file (`config.yaml`)

Created automatically on first launch:

```yaml
theme: system
app_name: autotester
auto_refresh: true
ia:
  ollama_url: http://localhost:11434
  embedding_model: qwen3-embedding:4b
  chunk_size: 500
  chunk_overlap: 50
```

You can edit it manually; missing keys fall back to defaults and an invalid
`theme` value is corrected to `system`.

## License

See [LICENSE](LICENSE).