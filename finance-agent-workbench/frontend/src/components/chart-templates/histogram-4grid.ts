/** histogram-4grid 联动直方图模板（P6-②）
 *  - histogram-4grid  4 宫格：散点 + 按 x 分箱直方图 + 按 y 分箱直方图
 * 数据结构：
 *   series[0].data = [[x, y], ...]  原始双变量数据
 *   data.xAxisName / data.yAxisName  轴名（可选）
 *   data.bins 可选：{x: number, y: number} 分箱数（默认 sturges 公式）
 * 注：echarts-stat npm 版有 bug（AMD + 二维 histogram），用自研 sturges 分箱等价实现。
 */
import type { EChartsOption } from "echarts";
import type { ChartData } from "./index";
import { valueAxisLabel } from "./axis";

interface Bin { x0: number; x1: number; count: number; label: string }

/** sturges 分箱：bin 数 = ceil(log2(n)) + 1 */
function histBins(values: number[], binCount: number): Bin[] {
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const step = range / binCount;
  const bins: Bin[] = [];
  for (let i = 0; i < binCount; i++) {
    const x0 = min + i * step;
    const x1 = i === binCount - 1 ? max + 0.0001 : min + (i + 1) * step;
    bins.push({
      x0,
      x1,
      count: 0,
      label: `${x0.toFixed(1)}~${i === binCount - 1 ? max.toFixed(1) : (min + (i + 1) * step).toFixed(1)}`,
    });
  }
  values.forEach((v) => {
    for (const b of bins) {
      if (v >= b.x0 && v < b.x1) { b.count++; break; }
    }
  });
  return bins;
}

export function buildHistogram4Grid(data: ChartData, _title?: string): EChartsOption {
  const s0 = data.series?.[0];
  const raw = (s0?.data || []) as [number, number][];
  const xName = (data.xAxisName as string) || "X";
  const yName = (data.yAxisName as string) || "Y";

  const xs = raw.map((d) => d[0]);
  const ys = raw.map((d) => d[1]);
  const binOpt = (data.bins as { x?: number; y?: number }) || {};
  // 官网 31 点 → 手动分箱更美观（官网 ~7 箱）；用 sqrt 规则避免过细
  const xBinN = binOpt.x ?? Math.max(5, Math.round(Math.sqrt(xs.length)));
  const yBinN = binOpt.y ?? Math.max(5, Math.round(Math.sqrt(ys.length)));
  const xBins = histBins(xs, xBinN);
  const yBins = histBins(ys, yBinN);

  // 官网风格配色：散点用主题蓝、上下直方图用蓝渐变
  const scatterColor = "#5470c6";
  const barColor = "#5470c6";

  return {
    tooltip: {
      trigger: "item",
      formatter: ((p: { seriesName?: string; data?: unknown }) => {
        if (p.seriesName?.includes("分箱")) return `${p.seriesName}：${p.data}`;
        const d = p.data as number[];
        return `${xName}: ${d[0]}<br>${yName}: ${d[1]}`;
      }) as never,
    },
    grid: [
      { top: "52%", right: "50%" },
      { bottom: "54%", right: "50%" },
      { top: "52%", left: "52%" },
    ],
    xAxis: [
      { type: "value", scale: true, gridIndex: 0, name: xName, axisLabel: valueAxisLabel, axisLine: { lineStyle: { color: "#cbd5e1" } } },
      {
        type: "category",
        data: xBins.map((b) => b.label),
        axisTick: { show: false },
        axisLabel: { show: false },
        axisLine: { show: false },
        gridIndex: 1,
      },
      { type: "value", scale: true, gridIndex: 2, axisLabel: valueAxisLabel, axisLine: { lineStyle: { color: "#cbd5e1" } } },
    ],
    yAxis: [
      { type: "value", scale: true, gridIndex: 0, name: yName, axisLabel: valueAxisLabel, axisLine: { lineStyle: { color: "#cbd5e1" } } },
      { type: "value", gridIndex: 1, axisLabel: valueAxisLabel, splitLine: { show: false } },
      {
        type: "category",
        data: yBins.map((b) => b.label),
        axisTick: { show: false },
        axisLabel: { show: false },
        axisLine: { show: false },
        gridIndex: 2,
      },
    ],
    series: [
      {
        name: "原始散点",
        type: "scatter",
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: raw as never,
        itemStyle: { color: scatterColor, opacity: 0.7 },
        symbolSize: 7,
      },
      {
        name: `${xName} 分箱`,
        type: "bar",
        xAxisIndex: 1,
        yAxisIndex: 1,
        barWidth: "99.3%",
        data: xBins.map((b) => b.count) as never,
        label: { show: true, position: "top", fontSize: 9, color: "#334155" },
        itemStyle: { color: barColor, opacity: 0.85, borderRadius: [1, 1, 0, 0] },
      },
      {
        name: `${yName} 分箱`,
        type: "bar",
        xAxisIndex: 2,
        yAxisIndex: 2,
        barWidth: "99.3%",
        data: yBins.map((b) => b.count) as never,
        label: { show: true, position: "right", fontSize: 9, color: "#334155" },
        itemStyle: { color: barColor, opacity: 0.85, borderRadius: [0, 1, 1, 0] },
      },
    ],
  };
}
