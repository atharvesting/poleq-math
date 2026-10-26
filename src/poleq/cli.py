"""JSON-first CLI. Every command works without the web server."""
import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from .store import MODELS, Problem, Store, atomic_json


def read_json(path):
    return json.loads(sys.stdin.read() if path == "-" else Path(path).read_text())


class JsonArgumentParser(argparse.ArgumentParser):
    """Keep even argument errors machine-readable."""

    def error(self, message):
        self.exit(2, json.dumps({"error": {"code": "invalid_arguments", "message": message}}, ensure_ascii=False) + "\n")


def main(argv=None):
    parser = JsonArgumentParser(prog="poleq", description="Offline mathematics knowledge base. JSON output is agent-friendly.")
    parser.add_argument("--db", help="SQLite path (default: POLEQ_DB or this project's .data/library.sqlite3)")
    parser.add_argument("--compact", action="store_true", help="Emit single-line JSON instead of indented JSON")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Open the local web app and API")
    serve.add_argument("--port", type=int, default=8765)
    for command in ["add", "update"]:
        p = sub.add_parser(command, help="Validate and save a structured JSON record")
        p.add_argument("entity", choices=MODELS)
        if command == "update":
            p.add_argument("id", type=UUID)
        p.add_argument("file", help="JSON file, or - for stdin")
    for command in ["get", "delete"]:
        p = sub.add_parser(command)
        p.add_argument("entity", choices=MODELS)
        p.add_argument("id", type=UUID)
        if command == "delete":
            p.add_argument("--yes", action="store_true", help="Confirm deletion; a backup is saved first")
    p = sub.add_parser("list")
    p.add_argument("entity", choices=MODELS)
    p = sub.add_parser("opened", help="Record that a concept or entry was opened; feeds the staleness filter")
    p.add_argument("entity", choices=["concepts", "entries"])
    p.add_argument("id", type=UUID)
    p = sub.add_parser("search")
    p.add_argument("query", nargs="?", default="")
    p.add_argument("--entity", choices=MODELS)
    p.add_argument("--domain", type=UUID, action="append", default=[])
    p.add_argument("--concept", type=UUID, action="append", default=[])
    p.add_argument("--mode", choices=["any", "all"], default="any")
    p.add_argument("--kind", choices=["property", "proof", "equivalence", "note"])
    p.add_argument("--stale", type=int, metavar="DAYS", help="Only records not opened for at least DAYS")
    p.add_argument("--stale-max", type=int, metavar="DAYS", help="Exclusive upper bound; excludes never-opened records")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--offset", type=int, default=0)
    p = sub.add_parser("graph")
    p.add_argument("--level", choices=["concepts", "domains", "hierarchy"], default="concepts")
    p.add_argument("--domain", type=UUID)
    p.add_argument("--focus", type=UUID)
    p = sub.add_parser("export")
    p.add_argument("file", nargs="?", default="-")
    p = sub.add_parser("import")
    p.add_argument("file")
    p.add_argument("--replace", action="store_true", help="Replace this library after saving a backup")
    sub.add_parser("backup")
    sub.add_parser("model", help="Check the configured local Ollama model")
    p = sub.add_parser("draft", help="Generate a reviewed-later entry; does not save it")
    p.add_argument("text", help="Raw text, or - for stdin")
    p.add_argument("--concept", type=UUID, action="append", required=True)
    p.add_argument("--kind", choices=["property", "proof", "equivalence", "note"], default="property")
    p = sub.add_parser("draft-concept", help="Draft an English/LaTeX concept definition without saving")
    p.add_argument("name")
    p.add_argument("--domain", type=UUID, action="append", required=True)
    p.add_argument("--context", default="", help="Optional existing definition or constraints")
    p = sub.add_parser("validate", help="Validate a structured record without saving")
    p.add_argument("file")
    p.add_argument("--entity", choices=MODELS, default="entries", help="Record kind to validate (default: entries)")
    sub.add_parser("schema", help="JSON Schema for the portable archive")
    args = parser.parse_args(argv)
    try:
        store = Store(args.db)
        match args.command:
            case "serve":
                import uvicorn
                from .api import create_app
                print(f"PolEQ: http://127.0.0.1:{args.port}", file=sys.stderr)
                uvicorn.run(create_app(store.path), host="127.0.0.1", port=args.port)
                return
            case "add" | "update":
                data = read_json(args.file)
                if args.command == "update" and isinstance(data, dict):
                    # GET output can be edited and fed back to update unchanged.
                    data = {key: value for key, value in data.items() if key not in {"id", "created_at", "updated_at", "last_opened_at"}}
                result = store.save(args.entity, data, getattr(args, "id", None))
            case "get":
                result = store.get(args.entity, args.id)
                if args.entity != "domains":
                    result["last_opened_at"] = store.opened_at(args.entity, args.id)
            case "opened":
                result = store.mark_opened(args.entity, args.id)
            case "delete":
                if not args.yes:
                    raise Problem("Use --yes to confirm deletion. A backup will be saved first.", code="confirmation_required")
                store.delete(args.entity, args.id)
                result = {"deleted": str(args.id)}
            case "list":
                result = store.list(args.entity)
            case "search":
                if not 1 <= args.limit <= 500 or args.offset < 0 or (args.stale is not None and args.stale < 0):
                    raise Problem("Limit must be 1–500, offset and staleness must be nonnegative", code="invalid_range")
                result = store.search(args.query, args.entity, args.domain, args.concept, args.mode, args.kind, args.limit, args.offset, args.stale, args.stale_max)
            case "graph":
                result = store.graph(args.level, args.domain, args.focus)
            case "export":
                result = store.export()
                if args.file != "-":
                    atomic_json(args.file, result)
                    result = {"exported": str(Path(args.file).resolve())}
            case "import":
                result = store.restore(read_json(args.file), args.replace)
            case "backup":
                result = {"path": store.backup()}
            case "model":
                from .llm import status
                result = status()
            case "draft":
                from .llm import draft
                result = draft(store, {"text": sys.stdin.read() if args.text == "-" else args.text, "kind": args.kind, "concept_ids": args.concept})
            case "draft-concept":
                from .llm import draft_concept
                result = draft_concept(store, {"name": args.name, "domain_ids": args.domain, "context": args.context})
            case "validate":
                result = store._check(args.entity, read_json(args.file))
                if args.entity == "entries":
                    for cid in result["concept_ids"]:
                        store.get("concepts", cid)
                elif args.entity == "concepts":
                    for did in result["domain_ids"]:
                        store.get("domains", did)
                result = {"valid": True, "entity": args.entity, "record": result}
            case "schema":
                from .data_model import Archive
                result = Archive.model_json_schema()
        print(json.dumps(result, ensure_ascii=False, indent=None if args.compact else 2, default=str))
    except Exception as exc:
        if isinstance(exc, Problem):
            detail = exc.detail
        elif isinstance(exc, ValidationError):
            detail = {"code": "validation_error", "message": "Invalid record", "errors": exc.errors(include_context=False)}
        elif isinstance(exc, ValueError):
            detail = {"code": "invalid_input", "message": str(exc)}
        elif isinstance(exc, OSError):
            detail = {"code": "io_error", "message": str(exc)}
        else:
            detail = {"code": "internal_error", "message": str(exc), "type": type(exc).__name__}
        print(json.dumps({"error": detail}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
