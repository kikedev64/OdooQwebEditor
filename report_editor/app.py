import base64
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import demo
from .project import DockerOdooClient, export_template

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="QWeb Studio local")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@dataclass
class Session:
    client: DockerOdooClient | None = None
    source: str = demo.TEMPLATE
    revision: int = 1
    touched: float = field(default_factory=time.monotonic)
    lock: threading.Lock = field(default_factory=threading.Lock)
    pdf: bytes | None = None
    pdf_token: str = ""


sessions: dict[str, Session] = {}
sessions_lock = threading.Lock()


@app.middleware("http")
async def local_requests(request: Request, call_next):
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if (origin and origin != str(request.base_url).rstrip("/")) or request.headers.get("x-editor-request") != "1":
            return JSONResponse({"detail": "Petición externa rechazada."}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


def session(request: Request, response: Response):
    now = time.monotonic()
    with sessions_lock:
        for token in list(sessions):
            if now - sessions[token].touched > 8 * 3600:
                expired = sessions[token].client
                if expired and expired is not getattr(app.state, "project_client", None):
                    expired.close()
                del sessions[token]
        token = request.cookies.get("editor_session")
        if token not in sessions:
            token = secrets.token_urlsafe(32)
            sessions[token] = Session(client=getattr(app.state, "project_client", None))
            response.set_cookie("editor_session", token, httponly=True, samesite="strict", max_age=8 * 3600)
        current = sessions[token]
        current.touched = now
    return current


@app.exception_handler(ValueError)
async def invalid_value(request, exc):
    return JSONResponse({"detail": str(exc), "diagnostic": getattr(exc, "diagnostic", None)}, status_code=400)


class DatabaseSelection(BaseModel):
    database: str


class Draft(BaseModel):
    template_id: int
    record_id: int = Field(gt=0)
    source: str = Field(max_length=500_000)
    model: str = "sale.order"
    report_id: int | None = None
    context: dict = Field(default_factory=dict)
    placeholders: bool = True
    format: Literal["html", "pdf"] = "html"


class Save(BaseModel):
    template_id: int
    source: str = Field(max_length=500_000)
    revision: str


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/status")
def status(request: Request, response: Response):
    current = session(request, response)
    client = current.client
    return {"mode": "docker" if client else "demo", "url": client.url if client else None,
            "version": client.version if client else None,
            "directory": str(client.project.directory) if client else str(getattr(app.state, "export_directory", Path.cwd())),
            "service": client.project.service if client else None,
            "database": client.database if client else None,
            "databases": client.databases if client else []}


@app.post("/api/database")
def choose_database(body: DatabaseSelection, request: Request, response: Response):
    current = session(request, response)
    if not current.client:
        raise ValueError("Arranca el editor desde el directorio de un proyecto Odoo.")
    with current.lock:
        previous = current.client
        current.client = previous.for_database(body.database)
        current.pdf = None
        current.pdf_token = ""
        if previous is not getattr(app.state, "project_client", None):
            previous.close()
    return {"database": current.client.database}


@app.get("/api/templates")
def templates(request: Request, response: Response, q: str = "", report_id: int | None = None):
    current = session(request, response)
    if current.client:
        return current.client.call("list_templates", q, report_id)
    return [{"id": 1, "name": "Presupuesto de venta", "key": "demo.sale_order", "model": "sale.order", "report_id": None}]


@app.get("/api/templates/{template_id}")
def template(template_id: int, request: Request, response: Response):
    current = session(request, response)
    if current.client:
        return current.client.call("get_template", template_id)
    if template_id != 1:
        raise HTTPException(404, "Plantilla no encontrada")
    return {"id": 1, "source": current.source, "revision": str(current.revision), "name": "Presupuesto de venta", "key": "demo.sale_order", "model": "sale.order"}


@app.get("/api/records")
def records(request: Request, response: Response, model: str = "sale.order", q: str = ""):
    current = session(request, response)
    if current.client:
        return current.client.call("list_records", model, q)
    return [{"id": r["id"], "display_name": r["display_name"]} for r in demo.RECORDS
            if not q or q.lstrip("#") == str(r["id"]) or q.lower() in r["display_name"].lower()]


@app.get("/api/fields")
def fields(request: Request, response: Response, model: str = "sale.order"):
    current = session(request, response)
    if current.client:
        return current.client.call("list_fields", model)
    return [{"name": name, "string": label, "type": kind} for name, label, kind in [
        ("name", "Referencia", "char"), ("partner_id.name", "Nombre del cliente", "char"),
        ("partner_id.street", "Dirección", "char"), ("date_order", "Fecha", "date"),
        ("amount_total", "Total", "monetary"), ("amount_untaxed", "Base imponible", "monetary")]]


@app.get("/api/reports")
def reports(request: Request, response: Response):
    current = session(request, response)
    return current.client.call("list_reports") if current.client else [
        {"id": 1, "name": "Presupuesto de venta", "model": "sale.order", "model_name": "Pedido de venta", "key": "demo.sale_order"}]


@app.post("/api/preview")
def preview(body: Draft, request: Request, response: Response):
    current = session(request, response)
    source = demo.annotate(body.source)
    client = current.client
    if client:
        with current.lock:
            result = client.call("preview", body.template_id, body.record_id, source, body.model, body.report_id,
                                 {**body.context, "editor_placeholders": body.placeholders, "editor_format": body.format})
            if isinstance(result, dict) and "pdf" in result:
                current.pdf = base64.b64decode(result.pop("pdf"), validate=True)
                current.pdf_token = secrets.token_urlsafe(24)
                return {**result, "pdf_url": f"/api/preview.pdf?token={current.pdf_token}"}
        if isinstance(result, dict):
            return {**result, "base_url": client.url}
        return {"html": result, "base_url": client.url}
    if body.format == "pdf":
        raise ValueError("La vista PDF necesita una conexión a Odoo y una acción de informe PDF.")
    return {**demo.preview(body.source, body.record_id, body.placeholders), "base_url": ""}


@app.get("/api/preview.pdf")
def preview_pdf(request: Request, response: Response, token: str):
    current = session(request, response)
    if not current.pdf or not secrets.compare_digest(token, current.pdf_token):
        raise HTTPException(404, "PDF no disponible. Actualiza la vista previa.")
    return Response(current.pdf, media_type="application/pdf", headers={
        "Content-Disposition": 'inline; filename="vista-previa.pdf"',
    })


@app.post("/api/save")
def save(body: Save, request: Request, response: Response):
    current = session(request, response)
    demo.parse_xml(body.source)
    with current.lock:
        if current.client:
            template = current.client.call("get_template", body.template_id)
            result = export_template(current.client.project.directory, template, body.source)
            return {**result, "revision": template["revision"]}
        if body.template_id != 1:
            raise ValueError("Plantilla no encontrada.")
        if body.revision != str(current.revision):
            raise ValueError("La plantilla ha cambiado. Recárgala antes de guardar.")
        result = export_template(getattr(app.state, "export_directory", Path.cwd()),
                                 {"id": 1, "name": "Presupuesto de venta", "key": "demo.sale_order"}, body.source)
        current.source = body.source
        current.revision += 1
        return {**result, "revision": str(current.revision)}
