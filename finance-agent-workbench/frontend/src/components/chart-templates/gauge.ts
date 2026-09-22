/** gauge 仪表盘模板（P5-② 三变体）
 *  - gauge-simple   进度式仪表（默认）
 *  - gauge-progress 大进度环（百分比，progress 高亮）
 *  - gauge-stage    阶段区间（红黄绿分段，KPI 预警）
 */
import type { EChartsOption } from "echarts";
import type { ChartData } from "./index";

function gaugeValue(data: ChartData): { v: number; max: number; name: string } {
  const s0 = data.series?.[0];
  const raw = s0?.data?.[0];
  const v: number = typeof raw === "object" ? Number((raw as { value?: number }).value ?? 0) : Number(raw ?? 0);
  const max = Number((s0?.max as number) || 100);
  const name = typeof raw === "object" ? ((raw as { name?: string }).name ?? "") : (s0?.name || "KPI");
  return { v, max, name };
}

export function buildGauge(data: ChartData, _title?: string): EChartsOption {
  const { v, max, name } = gaugeValue(data);
  return {
    series: [
      {
        type: "gauge",
        min: 0,
        max,
        progress: { show: true, width: 12 },
        axisLine: { lineStyle: { width: 12 } },
        axisTick: { show: false },
        splitLine: { length: 10, lineStyle: { width: 1 } },
        axisLabel: { distance: 16, fontSize: 9 },
        pointer: { width: 4 },
        detail: {
          valueAnimation: true,
          formatter: (x: number) => `${x.toFixed(1)}%`,
          fontSize: 16,
        },
        data: [{ value: v, name }],
      },
    ],
  };
}

/** 大进度环（gauge-progress）：进度弧线高亮，适合目标达成率 */
export function buildGaugeProgress(data: ChartData, _title?: string): EChartsOption {
  const { v, max, name } = gaugeValue(data);
  return {
    series: [
      {
        type: "gauge",
        min: 0,
        max,
        startAngle: 90,
        endAngle: -270,
        progress: { show: true, width: 18, roundCap: true },
        axisLine: { lineStyle: { width: 18 } },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: { show: false },
        pointer: { show: false },
        detail: {
          valueAnimation: true,
          offsetCenter: [0, "-5%"],
          formatter: (x: number) => `${x.toFixed(1)}%`,
          fontSize: 22,
          fontWeight: "bolder" as const,
        },
        title: { offsetCenter: [0, "25%"], fontSize: 12 },
        data: [{ value: v, name }],
      },
    ],
  };
}

/** 阶段区间（gauge-stage）：红黄绿分段，KPI 预警 */
export function buildGaugeStage(data: ChartData, _title?: string): EChartsOption {
  const { v, max, name } = gaugeValue(data);
  return {
    series: [
      {
        type: "gauge",
        min: 0,
        max,
        progress: { show: true, width: 14 },
        axisLine: {
          lineStyle: {
            width: 14,
            color: [
              [0.33, "#dc2626"],
              [0.66, "#f59e0b"],
              [1, "#059669"],
            ],
          },
        },
        axisTick: { show: false },
        splitLine: { length: 8, lineStyle: { width: 1 } },
        axisLabel: { distance: 12, fontSize: 9 },
        pointer: { width: 4 },
        detail: {
          valueAnimation: true,
          formatter: (x: number) => `${x.toFixed(0)}%`,
          fontSize: 15,
          color: "auto",
        },
        data: [{ value: v, name }],
      },
    ],
  };
}

