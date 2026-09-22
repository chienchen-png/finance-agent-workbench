/** DashboardChart — 工作台总览轻量 ECharts 容器（D4）。
 *
 * 设计文档：`docs/工作台总览设计方案.md` §4.3 决策 6（复用 chart-templates 生态）
 * 复用 `buildChartOption` 模板注册表（不另起 echarts 实例逻辑），
 * 内部管理 echarts 生命周期（init / setOption / ResizeObserver / resize / dispose）。
 * `overrides`：对模板产物做顶层覆盖（deepMerge）——用于「简约化」：
 * 去掉 toolbox/dataZoom、精简 grid、降频 x 标签等。
 */

import { useLayoutEffect, useRef } from "react";
import * as echarts from "echarts";
import { buildChartOption, type ChartData } from "../chart-templates";

export default function DashboardChart({
  template,
  data,
  height = 160,
  overrides,
}: {
  template: string;
  data: ChartData;
  height?: number;
  overrides?: Record<string, unknown>;
}) {
  const elRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useLayoutEffect(() => {
    if (!elRef.current) return;
    let disposed = false;
    let ro: ResizeObserver | null = null;

    const option = buildChartOption(template, data, undefined, overrides);
    if (!option) return;

    const tryInit = () => {
      if (disposed || !elRef.current || chartRef.current) return;
      const w = elRef.current.clientWidth;
      const h = elRef.current.clientHeight;
      if (w < 10 || h < 10) return; // 容器无尺寸 → 等 ResizeObserver
      try {
        const inst = echarts.init(elRef.current);
        chartRef.current = inst;
        inst.setOption(option as echarts.EChartsOption, true);
        inst.resize();
      } catch (e) {
        console.error("[DashboardChart] init/setOption failed:", e);
      }
    };

    tryInit();
    if (!chartRef.current) {
      ro = new ResizeObserver(() => tryInit());
      ro.observe(elRef.current);
    }
    const onResize = () => chartRef.current?.resize();
    window.addEventListener("resize", onResize);

    return () => {
      disposed = true;
      ro?.disconnect();
      window.removeEventListener("resize", onResize);
      chartRef.current?.dispose();
      chartRef.current = null;
    };
  }, [template, data]);

  return <div ref={elRef} style={{ height }} className="w-full" />;
}
