/** calendar 日历热力图模板（P5-③ 新增类型）
 *  - calendar-simple   单年日历热力（每日回款/支出）
 *  - calendar-year    多年日历（上下排列，跨年对比）
 * 数据结构：
 *   data.calendarRange = [start, end]（如 ["2025-01-01","2025-12-31"]）
 *   series[0].data = [["2025-01-05", 1200], ...]（日期, 值）
 */
import type { EChartsOption } from "echarts";
import type { ChartData } from "./index";

function calendarCells(data: ChartData): [string, number][] {
  const s0 = data.series?.[0];
  return (s0?.data || []) as [string, number][];
}

/** 单年日历热力（calendar / calendar-simple） */
export function buildCalendar(data: ChartData, _title?: string): EChartsOption {
  const cal = (data as Record<string, unknown>).calendarRange as [string, string] | undefined;
  const range: [string, string] = cal ?? [
    (data.categories?.[0] as string) || "2025-01-01",
    (data.categories?.[data.categories.length - 1] as string) || "2025-12-31",
  ];
  const cells = calendarCells(data);
  const min = cells.length ? Math.min(...cells.map((c) => c[1])) : 0;
  const max = cells.length ? Math.max(...cells.map((c) => c[1])) : 100;
  return {
    tooltip: {
      formatter: (p: { data: [string, number] }) => `${p.data[0]}: ${p.data[1]}`,
    } as never,
    visualMap: {
      min,
      max,
      orient: "horizontal",
      left: "center",
      bottom: 4,
      inRange: { color: ["#e0f2fe", "#60a5fa", "#2563eb", "#1e3a8a"] },
    },
    calendar: {
      range,
      left: 40,
      top: 20,
      cellSize: ["auto", 16],
      itemStyle: { borderWidth: 1, borderColor: "#fff" },
      yearLabel: { show: true, fontSize: 12 },
      dayLabel: { fontSize: 9 },
    },
    series: [{ type: "heatmap", coordinateSystem: "calendar", data: cells as never }],
  };
}

/** 多年日历（calendar-year）：每年一行，跨年对比 */
export function buildCalendarYear(data: ChartData, _title?: string): EChartsOption {
  const cal = (data as Record<string, unknown>).calendarRange as [string, string] | undefined;
  const range: [string, string] = cal ?? ["2024-01-01", "2025-12-31"];
  const cells = calendarCells(data);
  const min = cells.length ? Math.min(...cells.map((c) => c[1])) : 0;
  const max = cells.length ? Math.max(...cells.map((c) => c[1])) : 100;
  return {
    tooltip: {
      formatter: (p: { data: [string, number] }) => `${p.data[0]}: ${p.data[1]}`,
    } as never,
    visualMap: {
      min,
      max,
      orient: "horizontal",
      left: "center",
      bottom: 4,
      inRange: { color: ["#ecfdf5", "#34d399", "#059669", "#064e3b"] },
    },
    calendar: [
      { range, top: 20, left: 40, cellSize: ["auto", 14], itemStyle: { borderWidth: 1, borderColor: "#fff" } },
    ],
    series: [{ type: "heatmap", coordinateSystem: "calendar", data: cells as never }],
  };
}
