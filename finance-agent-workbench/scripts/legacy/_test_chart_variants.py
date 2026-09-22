# -*- coding: utf-8 -*-
"""P5 变体底座回归测试：generate_chart 变体解析（§13.1 验收）。

覆盖：
  1. line / line-smooth / line-simple 全部可解析
  2. line ≡ line-smooth（平滑）；line-simple = 无平滑（行为差异正确）
  3. bar-stacked（含连字符类型名）不被 bar 抢
  4. 非法变体名报错且列出可用清单（变体白名单）
  5. 其余 14 类型默认变体行为不变（回归兼容）

运行: python scripts/_test_chart_variants.py
"""
from __future__ import annotations

import os
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import storage.db as sdb  # noqa: E402
_tmp = tempfile.mkdtemp(prefix="p5v_")
sdb.DB_PATH = os.path.join(_tmp, "test.db")

from tools.financial_analysis_tools import (  # noqa: E402
    generate_chart, _resolve_chart_template, CHART_TEMPLATE_NAMES,
)

FAIL = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(("PASS" if ok else "FAIL"), label, detail)
    if not ok:
        FAIL.append(label)


def main() -> None:
    data = {"categories": ["1月", "2月", "3月"], "series": [{"name": "收入", "data": [100, 120, 110]}]}
    dt = [{"月": "1月", "收入": 100}, {"月": "2月", "收入": 120}, {"月": "3月", "收入": 110}]

    # 1. 解析
    check("解析 line", _resolve_chart_template("line") == ("line", None))
    check("解析 line-smooth", _resolve_chart_template("line-smooth") == ("line", "smooth"))
    check("解析 line-simple", _resolve_chart_template("line-simple") == ("line", "simple"))
    check("解析 line-area", _resolve_chart_template("line-area") == ("line", "area"))
    check("解析 line-area-stack", _resolve_chart_template("line-area-stack") == ("line", "area-stack"))
    check("解析 line-forecast", _resolve_chart_template("line-forecast") == ("line", "forecast"))
    check("解析 bar-rounded", _resolve_chart_template("bar-rounded") == ("bar", "rounded"))
    check("解析 bar-horizontal", _resolve_chart_template("bar-horizontal") == ("bar", "horizontal"))
    check("解析 pie-half-donut", _resolve_chart_template("pie-half-donut") == ("pie", "half-donut"))
    check("解析 pie-nested", _resolve_chart_template("pie-nested") == ("pie", "nested"))
    check("解析 scatter-regression", _resolve_chart_template("scatter-regression") == ("scatter", "regression"))
    check("解析 heatmap-calendar", _resolve_chart_template("heatmap-calendar") == ("heatmap", "calendar"))
    check("解析 gauge-stage", _resolve_chart_template("gauge-stage") == ("gauge", "stage"))
    check("解析 bar-stacked 不被 bar 抢", _resolve_chart_template("bar-stacked") == ("bar-stacked", None))
    check("非法变体拒绝", _resolve_chart_template("line-xyz") == (None, None))
    check("未知类型拒绝", _resolve_chart_template("nope") == (None, None))

    # 2. 行为：line ≡ line-smooth（smooth=True）；line-simple 无平滑；line-area 面积；line-forecast 虚线
    r1 = generate_chart("line", data=data, data_table=dt)["result"]["option"]["series"][0]
    r2 = generate_chart("line-smooth", data=data, data_table=dt)["result"]["option"]["series"][0]
    r3 = generate_chart("line-simple", data=data, data_table=dt)["result"]["option"]["series"][0]
    r4 = generate_chart("line-area", data=data, data_table=dt)["result"]["option"]["series"][0]
    r5 = generate_chart("line-forecast", data=data, data_table=dt)["result"]["option"]["series"][0]
    check("line 平滑", r1.get("smooth") is True)
    check("line-smooth 平滑", r2.get("smooth") is True)
    check("line ≡ line-smooth", r1 == r2)
    check("line-simple 无平滑", r3.get("smooth") is False)
    check("line-area 面积", "areaStyle" in r4, str(list(r4.keys())))
    check("line-forecast 虚线", r5.get("lineStyle", {}).get("type") == "dashed", str(r5.get("lineStyle")))

    # 3. bar-stacked 堆叠 + bar-horizontal 水平
    rb = generate_chart("bar-stacked", data=data, data_table=dt)["result"]["option"]["series"]
    check("bar-stacked stack=total", all(s.get("stack") == "total" for s in rb))
    rh = generate_chart("bar-horizontal", data=data, data_table=dt)["result"]["option"]
    check("bar-horizontal y 轴类别", rh.get("yAxis", {}).get("type") == "category", str(rh.get("yAxis")))

    # 4. 非法变体报错列出清单（变体白名单）
    err = generate_chart("line-xyz", data=data, data_table=dt)
    check("非法变体报错", not err.get("success") and "可用" in (err.get("error") or ""))
    check("可用清单含新变体", "line-area" in (err.get("error") or ""))
    check("可用清单含 bar-rounded", "bar-rounded" in (err.get("error") or ""))

    # 5. 其余 14 类型默认变体行为不变（回归兼容）
    ok_count = 0
    for t in ["bar", "pie", "scatter", "heatmap", "waterfall", "radar", "boxplot",
              "histogram", "tornado", "funnel", "dual-axis", "sunburst", "sankey", "gauge"]:
        r = generate_chart(t, data=data, data_table=dt)
        if r.get("success") and r["result"]["option"].get("series"):
            ok_count += 1
        else:
            FAIL.append(f"类型 {t}")
    check("14 类型默认变体渲染", ok_count == 14, f"{ok_count}/14")

    # 6. 新变体也能产出 option（pie-nested / gauge-stage / scatter-regression）
    for t in ["pie-nested", "gauge-stage", "scatter-regression", "heatmap-discrete",
              "sankey-vertical", "funnel-compare", "boxplot-multi", "waterfall-bar", "radar-multi"]:
        r = generate_chart(t, data=data, data_table=dt)
        check(f"变体 {t} 可产出", r.get("success") and r["result"]["option"].get("series") is not None,
              "error=" + str(r.get("error")) if not r.get("success") else "")

    # 7. 模板名清单完整性
    check("模板名清单含新变体", "line-area" in CHART_TEMPLATE_NAMES, str(CHART_TEMPLATE_NAMES))
    check("模板名清单不含等价变体 line-smooth", "line-smooth" not in CHART_TEMPLATE_NAMES)

    # 8. P5-③ 新增类型可解析 + 可产出
    check("解析 treemap", _resolve_chart_template("treemap") == ("treemap", None))
    check("解析 treemap-drilldown", _resolve_chart_template("treemap-drilldown") == ("treemap", "drilldown"))
    check("解析 graph-circle", _resolve_chart_template("graph-circle") == ("graph", "circle"))
    check("解析 parallel", _resolve_chart_template("parallel") == ("parallel", None))
    check("解析 error-bar", _resolve_chart_template("error-bar") == ("error-bar", None))
    check("解析 error-bar-range", _resolve_chart_template("error-bar-range") == ("error-bar", "range"))
    check("解析 calendar-year", _resolve_chart_template("calendar-year") == ("calendar", "year"))
    check("模板名清单含新类型", all(n in CHART_TEMPLATE_NAMES for n in ["treemap", "graph", "parallel", "error-bar", "calendar"]))

    # 树形数据
    tree_data = {"series": [{"name": "预算", "data": [
        {"name": "销售部", "value": 100, "children": [{"name": "A组", "value": 60}, {"name": "B组", "value": 40}]},
        {"name": "研发部", "value": 80},
    ]}]}
    graph_data = {"categories": ["客户", "内部"], "nodes": [
        {"name": "A公司", "category": 0, "value": 100},
        {"name": "B公司", "category": 0, "value": 80},
        {"name": "销售部", "category": 1, "value": 180},
    ], "links": [{"source": "A公司", "target": "销售部", "value": 100}, {"source": "B公司", "target": "销售部", "value": 80}]}
    parallel_data = {"categories": ["营收", "利润率", "周转"], "series": [{"name": "公司1", "data": [[100, 0.15, 1.2], [200, 0.2, 1.5]]}]}
    err_data = {"categories": ["1月", "2月"], "series": [{"name": "预测", "data": [[100, 90, 110], [120, 105, 135]]}]}
    cal_data = {"series": [{"name": "回款", "data": [["2025-01-05", 1200], ["2025-01-06", 800]]}]}
    cal_data2 = {"categories": ["2025-01-01", "2025-12-31"], "series": [{"name": "回款", "data": [["2025-01-05", 1200]]}]}

    r_treemap = generate_chart("treemap", data=tree_data, data_table=dt)["result"]["option"]["series"][0]
    check("treemap 树形数据", r_treemap.get("type") == "treemap" and r_treemap.get("data"), str(r_treemap.get("type")))
    r_drill = generate_chart("treemap-drilldown", data=tree_data, data_table=dt)["result"]["option"]["series"][0]
    check("treemap-drilldown leafDepth", r_drill.get("leafDepth") == 1, str(r_drill.get("leafDepth")))

    r_graph = generate_chart("graph", data=graph_data, data_table=dt)["result"]["option"]["series"][0]
    check("graph force 布局", r_graph.get("layout") == "force", str(r_graph.get("layout")))
    r_circle = generate_chart("graph-circle", data=graph_data, data_table=dt)["result"]["option"]["series"][0]
    check("graph-circle 环形布局", r_circle.get("layout") == "circular", str(r_circle.get("layout")))

    r_parallel = generate_chart("parallel", data=parallel_data, data_table=dt)["result"]["option"]
    check("parallel 维度", len(r_parallel.get("parallelAxis") or []) == 3, str(len(r_parallel.get("parallelAxis") or [])))

    r_err = generate_chart("error-bar", data=err_data, data_table=dt)["result"]["option"]
    check("error-bar 产出", r_err.get("series"), str(r_err.get("series"))[:80])
    r_err_range = generate_chart("error-bar-range", data=err_data, data_table=dt)["result"]["option"]
    check("error-bar-range 区间带", len(r_err_range.get("series") or []) == 3, str(len(r_err_range.get("series") or [])))

    r_cal = generate_chart("calendar", data=cal_data, data_table=dt)["result"]["option"]
    check("calendar 日历", r_cal.get("calendar") and r_cal.get("series"), str(r_cal.get("calendar", {}).get("range")))
    r_cal2 = generate_chart("calendar", data=cal_data2, data_table=dt)["result"]["option"]
    check("calendar categories 兜底", (r_cal2.get("calendar") or {}).get("range") == ["2025-01-01", "2025-12-31"],
          str((r_cal2.get("calendar") or {}).get("range")))

    # ── P6-② 3D + 联动 ──
    # 9. scatter3d / bar3d / histogram-4grid 解析 + 产出
    check("解析 scatter3d", _resolve_chart_template("scatter3d") == ("scatter3d", None))
    check("解析 bar3d", _resolve_chart_template("bar3d") == ("bar3d", None))
    check("解析 histogram-4grid", _resolve_chart_template("histogram-4grid") == ("histogram-4grid", None))
    check("模板名清单含 3D/联动", all(n in CHART_TEMPLATE_NAMES for n in ["scatter3d", "bar3d", "histogram-4grid"]))

    s3d_data = {"axisNames": ["收入", "利润率", "周转率"], "color_scheme": "blacks",
                "series": [{"name": "样本", "data": [[50, 8, 1.2], [120, 15, 0.8], [80, 12, 2.1]]}]}
    r_s3d = generate_chart("scatter3d", data=s3d_data, data_table=dt)["result"]["option"]
    check("scatter3d 类型", r_s3d.get("series", [{}])[0].get("type") == "scatter3D",
          str(r_s3d.get("series", [{}])[0].get("type")))
    check("scatter3d grid3D+viewControl", "grid3D" in r_s3d and "viewControl" in r_s3d.get("grid3D", {}),
          str(list(r_s3d.keys())))
    check("scatter3d visualMap 深浅", "visualMap" in r_s3d and r_s3d["visualMap"].get("inRange", {}).get("color"),
          str(r_s3d.get("visualMap", {}).get("inRange")))

    b3d_data = {"xCategories": ["销售部", "研发部"], "yCategories": ["Q1", "Q2"],
                "color_scheme": "blacks",
                "series": [{"name": "金额", "data": [[0, 0, 120], [0, 1, 135], [1, 0, 90], [1, 1, 105]]}]}
    r_b3d = generate_chart("bar3d", data=b3d_data, data_table=dt)["result"]["option"]
    check("bar3d 类型", r_b3d.get("series", [{}])[0].get("type") == "bar3D",
          str(r_b3d.get("series", [{}])[0].get("type")))
    check("bar3d lambert 着色", r_b3d.get("series", [{}])[0].get("shading") == "lambert",
          str(r_b3d.get("series", [{}])[0].get("shading")))
    check("bar3d xAxis3D 类别", r_b3d.get("xAxis3D", {}).get("data") == ["销售部", "研发部"],
          str(r_b3d.get("xAxis3D", {}).get("data")))

    h4_data = {"xAxisName": "单价", "yAxisName": "销量",
               "series": [{"name": "样本", "data": [[8.3, 143], [8.6, 214], [10.5, 26], [11.0, 176]]}]}
    r_h4 = generate_chart("histogram-4grid", data=h4_data, data_table=dt)["result"]["option"]
    check("histogram-4grid 3 series", len(r_h4.get("series") or []) == 3, str(len(r_h4.get("series") or [])))
    check("histogram-4grid 3 grid", len(r_h4.get("grid") or []) == 3, str(len(r_h4.get("grid") or [])))
    check("histogram-4grid 散点+分箱", r_h4.get("series", [{}])[0].get("type") == "scatter"
          and r_h4.get("series", [{}])[1].get("type") == "bar",
          str([s.get("type") for s in r_h4.get("series", [])]))

    # 10. 3D 数据点 z 值范围计算 visualMap
    check("scatter3d visualMap min/max", r_s3d["visualMap"]["min"] == 0.8 and r_s3d["visualMap"]["max"] == 2.1,
          f"{r_s3d['visualMap']['min']}~{r_s3d['visualMap']['max']}")

    print("\n失败项:", FAIL if FAIL else "无")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
