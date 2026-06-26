# autotester

Web application for managing PDF projects. Upload PDFs, organize them into
per-project folders, and configure the application (theme, options) through a
clean MVC interface built on Flask + Bootstrap 5.

> Creates Duolingo-style tests from a document using local AI LLMs.

## Features

- **MVC architecture** (Flask blueprints + Jinja2 templates).
- **Modern responsive UI** with Bootstrap 5 (CDN) and Bootstrap Icons.
- **Fixed top navbar** with *File → Open* and *Configuration* menus.
- **Sidebar** listing all projects with rename (pencil) and delete (trash) actions.
- **PDF upload** validated by extension and magic bytes.
- **Per-project folders** stored under `./projects/<project_name>/`.
- **Theme switcher**: Light / Dark / System, persisted in `config.yaml`.
- **Toast notifications** for user feedback.
- **Comprehensive test suite** (65 tests) built with pytest.

## Project layout

```
autotester/
├── app/
│   ├── __init__.py              # Application factory
│   ├── config.py                # Flask configuration
│   ├── controllers/             # Route blueprints (MVC controllers)
│   │   ├── main_controller.py
│   │   ├── files_controller.py
│   │   └── config_controller.py
│   ├── models/                  # Domain logic (MVC models)
│   │   ├── config_manager.py    # YAML configuration manager
│   │   └── file_manager.py      # Project CRUD on disk
│   ├── utils/
│   │   └── validators.py        # PDF + project-name validators
│   └── views/
│       ├── static/              # CSS / JS
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

## Installation

```bash
# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate          # Linux / macOS
# .venv\Scripts\activate           # Windows

# Install dependencies
pip install -r requirements.txt
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

The suite covers validators, configuration persistence, file CRUD, HTTP routes
and end-to-end PDF upload flows (65 tests).

## Usage

1. Click **File → Open** (or the *Add PDF* button) and choose a project name
   plus a PDF file from your disk.
2. The PDF is stored under `./projects/<project_name>/`.
3. In the sidebar you can:
   - **Rename** a project (pencil icon) — moves the folder.
   - **Delete** a project (trash icon) — removes the folder and its PDF.
4. Click **Configuration** to pick a theme:
   - *Light* — always light.
   - *Dark* — always dark.
   - *System* — follows your OS preference.

The chosen theme is persisted in `config.yaml` and applied on every page load.

## Configuration file (`config.yaml`)

Created automatically on first launch:

```yaml
theme: system
app_name: autotester
auto_refresh: true
```

You can edit it manually; missing keys fall back to defaults and an invalid
`theme` value is corrected to `system`.

## License

See [LICENSE](LICENSE).