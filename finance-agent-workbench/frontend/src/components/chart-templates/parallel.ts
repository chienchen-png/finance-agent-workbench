/** parallel 平行坐标图模板（P5-③ 新增类型）
 *  - parallel-simple  平行坐标（多维公司/产品对比）
 * 数据结构：
 *   dimensions: [{name, min?, max?}]  坐标维度
 *   series[0].data = [[v1,v2,v3,...], ...]  每行一条线（一个实体）
 */
import type { EChartsOption } from "echarts";
import type { ChartData } from "./index";
import { valueAxisLabel } from "./axis";

/** 平行坐标（parallel / parallel-simple）：多维对比 */
export function buildParallel(data: ChartData, _title?: string): EChartsOption {
  const dims = (data.dimensions || (data.categories || []).map((c) => ({ name: c }))) as {
    name: string;
    min?: number;
    max?: number;
  }[];
  const s0 = data.series?.[0];
  const rows = (s0?.data || []) as (number | string)[][];
  const dimIndex = (data as Record<string, unknown>).dimIndex as number[] | undefined;
  return {
    tooltip: { trigger: "item" },
    parallelAxis: dims.map((d, i) => ({
      dim: i,
      name: d.name,
      min: d.min,
      max: d.max,
      nameLocation: "start",
      axisLabel: valueAxisLabel,
    })),
    parallel: { left: 40, right: 60, top: 30, bottom: 40, parallelAxisDefault: { type: "value", axisLabel: valueAxisLabel } },
    series: [
      {
        type: "parallel",
        lineStyle: { width: 1.5, opacity: 0.7 },
        emphasis: { lineStyle: { width: 4, opacity: 1 } },
        data: rows as never,
        ...(dimIndex ? { parallelIndex: 0 } : {}),
      },
    ],
  };
}
