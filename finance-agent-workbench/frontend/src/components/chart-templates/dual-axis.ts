/** dual-axis 双轴组合图模板（实际 vs 预算 / 量价） */
import type { EChartsOption } from "echarts";
import type { ChartData } from "./index";
import { CHART_COLORS } from "./index";
import { valueAxisLabel, zoomXOnly } from "./axis";

export function buildDualAxis(data: ChartData, _title?: string): EChartsOption {
  const cats = data.categories || [];
  const series = (data.series || []).map((s) => {
    const yi = (s.yAxisIndex as number) || 0;
    return {
      name: s.name,
      type: ((s.type as "bar" | "line") || (yi === 0 ? "bar" : "line")) as "bar" | "line",
      yAxisIndex: yi,
      data: s.data as never,
      ...(yi === 1 ? { smooth: true } : { barMaxWidth: 30 }),
    };
  });
  const y0Name = (data.yAxis0Name as string) || "左轴";
  const y1Name = (data.yAxis1Name as string) || "右轴";
  return {
    color: CHART_COLORS,
    tooltip: { trigger: "axis" },
    legend: { bottom: 0, type: "scroll" },
    grid: { left: 52, right: 60, top: 20, bottom: 50 },
    xAxis: { type: "category", data: cats },
    yAxis: [
      { type: "value", name: y0Name, position: "left", axisLabel: valueAxisLabel },
      { type: "value", name: y1Name, position: "right", axisLabel: valueAxisLabel },
    ],
    // 双轴图：右轴已有第二套刻度，纵向用 inside 平移（不占可见滑块，避免与右轴标签重叠）
    dataZoom: zoomXOnly(),
    series,
  };
}
