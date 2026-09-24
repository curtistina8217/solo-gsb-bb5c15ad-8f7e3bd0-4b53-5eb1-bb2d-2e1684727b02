"""FastAPI 入口：拼版计算与 SVG 导出接口，以及静态前端。"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .calibration import (
    build_transform,
    check_all_pages_fit,
)
from .layout import compute_layout
from .models import (
    Calibration,
    CalibrationRequest,
    LayoutRequest,
    LayoutResponse,
    SvgRequest,
)
from .svg import build_calibration_svg, build_svg, default_calibration_marks

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="小批量标签拼版工具", version="1.1.0")


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/layout", response_model=LayoutResponse, tags=["layout"])
def api_layout(req: LayoutRequest) -> LayoutResponse:
    """排版接口：坐标、数量等始终为原始设计值，不受打印校准影响。"""
    try:
        return compute_layout(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/svg", tags=["layout"])
def api_svg(req: SvgRequest) -> Response:
    try:
        plan = compute_layout(req.params)
        # 校准只影响导出的标签内容（逆变换）；排版坐标与 /api/layout 一致
        transform = build_transform(req.calibration)
        check_all_pages_fit(plan, transform)
        svg = build_svg(
            plan, req.page, req.show_margins, req.show_annotations,
            req.show_occupied, transform,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    filename = f"labels-page-{req.page}.svg"
    return Response(
        content=svg,
        media_type="image/svg+xml; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


# ---------------- 打印位置校准 ----------------


class MarksRequest(BaseModel):
    page_width: float = Field(..., gt=0)
    page_height: float = Field(..., gt=0)


class MarksResponse(BaseModel):
    x_designed: list[float]
    y_designed: list[float]


class AxisReport(BaseModel):
    used: int = Field(..., description="参与拟合的刻线数，0 表示该方向不校准")
    scale: float = Field(..., description="走纸比例 k（实测 = k·设计 + b）")
    offset: float = Field(..., description="零位偏移 b（mm）")
    scale_percent: float = Field(..., description="走纸比例相对 100% 的百分比")
    identity: bool = Field(..., description="是否与无误差一致")


class CalibrationValidateResponse(BaseModel):
    x: AxisReport
    y: AxisReport
    all_pages_fit: bool = Field(..., description="补偿后所有页标签是否都在纸张内")
    page_count: int


@app.post("/api/calibration/marks", response_model=MarksResponse, tags=["calibration"])
def api_calibration_marks(req: MarksRequest) -> MarksResponse:
    """返回当前纸张尺寸下校准测试页的默认刻线设计坐标。"""
    try:
        xs, ys = default_calibration_marks(req.page_width, req.page_height)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MarksResponse(x_designed=xs, y_designed=ys)


@app.get("/api/calibration/test-page", tags=["calibration"])
def api_calibration_test_page(width: float, height: float) -> Response:
    """下载含横、纵两组基准刻线的校准测试页 SVG（按纸张实际毫米尺寸）。"""
    if not (width > 0 and height > 0):
        raise HTTPException(status_code=400, detail="纸张宽、高必须为正数。")
    try:
        svg = build_calibration_svg(width, height)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        content=svg,
        media_type="image/svg+xml; charset=utf-8",
        headers={
            "Content-Disposition": 'inline; filename="calibration-test-page.svg"'
        },
    )


@app.post(
    "/api/calibration/validate",
    response_model=CalibrationValidateResponse,
    tags=["calibration"],
)
def api_calibration_validate(req: CalibrationRequest) -> CalibrationValidateResponse:
    """根据刻线录入拟合 X/Y 走纸误差，并对当前排版逐页检查补偿是否越界。

    基准点重合、实测顺序颠倒、补偿超出纸张时返回 HTTP 400 及中文原因。
    """
    calibration: Calibration = req.calibration
    if not calibration.x_points and not calibration.y_points:
        raise HTTPException(
            status_code=400,
            detail="请至少在一个方向录入刻线实测值（求走纸比例需同一方向两条不同位置的刻线）。",
        )
    try:
        transform = build_transform(calibration)
        plan = compute_layout(req.params)
        check_all_pages_fit(plan, transform)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    def report(axis) -> AxisReport:
        return AxisReport(
            used=axis.used,
            scale=round(axis.scale, 6),
            offset=round(axis.offset, 3),
            scale_percent=round(axis.scale * 100.0, 4),
            identity=axis.is_identity,
        )

    return CalibrationValidateResponse(
        x=report(transform.x),
        y=report(transform.y),
        all_pages_fit=True,
        page_count=len(plan.pages),
    )


# 静态资源（index.html / app.js / style.css）
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index() -> HTMLResponse:
    with open(_STATIC_DIR / "index.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())
