"""Local API: inspect /openapi.json for the complete agent contract."""
from typing import Annotated, Literal
from uuid import UUID

from fastapi import FastAPI, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .data_model import Archive, Concept, ConceptDraftRequest, Domain, DraftRequest, Entry, Kind
from . import llm
from .store import Problem, STATIC, Store

Entity = Literal["domains", "concepts", "entries"]


def create_app(path=None):
    app = FastAPI(title="PolEQ", version="0.1.0", docs_url=None, redoc_url=None)
    app.state.store = store = Store(path)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"])

    @app.middleware("http")
    async def local_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
                return JSONResponse({"detail": {"code": "forbidden", "message": "Cross-origin writes are disabled"}}, status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": {"code": "forbidden", "message": "Cross-site writes are disabled"}}, status_code=403)
            if request.headers.get("content-length") and int(request.headers["content-length"]) > 20_000_000:
                return JSONResponse({"detail": {"code": "payload_too_large", "message": "Request exceeds 20 MB"}}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    @app.exception_handler(Problem)
    async def problem_handler(request, exc):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status)

    @app.exception_handler(ValidationError)
    async def validation_handler(request, exc):
        return JSONResponse({"detail": {"code": "validation_error", "message": "Invalid record", "errors": exc.errors(include_context=False)}}, status_code=422)

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(request, exc):
        return JSONResponse({"detail": {"code": "validation_error", "message": "Invalid request", "errors": jsonable_encoder(exc.errors())}}, status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request, exc):
        detail = exc.detail
        if not isinstance(detail, dict):
            detail = {"code": "not_found" if exc.status_code == 404 else "http_error", "message": str(detail)}
        return JSONResponse({"detail": detail}, status_code=exc.status_code, headers=exc.headers)

    @app.get("/api/health")
    def health():
        return {"ok": True, "counts": {e: len(store.list(e)) for e in ("domains", "concepts", "entries")}}

    @app.get("/api/catalog")
    def catalog():
        return {e: store.list(e) for e in ("domains", "concepts")}

    @app.get("/api/search")
    def search(q: str = Query("", max_length=2000), entity: Entity | None = None, domain_id: Annotated[list[UUID] | None, Query()] = None,
               concept_id: Annotated[list[UUID] | None, Query()] = None, mode: Literal["any", "all"] = "any",
               kind: Kind | None = None, stale_days: int | None = Query(None, ge=0, le=36500),
               stale_max_days: int | None = Query(None, ge=1, le=36500),
               limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
        return store.search(q, entity, domain_id or (), concept_id or (), mode, kind, limit, offset, stale_days, stale_max_days)

    @app.get("/api/graph")
    def graph(level: Literal["concepts", "domains", "hierarchy"] = "concepts", domain_id: UUID | None = None,
              focus: UUID | None = None, limit: int = Query(300, ge=1, le=600)):
        return store.graph(level, domain_id, focus, limit)

    @app.get("/api/export")
    def export():
        return JSONResponse(store.export(), headers={"Content-Disposition": 'attachment; filename="poleq-library.json"'})

    @app.post("/api/import")
    def restore(archive: Archive, replace: bool = False):
        return store.restore(archive.model_dump(mode="json"), replace)

    @app.post("/api/backup")
    def backup():
        return {"path": store.backup()}

    @app.get("/api/model")
    def model_status():
        return llm.status()

    @app.post("/api/draft")
    def draft(request: DraftRequest):
        return llm.draft(store, request)

    @app.post("/api/draft/concept")
    def draft_concept(request: ConceptDraftRequest):
        return llm.draft_concept(store, request)

    @app.post("/api/validate/entry")
    def validate(entry: Entry):
        validated = store._check("entries", entry.model_dump(mode="json"))
        for cid in entry.concept_ids:
            store.get("concepts", cid)
        return {"valid": True, "entry": validated}

    @app.post("/api/domains", status_code=201)
    def add_domain(domain: Domain):
        return store.save("domains", domain.model_dump(mode="json"))

    @app.put("/api/domains/{record_id}")
    def update_domain(record_id: UUID, domain: Domain):
        return store.save("domains", domain.model_dump(mode="json"), record_id)

    @app.post("/api/concepts", status_code=201)
    def add_concept(concept: Concept):
        return store.save("concepts", concept.model_dump(mode="json"))

    @app.put("/api/concepts/{record_id}")
    def update_concept(record_id: UUID, concept: Concept):
        return store.save("concepts", concept.model_dump(mode="json"), record_id)

    @app.post("/api/entries", status_code=201)
    def add_entry(entry: Entry):
        return store.save("entries", entry.model_dump(mode="json"))

    @app.put("/api/entries/{record_id}")
    def update_entry(record_id: UUID, entry: Entry):
        return store.save("entries", entry.model_dump(mode="json"), record_id)

    @app.get("/api/{entity}/{record_id}")
    def get(entity: Entity, record_id: UUID):
        record = store.get(entity, record_id)
        if entity != "domains":
            record["last_opened_at"] = store.opened_at(entity, record_id)
        return record

    @app.post("/api/{entity}/{record_id}/opened")
    def opened(entity: Entity, record_id: UUID):
        return store.mark_opened(entity, record_id)

    @app.delete("/api/{entity}/{record_id}", status_code=204)
    def delete(entity: Entity, record_id: UUID):
        store.delete(entity, record_id)

    @app.get("/")
    def home():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
