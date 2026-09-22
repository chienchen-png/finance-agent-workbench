/** waterfall 瀑布图模板（P5-② 两变体）
 *  - waterfall-simple  桥接瀑布（期初→调整→期末，默认）
 *  - waterfall-bar     柱状增量瀑布（更紧凑，适合更多项）
 */
import type { EChartsOption } from "echarts";
import type { ChartData } from "./index";
import { CHART_COLORS } from "./index";
import { valueAxisLabel, zoom2D } from "./axis";

export function buildWaterfall(data: ChartData, _title?: string): EChartsOption {
  const s0 = data.series?.[0];
  const raw = (s0?.data || []) as (number | { value: number; name?: string })[];
  const names = data.categories || raw.map((r, i) => (typeof r === "object" ? (r as { name?: string }).name || `项${i + 1}` : `项${i + 1}`));
  const vals = raw.map((r) => (typeof r === "object" ? (r as { value: number }).value : (r as number)));

  // 瀑布：首尾灰、中间增减；堆叠 + 透明占位
  const placeholders: number[] = [];
  const bars: number[] = [];
  let acc = 0;
  vals.forEach((v, i) => {
    if (i === 0) {
      placeholders.push(0);
      bars.push(v);
      acc = v;
    } else if (i === vals.length - 1) {
      placeholders.push(0);
      bars.push(v);
    } else {
      if (v >= 0) {
        placeholders.push(acc);
        bars.push(v);
      } else {
        placeholders.push(acc + v);
        bars.push(v);
      }
      acc += v;
    }
  });

  const isTotal = (_: unknown, i: number) => i === 0 || i === vals.length - 1;
  return {
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    legend: { bottom: 0 },
    grid: { left: 48, right: 60, top: 20, bottom: 50 },
    xAxis: { type: "category", data: names },
    yAxis: { type: "value", axisLabel: valueAxisLabel },
    dataZoom: zoom2D(),
    series: [
      {
        name: "占位",
        type: "bar",
        stack: "wf",
        data: placeholders as never,
        itemStyle: { color: "rgba(0,0,0,0)" },
        tooltip: { show: false },
      },
      {
        name: "金额",
        type: "bar",
        stack: "wf",
        data: bars as never,
        label: { show: true, position: "top", fontSize: 10 },
        itemStyle: {
          color: (p: { dataIndex: number }) =>
            isTotal(p, p.dataIndex) ? "#94a3b8" : (bars[p.dataIndex] ?? 0) >= 0 ? CHART_COLORS[1] : CHART_COLORS[3],
        },
      },
    ],
  };
}

/** 柱状增量瀑布（waterfall-bar）：更紧凑，适合大量增减项（D3 预算差异） */
export function buildWaterfallBar(data: ChartData, _title?: string): EChartsOption {
  const s0 = data.series?.[0];
  const raw = (s0?.data || []) as (number | { value: number; name?: string })[];
  const names = data.categories || raw.map((r, i) => (typeof r === "object" ? (r as { name?: string }).name || `项${i + 1}` : `项${i + 1}`));
  const vals = raw.map((r) => (typeof r === "object" ? (r as { value: number }).value : (r as number)));

  const placeholders: number[] = [];
  const bars: number[] = [];
  let acc = 0;
  vals.forEach((v, i) => {
    if (i === 0) {
      placeholders.push(0);
      bars.push(v);
      acc = v;
    } else if (i === vals.length - 1) {
      placeholders.push(0);
      bars.push(v);
    } else {
      if (v >= 0) {
        placeholders.push(acc);
        bars.push(v);
      } else {
        placeholders.push(acc + v);
        bars.push(v);
      }
      acc += v;
    }
  });

  const isTotal = (_: unknown, i: number) => i === 0 || i === vals.length - 1;
  return {
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    grid: { left: 48, right: 60, top: 20, bottom: 50 },
    xAxis: {
      type: "category",
      data: names,
      axisLabel: { rotate: names.length > 8 ? 30 : 0 },
    },
    yAxis: { type: "value", axisLabel: valueAxisLabel },
    dataZoom: zoom2D(),
    series: [
      {
        name: "占位",
        type: "bar",
        stack: "wf2",
        data: placeholders as never,
        itemStyle: { color: "rgba(0,0,0,0)" },
        tooltip: { show: false },
      },
      {
        name: "金额",
        type: "bar",
        stack: "wf2",
        barMaxWidth: 26,
        data: bars as never,
        label: { show: true, position: "top", fontSize: 9 },
        itemStyle: {
          borderRadius: [3, 3, 0, 0],
          color: (p: { dataIndex: number }) =>
            isTotal(p, p.dataIndex) ? "#94a3b8" : (bars[p.dataIndex] ?? 0) >= 0 ? "#059669" : "#dc2626",
        },
      },
    ],
  };
}
