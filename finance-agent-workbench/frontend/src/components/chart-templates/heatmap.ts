/** heatmap 热力图模板（P5-② 三变体）
 *  - heatmap-simple    连续色热力（相关矩阵/双变量敏感性，默认）
 *  - heatmap-discrete  离散色阶（区间分段着色）
 *  - heatmap-calendar  日历热力（data.calendarRange: [start,end] 或 [ [start,end], ymax ]）
 */
import type { EChartsOption } from "echarts";
import type { ChartData } from "./index";

function extractCells(data: ChartData): [number, number, number][] {
  const xc = data.xCategories || data.categories || [];
  const s0 = data.series?.[0];
  const cells = (s0?.data || []) as [number, number, number][];
  const matrix = (s0 as Record<string, unknown>)?.matrix as number[][] | undefined;
  let cellData = cells;
  if ((!cells.length || cells.length === 0) && matrix && xc.length) {
    cellData = [];
    matrix.forEach((row, i) => {
      row.forEach((v, j) => {
        cellData.push([j, i, v]);
      });
    });
  }
  return cellData;
}

export function buildHeatmap(data: ChartData, _title?: string): EChartsOption {
  const xc = data.xCategories || data.categories || [];
  const yc = data.yCategories || [];
  const cellData = extractCells(data);
  const min = cellData.length ? Math.min(...cellData.map((c) => c[2])) : 0;
  const max = cellData.length ? Math.max(...cellData.map((c) => c[2])) : 1;
  return {
    tooltip: { position: "top" },
    grid: { left: 60, right: 20, top: 20, bottom: 60 },
    xAxis: { type: "category", data: xc, splitArea: { show: true } },
    yAxis: { type: "category", data: yc, splitArea: { show: true } },
    visualMap: {
      min,
      max,
      calculable: true,
      orient: "horizontal",
      left: "center",
      bottom: 4,
      inRange: { color: ["#1e40af", "#2563eb", "#60a5fa", "#93c5fd", "#fca5a5", "#ef4444"] },
    },
    series: [{ type: "heatmap", data: cellData as never, label: { show: true, fontSize: 10 } }],
  };
}

/** 离散色阶（heatmap-discrete）：分段 4 色（低→高），适合等级/评分 */
export function buildHeatmapDiscrete(data: ChartData, _title?: string): EChartsOption {
  const xc = data.xCategories || data.categories || [];
  const yc = data.yCategories || [];
  const cellData = extractCells(data);
  const min = cellData.length ? Math.min(...cellData.map((c) => c[2])) : 0;
  const max = cellData.length ? Math.max(...cellData.map((c) => c[2])) : 1;
  return {
    tooltip: { position: "top" },
    grid: { left: 60, right: 20, top: 20, bottom: 60 },
    xAxis: { type: "category", data: xc, splitArea: { show: true } },
    yAxis: { type: "category", data: yc, splitArea: { show: true } },
    visualMap: {
      min,
      max,
      calculable: true,
      orient: "horizontal",
      left: "center",
      bottom: 4,
      type: "piecewise",
      pieces: [
        { lte: min + (max - min) * 0.25, color: "#3b82f6" },
        { gt: min + (max - min) * 0.25, lte: min + (max - min) * 0.5, color: "#22d3ee" },
        { gt: min + (max - min) * 0.5, lte: min + (max - min) * 0.75, color: "#fbbf24" },
        { gt: min + (max - min) * 0.75, color: "#ef4444" },
      ],
    },
    series: [{ type: "heatmap", data: cellData as never, label: { show: true, fontSize: 10 } }],
  };
}

/** 日历热力（heatmap-calendar）：按日期分布（data.calendarRange = [start, end]） */
export function buildHeatmapCalendar(data: ChartData, _title?: string): EChartsOption {
  const cal = (data as Record<string, unknown>).calendarRange as [string, string] | undefined;
  const range: [string, string] = cal ?? [
    (data.categories?.[0] as string) || "2025-01-01",
    (data.categories?.[data.categories.length - 1] as string) || "2025-12-31",
  ];
  const s0 = data.series?.[0];
  const cellData = (s0?.data || []) as [string, number][];
  return {
    tooltip: { formatter: (p: { data: [string, number] }) => `${p.data[0]}: ${p.data[1]}` } as never,
    visualMap: {
      min: cellData.length ? Math.min(...cellData.map((c) => c[1])) : 0,
      max: cellData.length ? Math.max(...cellData.map((c) => c[1])) : 100,
      orient: "horizontal",
      left: "center",
      bottom: 4,
      inRange: { color: ["#e0f2fe", "#3b82f6", "#1e3a8a"] },
    },
    calendar: { range, left: 40, top: 20, cellSize: ["auto", 16], itemStyle: { borderWidth: 1, borderColor: "#fff" } },
    series: [{ type: "heatmap", coordinateSystem: "calendar", data: cellData as never }],
  };
}

