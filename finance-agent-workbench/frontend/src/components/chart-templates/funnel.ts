/** funnel 漏斗图模板（P5-② 两变体）
 *  - funnel-simple   阶段转化（默认）
 *  - funnel-compare  多系列对比漏斗（series 多组）
 */
import type { EChartsOption } from "echarts";
import type { ChartData } from "./index";
import { CHART_COLORS } from "./index";

export function buildFunnel(data: ChartData, _title?: string): EChartsOption {
  const cats = data.categories || [];
  const s0 = data.series?.[0];
  const vals = (s0?.data || []) as number[];
  const fdata = cats.map((c, i) => ({ name: c, value: typeof vals[i] === "number" ? vals[i] : 0 }));
  return {
    color: CHART_COLORS,
    tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
    series: [
      {
        type: "funnel",
        left: "12%",
        top: 20,
        width: "76%",
        sort: "descending" as const,
        gap: 2,
        label: { show: true, formatter: "{b}\n{c}" },
        itemStyle: { borderColor: "#fff", borderWidth: 1 },
        data: fdata as never,
      },
    ],
  };
}

/** 多系列漏斗（funnel-compare）：两个漏斗并列对比（实际 vs 目标/去年） */
export function buildFunnelCompare(data: ChartData, _title?: string): EChartsOption {
  const cats = data.categories || [];
  const series = (data.series || []).map((s, si) => ({
    name: s.name || `系列${si + 1}`,
    type: "funnel" as const,
    left: si === 0 ? "4%" : "54%",
    width: "40%",
    top: 20,
    sort: "descending" as const,
    gap: 2,
    label: { show: true, formatter: "{b}\n{c}" },
    itemStyle: { borderColor: "#fff", borderWidth: 1 },
    data: (s.data || []).map((v, i) => ({
      name: cats[i] || `项${i + 1}`,
      value: typeof v === "number" ? v : 0,
    })) as never,
  }));
  return {
    color: CHART_COLORS,
    tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
    legend: { bottom: 0 },
    series,
  };
}
