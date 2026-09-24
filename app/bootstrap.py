"""启动初始化：校验配置、自检关键模块可导入。

容器启动时由 entrypoint.sh 调用（python -m app.bootstrap）。
无数据库等外部依赖；这里执行运行环境自检并输出启动横幅。
"""

from __future__ import annotations

import sys


def main() -> int:
    print("[bootstrap] 小批量标签拼版工具 —— 初始化开始")

    # 依赖与核心模块自检
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
        import pydantic  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        print(f"[bootstrap] 依赖缺失: {exc}", file=sys.stderr)
        return 1

    from .calibration import (
        ensure_calibrated_bounds,
        solve_calibration,
    )
    from .layout import compute_layout
    from .models import (
        CalibrationData,
        CalibrationLine,
        LayoutRequest,
        LabelSpec,
        OccupiedZone,
    )
    from .svg import _fmt, build_calibration_page, build_svg

    # 用一个最小样例冒烟测试排版 + SVG 管线
    smoke = LayoutRequest(
        page_width=210, page_height=297,
        margin_top=8, margin_right=8, margin_bottom=8, margin_left=8,
        gap_x=2, gap_y=2,
        labels=[LabelSpec(width=60, height=30, count=4, allow_rotate=True)],
    )
    plan = compute_layout(smoke)
    build_svg(plan, 1)
    assert plan.total_placed == 4

    # 首张纸占用区：障碍位于 (48,48)、100×100，间距 2。
    # 标签盒为 52×32，障碍碰撞盒右缘 150、下沿 150。
    occ = LayoutRequest(
        page_width=210, page_height=297,
        margin_top=8, margin_right=8, margin_bottom=8, margin_left=8,
        gap_x=2, gap_y=2,
        labels=[LabelSpec(name="避让标签", width=50, height=30, count=40)],
        occupied_zones=[OccupiedZone(x=48, y=48, width=100, height=100)],
    )
    p2 = compute_layout(occ)
    p2_svg = build_svg(p2, 1, show_occupied=True)
    export_svg = build_svg(p2, 1)  # 导出不含占用区绘制
    assert 'class="occupied"' in p2_svg and "已占用" in p2_svg
    assert 'class="occupied"' not in export_svg and "已占用" not in export_svg
    # 不丢失、不重复
    assert sum(len(pg.labels) for pg in p2.pages) == 40
    assert p2.total_placed == 40
    assert len(p2.pages) >= 2  # 障碍占掉首页空间，必然续页
    z = occ.occupied_zones[0]
    for lab in p2.pages[0].labels:
        # 盒 = 标签矩形 + 右/下一个间距；盒与障碍碰撞盒不得重叠
        bx2, by2 = lab.x + lab.width + 2, lab.y + lab.height + 2
        assert not (
            lab.x < z.x + z.width + 2 and bx2 > z.x
            and lab.y < z.y + z.height + 2 and by2 > z.y
        ), f"标签与占用区间距不足: {lab}"
    # 续页为无障碍空白页，正常排满
    assert len(p2.pages[1].labels) > 0

    # 越界占用区必须报明确错误
    def _expect_error(z: OccupiedZone) -> None:
        bad = LayoutRequest(
            page_width=210, page_height=297,
            labels=[LabelSpec(width=10, height=10, count=1)],
            occupied_zones=[z],
        )
        try:
            compute_layout(bad)
        except ValueError:
            return
        raise AssertionError(f"占用区 {z} 越界却未报错")

    _expect_error(OccupiedZone(x=120, y=10, width=100, height=10))
    _expect_error(OccupiedZone(x=10, y=250, width=10, height=60))
    _expect_error(OccupiedZone(x=-1, y=0, width=10, height=10))

    # ---- 打印位置校准：拟合、逆变换修正与三类拦截 ----
    def _lines(scale: float, offset: float) -> list[CalibrationLine]:
        return [
            CalibrationLine(design=d, measured=round(scale * d + offset, 3))
            for d in (21.0, 63.0, 105.0, 147.0, 189.0)
        ]

    cal_data = CalibrationData(
        x_lines=_lines(1.01, -0.3), y_lines=_lines(0.99, 0.5)
    )
    cal = solve_calibration(cal_data)
    assert abs(cal.x.scale - 1.01) < 5e-4 and abs(cal.x.offset + 0.3) < 1e-2
    assert abs(cal.y.scale - 0.99) < 5e-4 and abs(cal.y.offset - 0.5) < 1e-2

    # 校准导出：标签坐标按逆变换 (设计 - offset) / scale 修正
    lab0 = plan.pages[0].labels[0]
    svg_cal = build_svg(plan, 1, calibration=cal)
    exp_x = _fmt((lab0.x - cal.x.offset) / cal.x.scale)
    exp_w = _fmt(lab0.width / cal.x.scale)
    assert f'x="{exp_x}"' in svg_cal and f'width="{exp_w}"' in svg_cal
    assert "打印位置校准已应用" in svg_cal
    # 未校准导出仍是原坐标，且不含校准注释
    svg_plain = build_svg(plan, 1)
    assert f'x="{_fmt(lab0.x)}"' in svg_plain
    assert "打印位置校准已应用" not in svg_plain
    # 无校准参数的导出与新增功能前保持一致（同一渲染管线恒等分支）
    assert build_svg(plan, 1, True, True, False) == build_svg(
        plan, 1, True, True, False, calibration=None
    )

    # 基准点重合：设计坐标重复 / 实测坐标全部相同，均拒绝
    def _expect_cal_error(data: CalibrationData, key: str) -> None:
        try:
            solve_calibration(data)
        except ValueError as exc:
            assert key in str(exc), f"错误信息未包含「{key}」: {exc}"
            return
        raise AssertionError(f"校准数据应被拦截（{key}）却通过求解")

    same_design = [
        CalibrationLine(design=100.0, measured=100.0 + i) for i in range(3)
    ]
    _expect_cal_error(
        CalibrationData(x_lines=same_design, y_lines=_lines(1.0, 0.0)),
        "基准点重合",
    )
    same_measured = [
        CalibrationLine(design=float(d), measured=50.0)
        for d in (21.0, 63.0, 105.0)
    ]
    _expect_cal_error(
        CalibrationData(x_lines=same_measured, y_lines=_lines(1.0, 0.0)),
        "基准点重合",
    )
    # 实测顺序颠倒（从右往左读数），拒绝
    reversed_rows = [
        CalibrationLine(design=21.0, measured=190.0),
        CalibrationLine(design=63.0, measured=148.0),
        CalibrationLine(design=105.0, measured=105.0),
        CalibrationLine(design=147.0, measured=62.0),
        CalibrationLine(design=189.0, measured=20.0),
    ]
    _expect_cal_error(
        CalibrationData(x_lines=reversed_rows, y_lines=_lines(1.0, 0.0)),
        "顺序",
    )
    # 补偿后内容超出纸张：offset=50 使修正后内容整体左移 50mm
    cal_shift = solve_calibration(
        CalibrationData(x_lines=_lines(1.0, 50.0), y_lines=_lines(1.0, 0.0))
    )
    try:
        ensure_calibrated_bounds(plan, 1, cal_shift)
    except ValueError as exc:
        assert "超出纸张" in str(exc), str(exc)
    else:
        raise AssertionError("补偿后标签出界却未拦截校准导出")

    # 校准测试页：横竖两组刻线及设计坐标标注齐全
    page_svg = build_calibration_page(210, 297)
    assert 'class="vline"' in page_svg and 'class="hline"' in page_svg
    assert "X1=21" in page_svg and "X5=189" in page_svg
    assert "Y1=29.7" in page_svg and "Y5=267.3" in page_svg


    print(f"[bootstrap] 自检通过（FastAPI {fastapi.__version__}, "
          f"Pydantic {pydantic.VERSION}）")
    print("[bootstrap] 初始化完成，等待 uvicorn 启动 ...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
