"""打印位置校准：拟合走纸误差并给出逆变换。

打印机走纸存在线性误差：实测坐标 m 与设计坐标 d 之间近似为
    m = k*d + b
其中 k 为缩放（走纸比例）误差、b 为平移（起始位置）误差。
对横、纵两组基准刻线分别做最小二乘拟合，得到 X / Y 两个方向各自的
(k, b)。导出 SVG 时对标签内容做逆变换，使打印结果落回设计位置：

    x_draw = (x - b_x) / k_x          y_draw = (y - b_y) / k_y

即 SVG 仿射矩阵 matrix(1/kx, 0, 0, 1/ky, -bx/kx, -by/ky)。

以下情况无法构成有效的线性校准，直接阻止导出：

1. 基准点重合——同一方向两条刻线的设计坐标相同，拟合分母为零；
2. 实测顺序颠倒——实测坐标没有随设计坐标同向增大（k <= 0），
   通常是录入顺序或读数方向错误；
3. 补偿后超出纸张——逆变换后的标签（含外侧裁切角线）越过纸边。

某方向没有任何刻线时该方向不做修正（恒等）；只有一条刻线时
按纯平移处理（k = 1）。
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import (
    Calibration,
    CalibPoint,
    LayoutResponse,
    PageLayout,
)

EPS = 1e-9
FIT_EPS = 1e-6  # 判定“无缩放误差/无偏移”的容差 mm
PAPER_EPS = 0.01  # 补偿后允许越过纸边的容差 mm
CUT_OUTSET = 1.5  # 裁切角线相对标签轮廓的外扩，须与 svg.py 中一致


@dataclass(frozen=True)
class AxisFit:
    """一个方向（X 或 Y）的线性走纸误差拟合结果。"""

    scale: float  # k：每 1mm 设计坐标在纸上的实测长度
    offset: float  # b：零位偏移 mm
    used: int  # 参与拟合的刻线数

    @property
    def is_identity(self) -> bool:
        return self.used == 0 or (
            abs(self.scale - 1.0) <= FIT_EPS and abs(self.offset) <= FIT_EPS
        )

    def inverse(self, v: float) -> float:
        """设计坐标 -> 用于绘制的补偿坐标。"""
        return (v - self.offset) / self.scale


@dataclass(frozen=True)
class CalibrationTransform:
    """X / Y 双方向逆变换。"""

    x: AxisFit
    y: AxisFit

    @property
    def is_identity(self) -> bool:
        return self.x.is_identity and self.y.is_identity

    def matrix_values(self) -> tuple[float, float, float, float, float, float]:
        """SVG transform="matrix(a,b,c,d,e,f)" 的六个参数（毫米）。"""
        return (
            1.0 / self.x.scale,
            0.0,
            0.0,
            1.0 / self.y.scale,
            -self.x.offset / self.x.scale,
            -self.y.offset / self.y.scale,
        )


IDENTITY_AXIS = AxisFit(scale=1.0, offset=0.0, used=0)
IDENTITY_TRANSFORM = CalibrationTransform(x=IDENTITY_AXIS, y=IDENTITY_AXIS)


def _validated(points: list[CalibPoint], axis_name: str) -> list[tuple[float, float]]:
    """整理一个方向的刻线录入值并做基础校验，返回按设计坐标排序的
    (设计, 实测) 列表。"""
    pairs: list[tuple[float, float]] = []
    for i, p in enumerate(points):
        d, m = p.designed, p.measured
        # Pydantic 保证字段存在；这里拦截 NaN / 无穷（float("nan") 可通过类型）
        if any(v != v or v in (float("inf"), float("-inf")) for v in (d, m)):
            raise ValueError(f"{axis_name}方向刻线 {i + 1} 的坐标不是有效数字。")
        if d < 0:
            raise ValueError(
                f"{axis_name}方向刻线 {i + 1} 的设计坐标 ({_num(d)}) 不能为负数。"
            )
        if m < 0:
            raise ValueError(
                f"{axis_name}方向刻线 {i + 1} 的实测坐标 ({_num(m)}) 不能为负数，"
                "请核对测量起点（纸左边缘 / 上边缘）。"
            )
        pairs.append((d, m))
    pairs.sort(key=lambda t: t[0])
    return pairs


def fit_axis(points: list[CalibPoint], axis_name: str) -> AxisFit:
    """最小二乘拟合 实测 = k·设计 + b。

    n=0 恒等；n=1 纯平移；n>=2 线性拟合。
    基准点重合、实测顺序颠倒时抛出带中文原因的 ValueError。
    """
    pairs = _validated(points, axis_name)
    n = len(pairs)
    if n == 0:
        return IDENTITY_AXIS
    if n == 1:
        d, m = pairs[0]
        return AxisFit(scale=1.0, offset=m - d, used=1)

    ds = [d for d, _ in pairs]
    # 阻止条件①：基准点重合（所有设计坐标相同 → 拟合分母为 0）
    if max(ds) - min(ds) <= FIT_EPS:
        raise ValueError(
            f"{axis_name}方向的基准点重合：{n} 条刻线的设计坐标均为 "
            f"{_num(ds[0])}mm，无法求出走纸比例，请使用不同位置的刻线。"
        )

    mean_d = sum(ds) / n
    mean_m = sum(m for _, m in pairs) / n
    sxx = sum((d - mean_d) ** 2 for d in ds)
    sxy = sum((d - mean_d) * (m - mean_m) for d, m in pairs)
    k = sxy / sxx
    b = mean_m - k * mean_d

    # 阻止条件②：实测顺序颠倒（含全部读数相同）。
    # k<=0 意味着实测坐标没有随设计坐标同向增大，必然是录入有误。
    if k <= EPS:
        order = "、".join(_num(m) for _, m in pairs)
        raise ValueError(
            f"{axis_name}方向实测顺序颠倒：设计坐标递增（"
            f"{' → '.join(_num(d) for d in ds)}）但实测坐标为 {order}，"
            "实测坐标必须随设计坐标同向增大，请核对读数方向与录入顺序。"
        )
    return AxisFit(scale=k, offset=b, used=n)


def build_transform(calibration: Calibration | None) -> CalibrationTransform:
    """由校准录入构造 X/Y 逆变换；calibration 为 None 时为恒等。"""
    if calibration is None:
        return IDENTITY_TRANSFORM
    return CalibrationTransform(
        x=fit_axis(calibration.x_points, "X（纵向刻线）"),
        y=fit_axis(calibration.y_points, "Y（横向刻线）"),
    )


def _num(v: float) -> str:
    """错误信息中的坐标格式化。"""
    return f"{v:.2f}".rstrip("0").rstrip(".")


def check_page_fits(
    page: PageLayout,
    page_width: float,
    page_height: float,
    tr: CalibrationTransform,
) -> str | None:
    """阻止条件③：逆变换后的标签（含外扩裁切角线）必须在纸张内。

    返回越界原因；本页全部在纸内时返回 None。恒等变换直接通过。
    """
    if tr.is_identity:
        return None
    for lab in page.labels:
        x0 = tr.x.inverse(lab.x) - CUT_OUTSET
        y0 = tr.y.inverse(lab.y) - CUT_OUTSET
        x1 = tr.x.inverse(lab.x + lab.width) + CUT_OUTSET
        y1 = tr.y.inverse(lab.y + lab.height) + CUT_OUTSET
        if x0 < -PAPER_EPS:
            return (
                f"第 {page.page} 页标签「{lab.name or lab.type_index + 1}」"
                f"补偿后左缘到达 {_num(x0)}mm，超出纸张左边缘，"
                "请减小 X 方向校准量或加大左页边距后再导出。"
            )
        if x1 > page_width + PAPER_EPS:
            return (
                f"第 {page.page} 页标签「{lab.name or lab.type_index + 1}」"
                f"补偿后右缘到达 {_num(x1)}mm，超出纸张宽度 {_num(page_width)}mm，"
                "请减小 X 方向校准量或加大右页边距后再导出。"
            )
        if y0 < -PAPER_EPS:
            return (
                f"第 {page.page} 页标签「{lab.name or lab.type_index + 1}」"
                f"补偿后上缘到达 {_num(y0)}mm，超出纸张上边缘，"
                "请减小 Y 方向校准量或加大上页边距后再导出。"
            )
        if y1 > page_height + PAPER_EPS:
            return (
                f"第 {page.page} 页标签「{lab.name or lab.type_index + 1}」"
                f"补偿后下缘到达 {_num(y1)}mm，超出纸张高度 {_num(page_height)}mm，"
                "请减小 Y 方向校准量或加大下页边距后再导出。"
            )
    return None


def check_all_pages_fit(plan: LayoutResponse, tr: CalibrationTransform) -> None:
    """所有页逐页做越界检查，发现越界即抛出中文原因。"""
    if tr.is_identity:
        return
    for page in plan.pages:
        reason = check_page_fits(page, plan.page_width, plan.page_height, tr)
        if reason:
            raise ValueError("校准补偿超出纸张：" + reason)
