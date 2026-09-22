/** scatter 散点图模板（P5-② 三变体）
 *  - scatter-simple      基础散点（+可选回归线系列）
 *  - scatter-effect      涟漪特效散点（重点标注大值/异常）
 *  - scatter-regression  线性回归可视化（scatter + trend line）
 */
import type { EChartsOption } from "echarts";
import type { ChartData } from "./index";
import { CHART_COLORS } from "./index";
import { valueAxisLabel, zoom2D } from "./axis";

export function buildScatter(data: ChartData, _title?: string): EChartsOption {
  const series = (data.series || []).map((s, i) => {
    const isLine = s.type === "line" || i > 0;
    return {
      name: s.name,
      type: isLine ? ("line" as const) : ("scatter" as const),
      data: s.data as never,
      ...(isLine
        ? { lineStyle: { type: "dashed" as const, width: 1.5 }, symbol: "none" }
        : { symbolSize: 7 }),
    };
  });
  return {
    color: CHART_COLORS,
    tooltip: { trigger: "item" },
    legend: series.length > 1 ? { bottom: 0 } : undefined,
    grid: { left: 56, right: 24, top: 20, bottom: 30 },
    xAxis: { type: "value", name: data.xAxisName as string | undefined, axisLabel: valueAxisLabel },
    yAxis: { type: "value", name: data.yAxisName as string | undefined, axisLabel: valueAxisLabel },
    dataZoom: zoom2D(),
    series,
  };
}

/** 涟漪特效散点（scatter-effect）：重点点放大涟漪（data.effectIndices 或值最大的 3 点） */
export function buildScatterEffect(data: ChartData, _title?: string): EChartsOption {
  const series = (data.series || []).map((s, i) => {
    const pts = (s.data || []) as [number, number][];
    // 按 y 值取 Top-3 作为涟漪点
    const effectIdx = (data as Record<string, unknown>).effectIndices as number[] | undefined;
    const sorted = pts
      .map((p, idx) => ({ idx, y: typeof p?.[1] === "number" ? p[1] : 0 }))
      .sort((a, b) => b.y - a.y)
      .slice(0, 3)
      .map((x) => x.idx);
    const idxSet = new Set(effectIdx ?? sorted);
    const isLine = s.type === "line" || i > 0;
    return {
      name: s.name,
      type: (isLine ? "line" : "scatter") as "line" | "scatter",
      data: s.data as never,
      ...(isLine
        ? { lineStyle: { type: "dashed" as const, width: 1.5 }, symbol: "none" }
        : {
            symbolSize: (v: unknown[]) => (idxSet.has(Number(v[2])) ? 22 : 9),
            itemStyle: {
              color: (p: { dataIndex: number }) =>
                idxSet.has(p.dataIndex) ? "#f97316" : CHART_COLORS[0],
              shadowBlur: (p: { dataIndex: number }) => (idxSet.has(p.dataIndex) ? 14 : 0),
              shadowColor: "#f97316",
            },
          }),
    } as never;
  });
  return {
    color: CHART_COLORS,
    tooltip: { trigger: "item" },
    legend: series.length > 1 ? { bottom: 0 } : undefined,
    grid: { left: 56, right: 60, top: 20, bottom: 50 },
    xAxis: { type: "value", name: data.xAxisName as string | undefined, axisLabel: valueAxisLabel },
    yAxis: { type: "value", name: data.yAxisName as string | undefined, axisLabel: valueAxisLabel },
    dataZoom: zoom2D(),
    series: series as never,
  };
}

/** 回归可视化（scatter-regression）：scatter + 趋势 line（series[1] 为回归线数据） */
export function buildScatterRegression(data: ChartData, _title?: string): EChartsOption {
  const series = (data.series || []).map((s, i) => {
    const isLine = i > 0 || s.type === "line";
    return {
      name: s.name,
      type: isLine ? ("line" as const) : ("scatter" as const),
      data: s.data as never,
      ...(isLine
        ? {
            lineStyle: { color: "#dc2626", width: 2 },
            symbol: "none",
            smooth: true,
            markLine: {
              symbol: "none",
              lineStyle: { type: "dashed" as const, color: "#f59e0b" },
            },
          }
        : { symbolSize: 7 }),
    };
  });
  return {
    color: CHART_COLORS,
    tooltip: { trigger: "item" },
    legend: series.length > 1 ? { bottom: 0 } : undefined,
    grid: { left: 56, right: 60, top: 20, bottom: 50 },
    xAxis: { type: "value", name: data.xAxisName as string | undefined, axisLabel: valueAxisLabel },
    yAxis: { type: "value", name: data.yAxisName as string | undefined, axisLabel: valueAxisLabel },
    dataZoom: zoom2D(),
    series,
  };
}

