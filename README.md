# PolEQ

A personal, offline mathematics knowledge base. Store domains, concepts, properties, proofs, equivalences and notes; retrieve them by keyword, alias or parent concept; follow their connections in a graph.

## Setup

### Requirements

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Git
- Node.js 20+ to validate and save records, and to rebuild/test the frontend
- [Ollama](https://ollama.com/) optional, for local model drafts

The repository includes the built frontend assets (`src/poleq/static`), so no CDN or frontend build is needed to start. Node.js is still required at runtime when saving: LaTeX is validated locally through the bundled `validate.cjs`. Without Node.js the app starts, browses and saves domains, but concept/entry saves and imports fail with `validator_unavailable`. Python dependencies are fetched once by `uv sync` during setup.

If `uv` is not installed:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### From a fresh clone

```bash
git clone <your-repository-url> poleq
cd poleq
uv sync
./run.sh
```

Open **http://127.0.0.1:8765** and stop with Ctrl+C. The first launch creates `.data/library.sqlite3` automatically; backups are written under `.data/backups/`. Everything in `.data` is personal/generated data and excluded from Git.

To use another port or library:

```bash
./run.sh --port 8766
POLEQ_DB="$PWD/notes.sqlite3" ./run.sh
```

A checkout uses `.data/library.sqlite3` by default. The CLI defaults to that same file even when invoked from another directory; `POLEQ_DB` or `--db` selects another library. A separately installed wheel without this source project uses `~/.local/share/poleq/library.sqlite3`.

### Use a local model (optional)

Viewing, search, manual editing, export, restore and the CLI work without a model. To enable drafting, install Ollama and pull the default model once:

```bash
ollama pull qwen3:0.6b
./run.sh
```

If Ollama is already listening on the default endpoint, `run.sh` uses it; otherwise it starts an installed Ollama server. Change the model or endpoint with environment variables:

```bash
POLEQ_MODEL=qwen2.5:0.5b ./run.sh
POLEQ_OLLAMA_URL=http://127.0.0.1:11434 ./run.sh
```

See [Local model](#local-model) for the workspace-local runtime and model limitations.

### Rebuild the frontend (only after changing `web/`)

```bash
npm ci
npm run build
```

This regenerates `src/poleq/static`. The generated assets are committed so that other checkouts can run without a frontend build.

### First records

1. Create a domain, such as **Matrices**.
2. Create a concept, such as **Skew-symmetric matrix**, with a definition, at least one domain, and optional aliases.
3. Add an entry, link its concepts, and enter the Markdown body and bare LaTeX statement.
4. Save, then search for it or open its graph node.

The editor can create missing domains and concepts without losing the entry draft. See [Add knowledge](#add-knowledge) for the full workflow.

### Verify the installation

```bash
npm ci       # installs the frontend test dependencies
./check.sh   # runs both test suites
```

`check.sh` runs the Python suite and then `npm test`. To run them separately:

```bash
.venv/bin/python -m unittest discover -s tests -v
npm test
```

The Python suite runs directly after `uv sync`. Node.js 20+ is required for both the LaTeX validator and the frontend tests.

## Interface

Switch light/dark mode from the bottom of the left sidebar, beside the model status. New entry, export, restore and backup actions are also there. The list and selected-record reader scroll independently; the reader stays on the right and becomes a closable side overlay in narrow windows.

Knowledge cards use compact 100 px previews. Their outlines identify the record type; open **Types** for the key. Select a card to read the complete formula and Markdown.

## Add knowledge

1. Create a domain, such as **Matrices**.
2. Create a concept, such as **Skew-symmetric matrix**, with its definition and one or more domains. Add **SSM** as an alias if useful.
3. Add an entry. Select all related concepts, enter your English/Markdown text, and supply a technical LaTeX statement or request a local-model draft.
4. Review the rendered mathematics and save. Missing concepts and domains can be created inside the editor without losing the entry draft.

In the concept editor, enter a name and choose its domains, then use **Draft definition**. It fills the English/Markdown definition and the separate **Technical LaTeX definition** field. Any existing definition or formula supplies optional context; both can be restored after drafting. Review the result, then save. Changing the name, definition, formula or parent domains while the model runs discards the stale draft and preserves your edits.

Every entry has a title, kind, Markdown body, required bare LaTeX statement, and at least one linked concept. Concepts have a name, English/Markdown definition, required bare LaTeX definition, at least one domain, and optional aliases. Domains have a name and optional aliases. IDs and timestamps are maintained automatically.

Use `$...$` for inline math and `$$...$$` or `\[...\]` for display math in Markdown. The separate technical-LaTeX field takes **no enclosing delimiters**. KaTeX validates both the technical statement and recognized math expressions in Markdown. Supported mathematics is [KaTeX's command set](https://katex.org/docs/supported); full LaTeX documents, arbitrary packages and user-defined global macros are outside this format.

The reader sets a display formula one clause per line, centred, and one clause per line is all that is centred: a formula that fits on one line stays flush left and scrolls if it is still too wide. A comma always breaks after `\quad`, `\qquad` or a semicolon, and a bare comma breaks only when both sides carry a relation (`=`, `<`, `\in`, `\implies`, …) or a multi-word `\text{…}`; a list such as `\lambda_1,\lambda_2,\dots,\lambda_n` therefore stays on one line. Commas inside parentheses, brackets, braces, sets, `\left…\right` groups or matrix/cases environments never break. Write `\begin{aligned}…\\…\end{aligned}` yourself to control the layout; such a block is kept intact and can still be separated from clauses that follow it.

Names and aliases are unique within domains and within concepts after Unicode/case/whitespace normalization. Identical entry kind + normalized English body + exact LaTeX cannot be saved twice; update the existing entry's concept links. Different wording or mathematically equivalent formulas are not automatically merged. Syntax/relationship validation establishes record consistency; it does not prove mathematical truth.

Entry titles must differ from the English description, ignoring case, punctuation and whitespace. Generated titles use a concise descriptive label of at most ten words and cannot simply repeat the raw input; the model gets one correction attempt if it fails these checks.

## Search and graph

Search is ranked SQLite FTS5 prefix search across titles, text, formulas, aliases, and linked concept/domain names. Multiple words must all match. Use domains, entry kinds and concept filters together; multiple concept filters support **any** or **all**. Searches are keyword-based rather than semantic/vector search. Results are paginated.

**Opened** restricts results to records you last opened 15–30, 30–45 or 45+ days ago. The windows do not overlap, and the 45+ window also holds records never opened, which are treated as infinitely stale. With this filter active, results are ordered longest-untouched first rather than by rank. A new concept or entry starts its clock at creation; editing a record does not reset it, and only opening it in the reader does. This history is local review state, so it is not written to exports or backups and is cleared when an archive is restored.

The concept graph connects concepts through shared entries. Selecting an edge reveals the actual supporting entries. The domain graph connects domains through shared concepts or cross-domain entries. The hierarchy view displays the actual domain/concept/entry records; no duplicate graph nodes are stored. Select a node to read or edit its record. Focus on one node or domain for larger libraries. The initial graph is limited to 300 nodes with an explicit truncation notice; the saved library and search have no such limit. An accessible connection list accompanies the interactive canvas. Cytoscape renders the graph; D3's force simulation handles springs, repulsion and gravity. Adjust **Gravity** (0–10) to change attraction toward the graph's center: 0 disables that pull, low values leave a loose layout, and high values compact the graph. Changes apply when you release the slider. Dragging moves the node within the ongoing simulation; releasing it allows natural movement without repacking the graph or changing your zoom/pan. **Fit** recenters the viewport. Gravity follows the new arrangement's center after a drag, rather than pulling the graph back to its original position. The simulation sleeps when settled. With reduced motion enabled, dragging stays manual; changing gravity computes a static result on release. Rebuilt script/style URLs include content hashes so reloading picks up the current build.

## Local model

The default is [Qwen3 `0.6b`](https://ollama.com/library/qwen3:0.6b), a general-purpose model with a roughly 523 MB quantized download. The app talks to [Ollama's structured-output API](https://docs.ollama.com/capabilities/structured-outputs), with thinking disabled, a 4096-token context, deterministic sampling and one format-repair attempt. Model output is validated against the same schema and KaTeX renderer as agent/manual input. Selected concept IDs are supplied by the app, not invented by the model. Drafting never saves anything.

If Ollama is installed normally:

```bash
ollama pull qwen3:0.6b
./run.sh
```

This working directory also supports an optional workspace-local CPU runtime in `.runtime/bin/ollama`, with model files in `.data/ollama`. These generated files are not included in the portable knowledge archive or Git. To pull another model into that running runtime, use `.runtime/bin/ollama pull MODEL`.

Change the model without editing code:

```bash
POLEQ_MODEL=qwen2.5:0.5b ./run.sh
```

`POLEQ_OLLAMA_URL` can point the app at another locally configured Ollama endpoint (default `http://127.0.0.1:11434`). The start script manages only the default loopback endpoint. The model is optional for viewing, search, manual editing, structured agent input, export and restore. A small model can omit assumptions or change mathematical meaning; inspect its draft and correct it before saving.

On this laptop, the installed Qwen3 0.6B runtime reported about 1 GB of loaded CPU memory. Small drafts took roughly 1.6–3.7 seconds in spot checks. The skew-symmetric determinant example was usable, but an orthogonal-matrix draft introduced an inconsistent variable and a Hessian draft gave its definition instead of the symmetry property. These are observations from a few examples, not an accuracy benchmark: schema and renderer checks cannot establish mathematical correctness. The editor preserves your original note during drafting and requires an explicit save after review.

## CLI and coding agents

The CLI invokes the same storage/validation code as the API. Its input/output is JSON, with nonzero exit status and JSON stderr on failures. Files may be replaced by `-` for stdin. For a complete runtime agent workflow, HTTP recipes and the error-code table, see [`docs/agent-guide.md`](docs/agent-guide.md). Coding agents working on this repository should read [`AGENTS.md`](AGENTS.md).

```bash
export POLEQ_DB="$PWD/.data/library.sqlite3"
.venv/bin/poleq list domains
.venv/bin/poleq add domains domain.json
.venv/bin/poleq add concepts concept.json
.venv/bin/poleq add entries entry.json
.venv/bin/poleq validate entry.json
.venv/bin/poleq validate --entity concepts concept.json
.venv/bin/poleq search 'SSM determinant' --entity entries
.venv/bin/poleq search --concept CONCEPT_UUID --concept OTHER_UUID --mode all
.venv/bin/poleq get entries ENTRY_UUID
.venv/bin/poleq opened entries ENTRY_UUID
.venv/bin/poleq update entries ENTRY_UUID updated-entry.json
.venv/bin/poleq delete entries ENTRY_UUID --yes
.venv/bin/poleq draft 'An odd-order real skew-symmetric matrix has zero determinant.' --concept CONCEPT_UUID
.venv/bin/poleq draft-concept 'Orthogonal matrix' --domain DOMAIN_UUID --context 'Use real square matrices.'
.venv/bin/poleq graph --level concepts
.venv/bin/poleq model
```

`--compact` is a global option that emits single-line JSON instead of indented JSON, for example `.venv/bin/poleq --compact list domains`. Failures include a stable `code` such as `duplicate_name`, `invalid_latex`, `record_in_use` or `model_unavailable`; argument errors exit 2 and other failures exit 1. `update` accepts the output of `get` directly and strips server-owned fields.

Structured inputs:

```json
{"name":"Matrices","aliases":["Linear algebra"]}
```

```json
{"name":"Skew-symmetric matrix","definition":"A real square matrix whose transpose equals its negative.","latex":"A\\in\\mathbb{R}^{n\\times n},\\quad A^{\\mathsf{T}}=-A","aliases":["SSM"],"domain_ids":["DOMAIN_UUID"]}
```

```json
{"title":"Odd-order skew-symmetric determinant","kind":"property","body":"A real skew-symmetric matrix of odd order has zero determinant.","latex":"A\\in\\mathbb{R}^{n\\times n},\\quad A^{\\mathsf{T}}=-A,\\quad n\\text{ odd}\\implies\\det(A)=0","concept_ids":["CONCEPT_UUID"]}
```

Replace the UUID placeholders with IDs returned by creation/list commands. Unknown fields, malformed IDs, empty parent lists, repeated links, unknown parents, malformed math, and conflicting names/aliases are rejected. Deleting a referenced domain/concept is refused; reassign or delete its dependent records first. All mutations are transactional.

For HTTP agents, start the server and retrieve **`GET /openapi.json`** for machine-readable operations and schemas. The browser and agents use the same local endpoints:

| Operation | Endpoint |
|---|---|
| Domain/concept catalog | `GET /api/catalog` |
| Ranked search and pagination | `GET /api/search?q=...&entity=entries&domain_id=UUID&concept_id=UUID&mode=all&kind=property&stale_days=15&stale_max_days=30&limit=50&offset=0` |
| Create | `POST /api/domains`, `/api/concepts`, `/api/entries` |
| Read/update/delete | `GET`, `PUT`, `DELETE /api/{entity}/{UUID}` |
| Record that a record was opened | `POST /api/{entity}/{UUID}/opened` |
| Validate without saving | `POST /api/validate/entry` |
| Generate a draft | `POST /api/draft` with `text`, `kind`, `concept_ids` |
| Draft a concept definition | `POST /api/draft/concept` with `name`, `domain_ids`, optional `aliases` and `context` |
| Graph | `GET /api/graph?level=concepts&domain_id=UUID&focus=UUID&limit=300` |
| Full archive | `GET /api/export` |
| Restore | `POST /api/import` (explicit `?replace=true` for a nonempty library) |
| Backup / model availability | `POST /api/backup`, `GET /api/model` |

The server binds only to loopback, rejects foreign browser origins for writes, disables raw Markdown HTML, sanitizes rendered HTML, and bundles all frontend assets locally. It is intended for a trusted personal laptop rather than shared/network hosting. No account or paid API is required.

## Portable export, restore and backup

```bash
.venv/bin/poleq export library.json
.venv/bin/poleq --db new-library.sqlite3 import library.json
.venv/bin/poleq import library.json --replace
.venv/bin/poleq backup
.venv/bin/poleq schema > archive.schema.json
```

A single UTF-8 JSON file contains a `format: "poleq"`, `version: 2` envelope and all domain, concept and entry records with original IDs, timestamps, text, separate LaTeX fields, aliases and relationship IDs. Another application can recreate every stored knowledge record without SQLite or PolEQ. Search indexes and graph views are derived from these records and rebuilt on restore.

Version 1 exports predate required concept LaTeX fields. To restore one, add an appropriate `latex` expression to each concept and set `version` to `2`; missing formulas are rejected rather than invented during import. Existing version 1 backup files are retained. Existing concepts without a formula can still be opened in the editor and completed manually or with a reviewed model draft.

Restore validates the complete archive before replacing anything, is atomic, and refuses replacement of a nonempty library without explicit confirmation. An identical existing archive is an idempotent no-op. Broken parent links, duplicate IDs/names, unsupported versions and invalid math reject the whole import. Backup files are portable archives too.

A dated snapshot is saved before the first change each UTC day once the library has content. Every deletion or replacement also saves a separate snapshot. Find them beside the database in `backups/`. Backups are retained until you remove them. Exports and backups are written using a temporary file and atomic rename. There is no per-entry edit history.

## Verify

```bash
npm ci
./check.sh
```

The workflow tests cover shared API/CLI contracts, populated catalogs, persistence, ranked/alias search, any/all filters, disjoint opening-staleness windows, real graph IDs and edge evidence, edit relinking, duplicate and invalid-input rejection, blocked orphaning, exact export/restore, backup preservation, rollback on corrupt imports, browser-origin protection, and LLM repair/failure without database writes. They include a 5,000-entry restore/search check and use temporary databases and a fake model endpoint; actual model output is checked separately. Async API tests need permission for local event-loop sockets in a restricted sandbox.

The design is SQLite + Python's CLI/filesystem tools, FastAPI/Pydantic for the API contract, Markdown-it + its TeX plugin and KaTeX for mathematical formatting, DOMPurify for rendered content, and Cytoscape.js for graph interaction. The interface uses React 18 and Palantir Blueprint 6. There is no graph database, vector database or agent framework. For this personal library, writes rebuild the small FTS index; optimize affected-row updates if measured write latency becomes a problem.
