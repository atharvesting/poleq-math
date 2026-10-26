"""SQLite records, derived relationships, full-text search and portable backups."""
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from hashlib import sha256
from itertools import combinations
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
import unicodedata
from uuid import uuid4

from .data_model import Archive, Concept, Domain, Entry

MODELS = {"domains": Domain, "concepts": Concept, "entries": Entry}
STATIC = Path(__file__).parent / "static"


class Problem(Exception):
    """A machine-readable failure shared by the CLI and the HTTP API."""

    DEFAULT_CODES = {
        400: "bad_request",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        413: "payload_too_large",
        422: "invalid",
        502: "upstream_error",
        503: "unavailable",
    }

    def __init__(self, message, status=422, code=None, **details):
        self.code = code or self.DEFAULT_CODES.get(status, "error")
        self.detail = {"code": self.code, "message": message, **details}
        self.status = status
        super().__init__(message)


def normalized(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def age_days(stamp, now=None):
    """Whole days since an ISO timestamp; naive values are treated as UTC."""
    moment = datetime.fromisoformat(stamp)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return ((now or datetime.now(timezone.utc)) - moment).total_seconds() / 86400


def check_math_many(records):
    try:
        result = subprocess.run(
            ["node", str(STATIC / "validate.cjs")],
            input=json.dumps(records),
            text=True, capture_output=True, timeout=15, check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise Problem("LaTeX validator unavailable. Install Node.js and run npm run build.", 503, "validator_unavailable") from exc
    for index, errors in enumerate(json.loads(result.stdout)):
        if errors:
            raise Problem("LaTeX cannot be rendered. Correct the expression before saving.", code="invalid_latex", errors=errors, record_index=index)


@lru_cache(maxsize=512)
def check_math(body, latex):
    check_math_many([{"body": body, "latex": latex}])


def atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".poleq-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class Store:
    def __init__(self, path=None):
        source_root = Path(__file__).resolve().parents[2]
        default = source_root / ".data/library.sqlite3" if (source_root / "pyproject.toml").is_file() else Path.home() / ".local/share/poleq/library.sqlite3"
        self.path = Path(path or os.environ.get("POLEQ_DB", default)).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS records (
                    id TEXT PRIMARY KEY, entity TEXT NOT NULL,
                    payload TEXT NOT NULL, fingerprint TEXT UNIQUE
                );
                CREATE TABLE IF NOT EXISTS terms (
                    entity TEXT NOT NULL, term TEXT NOT NULL,
                    record_id TEXT NOT NULL REFERENCES records(id) ON DELETE CASCADE,
                    PRIMARY KEY(entity, term)
                );
                CREATE TABLE IF NOT EXISTS links (
                    child TEXT NOT NULL REFERENCES records(id) ON DELETE CASCADE,
                    parent TEXT NOT NULL REFERENCES records(id) ON DELETE RESTRICT,
                    PRIMARY KEY(child, parent)
                );
                CREATE INDEX IF NOT EXISTS links_parent ON links(parent);
                CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(id UNINDEXED, label, content, tokenize='unicode61');
                CREATE TABLE IF NOT EXISTS opened (
                    record_id TEXT PRIMARY KEY REFERENCES records(id) ON DELETE CASCADE,
                    at TEXT NOT NULL
                );
                PRAGMA user_version=2;
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.execute("PRAGMA foreign_keys=ON")
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    def _archive(self, db):
        result = {"format": "poleq", "version": 2, **{key: [] for key in MODELS}}
        for row in db.execute("SELECT entity,payload FROM records ORDER BY id"):
            result[row["entity"]].append(json.loads(row["payload"]))
        if any(not c.get("latex") for c in result["concepts"]):
            result["version"] = 1
        return result

    def export(self):
        with self.connection() as db:
            return self._archive(db)

    def _backup(self, db, forced=False):
        if not db.execute("SELECT 1 FROM records LIMIT 1").fetchone():
            return None
        directory = self.path.parent / "backups"
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S-%f" if forced else "%Y-%m-%d")
        path = directory / f"poleq-{stamp}.json"
        if forced or not path.exists():
            atomic_json(path, self._archive(db))
        # ponytail: retain daily snapshots indefinitely; add a retention policy if disk usage matters.
        return str(path)

    def backup(self):
        with self.connection() as db:
            return self._backup(db, forced=True)

    def get(self, entity, record_id):
        with self.connection() as db:
            return self._get(db, entity, str(record_id))

    def _get(self, db, entity, record_id):
        row = db.execute("SELECT payload FROM records WHERE entity=? AND id=?", (entity, record_id)).fetchone()
        if not row:
            raise Problem("Record not found", 404, "not_found", record_id=str(record_id), entity=entity)
        return json.loads(row[0])

    def opened_at(self, entity, record_id):
        if entity not in {"concepts", "entries"}:
            return None
        with self.connection() as db:
            row = db.execute("SELECT at FROM opened WHERE record_id=?", (str(record_id),)).fetchone()
            return row[0] if row else None

    def mark_opened(self, entity, record_id, at=None):
        """Record a deliberate visit; used only for staleness review, never for search ranking."""
        if entity not in {"concepts", "entries"}:
            raise Problem("Only concepts and entries track when they were last opened", code="invalid_entity", entity=entity)
        if at is not None:
            try:
                datetime.fromisoformat(at)
            except ValueError as exc:
                raise Problem("Provide an ISO timestamp", code="invalid_timestamp") from exc
        with self.connection() as db:
            self._get(db, entity, str(record_id))
            at = at or datetime.now(timezone.utc).isoformat()
            db.execute("""INSERT INTO opened(record_id,at) VALUES (?,?)
                ON CONFLICT(record_id) DO UPDATE SET at=excluded.at""", (str(record_id), at))
            db.commit()
            return {"id": str(record_id), "entity": entity, "last_opened_at": at}

    def list(self, entity):
        with self.connection() as db:
            rows = db.execute("SELECT payload FROM records WHERE entity=? ORDER BY coalesce(json_extract(payload,'$.name'),json_extract(payload,'$.title')) COLLATE NOCASE, id", (entity,))
            return [json.loads(row[0]) for row in rows]

    def _check(self, entity, data, validate_math=True):
        validated = MODELS[entity].model_validate(data).model_dump(mode="json")
        if entity in {"concepts", "entries"}:
            if validated["latex"].startswith(("$", r"\[", r"\(")):
                raise Problem("The LaTeX field takes a bare expression, without math delimiters", code="invalid_latex")
            if validate_math:
                check_math(validated.get("body", validated.get("definition", "")), validated["latex"])
        return validated

    def _write(self, db, entity, record):
        record_id = record["id"]
        if entity == "entries":
            # Exact normalized content deduplication; mathematical equivalence needs human review.
            identity = [record["kind"], " ".join(unicodedata.normalize("NFKC", record["body"]).split()), record["latex"].strip()]
            fingerprint = sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
            terms = []
        else:
            fingerprint = None
            terms = [normalized(record["name"]), *map(normalized, record["aliases"])]
            if len(terms) != len(set(terms)):
                raise Problem("Name and aliases must be distinct", code="duplicate_name", field="name")
        for term in terms:
            existing = db.execute("SELECT record_id FROM terms WHERE entity=? AND term=? AND record_id!=?", (entity, term, record_id)).fetchone()
            if existing:
                raise Problem("That name or alias already belongs to a saved record", 409, "duplicate_name", existing_id=existing[0])
        if fingerprint:
            existing = db.execute("SELECT id FROM records WHERE fingerprint=? AND id!=?", (fingerprint, record_id)).fetchone()
            if existing:
                raise Problem("This entry already exists. Edit its concept links instead of making a copy.", 409, "duplicate_entry", existing_id=existing[0])
        parents = record.get("concept_ids", record.get("domain_ids", []))
        parent_entity = "concepts" if entity == "entries" else "domains"
        for parent in parents:
            self._get(db, parent_entity, parent)
        db.execute("""INSERT INTO records(id,entity,payload,fingerprint) VALUES (?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, fingerprint=excluded.fingerprint""",
            (record_id, entity, json.dumps(record, ensure_ascii=False), fingerprint))
        db.execute("DELETE FROM terms WHERE record_id=?", (record_id,))
        db.executemany("INSERT INTO terms VALUES (?,?,?)", [(entity, term, record_id) for term in terms])
        db.execute("DELETE FROM links WHERE child=?", (record_id,))
        db.executemany("INSERT INTO links VALUES (?,?)", [(record_id, parent) for parent in parents])

    def _reindex(self, db):
        # ponytail: rebuild the small library's index after writes; update affected rows if writes become slow.
        records = {row["id"]: (row["entity"], json.loads(row["payload"])) for row in db.execute("SELECT * FROM records")}
        db.execute("DELETE FROM search")
        for record_id, (entity, data) in records.items():
            related = list(data.get("concept_ids", data.get("domain_ids", [])))
            if entity == "entries":
                related += [domain for concept in data["concept_ids"] for domain in records[concept][1]["domain_ids"]]
            text = [data.get("body", data.get("definition", "")), data.get("latex", ""), *data.get("aliases", [])]
            for parent in set(related):
                text += [records[parent][1]["name"], *records[parent][1]["aliases"]]
            db.execute("INSERT INTO search VALUES (?,?,?)", (record_id, normalized(data.get("title", data.get("name"))), normalized("\n".join(text))))

    def save(self, entity, data, record_id=None):
        data = self._check(entity, data)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                self._backup(db)
                now = datetime.now(timezone.utc).isoformat()
                created = self._get(db, entity, str(record_id))["created_at"] if record_id else now
                record = {**data, "id": str(record_id or uuid4()), "created_at": created, "updated_at": now}
                self._write(db, entity, record)
                if not record_id and entity in {"concepts", "entries"}:
                    # A new record has just been seen; before this it was in no review state at all.
                    db.execute("INSERT INTO opened(record_id,at) VALUES (?,?)", (record["id"], now))
                self._reindex(db)
                db.commit()
                return record
            except BaseException:
                db.rollback()
                raise

    def delete(self, entity, record_id):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                self._get(db, entity, str(record_id))
                used = db.execute("SELECT child FROM links WHERE parent=?", (str(record_id),)).fetchall()
                if used:
                    raise Problem("This record is still linked. Edit or delete the dependent records first.", 409, "record_in_use", dependent_ids=[row[0] for row in used])
                self._backup(db, forced=True)
                db.execute("DELETE FROM records WHERE id=?", (str(record_id),))
                self._reindex(db)
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def restore(self, payload, replace=False):
        archive = Archive.model_validate(payload).model_dump(mode="json")
        records = [r for entity in MODELS for r in archive[entity]]
        if len({r["id"] for r in records}) != len(records):
            raise Problem("Archive contains duplicate record IDs", code="invalid_archive")
        for entity in MODELS:
            for record in archive[entity]:
                self._check(entity, {k: v for k, v in record.items() if k not in {"id", "created_at", "updated_at"}}, validate_math=False)
        math_records = [*archive["concepts"], *archive["entries"]]
        for start in range(0, len(math_records), 256):
            check_math_many(math_records[start:start+256])
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                if not replace and db.execute("SELECT 1 FROM records LIMIT 1").fetchone():
                    if self._archive(db) == archive:
                        db.rollback()
                        return {"restored": len(records), "unchanged": True}
                    raise Problem("Library is not empty. Explicitly request replacement; a backup is created first.", 409, "replace_required")
                self._backup(db, forced=True)
                db.execute("DELETE FROM links")
                db.execute("DELETE FROM records")
                for entity in MODELS:
                    for record in archive[entity]:
                        self._write(db, entity, record)
                self._reindex(db)
                db.commit()
                return {"restored": len(records), "unchanged": False}
            except BaseException:
                db.rollback()
                raise

    def search(self, q="", entity=None, domain_ids=(), concept_ids=(), mode="any", kind=None, limit=50, offset=0,
               stale_days=None, stale_max_days=None):
        if stale_days is not None and stale_max_days is not None and stale_max_days <= stale_days:
            raise Problem("The staleness range must end after it begins", code="invalid_range")
        stale = stale_days is not None or stale_max_days is not None
        now = datetime.now(timezone.utc)
        domain_ids, concept_ids = set(map(str, domain_ids)), set(map(str, concept_ids))
        with self.connection() as db:
            catalog = self._archive(db)
            concepts = {c["id"]: c for c in catalog["concepts"]}
            records = {r["id"]: (e, r) for e in MODELS for r in catalog[e]}
            opened = {row["record_id"]: row["at"] for row in db.execute("SELECT record_id,at FROM opened")}
            words = re.findall(r"\w+", normalized(q), re.UNICODE)
            if words:
                match = " AND ".join('"' + word.replace('"', '""') + '"*' for word in words)
                ids = [r[0] for r in db.execute("SELECT id FROM search WHERE search MATCH ? ORDER BY bm25(search,0,5,1)", (match,))]
            elif q.strip():
                ids = [r[0] for r in db.execute("SELECT id FROM search WHERE instr(content,?)>0 OR instr(label,?)>0", (q, q))]
            else:
                ids = sorted(records, key=lambda i: records[i][1]["updated_at"], reverse=True)
            items = []
            for record_id in ids:
                e, record = records[record_id]
                if entity and e != entity or kind and (e != "entries" or record["kind"] != kind):
                    continue
                if stale and e == "domains":
                    continue
                cids = set(record.get("concept_ids", [record_id] if e == "concepts" else []))
                dids = set(record.get("domain_ids", [record_id] if e == "domains" else []))
                if e == "entries":
                    dids = {d for c in cids for d in concepts[c]["domain_ids"]}
                if domain_ids and not dids & domain_ids:
                    continue
                if concept_ids and (not cids & concept_ids if mode == "any" else not concept_ids <= cids):
                    continue
                last_opened = opened.get(record_id)
                if stale:
                    # Never opened is infinitely stale: it satisfies a lower bound but no upper one.
                    age = None if last_opened is None else age_days(last_opened, now)
                    if age is None:
                        if stale_max_days is not None:
                            continue
                    elif stale_days is not None and age < stale_days:
                        continue
                    elif stale_max_days is not None and age >= stale_max_days:
                        continue
                items.append({"entity": e, "record": record, "last_opened_at": last_opened})
            if stale:
                # Review order: longest untouched first, records never opened ahead of them.
                items.sort(key=lambda item: float("-inf") if item["last_opened_at"] is None else -age_days(item["last_opened_at"], now))
            return {"items": items[offset:offset+limit], "total": len(items)}

    def graph(self, level="concepts", domain_id=None, focus=None, limit=300):
        archive = self.export()
        domains = {r["id"]: r for r in archive["domains"]}
        concepts = {r["id"]: r for r in archive["concepts"] if not domain_id or str(domain_id) in r["domain_ids"]}
        entries = [r for r in archive["entries"] if set(r["concept_ids"]) & concepts.keys()]
        nodes, edges = {}, {}

        def node(entity, r):
            nodes[r["id"]] = {"data": {"id": r["id"], "label": r.get("name", r.get("title")), "entity": entity}}

        def edge(a, b, entry_ids=(), concept_ids=()):
            if a == b:
                return
            a, b = sorted((a, b))
            key = (a, b)
            if key not in edges:
                edges[key] = {"id": f"{a}:{b}", "source": a, "target": b, "entry_ids": set(), "concept_ids": set()}
            edges[key]["entry_ids"].update(entry_ids)
            edges[key]["concept_ids"].update(concept_ids)

        if level == "domains":
            for d in domains.values():
                node("domains", d)
            for c in concepts.values():
                for a, b in combinations(c["domain_ids"], 2):
                    edge(a, b, concept_ids=[c["id"]])
            for entry in entries:
                dids = sorted({d for c in entry["concept_ids"] if c in concepts for d in concepts[c]["domain_ids"]})
                for a, b in combinations(dids, 2):
                    edge(a, b, entry_ids=[entry["id"]])
        else:
            for c in concepts.values():
                node("concepts", c)
            if level == "hierarchy":
                for c in concepts.values():
                    for did in c["domain_ids"]:
                        node("domains", domains[did])
                        edge(c["id"], did)
                for entry in entries:
                    node("entries", entry)
                    for cid in entry["concept_ids"]:
                        if cid in concepts:
                            edge(entry["id"], cid)
            else:
                for entry in entries:
                    for a, b in combinations(sorted(set(entry["concept_ids"]) & concepts.keys()), 2):
                        edge(a, b, entry_ids=[entry["id"]])
        if focus:
            focus = str(focus)
            keep = {focus}
            for a, b in edges:
                if focus in (a, b):
                    keep.update((a, b))
            nodes = {i: n for i, n in nodes.items() if i in keep}
        total = len(nodes)
        nodes = dict(list(nodes.items())[:limit])
        elements = list(nodes.values())
        for (a, b), data in edges.items():
            if a in nodes and b in nodes:
                data["entry_ids"] = sorted(data["entry_ids"])
                data["concept_ids"] = sorted(data["concept_ids"])
                data["weight"] = max(1, len(data["entry_ids"]) + len(data["concept_ids"]))
                elements.append({"data": data})
        return {"elements": elements, "total_nodes": total, "shown_nodes": len(nodes), "truncated": total > limit}
