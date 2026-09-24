"""请求 / 响应数据模型（单位均为毫米）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LabelSpec(BaseModel):
    """一种标签规格及其需要的份数。"""

    name: str = Field("", description="标签名称")
    width: float = Field(..., gt=0, description="标签宽度 mm")
    height: float = Field(..., gt=0, description="标签高度 mm")
    count: int = Field(..., ge=1, description="需要份数")
    allow_rotate: bool = Field(False, description="是否允许旋转 90 度排版")


class OccupiedZone(BaseModel):
    """首张纸上已被占用的区域（如已贴过的标签），单位毫米。

    坐标原点为纸张左上角。排版时视为障碍，新标签与其保持裁切间距；
    仅作用于第一页，放不下的份数续到后续空白页。
    """

    x: float = Field(..., description="左上角横坐标 mm")
    y: float = Field(..., description="左上角纵坐标 mm")
    width: float = Field(..., gt=0, description="占用区宽度 mm")
    height: float = Field(..., gt=0, description="占用区高度 mm")


class LayoutRequest(BaseModel):
    """拼版参数。"""

    page_width: float = Field(..., gt=0, description="纸张宽度 mm")
    page_height: float = Field(..., gt=0, description="纸张高度 mm")
    margin_top: float = Field(0, ge=0)
    margin_right: float = Field(0, ge=0)
    margin_bottom: float = Field(0, ge=0)
    margin_left: float = Field(0, ge=0)
    gap_x: float = Field(0, ge=0, description="水平裁切间距 mm")
    gap_y: float = Field(0, ge=0, description="垂直裁切间距 mm")
    labels: list[LabelSpec] = Field(..., min_length=1)
    occupied_zones: list[OccupiedZone] = Field(
        default_factory=list, description="首张纸占用区（障碍），可多个"
    )


class PlacedLabel(BaseModel):
    """单个已排入标签（毫米坐标，原点为纸张左上角）。"""

    type_index: int
    name: str
    x: float
    y: float
    width: float
    height: float
    rotated: bool


class PageLayout(BaseModel):
    page: int
    width: float
    height: float
    labels: list[PlacedLabel]


class LabelSummary(BaseModel):
    type_index: int
    name: str
    width: float
    height: float
    requested: int
    placed: int
    rotated: int
    unplaced: int


class LayoutResponse(BaseModel):
    pages: list[PageLayout]
    summaries: list[LabelSummary]
    total_requested: int
    total_placed: int
    warnings: list[str]
    # 回显参数，供绘制 / 导出使用，保证预览与导出同源
    page_width: float
    page_height: float
    margin_top: float
    margin_right: float
    margin_bottom: float
    margin_left: float
    gap_x: float
    gap_y: float
    occupied_zones: list[OccupiedZone] = Field(
        default_factory=list, description="回显首张纸占用区"
    )


class CalibPoint(BaseModel):
    """一条校准刻线：设计坐标与打印后在纸上的实测坐标，单位毫米。

    X 方向对应纵向刻线（测量其到纸张左边缘的距离），
    Y 方向对应横向刻线（测量其到纸张上边缘的距离）。
    """

    designed: float = Field(..., description="刻线设计坐标 mm")
    measured: float = Field(..., description="纸上实测坐标 mm")


class Calibration(BaseModel):
    """打印位置校准参数（仅作用于下载 / 打印 SVG，不影响排版坐标）。"""

    x_points: list[CalibPoint] = Field(
        default_factory=list, description="纵向刻线：X 方向设计/实测坐标"
    )
    y_points: list[CalibPoint] = Field(
        default_factory=list, description="横向刻线：Y 方向设计/实测坐标"
    )


class CalibrationRequest(BaseModel):
    """校准校验请求：当前排版参数 + 刻线录入数据。"""

    params: LayoutRequest
    calibration: Calibration


class SvgRequest(BaseModel):
    """SVG 导出请求：参数与 /api/layout 完全一致，附带页码与显示开关。

    calibration 仅在下载 / 打印时传入；常规预览传 null，坐标与
    /api/layout 保持一致。
    """

    page: int = Field(1, ge=1)
    show_margins: bool = True
    show_annotations: bool = True
    show_occupied: bool = Field(
        False,
        description="是否绘制首张纸占用区（预览用；下载/打印应为 false，只含新标签）",
    )
    calibration: Calibration | None = Field(
        None,
        description="打印位置校准（仅修正导出的标签轮廓/裁切线/标注）；预览为 null",
    )
    params: LayoutRequest


class SvgResponse(BaseModel):
    svg: str
