/** radar 雷达图模板（P5-② 两变体）
 *  - radar-simple   基础雷达（默认）
 *  - radar-multi    多系列对比（杜邦/同业，突出面积分层）
 */
import type { EChartsOption } from "echarts";
import type { ChartData } from "./index";
import { CHART_COLORS } from "./index";

export function buildRadar(data: ChartData, _title?: string): EChartsOption {
  const inds = data.indicators || (data.categories || []).map((c) => ({ name: c, max: 100 }));
  const series = (data.series || []).map((s, si) => ({
    name: s.name,
    type: "radar" as const,
    data: [{ value: s.data as never }],
    // v6.8：官方观感——区域渐变（主色→透明）+ 圆点
    symbol: "circle",
    symbolSize: 4,
    lineStyle: { width: 2 },
    areaStyle: {
      color: {
        type: "radial" as const,
        x: 0.5, y: 0.5, r: 0.8,
        colorStops: [
          { offset: 0, color: CHART_COLORS[si % CHART_COLORS.length] + "66" },
          { offset: 1, color: CHART_COLORS[si % CHART_COLORS.length] + "11" },
        ],
      },
    },
  }));
  return {
    color: CHART_COLORS,
    tooltip: { trigger: "item" },
    legend: series.length > 1 ? { bottom: 0 } : undefined,
    radar: {
      indicator: inds,
      radius: "62%",
      splitNumber: 4,
      axisName: { fontSize: 10, color: "#52525b" },
      splitArea: { areaStyle: { color: ["rgba(37,99,235,0.02)", "rgba(37,99,235,0.05)"] } },
      splitLine: { lineStyle: { color: "#e4e4e7" } },
      axisLine: { lineStyle: { color: "#d4d4d8" } },
    },
    series,
  };
}

/** 多系列雷达（radar-multi）：杜邦/同业对比，强调面积分层 */
export function buildRadarMulti(data: ChartData, _title?: string): EChartsOption {
  const inds = data.indicators || (data.categories || []).map((c) => ({ name: c, max: 100 }));
  const series = (data.series || []).map((s) => ({
    name: s.name,
    type: "radar" as const,
    data: [{ value: s.data as never }],
    symbolSize: 3,
    areaStyle: { opacity: 0.22 },
    lineStyle: { width: 2 },
  }));
  return {
    color: CHART_COLORS,
    tooltip: { trigger: "item" },
    legend: { bottom: 0, type: "scroll" },
    radar: {
      indicator: inds,
      radius: "62%",
      splitNumber: 4,
      axisName: { fontSize: 10 },
      splitArea: { areaStyle: { color: ["rgba(37,99,235,0.02)", "rgba(37,99,235,0.05)"] } },
    },
    series,
  };
}

