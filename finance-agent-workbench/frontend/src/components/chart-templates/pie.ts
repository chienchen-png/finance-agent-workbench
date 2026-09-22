/** pie 饼图/环形图模板（P5-② 五变体）
 *  - pie-donut       环形图（默认）
 *  - pie-simple      基础饼图（实心）
 *  - pie-half-donut  半环形（KPI 达成）
 *  - pie-rounded     圆角环形
 *  - pie-nested      嵌套环形（内外层，series 提供两层）
 */
import type { EChartsOption } from "echarts";
import type { ChartData } from "./index";
import { CHART_COLORS } from "./index";

function pieDataOf(data: ChartData): { name: string; value: number }[] {
  const cats = data.categories || [];
  const s0 = data.series?.[0];
  const values = (s0?.data || []) as number[];
  return cats.map((c, i) => ({
    name: c,
    value: typeof values[i] === "number" ? values[i] : 0,
  }));
}

/** 环形图（pie / pie-donut，默认）：中空环形，v5.3-3 官方交互（悬停放大） */
export function buildPie(data: ChartData, _title?: string): EChartsOption {
  return {
    color: CHART_COLORS,
    tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
    legend: { bottom: 0, type: "scroll", orient: "horizontal" },
    // v5.3-3：官方级 emphasis——悬停扇区放大 + 数值上浮（对齐 pie-doughnut）
    emphasis: { scale: true, scaleSize: 6 },
    series: [
      {
        type: "pie",
        radius: ["38%", "62%"],
        center: ["50%", "46%"],
        avoidLabelOverlap: true,
        itemStyle: { borderRadius: 4, borderColor: "#fff", borderWidth: 1.5 },
        label: { show: true, formatter: "{b}\n{d}%" },
        labelLine: { length: 12, length2: 8 },
        data: pieDataOf(data) as never,
      },
    ],
  };
}

/** 基础饼图（pie-simple）：实心扇形 */
export function buildPieSimple(data: ChartData, _title?: string): EChartsOption {
  return {
    color: CHART_COLORS,
    tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
    legend: { bottom: 0, type: "scroll", orient: "horizontal" },
    series: [
      {
        type: "pie",
        radius: "68%",
        center: ["50%", "46%"],
        avoidLabelOverlap: true,
        label: { show: true, formatter: "{b}: {d}%" },
        data: pieDataOf(data) as never,
      },
    ],
  };
}

/** 半环形（pie-half-donut）：上半环，适合 KPI 达成率 */
export function buildPieHalfDonut(data: ChartData, _title?: string): EChartsOption {
  return {
    color: CHART_COLORS,
    tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
    legend: { bottom: 0, type: "scroll", orient: "horizontal" },
    series: [
      {
        type: "pie",
        radius: ["45%", "70%"],
        center: ["50%", "70%"],
        startAngle: 180,
        endAngle: 360,
        avoidLabelOverlap: true,
        itemStyle: { borderRadius: 4, borderColor: "#fff", borderWidth: 1.5 },
        label: { show: true, position: "outside", formatter: "{b}\n{d}%" },
        data: pieDataOf(data) as never,
      },
    ],
  };
}

/** 圆角环形（pie-rounded）：大圆角扇区 + 间隙 */
export function buildPieRounded(data: ChartData, _title?: string): EChartsOption {
  return {
    color: CHART_COLORS,
    tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
    legend: { bottom: 0, type: "scroll", orient: "horizontal" },
    series: [
      {
        type: "pie",
        radius: ["30%", "62%"],
        center: ["50%", "46%"],
        padAngle: 3,
        itemStyle: { borderRadius: 12, borderColor: "#fff", borderWidth: 2 },
        label: { show: true, formatter: "{b}\n{d}%" },
        data: pieDataOf(data) as never,
      },
    ],
  };
}

/** 嵌套环形（pie-nested）：series[0] 内层 / series[1] 外层（data 各层值） */
export function buildPieNested(data: ChartData, _title?: string): EChartsOption {
  const cats = data.categories || [];
  const series = (data.series || []).map((s, si) => ({
    name: s.name || `层${si + 1}`,
    type: "pie" as const,
    radius: si === 0 ? ["12%", "38%"] : ["42%", "62%"],
    center: ["50%", "46%"],
    avoidLabelOverlap: true,
    itemStyle: { borderRadius: 4, borderColor: "#fff", borderWidth: 1.5 },
    label: { show: si === 0, formatter: "{b}" },
    emphasis: { label: { show: true, fontSize: 12, fontWeight: "bolder" as const } },
    data: (s.data || []).map((v, i) => ({
      name: cats[i] || `${si + 1}-${i + 1}`,
      value: typeof v === "number" ? v : 0,
    })) as never,
  }));
  return {
    color: CHART_COLORS,
    tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
    legend: { bottom: 0, type: "scroll", orient: "horizontal" },
    series,
  };
}

