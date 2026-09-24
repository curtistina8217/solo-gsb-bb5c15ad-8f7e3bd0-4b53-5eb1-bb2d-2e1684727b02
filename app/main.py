"""FastAPI 入口：拼版计算与 SVG 导出接口，以及静态前端。"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from .layout import compute_layout
from .models import (
    LayoutRequest,
    LayoutResponse,
    SvgRequest,
)
from .svg import build_svg

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="小批量标签拼版工具", version="1.0.0")


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/layout", response_model=LayoutResponse, tags=["layout"])
def api_layout(req: LayoutRequest) -> LayoutResponse:
    try:
        return compute_layout(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/svg", tags=["layout"])
def api_svg(req: SvgRequest) -> Response:
    try:
        plan = compute_layout(req.params)
        svg = build_svg(
            plan, req.page, req.show_margins, req.show_annotations, req.show_occupied
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    filename = f"labels-page-{req.page}.svg"
    return Response(
        content=svg,
        media_type="image/svg+xml; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


# 静态资源（index.html / app.js / style.css）
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index() -> HTMLResponse:
    with open(_STATIC_DIR / "index.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())
