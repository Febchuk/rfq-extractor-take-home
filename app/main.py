"""HTTP API and the operator dashboard."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.env import load_dotenv
from app.errors import ExtractionError, ModelConfigError
from app.pipeline import run
from app.store import store

load_dotenv()

app = FastAPI(title="RFQ ingest", docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {"records": store.list()},
    )


@app.get("/rfqs/{record_id}", response_class=HTMLResponse)
def detail(request: Request, record_id: str) -> HTMLResponse:
    record = store.get(record_id)
    if record is None:
        return templates.TemplateResponse(
            request,
            "missing.html",
            status_code=404,
        )
    return templates.TemplateResponse(
        request,
        "detail.html",
        {
            "record": record,
            "contract": record.contract.model_dump(mode="json"),
            "contract_json": json.dumps(record.contract.model_dump(mode="json"), indent=2),
        },
    )


@app.post("/ingest")
async def ingest(request: Request):
    content_type = request.headers.get("content-type", "")
    source_name = None
    wants_html = False
    try:
        if (
            "multipart/form-data" in content_type
            or "application/x-www-form-urlencoded" in content_type
        ):
            wants_html = True
            form = await request.form()
            upload = form.get("email")
            pasted = form.get("raw")
            if upload is not None and getattr(upload, "filename", None):
                source_name = upload.filename
                raw = (await upload.read()).decode("utf-8", errors="replace")
            elif isinstance(pasted, str) and pasted.strip():
                raw = pasted
            else:
                return _fail(request, "Choose an .eml file or paste the raw message.", 400, wants_html)
        else:
            raw = (await request.body()).decode("utf-8", errors="replace")
            if not raw.strip():
                return _fail(request, "Request body is empty.", 400, False)
        outcome = run(raw)
    except ModelConfigError as exc:
        return _fail(request, str(exc), 503, wants_html)
    except ExtractionError as exc:
        return _fail(request, str(exc), 502, wants_html)
    except Exception as exc:
        return _fail(request, str(exc), 500, wants_html)

    record = store.add(
        subject=outcome.subject,
        sender=outcome.sender,
        contract=outcome.contract,
        source_name=source_name,
        quote_probability=outcome.quote_probability,
        has_parts_probability=outcome.has_parts_probability,
        catalog_matches=outcome.catalog_matches,
    )
    if wants_html:
        return RedirectResponse(url=f"/rfqs/{record.id}", status_code=303)
    return JSONResponse(outcome.contract.model_dump(mode="json"))


def _fail(request: Request, message: str, status: int, wants_html: bool):
    if wants_html:
        return templates.TemplateResponse(
            request,
            "error.html",
            {"message": message},
            status_code=status,
        )
    return JSONResponse({"error": message}, status_code=status)
