/** treemap 矩形树图模板（P5-③ 新增类型）
 *  - treemap-simple  矩形树图（多层占比：科目/部门）
 *  - treemap-drilldown 可下钻矩形树（leafDepth=1 逐层下钻）
 * 数据结构：
 *   series[0].data = 树形嵌套数据（{name, value, children?}）
 *   categories 可选（根层级名）
 */
import type { EChartsOption } from "echarts";
import type { ChartData } from "./index";
import { CHART_COLORS } from "./index";

/** 基础矩形树图（treemap / treemap-simple）：多层占比一目了然 */
export function buildTreemap(data: ChartData, _title?: string): EChartsOption {
  const s0 = data.series?.[0];
  const tree = (s0?.data || []) as Record<string, unknown>[];
  return {
    color: CHART_COLORS,
    tooltip: {
      trigger: "item",
      formatter: (p: { name: string; value?: number }) => `${p.name}: ${p.value ?? "-"}`,
    } as never,
    series: [
      {
        type: "treemap",
        roam: false,
        nodeClick: "zoomToNode",
        breadcrumb: { show: true, height: 20 },
        label: { show: true, fontSize: 10, overflow: "truncate" },
        upperLabel: { show: true, height: 18, fontSize: 10 },
        itemStyle: { borderColor: "#fff", borderWidth: 1, gapWidth: 1 },
        levels: [
          { itemStyle: { borderColor: "#fff", borderWidth: 1, gapWidth: 1 } },
          { colorSaturation: [0.3, 0.6], itemStyle: { borderColor: "#fff", borderWidth: 1, gapWidth: 1 } },
        ],
        data: tree as never,
      },
    ],
  };
}

/** 可下钻矩形树（treemap-drilldown）：leafDepth=1 逐层下钻，适合层级多时 */
export function buildTreemapDrilldown(data: ChartData, _title?: string): EChartsOption {
  const s0 = data.series?.[0];
  const tree = (s0?.data || []) as Record<string, unknown>[];
  return {
    color: CHART_COLORS,
    tooltip: {
      trigger: "item",
      formatter: (p: { name: string; value?: number }) => `${p.name}: ${p.value ?? "-"}`,
    } as never,
    series: [
      {
        type: "treemap",
        roam: true,
        nodeClick: "zoomToNode",
        leafDepth: 1,
        breadcrumb: { show: true, height: 20 },
        label: { show: true, fontSize: 10, overflow: "truncate" },
        upperLabel: { show: true, height: 18, fontSize: 10 },
        itemStyle: { borderColor: "#fff", borderWidth: 1, gapWidth: 1 },
        data: tree as never,
      },
    ],
  };
}
