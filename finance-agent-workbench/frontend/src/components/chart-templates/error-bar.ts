/** error-bar 误差条/区间图模板（P5-③ 新增类型）
 *  - error-bar    误差条（点 + 上下误差）
 *  - error-range  区间带（上下界带状，预测置信区间）
 * 数据结构：
 *   categories: [期间]
 *   series[0].data = [base, low, high] 三元组 或 {value, low, high}
 *   （low/high 可为相对误差绝对值或绝对区间）
 */
import type { EChartsOption } from "echarts";
import type { ChartData } from "./index";
import { CHART_COLORS } from "./index";
import { valueAxisLabel, zoom2D } from "./axis";

interface Tri { value: number; low: number; high: number }

function triples(data: ChartData): Tri[] {
  const s0 = data.series?.[0];
  const raw = (s0?.data || []) as (number[] | Record<string, unknown>)[];
  return raw.map((r) => {
    if (Array.isArray(r)) {
      return { value: Number(r[0] ?? 0), low: Number(r[1] ?? 0), high: Number(r[2] ?? 0) };
    }
    const o = r as Record<string, unknown>;
    const v = Number(o.value ?? 0);
    const low = Number(o.low ?? o.lower ?? 0);
    const high = Number(o.high ?? o.upper ?? 0);
    return { value: v, low, high };
  });
}

/** 误差条（error-bar）：点 + 上下误差须（预测均值 ± 区间） */
export function buildErrorBar(data: ChartData, _title?: string): EChartsOption {
  const cats = data.categories || [];
  const tris = triples(data);
  const main = tris.map((t) => t.value);
  const upper = tris.map((t) => Math.abs(t.high - t.value));
  const lower = tris.map((t) => Math.abs(t.value - t.low));
  return {
    color: CHART_COLORS,
    tooltip: { trigger: "axis" },
    legend: { bottom: 0 },
    grid: { left: 56, right: 60, top: 24, bottom: 50 },
    xAxis: { type: "category", data: cats },
    yAxis: { type: "value", axisLabel: valueAxisLabel },
    dataZoom: zoom2D(),
    series: [
      {
        name: (data.series?.[0]?.name as string) || "均值",
        type: "bar",
        barMaxWidth: 30,
        data: main as never,
        itemStyle: { color: CHART_COLORS[0], borderRadius: [4, 4, 0, 0] },
        label: { show: true, position: "top", fontSize: 9 },
      },
      {
        name: "误差区间",
        type: "custom",
        renderItem: ((_: unknown, api: { value: (i: number) => number; coord: (v: unknown[]) => number[]; size: (v: unknown[], t: unknown) => number[] }) => {
          const i = Number(api.value(0));
          const base = api.coord([i, main[i] ?? 0]);
          const top = api.coord([i, (main[i] ?? 0) + (upper[i] ?? 0)]);
          const bot = api.coord([i, (main[i] ?? 0) - (lower[i] ?? 0)]);
          const w = api.size([0, 1], [0, 1])[0] * 0.35;
          return {
            type: "group",
            children: [
              { type: "line", shape: { x1: base[0] - w, y1: top[1], x2: base[0] + w, y2: top[1] }, style: { stroke: "#dc2626", lineWidth: 1.5 } },
              { type: "line", shape: { x1: base[0] - w, y1: bot[1], x2: base[0] + w, y2: bot[1] }, style: { stroke: "#dc2626", lineWidth: 1.5 } },
              { type: "line", shape: { x1: base[0], y1: top[1], x2: base[0], y2: bot[1] }, style: { stroke: "#dc2626", lineWidth: 1.5 } },
            ],
          };
        }) as never,
        data: tris.map((_, i) => [i, main[i] ?? 0]) as never,
        z: 3,
      },
    ],
  };
}

/** 区间带（error-range）：上下界折线带状（预测置信区间） */
export function buildErrorRange(data: ChartData, _title?: string): EChartsOption {
  const cats = data.categories || [];
  const tris = triples(data);
  const base = tris.map((t) => t.value);
  const upper = tris.map((t) => t.high);
  const lower = tris.map((t) => t.low);
  return {
    color: CHART_COLORS,
    tooltip: { trigger: "axis" },
    legend: { bottom: 0 },
    grid: { left: 56, right: 60, top: 20, bottom: 50 },
    xAxis: { type: "category", data: cats, boundaryGap: false },
    yAxis: { type: "value", axisLabel: valueAxisLabel },
    dataZoom: zoom2D(),
    series: [
      {
        name: "上界",
        type: "line",
        data: upper as never,
        lineStyle: { opacity: 0 },
        symbol: "none",
        stack: "band",
        silent: true,
      },
      {
        name: "区间",
        type: "line",
        data: lower as never,
        lineStyle: { opacity: 0 },
        symbol: "none",
        stack: "band",
        areaStyle: { color: "rgba(37,99,235,0.15)" },
        silent: true,
        tooltip: { show: false },
      },
      {
        name: (data.series?.[0]?.name as string) || "均值",
        type: "line",
        smooth: true,
        data: base as never,
        label: { show: true, position: "top", fontSize: 9 },
      },
    ],
  };
}
