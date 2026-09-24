"""打印 / 预览 SVG 生成。

与页面预览共用 compute_layout 输出的毫米坐标：浏览器和打印工具都
按 viewBox 等比缩放，坐标本身永远是毫米，因此预览所见即导出所得。

下载 / 打印时可传入打印位置校准逆变换：标签轮廓、裁切角线与标注
整体包在 <g transform="matrix(...)"> 中做逆仿射补偿；纸张边框、
页边距参考线、页码等不属于标签内容，不参与修正。
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from .calibration import (
    CalibrationTransform,
    IDENTITY_TRANSFORM,
)
from .models import LayoutResponse

_CUT = 3.0  # 裁切角线长度 mm
_CUT_INSET = 1.5  # 角线相对标签轮廓的外扩 mm


def _fmt(v: float) -> str:
    """SVG 属性中的毫米数：整数不带小数点，其余保留 2 位。"""
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _cut_marks(x: float, y: float, w: float, h: float) -> str:
    """在矩形四角画 8 段裁切参考线（在标签外侧 1.5mm）。"""
    x0, y0, x1, y1 = x - _CUT_INSET, y - _CUT_INSET, x + w + _CUT_INSET, y + h + _CUT_INSET
    c = _CUT
    return (
        f'<g class="cutmarks" stroke="#d23f3f" stroke-width="{_fmt(0.15)}" fill="none">'
        f'<path d="M{_fmt(x0)} {_fmt(y0 + c)} V{_fmt(y0)} H{_fmt(x0 + c)}"/>'
        f'<path d="M{_fmt(x1 - c)} {_fmt(y0)} H{_fmt(x1)} V{_fmt(y0 + c)}"/>'
        f'<path d="M{_fmt(x1)} {_fmt(y1 - c)} V{_fmt(y1)} H{_fmt(x1 - c)}"/>'
        f'<path d="M{_fmt(x0 + c)} {_fmt(y1)} H{_fmt(x0)} V{_fmt(y1 - c)}"/>'
        "</g>"
    )


def build_svg(plan: LayoutResponse, page_no: int,
              show_margins: bool = True, show_annotations: bool = True,
              show_occupied: bool = False,
              transform: CalibrationTransform = IDENTITY_TRANSFORM) -> str:
    page = next((p for p in plan.pages if p.page == page_no), None)
    if page is None:
        raise ValueError(f"页码超出范围：共 {len(plan.pages)} 页，请求第 {page_no} 页。")

    w, h = plan.page_width, plan.page_height
    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
            f'width="{_fmt(w)}mm" height="{_fmt(h)}mm" '
            f'viewBox="0 0 {_fmt(w)} {_fmt(h)}">'
        ),
        f'<rect x="0" y="0" width="{_fmt(w)}" height="{_fmt(h)}" fill="#ffffff"/>',
        (
            '<style>.label{fill:none;stroke:#222;stroke-width:0.15;}'
            ".annot{font-family:Arial,'Noto Sans CJK SC',sans-serif;"
            "font-size:2.2mm;fill:#9aa0a6;text-anchor:middle;}"
            ".marginguide{fill:none;stroke:#5b8def;stroke-width:0.1;stroke-dasharray:1 1;}"
            ".pageno{font-family:Arial,sans-serif;font-size:2.5mm;fill:#9aa0a6;}</style>"
        ),
    ]

    # 占用区仅存在于第一张纸；仅在预览（show_occupied）时绘制，
    # 下载 / 打印的 SVG 跳过本块（连同其专用样式），因此只含新标签。
    if show_occupied and page_no == 1 and plan.occupied_zones:
        parts.append(
            '<defs><pattern id="occHatch" patternUnits="userSpaceOnUse" '
            'width="3" height="3" patternTransform="rotate(45)">'
            '<rect width="3" height="3" fill="#e8eaed"/>'
            '<line x1="0" y1="0" x2="0" y2="3" stroke="#b9bdc4" stroke-width="0.5"/>'
            "</pattern></defs>"
        )
        parts.append(
            "<style>.occupied{fill:url(#occHatch);stroke:#9aa0a6;"
            "stroke-width:0.15;stroke-dasharray:1.2 0.8;}"
            ".occtext{font-family:Arial,'Noto Sans CJK SC',sans-serif;"
            "font-size:2.5mm;fill:#7b808a;text-anchor:middle;}</style>"
        )
        for z in plan.occupied_zones:
            parts.append(
                f'<rect class="occupied" x="{_fmt(z.x)}" y="{_fmt(z.y)}" '
                f'width="{_fmt(z.width)}" height="{_fmt(z.height)}"/>'
            )
            if min(z.width, z.height) >= 12:
                cx, cy = z.x + z.width / 2, z.y + z.height / 2
                parts.append(
                    f'<text class="occtext" x="{_fmt(cx)}" y="{_fmt(cy + 0.9)}">'
                    "已占用</text>"
                )

    if show_margins:
        mx0, my0 = plan.margin_left, plan.margin_top
        mx1, my1 = w - plan.margin_right, h - plan.margin_bottom
        parts.append(
            f'<rect class="marginguide" x="{_fmt(mx0)}" y="{_fmt(my0)}" '
            f'width="{_fmt(mx1 - mx0)}" height="{_fmt(my1 - my0)}"/>'
        )

    # 标签内容（轮廓 / 裁切角线 / 标注）整体做校准逆变换；
    # 预览与未启用校准时 transform 为恒等，不输出额外分组。
    label_parts: list[str] = []
    for lab in page.labels:
        label_parts.append(
            f'<rect class="label" x="{_fmt(lab.x)}" y="{_fmt(lab.y)}" '
            f'width="{_fmt(lab.width)}" height="{_fmt(lab.height)}"/>'
        )
        label_parts.append(_cut_marks(lab.x, lab.y, lab.width, lab.height))
        if show_annotations and min(lab.width, lab.height) >= 8:
            name = escape((lab.name or f"#{lab.type_index + 1}")[:12])
            tag = name + (" ↻" if lab.rotated else "")
            size_txt = f"{_fmt(lab.width)}×{_fmt(lab.height)}"
            fs = 2.2
            if len(tag) > 8:
                fs = 1.8
            cx, cy = lab.x + lab.width / 2, lab.y + lab.height / 2
            label_parts.append(
                f'<text class="annot" x="{_fmt(cx)}" y="{_fmt(cy - 0.2)}" '
                f'font-size="{_fmt(fs)}mm">{tag}</text>'
                f'<text class="annot" x="{_fmt(cx)}" y="{_fmt(cy + fs + 0.8)}" '
                f'font-size="{_fmt(min(fs, 2.0))}mm">{size_txt}</text>'
            )

    if not transform.is_identity:
        a, b, c, d, e, f = transform.matrix_values()
        parts.append(
            f'<g transform="matrix({a:.6f} {b:.6f} {c:.6f} {d:.6f} {e:.6f} {f:.6f})">'
        )
        parts.extend(label_parts)
        parts.append("</g>")
    else:
        parts.extend(label_parts)

    parts.append(
        f'<text class="pageno" x="{_fmt(w / 2)}" y="{_fmt(h - 2)}">'
        f"Page {page.page} / {len(plan.pages)}</text>"
    )
    parts.append("</svg>")
    return "\n".join(parts)


# ---------------- 打印位置校准测试页 ----------------

_CALIB_INSET = 20.0  # 最外侧刻线距纸边的距离 mm
_CALIB_COUNT = 3  # 每个方向的基准刻线条数


def default_calibration_marks(
    page_width: float, page_height: float
) -> tuple[list[float], list[float]]:
    """测试页默认刻线设计坐标：返回 (纵向刻线的 X 列表, 横向刻线的 Y 列表)。

    在 [inset, 纸宽/高-inset] 之间均匀取 _CALIB_COUNT 条，保留 1 位小数。
    """
    if page_width <= 2 * _CALIB_INSET or page_height <= 2 * _CALIB_INSET:
        raise ValueError("纸张过小：每边至少需要 40mm 才能排布校准刻线。")

    def marks(span: float) -> list[float]:
        lo, hi = _CALIB_INSET, span - _CALIB_INSET
        step = (hi - lo) / (_CALIB_COUNT - 1)
        return [round(lo + step * i, 1) for i in range(_CALIB_COUNT)]

    return marks(page_width), marks(page_height)


def build_calibration_svg(page_width: float, page_height: float) -> str:
    """生成含横、纵两组基准刻线的校准测试页（按纸张实际毫米尺寸）。

    - 纵向刻线组（蓝色）：靠近纸张顶部的水平测量轨 + 贯穿长线，
      沿轨读各刻线到纸左边缘的距离，用于 X 方向拟合；
    - 横向刻线组（橙色）：靠近纸张左缘的垂直测量轨 + 贯穿长线，
      沿轨读各刻线到纸上边缘的距离，用于 Y 方向拟合。

    两组轨道在纸面角落分离，不互相压住读数刻度。
    """
    xs, ys = default_calibration_marks(page_width, page_height)
    w, h = page_width, page_height

    x_rail_y = 34.0          # X 组水平测量轨的 y
    x_tick_h = 5.0           # 测量轨上的刻度高度
    x_label_y = x_rail_y + 9.0  # 设计坐标标注（轨下方）
    x_line_y0 = x_rail_y + 12.0  # 纵向长线起点
    y_rail_x = 34.0          # Y 组垂直测量轨的 x
    y_tick_w = 5.0           # 测量轨上的刻度宽度
    y_line_x0 = y_rail_x + 8.0  # 横向长线起点

    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
            f'width="{_fmt(w)}mm" height="{_fmt(h)}mm" '
            f'viewBox="0 0 {_fmt(w)} {_fmt(h)}">'
        ),
        f'<rect x="0" y="0" width="{_fmt(w)}" height="{_fmt(h)}" fill="#ffffff"/>',
        f'<rect x="0.25" y="0.25" width="{_fmt(w - 0.5)}" height="{_fmt(h - 0.5)}" '
        'fill="none" stroke="#333" stroke-width="0.15"/>',
        (
            "<style>"
            "text{font-family:Arial,'Noto Sans CJK SC',sans-serif;fill:#222;}"
            ".xt{stroke:#1a56db;}.yt{stroke:#c2570c;}"
            ".rail{stroke-width:0.2;fill:none;}"
            ".tick{stroke-width:0.2;}"
            ".long{stroke-width:0.12;opacity:0.55;}"
            ".xl{font-size:2.6mm;fill:#1a56db;text-anchor:middle;}"
            ".yl{font-size:2.6mm;fill:#c2570c;text-anchor:middle;}"
            ".xl,.yl{paint-order:stroke;stroke:#ffffff;stroke-width:0.7mm;}"
            ".tt{font-size:4mm;font-weight:bold;text-anchor:middle;}"
            ".st{font-size:2.4mm;fill:#555;text-anchor:middle;}"
            ".ft{font-size:2.4mm;fill:#555;text-anchor:middle;}"
            ".org{font-size:2.2mm;fill:#777;}"
            "</style>"
        ),
        # 标题与说明（位于顶部，避开 X 组测量轨）
        f'<text class="tt" x="{_fmt(w / 2)}" y="8">打印位置校准测试页</text>',
        f'<text class="st" x="{_fmt(w / 2)}" y="13.5">'
        "请以 100% 比例（关闭“适应页面/缩放”）打印本页后实测刻线位置</text>",
    ]

    # 原点标注：两条测量轨交汇处即纸张坐标原点方向
    parts.append(
        f'<text class="org" x="{_fmt(y_rail_x + 2)}" y="{_fmt(x_rail_y - x_tick_h - 7.2)}">'
        "纸左上角为原点 O →</text>"
    )

    # ---- X 方向：纵向刻线 + 顶部水平测量轨 ----
    parts.append(f'<g>')
    parts.append(
        f'<line class="xt rail" x1="0" y1="{_fmt(x_rail_y)}" '
        f'x2="{_fmt(w)}" y2="{_fmt(x_rail_y)}"/>'
    )
    for x in xs:
        parts.append(
            f'<line class="xt tick" x1="{_fmt(x)}" y1="{_fmt(x_rail_y - x_tick_h)}" '
            f'x2="{_fmt(x)}" y2="{_fmt(x_rail_y + x_tick_h)}"/>'
        )
        parts.append(
            f'<line class="xt long" x1="{_fmt(x)}" y1="{_fmt(x_line_y0)}" '
            f'x2="{_fmt(x)}" y2="{_fmt(h)}"/>'
        )
        # 标注位于测量轨下方、长线起点之前；白描边光晕保证压线可读
        parts.append(
            f'<text class="xl" x="{_fmt(x)}" y="{_fmt(x_label_y + 0.8)}">'
            f"X={_fmt(x)}</text>"
        )
    parts.append("</g>")

    # ---- Y 方向：横向刻线 + 左部垂直测量轨 ----
    parts.append(f'<g>')
    parts.append(
        f'<line class="yt rail" x1="{_fmt(y_rail_x)}" y1="0" '
        f'x2="{_fmt(y_rail_x)}" y2="{_fmt(h)}"/>'
    )
    for y in ys:
        parts.append(
            f'<line class="yt tick" x1="{_fmt(y_rail_x - y_tick_w)}" y1="{_fmt(y)}" '
            f'x2="{_fmt(y_rail_x + y_tick_w)}" y2="{_fmt(y)}"/>'
        )
        parts.append(
            f'<line class="yt long" x1="{_fmt(y_line_x0)}" y1="{_fmt(y)}" '
            f'x2="{_fmt(w)}" y2="{_fmt(y)}"/>'
        )
        # 竖排文字：旋转 -90°，沿垂直轨左侧自上而下
        parts.append(
            f'<text class="yl" transform="translate({_fmt(y_rail_x - y_tick_w - 2.2)} '
            f'{_fmt(y)}) rotate(-90)">Y={_fmt(y)}</text>'
        )
    parts.append("</g>")

    # 页脚：操作步骤
    steps = (
        "测量方法：①沿顶部蓝色横轨，量取每条蓝色竖线到纸左边缘的距离（X 实测）；"
        "②沿左侧橙色竖轨，量取每条橙色横线到纸上边缘的距离（Y 实测）；"
        "③把读数录入界面，保存校准后再下载/打印标签。"
    )
    parts.append(
        f'<text class="ft" x="{_fmt(w / 2)}" y="{_fmt(h - 6)}">{escape(steps)}</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts)
