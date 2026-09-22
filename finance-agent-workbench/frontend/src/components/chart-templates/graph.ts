/** graph 关系图模板（P5-③ 新增类型）
 *  - graph-force      力导向布局（资金往来/科目关联网络）
 *  - graph-circle     环形布局（环形对比/层级环）
 * 数据结构：
 *   nodes: [{name, value?, category?}]
 *   links: [{source, target, value?}]
 *   categories: [{name}] 节点分类（可选）
 */
import type { EChartsOption } from "echarts";
import type { ChartData } from "./index";
import { CHART_COLORS } from "./index";

function graphBase(data: ChartData): {
  nodes: Record<string, unknown>[];
  links: Record<string, unknown>[];
  cats: { name: string }[];
} {
  const nodes = (data.nodes || []) as Record<string, unknown>[];
  const links = (data.links || []) as Record<string, unknown>[];
  const cats = (data.categories || []).map((c) => ({ name: c }));
  return { nodes, links, cats };
}

/** 力导向关系图（graph / 默认）：资金往来/科目关联 */
export function buildGraph(data: ChartData, _title?: string): EChartsOption {
  const { nodes, links, cats } = graphBase(data);
  return {
    color: CHART_COLORS,
    tooltip: { trigger: "item" },
    legend: cats.length > 1 ? { bottom: 0 } : undefined,
    series: [
      {
        type: "graph",
        layout: "force",
        roam: true,
        draggable: true,
        force: { repulsion: 120, edgeLength: [40, 90], gravity: 0.1 },
        label: { show: true, fontSize: 9, overflow: "truncate" },
        // 默认：有向网络（箭头表示资金流向）
        edgeSymbol: ["none", "arrow"],
        lineStyle: { color: "source", curveness: 0.2, width: 1.2 },
        emphasis: { focus: "adjacency", lineStyle: { width: 3 } },
        categories: cats,
        data: nodes as never,
        links: links as never,
      },
    ],
  };
}

/** 无向网络（graph-force）：力导向无箭头，强调关联关系（v6.9 与默认差异化） */
export function buildGraphForce(data: ChartData, _title?: string): EChartsOption {
  const { nodes, links, cats } = graphBase(data);
  return {
    color: CHART_COLORS,
    tooltip: { trigger: "item" },
    legend: cats.length > 1 ? { bottom: 0 } : undefined,
    series: [
      {
        type: "graph",
        layout: "force",
        roam: true,
        draggable: true,
        force: { repulsion: 160, edgeLength: [30, 70], gravity: 0.05 },
        label: { show: true, fontSize: 9, overflow: "truncate" },
        // 无向：无箭头，线条更细（关联强度）
        lineStyle: { color: "source", curveness: 0.1, width: 1 },
        emphasis: { focus: "adjacency", lineStyle: { width: 3 } },
        categories: cats,
        data: nodes as never,
        links: links as never,
      },
    ],
  };
}

/** 环形关系图（graph-circle）：环形布局，适合层级环/环形对比 */
export function buildGraphCircle(data: ChartData, _title?: string): EChartsOption {
  const { nodes, links, cats } = graphBase(data);
  return {
    color: CHART_COLORS,
    tooltip: { trigger: "item" },
    legend: cats.length > 1 ? { bottom: 0 } : undefined,
    series: [
      {
        type: "graph",
        layout: "circular",
        roam: true,
        circular: { rotateLabel: true },
        label: { show: true, fontSize: 9, overflow: "truncate" },
        lineStyle: { color: "source", curveness: 0.2, width: 1.2 },
        emphasis: { focus: "adjacency", lineStyle: { width: 3 } },
        categories: cats,
        data: nodes as never,
        links: links as never,
      },
    ],
  };
}
