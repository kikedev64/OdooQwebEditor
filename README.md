# Odoo QWeb Editor

A visual editor for Odoo QWeb reports and templates, developed by **[kikedev64](https://github.com/kikedev64/kikedev64)**.

Repository: **[kikedev64/OdooQwebEditor](https://github.com/kikedev64/OdooQwebEditor)** · Application: **QWeb Studio** · Command: `odoo-report-editor`.

Open a terminal in your Odoo project, run `odoo-report-editor`, and select a model, report, and sample record. Edit the XML and see the result in an A4 preview that updates as you work.

![QWeb Studio editor](docs/images/editor.png)

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Quick start from GitHub](#quick-start-from-github)
- [Install the Debian package](#install-the-debian-package)
- [Build the installer](#build-the-installer)
- [Usage](#usage)
- [Exporting templates](#exporting-templates)
- [Sample fields and limitations](#sample-fields-and-limitations)
- [Connection and isolation](#connection-and-isolation)
- [Architecture and local API](#architecture-and-local-api)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [Credits and license](#credits-and-license)

## Features

- Discover the Odoo service and its databases from Docker Compose.
- Select a model → report → record, with searches by ID, name, reference, or customer.
- Edit XML alongside an Odoo-generated PDF of the current draft, with an HTML view for visual editing.
- Embed local fonts, CSS, and images from the selected database, including private resources and bundles generated during rendering.
- Keep visual element selection synchronized with its position in the code.
- Preview numbered A4 pages, report margins, and content flowing across multiple pages.
- Insert or drag text blocks, headings, tables, columns, images, and fields.
- Inspect text, expressions, colors, sizes, and spacing; undo and redo changes.
- Collapse the blocks and fields panel, zoom, and resize panels.
- Use sample fields to preview templates that reference missing fields.
- Export XML without overwriting modules or saving the draft in Odoo.

## Requirements

To install the Debian package:

- Ubuntu 24.04, or a Debian/Ubuntu system with Python 3.11+, FastAPI 0.101+, Uvicorn 0.27+, and lxml 5+. APT resolves these dependencies.
- A web browser to open the interface.

For a real project, you also need Docker, the **Docker Compose v2** plugin, permission to use Docker, and a running Odoo service with PostgreSQL. The installer does not install or start Odoo or Docker.

The integration has been tested with Odoo **14, 16, 18, and 19**. Individual report compatibility also depends on the installed modules and data. Demo mode works without Docker.

## Quick start from GitHub

With Git, Python 3.11 or later, and `venv` support installed:

```bash
git clone https://github.com/kikedev64/OdooQwebEditor.git
cd OdooQwebEditor
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
odoo-report-editor --demo
```

On Debian/Ubuntu, install `python3-venv` and `python3-pip` with APT if the Python tools are missing. Installing from source requires access to the package index to resolve dependencies.

The demo opens `http://127.0.0.1:8765` and lets you try the workflow with fictional quotations. To connect a real project, stop the demo with **Ctrl+C** and run the following from the same virtual environment:

```bash
odoo-report-editor /path/to/my-odoo-project --service odoo -d my_database
```

Replace the path, service, and database with your project's values. You can omit `--service` when discovery is unambiguous, and omit `-d` to choose the database in the interface. The editor is a standalone local application; installing it does not require adding an Odoo module.

## Install the Debian package

Download `odoo-report-editor_0.1.0_all.deb` and its `.sha256` file from [GitHub Releases](https://github.com/kikedev64/OdooQwebEditor/releases). From the download directory:

```bash
sha256sum -c odoo-report-editor_0.1.0_all.deb.sha256
sudo apt install ./odoo-report-editor_0.1.0_all.deb
```

Alternatively, build the package with `./build_deb.sh`, as described below, and install it from the repository root:

```bash
sudo apt install ./dist/odoo-report-editor_0.1.0_all.deb
```

The package installs `/usr/bin/odoo-report-editor` and the application in `/usr/share/odoo-report-editor/`. It uses Python libraries managed by APT; installation does not download packages with pip or require activating a virtual environment.

You can then run it from any terminal:

```bash
cd /path/to/my-odoo-project
odoo-report-editor
```

To uninstall it:

```bash
sudo apt remove odoo-report-editor
```

XML files exported into your projects are preserved.

## Build the installer

You need Bash, Python 3.11+, `dpkg-deb`, and standard GNU/Linux utilities. On Ubuntu:

```bash
sudo apt install python3 dpkg gzip coreutils findutils
./build_deb.sh
```

This creates `dist/odoo-report-editor_0.1.0_all.deb` and its SHA-256 checksum in a `.sha256` file. The version comes from `pyproject.toml`. Building requires no administrator privileges, Internet access, virtual environment, or Odoo project.

You can choose a different output directory:

```bash
./build_deb.sh /tmp/installers
```

To reproduce a package with the same build timestamps, set `SOURCE_DATE_EPOCH`. Otherwise, the latest commit's timestamp is used, or the current time in a directory without Git history.

```bash
SOURCE_DATE_EPOCH=1792627200 ./build_deb.sh
```

The package contains only the application, its web resources, and documentation. It excludes the virtual environment, tests, audit results, databases, and exports.

## Usage

You can also specify the project without changing directories:

```bash
odoo-report-editor /path/to/my-odoo-project
```

The browser opens `http://127.0.0.1:8765`.

1. If several databases are available, select the one to use.
2. Choose the **model** by its descriptive or technical name, such as `sale.order`.
3. Select the **report**, displayed as `ir.actions.report name - report_name`.
4. Find and select a **sample record**. `#123` searches directly for ID 123. The editor does not choose a record for you.
5. **Odoo PDF** (shown as **PDF de Odoo** in the interface), selected by default for real projects, displays the draft using the report's PDF engine, fonts, and paper format. Edit the XML and the view updates after a short pause. The PDF viewer has its own zoom controls. Switch to **Visual editing** (**Edición visual**) to use blocks, select elements, and use the inspector; its HTML pagination is approximate. HTML reports and the demo use this second mode.
6. Click **Save XML** (**Guardar XML**) to export the template. **Download draft** (**Descargar borrador**) downloads only its XML architecture.

The arrow in the blocks and fields panel collapses it; the browser remembers this preference. Elements repeated by a loop share the same template tag.

| Option | Purpose |
| --- | --- |
| `--demo` | Try the application with fictional data, without Odoo. |
| `--service NAME` | Select the Odoo service in Compose. |
| `--database NAME`, `-d NAME` | Choose the database. |
| `--compose-file FILE`, `-f FILE` | Use an alternative Compose file. |
| `--python PATH` | Choose the Python interpreter **inside the container**. |
| `--port NUMBER` | Change the editor's port; the default is 8765. |
| `--no-browser` | Start without automatically opening the browser. |
| `--help` | Show the available options. |

```bash
odoo-report-editor --demo
odoo-report-editor /path/to/project -d my_database --service odoo
odoo-report-editor /path/to/project -f development.yml --port 8877 --no-browser
```

Shortcuts: **Ctrl/Cmd S** saves XML; **Ctrl/Cmd Enter** refreshes the preview.

## Exporting templates

Each save creates a new file:

```text
my-odoo-project/
└── report_editor_exports/
    └── sale.report_saleorder_document_DATE_IDENTIFIER.xml
```

It contains an `ir.ui.view` record inside `<odoo>`, with its external identifier and QWeb architecture. You can include it in a module's data files and declare it in `__manifest__.py`.

Keep the external identifier to update an existing view. To create another view, assign a different identifier and connect it to the appropriate report. The editor does not apply this XML to the database or modify the project's original files.

## Sample fields and limitations

**Sample fields** (**Campos de ejemplo**) is disabled by default for real projects so you can check actual data and conditions. The demo enables it by default. When enabled, rendering first uses real data; if a missing field causes a failure, it is replaced in a temporary copy with a reference such as `[sale.order.custom_reference]`. A warning lists the replaced fields. Relations, loop aliases, and certain formatters for missing fields are supported, with up to 32 substitutions per request.

The preview is approximate: conditions may be enabled to display a section; calculations use zero, and missing collections use one sample row. Disable this option to check strict rendering. Placeholders are not saved in exported XML and do not create fields in Odoo.

Keep these limitations in mind:

- **Odoo PDF** uses the action's PDF engine and paper format, including margins, orientation, headers, and footers. Odoo's PDF generator must be installed. Previously attached reports are not reused. Drafts and their temporary resources are processed without committing the transaction.
- **Visual editing** uses paginated HTML in **portrait A4, 210 × 297 mm**. It preserves paper format margins, repeats external headers and footers, and avoids splitting table rows when they fit on a page. It may differ from the PDF, especially with complex tables, fixed positioning, or indivisible content larger than a page. Use PDF mode to check the final result.
- Base templates reachable through static `t-call` directives are listed. Visual editing of XPath extensions and dynamically computed calls has limitations.
- Elements added by inherited views do not necessarily have their own editor marker.
- A report may require wizard data, a specific record, or additional modules. Standard product labels prepare their wizard in memory; it is not saved to the database.
- Missing Python methods, context variables, and SQL columns are not fabricated. Code, schema, and module errors still require fixing the environment or template. The editor keeps the last valid preview and displays technical details.
- Module static resources, attachments, binary field images, and barcodes are read inside the container and embedded in the document, along with fonts referenced by CSS. External resources retain their URLs and must be accessible. Warnings identify local resources that are missing or cannot be embedded.
- Replace the palette's sample image with a valid URL before using the report outside the editor.
- Unexported drafts are lost when you close the application. SQL queries have a 30-second limit per statement.

## Connection and isolation

The editor resolves configuration with `docker compose config --format json`, respecting `.env` and the usual overrides. It recognizes connection options from the command, Odoo configuration, and common variables used by official images and Doodba.

The service's regular container is preferred. A single container created with `docker compose run` is also supported when the regular service is not running. The editor does not choose between ambiguous containers or start containers automatically.

Databases configured for Odoo are queried and filtered to those containing its schema. `POSTGRES_DB` is not automatically used as the editor's working database.

The ORM runs as superuser in a private process inside the container. Drafts are injected only into its cache, and each query ends with a rollback. No modules are installed or updated. Rollback cannot undo external calls made by custom modules, and registry initialization retains Odoo's normal behavior.

The interface listens only on `127.0.0.1`; the preview iframe disables scripts and forms.

## Architecture and local API

The interface is written in HTML, CSS, and JavaScript and served by FastAPI and Uvicorn. It requires neither Node.js nor a frontend build. `project.py` discovers Docker Compose and maintains a private Python process inside the Odoo container; `docker_worker.py` queries and renders using the project's own ORM and QWeb. `qweb_support.py` handles template resolution and sample fields, while `preview_resources.py` embeds report resources.

The preview flow is: browser → local API → process inside Odoo → HTML or PDF rendering → browser. Pagination and visual selection code lives in `report_editor/static/`.

With the server running, interactive documentation is available at [`/docs`](http://127.0.0.1:8765/docs), and the OpenAPI schema at [`/openapi.json`](http://127.0.0.1:8765/openapi.json).

| Method and path | Purpose |
| --- | --- |
| `GET /api/status` | Get the mode, project, service, and available databases. |
| `POST /api/database` | Select the session's database. |
| `GET /api/reports` | List reports and their models. |
| `GET /api/templates` | Search templates and filter by report. |
| `GET /api/templates/{template_id}` | Get a template's XML and revision. |
| `GET /api/records` | Search a model's records. |
| `GET /api/fields` | Query fields to insert into the template. |
| `POST /api/preview` | Render the draft as HTML or PDF. |
| `GET /api/preview.pdf` | Get the session's PDF using its temporary token. |
| `POST /api/save` | Export the template to a new XML file. |

The API uses the `editor_session` cookie. Requests that change state require `X-Editor-Request: 1`; if they include `Origin`, it must match the editor's origin. To automate requests, preserve the cookie between calls and consult OpenAPI for JSON request bodies; the interface handles these requirements automatically.

## Troubleshooting

| Symptom | Check or solution |
| --- | --- |
| Docker Compose is not found | Run the editor with the project path containing the Compose file, or specify the file with `-f`. |
| The service cannot be selected | Specify `--service NAME` and check `docker compose config` inside the project. |
| No running container is found | Check `docker compose ps` and start the Odoo environment using your project's normal procedure. |
| Docker denies access | Check that your user can run Docker and that the daemon is available. |
| Python cannot import Odoo | Use `--python` with the container's interpreter that has Odoo installed. |
| The database is missing | Check Odoo's PostgreSQL connection and select a database with an initialized Odoo schema. |
| No records appear | Confirm the model, selected database, and available data; search for a specific record with `#ID`. |
| The PDF preview fails | Check the container's PDF generator and the action's requirements; review the error's technical details. |
| Images or fonts are missing | Review resource warnings and check files, attachments, and external URLs. |
| A custom field prevents rendering | Enable **Sample fields** (**Campos de ejemplo**) to explore the layout, then fix the field or module to validate the actual report. |
| The port is already in use | Start with another port, such as `--port 8877`. |
| The browser does not open | Open the URL printed in the terminal manually; `--no-browser` disables automatic opening. |

To report a bug, use the [repository's issues](https://github.com/kikedev64/OdooQwebEditor/issues) and include reproduction steps, Python and Odoo versions, the mode used, and relevant technical details. Remove credentials and private data from examples.

## Development

Install an editable copy in a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev,browser]'
playwright install chromium
pytest -q
```

To check the interface, start the demo in one terminal:

```bash
odoo-report-editor --demo --port 8880 --no-browser
```

In another terminal using the same virtual environment:

```bash
python tests/browser_smoke.py --url http://127.0.0.1:8880
python tests/browser_layout.py --url http://127.0.0.1:8880
```

After installing the `.deb`, you can also check the command, API, and export from a temporary directory:

```bash
python3 tests/installed_smoke.py
```

To check real projects that are already running:

```bash
python tests/integration_projects.py /path/to/project-1 /path/to/project-2
python tests/browser_projects.py --url http://127.0.0.1:8765
```

The audit creates `artifacts/integration-results.json`. It goes through QWeb actions and tests their first editable template with the latest record, distinguishing rendered documents, models without records, reports without editable templates, and errors. It does not automatically find a record that satisfies each report's business conditions. Export is checked in a temporary directory, and browser tests do not save changes in Odoo.

```text
report_editor/          Python application and Odoo integration process
report_editor/static/   Interface, XML selection, and A4 pagination
tests/                  Automated and browser tests
packaging/              Debian package launcher and metadata
docs/images/            Interface screenshot
build_deb.sh            Installer builder
pyproject.toml          Python metadata and dependencies
```

Code comments are limited to Python docstrings and JSDoc in English. Executable shebangs are execution directives.

## Credits and license

Developed by **[kikedev64](https://github.com/kikedev64/kikedev64)**. The same attribution appears in the application's About dialog.

This project is distributed under the MIT license. See [LICENSE](LICENSE) for the full text.
