/** sunburst 旭日图模板（多层占比，树形嵌套） */
import type { EChartsOption } from "echarts";
import type { ChartData } from "./index";
import { CHART_COLORS } from "./index";

export function buildSunburst(data: ChartData, _title?: string): EChartsOption {
  const s0 = data.series?.[0];
  const tree = (s0?.data || []) as Record<string, unknown>[];
  return {
    color: CHART_COLORS,
    tooltip: { trigger: "item", formatter: "{b}: {c}" },
    series: [
      {
        type: "sunburst",
        radius: ["12%", "88%"],
        center: ["50%", "52%"],
        data: tree as never,
        label: { fontSize: 10 },
        emphasis: { focus: "ancestor" },
      },
    ],
  };
}
