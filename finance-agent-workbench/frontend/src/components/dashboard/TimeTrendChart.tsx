/** TimeTrendChart — 7 日使用时长趋势（D4）。
 *
 * 设计文档：`docs/工作台总览设计方案.md` §2.2 ④
 * - 柱 = 每日累计软件打开时长（分钟），线 = 当日打开次数（次 y 轴）
 * - 复用 chart-templates 的 `bar-line`（折线柱状图，双 y 轴）
 */

import type { TimeTrendPoint } from "../../lib/dashboard";
import DashboardChart from "./DashboardChart";

export default function TimeTrendChart({ trend }: { trend: TimeTrendPoint[] }) {
  const cats = trend.map((t) => t.day.slice(5)); // "MM-DD"
  const minutes = trend.map((t) => Math.round(t.duration_sec / 60));
  const sessions = trend.map((t) => t.sessions);
  const data: {
    categories: string[];
    series: { name: string; type: string; data: number[] }[];
    yAxis0Name: string;
    yAxis1Name: string;
  } = {
    categories: cats,
    series: [
      { name: "使用时长（分钟）", type: "bar", data: minutes },
      { name: "打开次数", type: "line", data: sessions },
    ],
    yAxis0Name: "分钟",
    yAxis1Name: "次",
  };

  // 简约化：去 toolbox/dataZoom、精简 grid；并完整覆盖 series（deepMerge 数组整体替换）
  // —— 折线改用低饱和琥珀色（模板默认 #dc2626 太刺眼），柱用淡蓝与活跃时段一致。
  const overrides: Record<string, unknown> = {
    toolbox: undefined,
    dataZoom: undefined,
    grid: { left: 60, right: 18, top: 30, bottom: 44 }, // left 留足双 y 轴标题（分钟/次）空间
    legend: {
      bottom: 0,
      icon: "circle",
      itemWidth: 8,
      itemHeight: 8,
      itemGap: 18,
      textStyle: { fontSize: 11, color: "#71717a" },
    },
    yAxis: [
      { type: "value", name: "分钟", nameTextStyle: { fontSize: 10, color: "#a1a1aa" }, axisLabel: { fontSize: 10, color: "#a1a1aa" }, splitLine: { lineStyle: { type: "dashed", opacity: 0.25, color: "#71717a" } } },
      { type: "value", name: "次", nameTextStyle: { fontSize: 10, color: "#a1a1aa" }, axisLabel: { fontSize: 10, color: "#a1a1aa" }, splitLine: { show: false } },
    ],
    series: [
      {
        name: "使用时长（分钟）",
        type: "bar",
        barMaxWidth: 24,
        data: minutes,
        itemStyle: { color: "#60a5fa", borderRadius: [4, 4, 0, 0] },
      },
      {
        name: "打开次数",
        type: "line",
        yAxisIndex: 1,
        smooth: true,
        symbol: "circle",
        symbolSize: 5,
        data: sessions,
        lineStyle: { width: 2 },
        itemStyle: { color: "#f59e0b" },
      },
    ],
  };

  return <DashboardChart template="bar-line" data={data} height={210} overrides={overrides} />;
}
