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

    from .layout import compute_layout
    from .models import LayoutRequest, LabelSpec, OccupiedZone
    from .svg import build_svg

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

    print(f"[bootstrap] 自检通过（FastAPI {fastapi.__version__}, "
          f"Pydantic {pydantic.VERSION}）")
    print("[bootstrap] 初始化完成，等待 uvicorn 启动 ...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
