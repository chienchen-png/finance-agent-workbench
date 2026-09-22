/** histogram 直方图模板（分箱频数） */
import type { EChartsOption } from "echarts";
import type { ChartData } from "./index";
import { CHART_COLORS } from "./index";
import { valueAxisLabel, zoom2D } from "./axis";

export function buildHistogram(data: ChartData, _title?: string): EChartsOption {
  const cats = data.categories || [];
  const s0 = data.series?.[0];
  const vals = (s0?.data || []) as number[];
  return {
    color: CHART_COLORS,
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    grid: { left: 48, right: 60, top: 20, bottom: 50 },
    xAxis: { type: "category", data: cats, axisLabel: { rotate: cats.length > 8 ? 30 : 0 } },
    yAxis: { type: "value", name: "频数", axisLabel: valueAxisLabel },
    dataZoom: zoom2D(),
    series: [{ name: s0?.name || "频数", type: "bar", data: vals as never, barMaxWidth: 48, itemStyle: { color: "#2563eb" } }],
  };
}
