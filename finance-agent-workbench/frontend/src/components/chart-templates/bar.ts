/** bar 柱状图模板（2026-08-23 按用户附件「图库优化.txt」重构为 5 变体）
 *
 *  - bar           分组柱状图（默认，多系列并排；附件【第一种】）
 *  - bar-simple    简单柱状图（单系列基础柱；附件：简单柱状图）
 *  - bar-line      折线柱状图（柱 + 折线双 y 轴；附件【第二种】）
 *  - bar-negative  正负条形图（盈亏红绿，横向；附件【第三种】）
 *  - bar-fancy     分组折线柱状图（trend 折线串各柱顶 + 多年柱；附件【第四种】）
 *
 * 已删除（用户未提供）：bar-rounded / bar-horizontal / bar-threshold / bar-stacked
 */
import type { EChartsOption } from "echarts";
import type { ChartData } from "./index";
import { CHART_COLORS } from "./index";
import { valueAxisLabel, zoom2D, zoomXOnly } from "./axis";

/** 柱体垂直线性渐变（官方风格：底部半透明 → 顶部主色饱和） */
function barGradient(color: string): Record<string, unknown> {
  return {
    color: {
      type: "linear" as const,
      x: 0, y: 0, x2: 0, y2: 1,
      colorStops: [
        { offset: 0, color },
        { offset: 1, color: color + "55" },
      ],
    },
  };
}

/** 简单柱状图（bar-simple / 默认单系列）：横轴类别 + 单系列柱 */
export function buildBar(data: ChartData, _title?: string): EChartsOption {
  const cats = data.categories || [];
  const series = (data.series || []).map((s, si) => ({
    name: s.name || `系列${si + 1}`,
    type: "bar" as const,
    barMaxWidth: 30,
    data: s.data as never,
    itemStyle: { borderRadius: [5, 5, 0, 0], ...barGradient(CHART_COLORS[si % CHART_COLORS.length]) },
    label: { show: true, position: "top" as const, fontSize: 10, color: "#52525b" },
    ...(cats.length > 12 ? { label: { show: false } } : {}),
  }));
  return {
    color: CHART_COLORS,
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    legend: series.length > 1 ? { bottom: 0 } : undefined,
    grid: { left: 48, right: 60, top: 20, bottom: series.length > 1 ? 56 : 50 },
    xAxis: { type: "category", data: cats, axisLabel: { rotate: cats.length > 8 ? 30 : 0 } },
    yAxis: { type: "value", axisLabel: valueAxisLabel },
    dataZoom: zoom2D(),
    series,
  };
}

/** 分组柱状图（bar-group）：多系列并排对比（每一列 = 一序列） */
export function buildBarGroup(data: ChartData, _title?: string): EChartsOption {
  const cats = data.categories || [];
  const series = (data.series || []).map((s, si) => ({
    name: s.name || `系列${si + 1}`,
    type: "bar" as const,
    barMaxWidth: 24,
    barGap: "10%",
    data: s.data as never,
    itemStyle: { ...barGradient(CHART_COLORS[si % CHART_COLORS.length]) },
    label: { show: true, position: "top" as const, fontSize: 10, color: "#52525b" },
    ...(cats.length > 12 ? { label: { show: false } } : {}),
  }));
  return {
    color: CHART_COLORS,
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    legend: { bottom: 0, type: "scroll" },
    grid: { left: 48, right: 60, top: 20, bottom: 56 },
    xAxis: { type: "category", data: cats, axisLabel: { rotate: cats.length > 8 ? 30 : 0 } },
    yAxis: { type: "value", axisLabel: valueAxisLabel },
    dataZoom: zoom2D(),
    series,
  };
}

/** 折线柱状图（bar-line）：柱（左 y 轴，量）+ 折线（右 y 轴，率/趋势），双 y 轴 */
export function buildBarLine(data: ChartData, _title?: string): EChartsOption {
  const cats = data.categories || [];
  const barSeries = (data.series || []).filter((s) => (s.type as string) !== "line");
  const lineSeries = (data.series || []).filter((s) => (s.type as string) === "line");
  const y0Name = (data.yAxis0Name as string) || "量";
  const y1Name = (data.yAxis1Name as string) || "率";
  const series: object[] = [];
  barSeries.forEach((s, si) => {
    series.push({
      name: s.name || `柱${si + 1}`,
      type: "bar",
      barMaxWidth: 26,
      data: s.data as never,
      itemStyle: { ...barGradient(CHART_COLORS[si % CHART_COLORS.length]) },
      tooltip: { valueFormatter: (v: number) => `${v} ${y0Name}` },
    });
  });
  lineSeries.forEach((s, si) => {
    series.push({
      name: s.name || `线${si + 1}`,
      type: "line",
      yAxisIndex: 1,
      smooth: true,
      symbolSize: 6,
      data: s.data as never,
      lineStyle: { width: 2.5 },
      itemStyle: { color: "#dc2626" },
      tooltip: { valueFormatter: (v: number) => `${v} ${y1Name}` },
    });
  });
  return {
    color: CHART_COLORS,
    tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
    legend: { bottom: 0, type: "scroll" },
    toolbox: {
      feature: { dataZoom: { yAxisIndex: "none" }, restore: {}, saveAsImage: {} },
    },
    grid: { left: 52, right: 60, top: 30, bottom: 56 },
    xAxis: { type: "category", data: cats, axisPointer: { type: "shadow" } },
    yAxis: [
      { type: "value", name: y0Name, axisLabel: valueAxisLabel },
      { type: "value", name: y1Name, axisLabel: valueAxisLabel },
    ],
    dataZoom: zoomXOnly(),
    series,
  };
}

/** 正负条形图（bar-negative）：横向 y 类别，正绿负红，堆叠显示 profit/income/expenses */
export function buildBarNegative(data: ChartData, _title?: string): EChartsOption {
  const cats = data.categories || [];
  const isExpense = (n: string) => /expense|费用|成本/i.test(n);
  const series = (data.series || []).map((s) => ({
    name: s.name || `系列`,
    type: "bar" as const,
    stack: isExpense(s.name || "") ? "Total" : undefined,
    data: s.data as never,
    label: { show: true, fontSize: 9, color: "#52525b" },
    itemStyle: {
      color: (p: { value?: unknown }) => (Number(p.value ?? 0) >= 0 ? "#059669" : "#dc2626"),
    },
    barMaxWidth: 20,
  }));
  return {
    color: CHART_COLORS,
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    legend: { top: 0, type: "scroll" },
    grid: { left: 100, right: 48, top: 24, bottom: 40 },
    xAxis: { type: "value", axisLabel: valueAxisLabel },
    yAxis: { type: "category", data: cats, inverse: true, axisLabel: { width: 90, overflow: "truncate" } },
    dataZoom: zoomXOnly(),
    series: series as never,
  };
}

/** 分组折线柱状图（bar-fancy）：多年分组柱 + trend 折线（custom polyline 串各柱顶），附件【第四种】 */
export function buildBarFancy(data: ChartData, _title?: string): EChartsOption {
  const cats = data.categories || [];
  const trendSeries = (data.series || []).find((s) => (s.type as string) === "custom");
  const groupSeries = (data.series || []).filter((s) => (s.type as string) !== "custom");
  const legendData: string[] = [];
  if (trendSeries) legendData.push(trendSeries.name || "trend");
  const yearCount = Math.max(groupSeries.length, 1);
  const encodeY: number[] = [];
  for (let i = 0; i < yearCount; i++) {
    legendData.push(String(i + 1));
    encodeY.push(1 + i);
  }
  const bars = groupSeries.map((s, index) => ({
    type: "bar" as const,
    animation: false,
    name: s.name || legendData[index + 1] || `系列${index + 1}`,
    barMaxWidth: 16,
    itemStyle: { opacity: 0.55, color: CHART_COLORS[index % CHART_COLORS.length] },
    data: s.data as never,
  }));
  const series: object[] = trendSeries
    ? [{
        type: "custom",
        name: trendSeries.name || "trend",
        renderItem: (
          params: { seriesIndex: number },
          api: {
            value: (i: number) => number;
            currentSeriesIndices: () => number[];
            barLayout: (o: object) => { offsetCenter: number }[];
            coord: (v: number[]) => number[];
            style: (o: object) => object;
            visual: (k: string) => string;
          },
        ) => {
          const xValue = api.value(0);
          const curIdx = api.currentSeriesIndices();
          const barLayout = api.barLayout({ barGap: "30%", barCategoryGap: "20%", count: curIdx.length - 1 });
          const points: number[][] = [];
          for (let i = 0; i < curIdx.length; i++) {
            const si = curIdx[i];
            if (si !== params.seriesIndex) {
              const point = api.coord([xValue, api.value(si)]);
              point[0] += barLayout[i - 1]?.offsetCenter ?? 0;
              point[1] -= 20;
              points.push(point);
            }
          }
          const style = api.style({ stroke: api.visual("color"), fill: "none" });
          return { type: "polyline", shape: { points }, style };
        },
        itemStyle: { borderWidth: 2 },
        encode: { x: 0, y: encodeY },
        data: (trendSeries.data || []).map((r) => {
          const arr = r as unknown as number[];
          return [arr[0], ...arr.slice(1)].map((v) => v);
        }),
        z: 100,
      }]
    : [];
  return {
    tooltip: { trigger: "axis" },
    legend: { data: legendData, top: 20, type: "scroll" },
    dataZoom: [
      { type: "slider", start: 50, end: 70 },
      { type: "inside", start: 50, end: 70 },
    ],
    xAxis: { type: "category", data: cats },
    yAxis: { type: "value", axisLabel: valueAxisLabel },
    grid: { left: 48, right: 60, top: 56, bottom: 56 },
    series: [...series, ...bars],
  };
}


