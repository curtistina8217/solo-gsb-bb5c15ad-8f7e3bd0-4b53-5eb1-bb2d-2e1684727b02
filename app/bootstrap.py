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
        CalibrationTransform,
        AxisFit,
        build_transform,
        check_all_pages_fit,
    )
    from .layout import compute_layout
    from .models import (
        Calibration,
        CalibPoint,
        LayoutRequest,
        LabelSpec,
        OccupiedZone,
    )
    from .svg import build_calibration_svg, build_svg, default_calibration_marks

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

    # ---- 打印位置校准 ----
    # 校准测试页：含横、纵两组刻线，设计坐标与默认接口一致
    xs, ys = default_calibration_marks(210, 297)
    assert len(xs) == 3 and len(ys) == 3 and xs[0] == 20 and xs[-1] == 190
    test_svg = build_calibration_svg(210, 297)
    assert 'class="xt' in test_svg and 'class="yt' in test_svg
    assert "X=20" in test_svg and "Y=20" in test_svg
    assert test_svg.count('<line class="xt tick"') == 3
    assert test_svg.count('<line class="yt tick"') == 3

    # 线性拟合：实测 = 1.002·设计 + 1.5（均匀采样，最小二乘应精确还原）
    cal_ok = Calibration(
        x_points=[CalibPoint(designed=d, measured=1.002 * d + 1.5) for d in xs],
        y_points=[CalibPoint(designed=d, measured=0.998 * d - 0.8) for d in ys],
    )
    tr = build_transform(cal_ok)
    assert abs(tr.x.scale - 1.002) < 1e-9 and abs(tr.x.offset - 1.5) < 1e-9
    assert abs(tr.y.scale - 0.998) < 1e-9 and abs(tr.y.offset - (-0.8)) < 1e-9
    # 逆变换把实测位置映回设计位置：inverse(k·d+b) == d
    assert abs(tr.x.inverse(1.002 * 50 + 1.5) - 50) < 1e-9
    a, b, c, d, e, f = tr.matrix_values()
    assert b == 0 and c == 0 and abs(a - 1 / 1.002) < 1e-12

    # 补偿后的导出 SVG：标签内容包在 matrix 分组内，且坐标/数量与排版一致
    calib_svg = build_svg(plan, 1, transform=tr)
    assert "<g transform=" in calib_svg
    assert 'class="marginguide"' in calib_svg  # 页边距参考线仍在组外、不补偿
    # 恒等校准不输出分组，与未校准时字节一致
    assert "<g transform=" not in build_svg(plan, 1)
    assert build_svg(plan, 1) == build_svg(plan, 1, transform=build_transform(None))

    # 单点刻线按纯平移处理（k=1）
    one = build_transform(
        Calibration(x_points=[CalibPoint(designed=50, measured=52)])
    )
    assert one.x.scale == 1.0 and abs(one.x.offset - 2.0) < 1e-9 and one.y.used == 0

    # 阻止条件①：基准点重合（设计坐标相同）
    for bad_cal, kw in [
        (Calibration(x_points=[
            CalibPoint(designed=50, measured=50),
            CalibPoint(designed=50, measured=51),
        ]), "重合"),
        # 阻止条件②：实测顺序颠倒
        (Calibration(x_points=[
            CalibPoint(designed=20, measured=90),
            CalibPoint(designed=100, measured=30),
        ]), "颠倒"),
    ]:
        try:
            bad_tr = build_transform(bad_cal)
            check_all_pages_fit(plan, bad_tr)
        except ValueError as exc:
            assert kw in str(exc), f"错误信息缺少「{kw}」: {exc}"
        else:
            raise AssertionError(f"校准异常（{kw}）未被阻止")

    # 阻止条件③：补偿超出纸张。给一个极大 X 缩放，逆变换后标签越过纸右缘
    big = CalibrationTransform(
        x=AxisFit(scale=0.5, offset=0.0, used=2), y=AxisFit(1.0, 0.0, 0)
    )
    try:
        check_all_pages_fit(plan, big)
    except ValueError as exc:
        assert "超出纸张" in str(exc)
    else:
        raise AssertionError("补偿越界未被阻止")

    print(f"[bootstrap] 自检通过（FastAPI {fastapi.__version__}, "
          f"Pydantic {pydantic.VERSION}）")
    print("[bootstrap] 初始化完成，等待 uvicorn 启动 ...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
