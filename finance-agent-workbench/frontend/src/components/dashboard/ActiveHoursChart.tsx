/** ActiveHoursChart — 活跃时段分布（D4）。
 *
 * 设计文档：`docs/工作台总览设计方案.md` §2.2 ④
 * - 24 小时逐时打开次数柱（近 7 天），回答「我通常几点打开工作台」
 * - 复用 chart-templates 的 `bar`（简单柱状图）
 */

import type { ActiveHourPoint } from "../../lib/dashboard";
import DashboardChart from "./DashboardChart";

export default function ActiveHoursChart({ hours }: { hours: ActiveHourPoint[] }) {
  const cats = hours.map((h) => `${String(h.hour).padStart(2, "0")}:00`);
  const data: {
    categories: string[];
    series: { name: string; data: number[] }[];
  } = {
    categories: cats,
    series: [{ name: "打开次数", data: hours.map((h) => h.sessions) }],
  };

  // 简约化：去 dataZoom、x 标签降频（每 3h 标一个、不旋转）、
  // 柱色统一浅蓝无渐变、无柱顶 label、网格虚线淡色
  const overrides: Record<string, unknown> = {
    dataZoom: undefined,
    grid: { left: 46, right: 14, top: 16, bottom: 28 }, // left 留足 y 轴「打开次数」标题空间
    xAxis: [
      {
        type: "category",
        data: cats,
        axisTick: { show: false },
        axisLine: { lineStyle: { color: "#e4e4e7" } },
        axisLabel: { interval: 2, rotate: 0, fontSize: 10, color: "#a1a1aa" },
      },
    ],
    yAxis: [
      {
        type: "value",
        name: "次数",
        nameTextStyle: { fontSize: 10, color: "#a1a1aa" },
        minInterval: 1,
        axisLabel: { fontSize: 10, color: "#a1a1aa" },
        splitLine: { lineStyle: { type: "dashed", opacity: 0.25, color: "#71717a" } },
      },
    ],
    series: [
      {
        type: "bar",
        barMaxWidth: 18,
        data: hours.map((h) => h.sessions),
        itemStyle: { color: "#60a5fa", borderRadius: [4, 4, 0, 0] },
        label: { show: false },
      },
    ],
  };

  return <DashboardChart template="bar" data={data} height={210} overrides={overrides} />;
}
