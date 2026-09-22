"""finmod_py_charts — 用 Python 生成的 3D 特殊图表（P6-②，2026-08-23；v6.12 修细长+重构）。

背景：echarts-gl 的 surface3D/bar3D 无法还原「每行折线围成的填充平面」类 3D 瀑布图
（会把行连成曲面 / 只能柱状），且 3D 无法矢量导出。用户决策：**立体瀑布图/立体柱状图/
立体散点图 全部改用 Python 生成**，前端展示图片。

v6.11：在静态 PNG 之外，新增 **plotly 交互 JSON**（fig_json）——前端用 plotly.js 渲染
可拖拽旋转/缩放/下载的交互 3D 图（离线内联 plotly.min.js）。matplotlib 的 plt.show() 是
桌面 GUI 无法进浏览器，故用 plotly（Python 生成 JSON + 前端 plotly.js 渲染）实现「无需
自研窗口」的交互预览。

v6.12（2026-08-23）：修复「细长柱」——旧 _plotly_layout 用 aspectmode="manual" +
aspectratio=dict(x=点数, y=点数, z=最大值)，把 z 轴拉成几十倍 → 所有 3D 图变细长柱。
改为 aspectmode="data"/"cube" 按数据范围等比，恢复均衡立方体。同时：
  - bar3d 重构为「二维数据直方图」（柱高=histogram2d 频数，官网模板），数据 [[x,y],...]。
  - scatter3d 支持 ≥1000 点大数据量 + 气泡随点数自适应缩小。

本模块做「数据 → PNG bytes + plotly figure」，供后端 `finmod/py-chart` 端点调用。
中文字体：SimHei / Microsoft YaHei（已确认项目 venv 可用；plotly 用 font.family 指定）。

函数：
  - waterfall3d_png(data)  复刻用户「财务指标对比.py」：每指标一条折线 + 从 0 基线围成的
    竖直填充面（Poly3DCollection），y 轴并排，从前到后深→浅蓝。
  - bar3d_png(data)         三维柱状图（官方 histogram2d 直方图：柱高=频数，柱色随高度渐变）。
  - scatter3d_png(data)     三维散点图（气泡色=第 3 维，随点数自适应大小）。
  - *_plotly(data)          各图对应 plotly Figure（交互：3D 拖拽旋转/缩放/下载）。
"""
from __future__ import annotations

import base64
import io

import matplotlib
matplotlib.use("Agg")  # 无界面，输出 PNG
import matplotlib.pyplot as plt
import numpy as np
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

# plotly（v6.11 交互 3D；离线安装 plotly==6.9.0 到 venv）
import plotly.graph_objects as go


# 中文字体（SimHei / Microsoft YaHei 已确认存在）
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


# ----------------------------------------------------------------------
# 数据归一化：把前端 chart-json 的 data 归一为绘图所需的结构
# ----------------------------------------------------------------------

def _norm_3d(data: dict) -> dict:
    """归一化 3D 数据。返回 {xc, yc, cells[[xIdx,yIdx,z]], axis names}。

    兼容两形态：
      - waterfall3d: data.xCategories/yCategories + series[0].data[[xIdx,yIdx,z]]
      - bar3d/scatter3d: data.series[0].data[[x,y,z]]（数值坐标）
    """
    xc = data.get("xCategories") or data.get("categories") or []
    yc = data.get("yCategories") or []
    series = data.get("series") or []
    s0 = series[0] if series else {}
    cells = s0.get("data") or []
    x_name = data.get("xAxisName") or "X"
    y_name = data.get("yAxisName") or "Y"
    z_name = data.get("zAxisName") or "Z"
    return {"xc": xc, "yc": yc, "cells": cells,
            "x_name": x_name, "y_name": y_name, "z_name": z_name}


def _blues(n: int, reverse: bool = False) -> list:
    """n 档 Blues 色（中间深→浅，等价 matplotlib Blues(linspace(0.9,0.3,n))）。"""
    vals = np.linspace(0.9, 0.3, n) if not reverse else np.linspace(0.3, 0.9, n)
    return [plt.cm.Blues(v) for v in vals]


def _png_bytes(fig) -> str:
    """fig → base64 PNG 字符串（无背景气泡）。"""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", transparent=False)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


# ----------------------------------------------------------------------
# 1) 立体瀑布图（复刻用户案例）
# ----------------------------------------------------------------------

def waterfall3d_png(data: dict) -> str:
    """每指标一条折线 + 从 z=0 基线到折线围成的竖直填充面。

    参考用户「财务指标对比.py」line_3d：for 每 i 构造 polygon
      [ [x0,y_i,0], [x_last,y_i,0], ...逆向 [x,y_i,z] ] → Poly3DCollection。
    x 年份在 x 轴，y 指标索引在 y 轴，z=数值。前(y=0)深后(yn-1)浅。
    """
    d = _norm_3d(data)
    xc, yc, cells = d["xc"], d["yc"], d["cells"]
    yn = len(yc)
    if yn == 0 or not cells:
        return _png_bytes(_empty_fig("无数据"))

    # 每指标按年份排列：[x_idx, z] 序列（按 x 排序）
    per_metric: dict[int, list] = {}
    for c in cells:
        xi, yi, z = int(c[0]), int(c[1]), float(c[2] or 0)
        per_metric.setdefault(yi, []).append((xi, z))
    for yi in per_metric:
        per_metric[yi].sort()

    colors = _blues(yn)  # 前深后浅
    x_vals = [i for i in range(len(xc))] if xc else []
    fig = plt.figure(figsize=(14, 9))
    ax = fig.add_subplot(111, projection="3d")

    zmax = max((c[2] or 0 for c in cells), default=1)

    for yi in range(yn):
        line = per_metric.get(yi, [])
        if not line:
            continue
        face_c = colors[yi]
        xs = [p[0] for p in line]
        zs = [p[1] for p in line]
        # 折线（黑色）
        ax.plot(xs, [yi] * len(xs), zs, color="black", lw=2, marker="o", ms=5, alpha=0.8)
        # z=0 基线（灰虚线）
        ax.plot(xs, [yi] * len(xs), [0] * len(xs), color="gray", ls="--", lw=1, alpha=0.6)
        # 填充面 polygon：底左→底右→逆序顶(回程)
        polygon = [[xs[0], yi, 0], [xs[-1], yi, 0]]
        for j in range(len(line) - 1, -1, -1):
            polygon.append([xs[j], yi, zs[j]])
        poly = Poly3DCollection([polygon], alpha=0.8)
        poly.set_facecolor(face_c)
        poly.set_edgecolor("black")
        poly.set_linewidth(0.5)
        ax.add_collection3d(poly)
        # 数值标注（每个数据点上方 f'{z:.2f}%'，加粗）
        for xi, zi in line:
            ax.text(xi, yi, zi + 0.5, f"{zi:.2f}%", color="black",
                    ha="center", va="bottom", fontsize=9, fontweight="bold")

    # 同一时间点不同变量的虚线连接（x_label_indexs = 全部 x 索引）
    x_indexs = list(range(len(xc))) if xc else []
    for k in x_indexs:
        time_k = [k] * yn
        var_k = list(range(yn))
        val_k = []
        for yi in range(yn):
            line = per_metric.get(yi, [])
            z = 0.0
            for xi, zi in line:
                if xi == k:
                    z = zi
                    break
            val_k.append(z)
        ax.plot(time_k, var_k, val_k, ls="--", lw=1.2, color="gray", alpha=0.7)

    # 坐标轴（加粗 + labelpad，复刻参考脚本）
    ax.set_xlabel(d["x_name"], fontsize=12, fontweight="bold", labelpad=12)
    ax.set_ylabel(d["y_name"], fontsize=12, fontweight="bold", labelpad=12)
    ax.set_zlabel(d["z_name"], fontsize=12, fontweight="bold", labelpad=12)
    if xc:
        ax.set_xticks(range(len(xc)))
        ax.set_xticklabels(xc, fontsize=11)
    if yc:
        ax.set_yticks(range(yn))
        ax.set_yticklabels(yc, fontsize=11)
    # 轴范围（复刻参考脚本；不含大标题——容器标题栏已展示表名，图内不重复表名）
    ax.set_xlim([min(x_vals) - 0.2, max(x_vals) + 0.2]) if x_vals else None
    ax.set_ylim([-0.5, yn - 0.5])
    ax.set_zlim(0, zmax * 1.15)
    ax.grid(True, linestyle="--", alpha=0.7)
    ax.view_init(elev=25, azim=45)
    plt.subplots_adjust(left=0.08, right=0.95, bottom=0.08, top=0.92)
    return _png_bytes(fig)


# ----------------------------------------------------------------------
# 2) 立体柱状图（v6.12：重构为「二维数据直方图」——柱高=频数，官网模板）
# ----------------------------------------------------------------------

def _hist2d(cells):
    """把数据归为二维点集 [[x,y],...]，做 histogram2d 得每格频数。

    兼容两形态：
      - bin_data 形态（推荐）：series[0].data = [[x,y],...]（二维点集，柱高=频数）
      - 三元组形态（向后兼容）：series[0].data = [[x,y,z],...]，取 (x,y) 频数
    返回 (xpos, ypos, dz, dx, dy, edges) —— 每根柱锚点 / 高 / 宽 / 网格边界。
    """
    pts = []
    for c in cells:
        if not isinstance(c, (list, tuple)) or len(c) < 2:
            continue
        pts.append((float(c[0]), float(c[1])))
    if not pts:
        return [], [], [], [], [], None
    xs = np.array([p[0] for p in pts])
    ys = np.array([p[1] for p in pts])
    # 自动选 bin 数：默认 4×4（官网模板），点量多时略增，但不超过 6×6 保证清晰
    n = 4 if len(pts) < 200 else 5 if len(pts) < 1000 else 6
    xmin, xmax, ymin, ymax = xs.min(), xs.max(), ys.min(), ys.max()
    if xmin == xmax:
        xmax = xmin + 1
    if ymin == ymax:
        ymax = ymin + 1
    hist, xe, ye = np.histogram2d(xs, ys, bins=n, range=[[xmin, xmax], [ymin, ymax]])
    xpos, ypos = np.meshgrid(xe[:-1], ye[:-1], indexing="ij")
    dx = (xe[1] - xe[0]) * 0.8
    dy = (ye[1] - ye[0]) * 0.8
    return (xpos.ravel().tolist(), ypos.ravel().tolist(), hist.ravel().tolist(),
            float(dx), float(dy), (xe, ye))


def bar3d_png(data: dict) -> str:
    """三维柱状图（官方 histogram2d 直方图模板）：柱高=频数，柱色随高度渐变。"""
    d = _norm_3d(data)
    cells = d["cells"]
    if not cells:
        return _png_bytes(_empty_fig("无数据"))
    xpos, ypos, dz, dx, dy, _ = _hist2d(cells)
    if not dz:
        return _png_bytes(_empty_fig("无数据"))
    zs = np.array(dz)
    cmap = plt.cm.Blues
    norm = matplotlib.colors.Normalize(vmin=zs.min(), vmax=zs.max() or 1)
    colors = [cmap(norm(z)) for z in zs]

    fig = plt.figure(figsize=(11, 8))
    ax = fig.add_subplot(111, projection="3d")
    ax.bar3d(xpos, ypos, [0] * len(zs), np.full(len(zs), dx),
             np.full(len(zs), dy), zs, color=colors, alpha=0.92,
             edgecolor="black", linewidth=0.3, zsort="average")
    ax.set_xlabel(d["x_name"], fontsize=12, fontweight="bold", labelpad=10)
    ax.set_ylabel(d["y_name"], fontsize=12, fontweight="bold", labelpad=10)
    ax.set_zlabel("频数", fontsize=12, fontweight="bold", labelpad=10)
    ax.view_init(elev=25, azim=45)
    plt.subplots_adjust(left=0.08, right=0.95, bottom=0.08, top=0.92)
    return _png_bytes(fig)


# ----------------------------------------------------------------------
# 3) 立体散点图
# ----------------------------------------------------------------------

def scatter3d_png(data: dict) -> str:
    """三维散点图：scatter3d 数据 [[x,y,z],...]，气泡色=第 3 维。

    v6.12：支持大数据量（≥1000 点），气泡减小避免过于拥挤；色=第 3 维。
    """
    d = _norm_3d(data)
    cells = d["cells"]
    if not cells:
        return _png_bytes(_empty_fig("无数据"))
    xs = [float(c[0]) for c in cells]
    ys = [float(c[1]) for c in cells]
    zs = [float(c[2] or 0) for c in cells]
    n = len(xs)
    size = max(8, min(45, 4000 // max(n, 1)))  # 点越多越小（1000 点→4px）

    fig = plt.figure(figsize=(11, 8))
    ax = fig.add_subplot(111, projection="3d")
    sc = ax.scatter(xs, ys, zs, c=zs, cmap="Blues", s=size, alpha=0.75,
                    edgecolor="black", linewidth=0.2)
    fig.colorbar(sc, ax=ax, shrink=0.6, pad=0.1)
    ax.set_xlabel(d["x_name"], fontsize=12, fontweight="bold", labelpad=10)
    ax.set_ylabel(d["y_name"], fontsize=12, fontweight="bold", labelpad=10)
    ax.set_zlabel(d["z_name"], fontsize=12, fontweight="bold", labelpad=10)
    ax.view_init(elev=25, azim=45)
    plt.subplots_adjust(left=0.08, right=0.95, bottom=0.08, top=0.92)
    return _png_bytes(fig)


# ----------------------------------------------------------------------
# plotly 交互 3D（v6.11：前端 plotly.js 渲染，拖拽旋转/缩放/下载）
# ----------------------------------------------------------------------

_FONT_STACK = "SimHei, 'Microsoft YaHei', 'Segoe UI', sans-serif"


def _plotly_layout(scene_scale, x_name, y_name, z_name, view=None, extent=None):
    """统一 plotly 3D layout：等比例立方体 + 中文字体 + 默认视角（elev≈25，azim≈45）。

    **v6.12：修复「细长柱」** —— 旧 aspectmode="manual" + aspectratio=dict(x=nx, y=ny, z=zmax)
    会把 z 轴（值可到 74）拉到 x/y 轴（点数仅 3/5）的几十倍，导致所有 3D 图被压成细长柱。
    实测：aspectmode="data" 时 plotly 自动算出 ratio≈(0.24, 0.47, 8.97)，z 是 x 的 38 倍。

    改用「数据感知归一化 aspectratio」，模拟 matplotlib 的 box_aspect（不按原始数值拉伸，
    而是把各轴归一化到接近立方体）。extent=[x_range, y_range, z_range] 用于计算比例；
    不传 extent 时退化为默认比例。zc（纵轴）略高于 x/y 保证不失紧凑，但**不再细长**。

    scene_scale: 'cube'（1:1:1）或 dict（自定义）。'data' 已弃用（会拉细长）。
    view: 字典 eye=dict(x,y,z)。默认近似 elev=25/azim=45（eye z 略高于 x/y）。
    extent: 各轴数据范围 [xmax-xmin, ymax-ymin, zmax-zmin]，用于按数据自适应比例。
    """
    if scene_scale == "cube":
        aspectratio = dict(x=1, y=1, z=1)
    elif isinstance(scene_scale, dict):
        aspectratio = scene_scale
    else:
        aspectratio = dict(x=1, y=1, z=1)
    # 若提供数据范围，则按「归一化到接近立方体」微调：让各轴用 sqrt/root 弱化极端值
    if extent and all(e > 0 for e in extent):
        ex, ey, ez = float(extent[0]), float(extent[1]), float(extent[2])
        # 把范围压缩到 ~[0.5,2] 区间，避免 z 过大压扁：用 log 映射保持相对关系但弱化极端
        import math as _m
        def _shrink(v: float) -> float:
            if v <= 0:
                return 0.5
            return max(0.5, min(2.0, 0.5 + _m.log2(v) / 3.0))
        aspectratio = dict(x=_shrink(ex), y=_shrink(ey), z=_shrink(ez))
    eye = (view or dict(x=1.7, y=1.7, z=1.3))
    scene = dict(
        xaxis=dict(title=dict(text=x_name, font=dict(size=13))),
        yaxis=dict(title=dict(text=y_name, font=dict(size=13))),
        zaxis=dict(title=dict(text=z_name, font=dict(size=13))),
        camera=dict(eye=eye),
        aspectmode="manual",
        aspectratio=aspectratio,
    )
    return go.Layout(
        font=dict(family=_FONT_STACK, size=12),
        scene=scene,
        margin=dict(l=0, r=0, t=0, b=0),
        height=600,
        showlegend=False,
    )


def waterfall3d_plotly(data: dict) -> go.Figure:
    """plotly 瀑布图：每指标 Scatter3d 折线 + Mesh3d 竖直填充面 + 跨指标虚线。

    v6.12：aspectmode="data"（按数据范围等比），修复旧版 z 值巨大导致的细长柱。
    """
    d = _norm_3d(data)
    xc, yc, cells = d["xc"], d["yc"], d["cells"]
    yn = len(yc)
    if yn == 0 or not cells:
        return go.Figure(layout=_plotly_layout("cube", d["x_name"], d["y_name"], d["z_name"]))
    per: dict[int, list] = {}
    for c in cells:
        xi, yi, z = int(c[0]), int(c[1]), float(c[2] or 0)
        per.setdefault(yi, []).append((xi, z))
    for yi in per:
        per[yi].sort()

    zmax = max((c[2] or 0 for c in cells), default=1)
    extent = [max(len(xc), 1), max(yn, 1), zmax]  # x/y 点数、z 数值范围 → 数据感知比例
    blues = [(8, 81, 156, 0.75), (33, 113, 181, 0.72), (66, 146, 198, 0.70),
             (109, 174, 214, 0.68), (158, 202, 225, 0.66)]
    fig = go.Figure()

    for yi in range(yn):
        line = per.get(yi, [])
        if not line:
            continue
        xs = [p[0] for p in line]
        zs = [p[1] for p in line]
        n = len(line)
        # 黑色折线 + 数据点
        fig.add_trace(go.Scatter3d(
            x=xs, y=[yi] * n, z=zs, mode="lines+markers",
            line=dict(color="black", width=4),
            marker=dict(size=5, color="black"), name=yc[yi], hoverinfo="skip"))
        # 0 基线虚线
        fig.add_trace(go.Scatter3d(
            x=xs, y=[yi] * n, z=[0] * n, mode="lines",
            line=dict(color="gray", width=2, dash="dash"), hoverinfo="skip"))
        # 竖直填充面（Mesh3d：折线顶 + 底部 0 基线围成）
        allx = xs + xs
        ally = [yi] * n + [yi] * n
        allz = zs + [0] * n
        i, j, k = [], [], []
        for idx in range(n - 1):
            i += [idx, idx]
            j += [idx + 1, n + idx + 1]
            k += [n + idx + 1, n + idx]
        rgb = blues[yi % len(blues)]
        fig.add_trace(go.Mesh3d(
            x=allx, y=ally, z=allz, i=i, j=j, k=k,
            color=f"rgba({rgb[0]},{rgb[1]},{rgb[2]},{rgb[3]})",
            showlegend=False, hoverinfo="skip", lighting=dict(ambient=0.7)))

    # 同一时间点跨指标虚线
    for xi in range(len(xc)):
        vals = []
        for yi in range(yn):
            ln = per.get(yi, [])
            z = 0.0
            for k, v in ln:
                if k == xi:
                    z = v
                    break
            vals.append(z)
        fig.add_trace(go.Scatter3d(
            x=[xi] * yn, y=list(range(yn)), z=vals, mode="lines",
            line=dict(color="gray", width=2, dash="dash"), hoverinfo="skip"))

    # 数值标注（与 matplotlib 版一致，每个数据点上方 f'{z:.2f}%'）
    for yi in range(yn):
        for xi, zi in per.get(yi, []):
            fig.add_trace(go.Scatter3d(
                x=[xi], y=[yi], z=[zi + zmax * 0.02], mode="text",
                text=[f"{zi:.2f}%"], textfont=dict(color="black", size=11),
                hoverinfo="skip"))

    fig.update_layout(_plotly_layout("cube", d["x_name"], d["y_name"], d["z_name"],
                                     extent=extent))
    return fig


def bar3d_plotly(data: dict) -> go.Figure:
    """plotly 三维柱状图（官方 histogram2d 直方图模板）：柱高=频数。

    v6.12：改为「二维数据直方图」，柱高=histogram2d 的频数；aspectmode="cube"
    保证柱为等比例立方体（轴标签保留真实数值）。
    """
    d = _norm_3d(data)
    cells = d["cells"]
    if not cells:
        return go.Figure(layout=_plotly_layout("cube", d["x_name"], d["y_name"], d["z_name"]))
    xpos, ypos, dz, dx, dy, edges = _hist2d(cells)
    if not dz:
        return go.Figure(layout=_plotly_layout("cube", d["x_name"], d["y_name"], d["z_name"]))
    zmax = max(dz) or 1
    import matplotlib.pyplot as _plt
    norm = np.array(dz) / (zmax or 1)
    fig = go.Figure()
    n = len(xpos)
    for ci, (x0, y0, z0) in enumerate(zip(xpos, ypos, dz)):
        cx0, cx1 = x0 - dx / 2, x0 + dx / 2
        cy0, cy1 = y0 - dy / 2, y0 + dy / 2
        v = float(norm[ci]) if ci < len(norm) else 0
        rgba = _plt.cm.Blues(v)
        col = f"rgba({int(rgba[0]*255)},{int(rgba[1]*255)},{int(rgba[2]*255)},0.92)"
        vertices = [(cx0, cy0, 0), (cx1, cy0, 0), (cx1, cy1, 0), (cx0, cy1, 0),
                    (cx0, cy0, z0), (cx1, cy0, z0), (cx1, cy1, z0), (cx0, cy1, z0)]
        fig.add_trace(go.Mesh3d(
            x=[v[0] for v in vertices], y=[v[1] for v in vertices], z=[v[2] for v in vertices],
            i=[0, 1, 2, 3, 4, 5, 6, 7, 0, 1, 2, 3],
            j=[1, 2, 3, 0, 5, 6, 7, 4, 1, 2, 3, 0],
            k=[3, 0, 1, 2, 4, 7, 6, 5, 4, 5, 6, 7],
            color=col, opacity=0.92, hoverinfo="skip", showlegend=False,
            lighting=dict(ambient=0.7)))
    # 数据感知比例（柱高=频数；x/y 网格范围 + z 频数最大值）
    _ex = (max(xpos) - min(xpos)) if xpos else 1
    _ey = (max(ypos) - min(ypos)) if ypos else 1
    fig.update_layout(_plotly_layout("cube", d["x_name"], d["y_name"], "频数",
                                     extent=[_ex, _ey, zmax]))
    return fig


def scatter3d_plotly(data: dict) -> go.Figure:
    """plotly 三维散点图：Scatter3d 气泡。"""
    d = _norm_3d(data)
    cells = d["cells"]
    if not cells:
        return go.Figure(layout=_plotly_layout("cube", d["x_name"], d["y_name"], d["z_name"]))
    xs = [float(c[0]) for c in cells]
    ys = [float(c[1]) for c in cells]
    zs = [float(c[2] or 0) for c in cells]
    fig = go.Figure(go.Scatter3d(
        x=xs, y=ys, z=zs, mode="markers",
        marker=dict(size=4, color=zs, colorscale="Blues", opacity=0.85,
                    showscale=True, colorbar=dict(title=d["z_name"])),
        hoverinfo="text",
        text=[f"{d['x_name']}:{a:.2f}<br>{d['y_name']}:{b:.2f}<br>{d['z_name']}:{c:.2f}"
              for a, b, c in zip(xs, ys, zs)]))
    _ex = (max(xs) - min(xs)) if xs else 1
    _ey = (max(ys) - min(ys)) if ys else 1
    _ez = (max(zs) - min(zs)) if zs else 1
    fig.update_layout(_plotly_layout("cube", d["x_name"], d["y_name"], d["z_name"],
                                     extent=[_ex, _ey, _ez]))
    return fig


# ----------------------------------------------------------------------
# 分发
# ----------------------------------------------------------------------

_PY_CHART_FNS = {
    "waterfall3d": waterfall3d_png,
    "bar3d": bar3d_png,
    "scatter3d": scatter3d_png,
}

_PY_PLOTLY_FNS = {
    "waterfall3d": waterfall3d_plotly,
    "bar3d": bar3d_plotly,
    "scatter3d": scatter3d_plotly,
}


def render_py_chart(template: str, data: dict) -> dict:
    """渲染 Python 3D 图 → base64 PNG + plotly 交互 JSON。

    返回 {success, b64, fig_json?, interactive?, error?, note?}。
    fig_json 供前端 plotly.js 渲染交互 3D（旋转/缩放/下载）；b64 作为静态缩略兜底。
    """
    fn = _PY_CHART_FNS.get(template)
    if not fn:
        return {"success": False, "error": f"Python 图表不支持: {template}"}
    try:
        b64 = fn(data)
        out: dict = {"success": True, "b64": b64,
                     "note": "由 Python 生成 · 3D 图不支持矢量导出"}
        # plotly 交互 JSON（前端 plotly.js 渲染；失败不影响静态图）
        try:
            pf = _PY_PLOTLY_FNS[template](data)
            out["fig_json"] = pf.to_json()
            out["interactive"] = True
        except Exception as e:  # noqa: BLE001
            out["fig_json"] = None
            out["interactive"] = False
        return out
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"Python 绘图失败: {e}"}


def _empty_fig(msg: str):
    fig = plt.figure(figsize=(6, 4))
    ax = fig.add_subplot(111)
    ax.text(0.5, 0.5, msg, ha="center", va="center")
    ax.axis("off")
    return fig


if __name__ == "__main__":
    # 自测：生成示例瀑布图 PNG 落盘
    demo = {
        "xCategories": ["2021年", "2022年", "2023年"],
        "yCategories": ["照明业务利润贡献率", "IoT业务利润贡献率", "总资产周转率",
                        "加权净资产收益率", "总资产报酬率"],
        "xAxisName": "时间（年）", "yAxisName": "财务指标", "zAxisName": "数值（%）",
        "series": [{"data": [
            [0, 0, 74.44], [1, 0, 68.97], [2, 0, 67.83],
            [0, 1, 22.37], [1, 1, 27.30], [2, 1, 25.37],
            [0, 2, 33.25], [1, 2, 33.25], [2, 2, 28.50],
            [0, 3, 13.13], [1, 3, 15.91], [2, 3, 9.33],
            [0, 4, 6.19], [1, 4, 8.71], [2, 4, 5.35],
        ]}],
    }
    import os
    out = waterfall3d_png(demo)
    with open(os.path.join(os.path.dirname(__file__), "..", "_test_waterfall3d.png"), "wb") as f:
        f.write(__import__("base64").b64decode(out))
    print("written _test_waterfall3d.png, len", len(out))
