/** sankey 桑基图模板（P5-② 两变体）
 *  - sankey-simple    水平流向（默认）
 *  - sankey-vertical  垂直流向（上下层级，适合组织/科目树）
 */
import type { EChartsOption } from "echarts";
import type { ChartData } from "./index";

export function buildSankey(data: ChartData, _title?: string): EChartsOption {
  const nodes = (data.nodes || []) as { name: string }[];
  const links = (data.links || []) as { source: string; target: string; value: number }[];
  return {
    tooltip: { trigger: "item", triggerOn: "mousemove" },
    // v6.8：官方观感——节点圆角 + 渐变边 + 透明度分层
    color: ["#2563eb", "#f97316", "#0d9488", "#db2777", "#7c3aed",
            "#059669", "#d97706", "#4f46e5", "#0ea5e9", "#dc2626"],
    series: [
      {
        type: "sankey",
        left: "6%",
        right: "8%",
        top: 16,
        bottom: 8,
        nodeAlign: "justify",
        nodeWidth: 14,
        nodeGap: 12,
        data: nodes as never,
        links: links as never,
        label: { fontSize: 10, color: "#52525b" },
        itemStyle: { borderWidth: 0, borderRadius: 3 },
        lineStyle: { color: "gradient", curveness: 0.5, opacity: 0.55 },
      },
    ],
  };
}

/** 垂直桑基（sankey-vertical）：orient=vertical，适合预算科目垂直分层 */
export function buildSankeyVertical(data: ChartData, _title?: string): EChartsOption {
  const nodes = (data.nodes || []) as { name: string }[];
  const links = (data.links || []) as { source: string; target: string; value: number }[];
  return {
    tooltip: { trigger: "item", triggerOn: "mousemove" },
    series: [
      {
        type: "sankey",
        orient: "vertical",
        left: 20,
        right: 20,
        top: 12,
        bottom: "8%",
        nodeAlign: "justify",
        data: nodes as never,
        links: links as never,
        label: { fontSize: 10 },
        lineStyle: { color: "gradient", curveness: 0.5 },
      },
    ],
  };
}
