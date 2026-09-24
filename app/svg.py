"""打印 / 预览 SVG 生成。

与页面预览共用 compute_layout 输出的毫米坐标：浏览器和打印工具都
按 viewBox 等比缩放，坐标本身永远是毫米，因此预览所见即导出所得。

打印位置校准：calibration 给定时（仅下载 / 打印的 SVG 会带），所有
绘制元素按线性走纸误差的逆变换逐点修正——坐标与尺寸平移/缩放，
线宽与字号保持不变；viewBox 与纸张尺寸仍是原始纸张。常规预览不传
calibration，坐标与 /api/layout 返回完全一致。
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from .calibration import calibration_marks
from .models import Calibration, LayoutResponse

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
              calibration: Calibration | None = None) -> str:
    page = next((p for p in plan.pages if p.page == page_no), None)
    if page is None:
        raise ValueError(f"页码超出范围：共 {len(plan.pages)} 页，请求第 {page_no} 页。")

    # 逆变换：打印机满足 实测 = scale·设计 + offset，导出写入 设计' 使得
    # scale·设计' + offset = 设计，即 (设计 - offset) / scale。
    # 无校准时恒等，输出与未加校准功能前逐字节同构。
    if calibration is None:
        def fx(v: float) -> float:
            return v
        fy = fw = fh = fx
    else:
        xs, xo = calibration.x.scale, calibration.x.offset
        ys, yo = calibration.y.scale, calibration.y.offset

        def fx(v: float) -> float:
            return (v - xo) / xs

        def fy(v: float) -> float:
            return (v - yo) / ys

        def fw(v: float) -> float:
            return v / xs

        def fh(v: float) -> float:
            return v / ys

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
    if calibration is not None:
        parts.append(
            f"<!-- 打印位置校准已应用：X scale={calibration.x.scale} "
            f"offset={calibration.x.offset}mm；Y scale={calibration.y.scale} "
            f"offset={calibration.y.offset}mm（按逆变换补偿） -->"
        )

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
                f'<rect class="occupied" x="{_fmt(fx(z.x))}" y="{_fmt(fy(z.y))}" '
                f'width="{_fmt(fw(z.width))}" height="{_fmt(fh(z.height))}"/>'
            )
            if min(z.width, z.height) >= 12:
                cx, cy = fx(z.x + z.width / 2), fy(z.y + z.height / 2)
                parts.append(
                    f'<text class="occtext" x="{_fmt(cx)}" y="{_fmt(cy + 0.9)}">'
                    "已占用</text>"
                )

    if show_margins:
        mx0, my0 = fx(plan.margin_left), fy(plan.margin_top)
        mx1, my1 = fx(w - plan.margin_right), fy(h - plan.margin_bottom)
        parts.append(
            f'<rect class="marginguide" x="{_fmt(mx0)}" y="{_fmt(my0)}" '
            f'width="{_fmt(mx1 - mx0)}" height="{_fmt(my1 - my0)}"/>'
        )

    for lab in page.labels:
        lx, ly, lw, lh = fx(lab.x), fy(lab.y), fw(lab.width), fh(lab.height)
        parts.append(
            f'<rect class="label" x="{_fmt(lx)}" y="{_fmt(ly)}" '
            f'width="{_fmt(lw)}" height="{_fmt(lh)}"/>'
        )
        parts.append(_cut_marks(lx, ly, lw, lh))
        if show_annotations and min(lab.width, lab.height) >= 8:
            name = escape((lab.name or f"#{lab.type_index + 1}")[:12])
            tag = name + (" ↻" if lab.rotated else "")
            size_txt = f"{_fmt(lab.width)}×{_fmt(lab.height)}"
            fs = 2.2
            if len(tag) > 8:
                fs = 1.8
            cx, cy = lx + lw / 2, ly + lh / 2
            parts.append(
                f'<text class="annot" x="{_fmt(cx)}" y="{_fmt(cy - 0.2)}" '
                f'font-size="{_fmt(fs)}mm">{tag}</text>'
                f'<text class="annot" x="{_fmt(cx)}" y="{_fmt(cy + fs + 0.8)}" '
                f'font-size="{_fmt(min(fs, 2.0))}mm">{size_txt}</text>'
            )

    parts.append(
        f'<text class="pageno" x="{_fmt(fx(w / 2))}" y="{_fmt(fy(h - 2))}">'
        f"Page {page.page} / {len(plan.pages)}</text>"
    )
    parts.append("</svg>")
    return "\n".join(parts)


def build_calibration_page(page_width: float, page_height: float) -> str:
    """打印位置校准测试页：横、纵两组基准刻线，每根刻线标注设计坐标。

    纵向实线（沿 X 方向均布）用于校准 X：尺量其到纸张左边缘的距离；
    横向虚线（沿 Y 方向均布）用于校准 Y：尺量其到纸张顶边缘的距离。
    所有位置按纸张比例布置，任意纸张尺寸均可使用；坐标标注与
    /api/calibration/marks 返回的设计坐标一致。
    """
    x_marks, y_marks = calibration_marks(page_width, page_height)
    w, h = page_width, page_height
    cx = w / 2
    line_top, line_bottom = h * 0.14, h * 0.95
    line_left, line_right = w * 0.08, w * 0.96
    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
            f'width="{_fmt(w)}mm" height="{_fmt(h)}mm" '
            f'viewBox="0 0 {_fmt(w)} {_fmt(h)}">'
        ),
        f'<rect x="0" y="0" width="{_fmt(w)}" height="{_fmt(h)}" fill="#ffffff"/>',
        (
            "<style>"
            ".cal-title{font-family:Arial,'Noto Sans CJK SC',sans-serif;"
            "font-size:4mm;fill:#111;text-anchor:middle;font-weight:bold;}"
            ".cal-note{font-family:Arial,'Noto Sans CJK SC',sans-serif;"
            "font-size:2.6mm;fill:#333;text-anchor:middle;}"
            ".vline{stroke:#0b57d0;stroke-width:0.3;}"
            ".hline{stroke:#0b57d0;stroke-width:0.3;stroke-dasharray:5 2;}"
            ".marklab{font-family:Arial,sans-serif;font-size:2.8mm;fill:#0b57d0;}"
            ".frame{fill:none;stroke:#9aa0a6;stroke-width:0.2;}"
            "</style>"
        ),
        f'<rect class="frame" x="0.4" y="0.4" width="{_fmt(w - 0.8)}" height="{_fmt(h - 0.8)}"/>',
        f'<text class="cal-title" x="{_fmt(cx)}" y="{_fmt(h * 0.04)}">'
        f"打印位置校准测试页（纸张 {_fmt(w)}×{_fmt(h)}mm）</text>",
        f'<text class="cal-note" x="{_fmt(cx)}" y="{_fmt(h * 0.04 + 4.5)}">'
        f"请以 100% 缩放打印并关闭「适应页面/无边距缩放」；"
        f"竖直实线 X1–X{len(x_marks)} 量到纸左缘、水平虚线 Y1–Y{len(y_marks)} "
        "量到纸顶缘，读数(mm)填入软件实测列</text>",
    ]
    for i, mx in enumerate(x_marks):
        parts.append(
            f'<line class="vline" x1="{_fmt(mx)}" y1="{_fmt(line_top)}" '
            f'x2="{_fmt(mx)}" y2="{_fmt(line_bottom)}"/>'
        )
        parts.append(
            f'<text class="marklab" text-anchor="middle" x="{_fmt(mx)}" '
            f'y="{_fmt(line_top - 2)}">X{i + 1}={_fmt(mx)}</text>'
        )
    for i, my in enumerate(y_marks):
        parts.append(
            f'<line class="hline" x1="{_fmt(line_left)}" y1="{_fmt(my)}" '
            f'x2="{_fmt(line_right)}" y2="{_fmt(my)}"/>'
        )
        parts.append(
            f'<text class="marklab" text-anchor="start" x="{_fmt(line_left)}" '
            f'y="{_fmt(my - 1.5)}">Y{i + 1}={_fmt(my)}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts)
