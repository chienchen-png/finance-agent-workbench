/** line 折线图模板（2026-08-23 按用户附件「图库优化.txt」重构为 3 变体）
 *
 *  - line           多维折线图·分组对比（默认，多系列折线 + markPoint/max/min + markLine 平均线；附件【第一种】）
 *  - line-simple    简单折线图（单系列基础折线；附件：简单折线图）
 *  - line-multi-x   多x轴折线图（双 x 轴，两时段同图对比；附件【第二种】）
 *
 * 已删除（用户未提供）：line-area / line-area-stack / line-step / line-forecast
 */
import type { EChartsOption } from "echarts";
import type { ChartData } from "./index";
import { CHART_COLORS } from "./index";
import { valueAxisLabel, zoom2D } from "./axis";

/** 简单折线图（line-simple / 默认单系列）：横轴类别 + 单系列折线 */
export function buildLine(data: ChartData, _title?: string): EChartsOption {
  const cats = data.categories || [];
  const series = (data.series || []).map((s, si) => ({
    name: s.name || `系列${si + 1}`,
    type: "line" as const,
    smooth: true,
    symbolSize: 5,
    lineStyle: { width: 2 },
    data: s.data as never,
    label: { show: true, position: "top" as const, fontSize: 10, color: "#52525b" },
    ...(cats.length > 12 ? { label: { show: false } } : {}),
  }));
  return {
    color: CHART_COLORS,
    tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
    legend: series.length > 1 ? { bottom: 0, type: "scroll" } : undefined,
    grid: { left: 48, right: 60, top: 20, bottom: series.length > 1 ? 56 : 50 },
    xAxis: { type: "category", data: cats, boundaryGap: false },
    yAxis: { type: "value", axisLabel: valueAxisLabel },
    dataZoom: zoom2D(),
    series,
  };
}

/** 多维折线图·分组对比（line，默认）：多系列折线 + markPoint(极值) + markLine(平均线) + toolbox */
export function buildLineGroup(data: ChartData, _title?: string): EChartsOption {
  const cats = data.categories || [];
  const series = (data.series || []).map((s, si) => ({
    name: s.name || `系列${si + 1}`,
    type: "line" as const,
    smooth: true,
    symbolSize: 5,
    lineStyle: { width: 2 },
    data: s.data as never,
    // 官方多维折线：markPoint 极值 + markLine 平均线
    markPoint: {
      data: [
        { type: "max" as const, name: "最大" },
        { type: "min" as const, name: "最小" },
      ],
    },
    markLine: {
      data: [{ type: "average" as const, name: "平均" }],
    },
  }));
  return {
    color: CHART_COLORS,
    tooltip: { trigger: "axis" },
    legend: { bottom: 0, type: "scroll" },
    toolbox: {
      feature: { dataZoom: { yAxisIndex: "none" }, restore: {}, saveAsImage: {} },
    },
    grid: { left: 48, right: 60, top: 30, bottom: series.length > 1 ? 56 : 50 },
    xAxis: { type: "category", data: cats, boundaryGap: false },
    yAxis: { type: "value", axisLabel: valueAxisLabel },
    dataZoom: zoom2D(),
    series: series as never,
  };
}

/** 多维折线图·多x轴（line-multi-x）：双 x 轴（两时段 contrast），series 用 xAxisIndex 绑定 */
export function buildLineMultiX(data: ChartData, _title?: string): EChartsOption {
  const x0 = data.xCategories || data.categories || [];
  // 第二 x 轴数据集（xCategories2 / series[Si].xAxisIndex=1）
  const x1 = (data.xCategories2 as string[]) || data.yCategories || [];
  const colors = ["#5470C6", "#EE6666"];
  const series = (data.series || []).map((s, si) => {
    const xi = (s.xAxisIndex as number) || (si >= x0.length ? 1 : 0);
    return {
      name: s.name || `系列${si + 1}`,
      type: "line" as const,
      xAxisIndex: xi,
      smooth: true,
      symbolSize: 5,
      lineStyle: { width: 2, color: colors[xi % 2] },
      itemStyle: { color: colors[xi % 2] },
      data: s.data as never,
    };
  });
  const xAxes: object[] = [];
  if (x0.length) {
    xAxes.push({
      type: "category",
      axisTick: { alignWithLabel: true },
      axisLine: { onZero: false, lineStyle: { color: colors[1] } },
      data: x0,
    });
  }
  if (x1.length) {
    xAxes.push({
      type: "category",
      axisTick: { alignWithLabel: true },
      axisLine: { onZero: false, lineStyle: { color: colors[0] } },
      data: x1,
    });
  }
  return {
    color: colors,
    tooltip: { trigger: "none", axisPointer: { type: "cross" } },
    legend: { bottom: 0, type: "scroll" },
    grid: { left: 48, right: 60, top: 40, bottom: 56 },
    xAxis: xAxes.length ? xAxes : { type: "category", data: x0 },
    yAxis: { type: "value", axisLabel: valueAxisLabel },
    dataZoom: zoom2D(),
    series,
  };
}


