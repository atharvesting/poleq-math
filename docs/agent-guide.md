# Agent guide

PolEQ is a local, offline knowledge base for mathematics. Agents can use the same JSON CLI and HTTP API as the browser. Both routes share one validation and storage layer, so a record accepted by one is accepted by the other.

For coding agents changing this repository, read [`AGENTS.md`](../AGENTS.md) instead.

## Before you start

From the repository root:

```bash
uv sync
export POLEQ_DB="$PWD/.data/library.sqlite3"
POLEQ=.venv/bin/poleq
```

Node.js 20+ must be on `PATH`: every save validates LaTeX with the bundled `src/poleq/static/validate.cjs`. Ollama is optional and only needed for drafting.

Do not write to `.data/library.sqlite3` with SQL or another program. Use the CLI or API so validation, indexing, backups and referential integrity stay consistent.

## Discover the contract

```bash
"$POLEQ" --compact list domains
"$POLEQ" --compact list concepts
"$POLEQ" --compact search 'skew determinant' --entity entries
"$POLEQ" --compact graph --level concepts
"$POLEQ" schema
```

`--compact` emits single-line JSON to reduce tokens. It is a global option and must come before the command.

For HTTP, start `./run.sh` and use:

- `GET http://127.0.0.1:8765/api/health` — readiness and record counts
- `GET http://127.0.0.1:8765/api/catalog` — all domains and concepts
- `GET http://127.0.0.1:8765/openapi.json` — complete machine-readable contract
- `GET http://127.0.0.1:8765/api/search?...` — the same search as the CLI

The server binds only to loopback and has no authentication. Do not expose it to a network.

## Minimal create workflow

Names and aliases are unique after Unicode, case and whitespace normalization. List first, then create only what is missing. Parent IDs are UUIDs returned by the server; never invent them.

1. Create a domain:

```json
{"name": "Matrices", "aliases": ["Linear algebra"]}
```

```bash
"$POLEQ" --compact add domains domain.json
```

2. Create a concept using the returned domain `id`:

```json
{
  "name": "Skew-symmetric matrix",
  "definition": "A real square matrix whose transpose equals its negative.",
  "latex": "A\\in\\mathbb{R}^{n\\times n},\\quad A^{\\mathsf{T}}=-A",
  "aliases": ["SSM"],
  "domain_ids": ["DOMAIN_UUID"]
}
```

```bash
"$POLEQ" --compact add concepts concept.json
```

3. Validate an entry without saving it:

```json
{
  "title": "Odd-order skew-symmetric determinant",
  "kind": "property",
  "body": "A real skew-symmetric matrix of odd order has zero determinant.",
  "latex": "A\\in\\mathbb{R}^{n\\times n},\\quad A^{\\mathsf{T}}=-A,\\quad n\\text{ odd}\\implies\\det(A)=0",
  "concept_ids": ["CONCEPT_UUID"]
}
```

```bash
"$POLEQ" --compact validate entry.json
"$POLEQ" --compact add entries entry.json
```

`validate` accepts `--entity domains|concepts|entries` and defaults to `entries`. It performs the same schema, parent-link and KaTeX checks as a save, but writes nothing.

To capture generated IDs without `jq`:

```bash
DOMAIN_ID=$("$POLEQ" --compact add domains domain.json | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
```

## Update safely

`get` returns the complete stored record, including `id`, `created_at`, `updated_at` and, for concepts and entries, `last_opened_at`. The CLI `update` command strips those server-owned fields, so this round trip is valid:

```bash
"$POLEQ" --compact get entries ENTRY_UUID > entry.json
# Edit title, body, latex or concept_ids.
"$POLEQ" --compact update entries ENTRY_UUID entry.json
```

For HTTP, remove `id`, `created_at`, `updated_at` and `last_opened_at` before `PUT`; the request models reject unknown fields. Re-read immediately before updating. Writes are transactional, but concurrent updates use last-write-wins rather than optimistic locking.

Deletion is intentionally harder:

```bash
"$POLEQ" --compact delete entries ENTRY_UUID --yes
```

A backup is written first. Domains and concepts that still have dependents cannot be deleted; reassign or delete the dependents first. The error includes `dependent_ids`.

## Draft with the local model

Drafting is optional and never saves anything. Inspect `needs_review` and the returned record before saving it.

```bash
"$POLEQ" --compact draft 'A real skew-symmetric matrix of odd order has zero determinant.' --concept CONCEPT_UUID
"$POLEQ" --compact draft-concept 'Orthogonal matrix' --domain DOMAIN_UUID --context 'Use real square matrices.'
"$POLEQ" --compact model
```

If Ollama is unavailable, `model_unavailable` is returned with a hint. Manual entry still works.

## HTTP recipes

Create a domain:

```bash
curl -sS -X POST http://127.0.0.1:8765/api/domains \
  -H 'Content-Type: application/json' \
  --data-binary @domain.json
```

Search with filters:

```bash
curl -sS 'http://127.0.0.1:8765/api/search?q=determinant&entity=entries&kind=property&limit=20&offset=0'
```

Validate an entry without saving:

```bash
curl -sS -X POST http://127.0.0.1:8765/api/validate/entry \
  -H 'Content-Type: application/json' \
  --data-binary @entry.json
```

`POST /api/import?replace=true` replaces a nonempty library after saving a backup. Export before any bulk replacement.

## Errors are machine-readable

The CLI writes JSON to stderr and exits nonzero:

```json
{"error": {"code": "duplicate_name", "message": "That name or alias already belongs to a saved record", "existing_id": "UUID"}}
```

The API uses the same `detail` object with an HTTP status:

```json
{"detail": {"code": "validation_error", "message": "Invalid record", "errors": []}}
```

Argument-parsing failures exit `2` with `invalid_arguments`. Other failures exit `1`.

| Code | Meaning and recovery |
|---|---|
| `validation_error` | Schema or field validation failed. Read `errors`; remove unknown fields. |
| `invalid_input` | A supplied value cannot be parsed or used. |
| `invalid_arguments` | CLI flags or subcommand are wrong. Check `--help`. |
| `not_found` | Record ID does not exist. Re-list the catalog. |
| `duplicate_name` | Name or alias is taken. Reuse `existing_id` or choose another. |
| `duplicate_entry` | Same kind, normalized body and LaTeX already exist. Update `existing_id`. |
| `record_in_use` | A parent still has dependents. Delete or relink `dependent_ids` first. |
| `invalid_latex` | KaTeX rejected a formula. Fix `errors`; keep the field bare, without `$`. |
| `validator_unavailable` | Node.js or the bundled validator is missing. Install Node 20+. |
| `replace_required` | Import target is nonempty. Export first, then pass `true`. |
| `invalid_archive` | Export envelope is malformed or has duplicate IDs. |
| `confirmation_required` | Pass `--yes` to confirm a deletion. |
| `invalid_range` | Search limit, offset or staleness range is out of bounds. |
| `invalid_entity` | Only concepts and entries track `opened` timestamps. |
| `invalid_timestamp` | `opened` received a non-ISO timestamp. |
| `invalid_title` | Draft title repeats the input or exceeds 10 words. |
| `invalid_draft` | The model produced an invalid draft after one repair attempt. |
| `model_unavailable` | Ollama is down or the model is not pulled. Manual entry works. |
| `model_response_invalid` | Ollama returned an unexpected response. |
| `forbidden` | Cross-origin or cross-site write rejected by the local server. |
| `payload_too_large` | Request body exceeds 20 MB. |
| `io_error` | A referenced file could not be read or written. |
| `internal_error` | Unexpected failure. Include `type` in a bug report. |

## Rules that prevent silent data loss

- Keep `latex` fields bare: no `$...$`, `\[...\]` or `\(...\)` delimiters.
- Use `$...$`, `$$...$$` or `\[...\]` only inside Markdown `body` and `definition`.
- Titles must be descriptive and must not repeat the body after case/punctuation/whitespace normalization.
- Concepts require at least one domain; entries require at least one concept.
- Unknown JSON fields are rejected rather than ignored.
- IDs, timestamps and graph edges are server-generated; never edit them.
- `.data` is ignored by Git and contains the personal library, backups and downloaded models. Never commit it.
