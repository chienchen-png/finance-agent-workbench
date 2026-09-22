/** boxplot 箱线图模板（P5-② 两变体）
 *  - boxplot-simple  单系列分布（默认）
 *  - boxplot-multi   多系列分组对比（每组一个箱）
 */
import type { EChartsOption } from "echarts";
import type { ChartData } from "./index";
import { CHART_COLORS } from "./index";
import { valueAxisLabel, zoom2D } from "./axis";

export function buildBoxplot(data: ChartData, _title?: string): EChartsOption {
  const cats = data.categories || [];
  const s0 = data.series?.[0];
  const boxData = (s0?.data || []) as number[][];
  return {
    color: CHART_COLORS,
    tooltip: { trigger: "item" },
    grid: { left: 48, right: 60, top: 20, bottom: 50 },
    xAxis: { type: "category", data: cats },
    yAxis: { type: "value", axisLabel: valueAxisLabel },
    dataZoom: zoom2D(),
    series: [
      {
        name: s0?.name || "分布",
        type: "boxplot",
        data: boxData as never,
        itemStyle: { color: "#2563eb", borderColor: "#1e40af" },
      },
    ],
  };
}

/** 多系列箱线（boxplot-multi）：每系列一个 boxplot，类别为系列名 */
export function buildBoxplotMulti(data: ChartData, _title?: string): EChartsOption {
  const series = (data.series || []).map((s, i) => ({
    name: s.name || `系列${i + 1}`,
    type: "boxplot" as const,
    data: (s.data || []) as never,
    itemStyle: { color: CHART_COLORS[i % CHART_COLORS.length], borderColor: CHART_COLORS[i % CHART_COLORS.length] },
  }));
  return {
    color: CHART_COLORS,
    tooltip: { trigger: "item" },
    legend: series.length > 1 ? { bottom: 0 } : undefined,
    grid: { left: 48, right: 60, top: 20, bottom: series.length > 1 ? 56 : 50 },
    xAxis: { type: "category", data: series.map((s) => s.name) },
    yAxis: { type: "value", axisLabel: valueAxisLabel },
    dataZoom: zoom2D(),
    series,
  };
}
