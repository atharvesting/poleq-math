# AGENTS.md

Instructions for coding agents working on this repository. For an external agent using PolEQ at runtime, read [`docs/agent-guide.md`](docs/agent-guide.md).

## What this is

PolEQ is a local, single-user, offline mathematics knowledge base. A browser UI, a JSON CLI and a loopback HTTP API all use the same SQLite storage and validation layer. There is no graph database, vector database or agent framework.

## Setup and commands

```bash
uv sync                 # Python 3.12+; creates .venv and the poleq CLI
npm ci                  # only for frontend tests/build
./run.sh                # http://127.0.0.1:8765
./check.sh              # Python + frontend test suites
```

- Node.js 20+ is required even when the frontend is not rebuilt: every record save validates LaTeX through the bundled `src/poleq/static/validate.cjs`.
- Ollama is optional and only used for drafting. Tests use a fake model endpoint.
- The server is loopback-only by design. Do not expose it or weaken the origin checks without an explicit security design.
- `.data/` contains the personal library, backups and optional model files. It is ignored by Git. Never edit `.data/library.sqlite3` directly and never use it from tests.

## Repository map

| Path | Responsibility |
|---|---|
| `src/poleq/data_model.py` | Strict Pydantic input and archive schemas; shared contract |
| `src/poleq/store.py` | SQLite records, links, FTS5 search, graph, validation, backups, restore |
| `src/poleq/api.py` | FastAPI app, error envelope, loopback/origin guards, OpenAPI |
| `src/poleq/cli.py` | JSON-first CLI; same store and validators as the API |
| `src/poleq/llm.py` | Optional Ollama drafting; never writes to the database |
| `web/` | JSX, CSS, graph and math source for the browser UI |
| `src/poleq/static/` | Generated/bundled frontend assets served by the API |
| `tests/test_poleq.py` | End-to-end storage, API, CLI, import/export and fake-model tests |
| `docs/agent-guide.md` | Runtime agent workflow, HTTP recipes and error codes |

Data flow: `data_model.py` → `store.py` → (`api.py` | `cli.py`). `llm.py` produces unsaved drafts that still pass through `store.py`.

## Invariants

- **One validation path.** Do not add browser-only or CLI-only record rules. Change `data_model.py`/`store.py` and cover both transports.
- **Bare LaTeX.** The `latex` field must not include `$`, `\[` or `\(` delimiters. Markdown body/definition may contain math delimiters.
- **Strict inputs.** Pydantic models use `extra="forbid"`. Unknown fields, duplicate links, empty parent lists and malformed UUIDs are rejected.
- **Unique names.** Domain/concept names and aliases are unique after NFKC, case and whitespace normalization. Entries are deduplicated by kind + normalized body + exact LaTeX.
- **Transactional writes.** Every mutation is transactional and creates a backup when the library has content. CLI deletions require `--yes`; linked parents cannot be deleted.
- **Server-owned fields.** IDs and `created_at`/`updated_at` are generated. `GET` also returns `last_opened_at` for concepts and entries. The CLI strips these on `update`; HTTP `PUT` models reject them as extra fields.
- **Generated frontend.** Edit `web/` and run `npm run build`. Do not hand-edit `src/poleq/static/app.js`, `style.css`, `index.html`, `validate.cjs`, fonts or copied CSS. Commit the regenerated assets so checkouts do not need a frontend build.
- **Archive compatibility.** The portable archive is `format: "poleq"`, `version: 2`. Any schema change needs a version bump, restore handling for older archives, and export/import tests.
- **Local only.** No accounts, no paid APIs, no CDN assets, no remote write access.
- **No new runtime dependency without a concrete need.** Keep Python 3.12 and the existing FastAPI/Pydantic/httpx stack unless the change justifies more.

## Common tasks

- **New record field:** update `data_model.py`, `store.py` indexes/search if relevant, API/CLI docs, archive schema/version handling, and tests.
- **New endpoint:** add it in `api.py`, ensure errors use `Problem` or the consistent `detail` envelope, add an OpenAPI assertion and a workflow test.
- **New CLI command:** use the shared `Store`; keep stdout JSON-only and failures as JSON on stderr with a nonzero exit.
- **Search/graph change:** verify filters, pagination, stable IDs and edge evidence in `tests/test_poleq.py`; remember `graph` limits nodes.
- **Frontend change:** edit `web/`, run `npm run build`, then `npm test`; do not commit `node_modules`.
- **Error change:** use a stable `code` via `Problem(..., code="...")`; keep the existing `message` useful and add a recovery hint or IDs. Update `docs/agent-guide.md`.

## Verification

```bash
./check.sh
```

Or separately:

```bash
.venv/bin/python -m unittest discover -s tests -v
npm test
```

Tests create temporary databases and must not depend on network access or the user's `.data` library. If a test needs a model, use the fake client pattern in `tests/test_poleq.py`.

## Definition of done

- Behavior is covered by a test (including rejection paths when relevant).
- Both test suites pass.
- Frontend assets are rebuilt if `web/` changed.
- README/docs and the OpenAPI-visible contract match the code.
- No generated data, secrets, `.venv`, `node_modules`, `.runtime` or `.data` files are staged.
- Machine-readable output and existing JSON key names remain stable unless the change is documented.
