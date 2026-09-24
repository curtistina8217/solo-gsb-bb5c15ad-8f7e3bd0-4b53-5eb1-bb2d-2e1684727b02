"""打印 / 预览 SVG 生成。

与页面预览共用 compute_layout 输出的毫米坐标：浏览器和打印工具都
按 viewBox 等比缩放，坐标本身永远是毫米，因此预览所见即导出所得。
"""

from __future__ import annotations

from xml.sax.saxutils import escape

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
              show_occupied: bool = False) -> str:
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

    for lab in page.labels:
        parts.append(
            f'<rect class="label" x="{_fmt(lab.x)}" y="{_fmt(lab.y)}" '
            f'width="{_fmt(lab.width)}" height="{_fmt(lab.height)}"/>'
        )
        parts.append(_cut_marks(lab.x, lab.y, lab.width, lab.height))
        if show_annotations and min(lab.width, lab.height) >= 8:
            name = escape((lab.name or f"#{lab.type_index + 1}")[:12])
            tag = name + (" ↻" if lab.rotated else "")
            size_txt = f"{_fmt(lab.width)}×{_fmt(lab.height)}"
            fs = 2.2
            if len(tag) > 8:
                fs = 1.8
            cx, cy = lab.x + lab.width / 2, lab.y + lab.height / 2
            parts.append(
                f'<text class="annot" x="{_fmt(cx)}" y="{_fmt(cy - 0.2)}" '
                f'font-size="{_fmt(fs)}mm">{tag}</text>'
                f'<text class="annot" x="{_fmt(cx)}" y="{_fmt(cy + fs + 0.8)}" '
                f'font-size="{_fmt(min(fs, 2.0))}mm">{size_txt}</text>'
            )

    parts.append(
        f'<text class="pageno" x="{_fmt(w / 2)}" y="{_fmt(h - 2)}">'
        f"Page {page.page} / {len(plan.pages)}</text>"
    )
    parts.append("</svg>")
    return "\n".join(parts)
