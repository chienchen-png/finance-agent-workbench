/** tornado 龙卷风图模板（敏感性排序） */
import type { EChartsOption } from "echarts";
import type { ChartData } from "./index";
import { valueAxisLabel, zoomXOnly } from "./axis";

export function buildTornado(data: ChartData, _title?: string): EChartsOption {
  const cats = data.categories || [];
  const series = (data.series || []).map((s, i) => ({
    name: s.name,
    type: "bar" as const,
    data: s.data as never,
    itemStyle: { color: i === 0 ? "#ef4444" : "#2563eb" },
    barMaxWidth: 20,
  }));
  return {
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    legend: { bottom: 0 },
    grid: { left: 80, right: 40, top: 20, bottom: 50 },
    xAxis: { type: "value", name: "对结果的影响", axisLabel: valueAxisLabel },
    yAxis: { type: "category", data: cats, axisLabel: { fontSize: 11 } },
    dataZoom: zoomXOnly(),
    series,
  };
}
