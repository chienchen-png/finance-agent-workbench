/** waterfall3d 三维瀑布图模板（L3 复杂，2026-08-23 v4：每指标独立山形竖带）。
 *
 * ⚠️ v6.9 退役说明：本模板的实际渲染已改走 **Python(mplot3d)**（`tools/finmod_py_charts.py`
 * → `/api/apps/finmod/py-chart` → base64 PNG），因为 echarts-gl 的 surface3D/line3D 无法复刻
 * 「每指标折线围成的填充平面」瀑布样式（会把行连成曲面）。
 * 本 build 函数仅保留用于：①模板注册表 resolveTemplate/variant 解析；②后端 generate_chart
 * 的 echarts option 骨架兼容。**前端 ChartPreview/ChartRenderer/FinModAppPage report 对
 * `waterfall3d` 已全部走 Python 分支，不再调用本 build 渲染。**
 */
import type { EChartsOption } from "echarts";
import type { ChartData } from "./index";
import { schemeColors } from "./colors";

export function buildWaterfall3d(data: ChartData, _title?: string): EChartsOption {
  const s0 = data.series?.[0];
  const xc = (data.xCategories as string[]) || (data.categories as string[]) || [];
  const yc = (data.yCategories as string[]) || [];
  const cells = (s0?.data || []) as [number, number, number][];
  const scheme = (data.color_scheme as string) || "blues";

  // 每指标一条（按 x 排序）
  const perMetric = yc.map((_, yi) =>
    cells.filter((c) => c[1] === yi).sort((a, b) => a[0] - b[0]),
  );
  const shades = schemeColors(scheme as never, yc.length || 5); // 浅→深
  const deepToShallow = [...shades].reverse();                   // 深→浅（前深后浅）

  const zs = cells.map((c) => c[2] ?? 0);
  const zMax = zs.length ? Math.max(...zs) : 1;

  // 每指标一个独立 surface3D 竖带：数据 = [x 采样点, y 恒定索引, z 值] 沿 x 的条带。
  // surface3D 的 data 是 [x,y,z] 数组；给每个指标 y 恒定（=yi），x 沿年份，z=数值。
  // 为让 echarts-gl 把「点序列」渲染成一条竖起的曲线面，each 指标单独 series。
  const surfaceSeries = yc.map((_, yi) => ({
    type: "surface" as const,
    data: (perMetric[yi] ?? []).map((p) => [p[0], p[1], p[2]] as never),
    shading: "color",
    wireframe: { show: false },
    // 每指标固定色（不依赖 visualMap，保证各指标独立清晰）
    itemStyle: { color: deepToShallow[yi % deepToShallow.length], opacity: 0.85 },
    silent: true,
  } as never));
  // 每指标顶部黑色轮廓折线 + 数据点
  const outlineSeries = yc.map((_, yi) => ({
    type: "line3D" as const,
    data: (perMetric[yi] ?? []).map((p) => [p[0], p[1], p[2]] as never),
    lineStyle: { color: "#0f172a", width: 2 },
    symbol: "circle",
    symbolSize: 5,
    silent: true,
  } as never));
  // 每指标底部灰色基线（z=0），虚线——还原案例 step2
  const baseSeries = yc.map((_, yi) => ({
    type: "line3D" as const,
    data: (perMetric[yi] ?? []).map((p) => [p[0], p[1], 0] as never),
    lineStyle: { color: "#94a3b8", width: 1, type: "dashed" },
    symbol: "none",
    silent: true,
  } as never));

  return {
    tooltip: {
      formatter: (p: { value: number[] }) =>
        `${xc[p.value[0]] ?? "X" + p.value[0]}<br>${yc[p.value[1]] ?? "Y" + p.value[1]}<br>值: ${p.value[2]}%`,
    } as never,
    grid3D: {
      boxWidth: 220,
      boxDepth: 160,
      boxHeight: 100,
      axisLine: { lineStyle: { color: "#cbd5e1" } },
      splitLine: { lineStyle: { color: "#e2e8f0" } },
      axisPointer: { lineStyle: { color: "#94a3b8" } },
      viewControl: {
        alpha: 25,
        beta: 50,
        distance: 250,
        rotateSensitivity: 2,
        zoomSensitivity: 2,
        panSensitivity: 1,
        autoRotate: false,
      },
      light: { main: { intensity: 1.3 }, ambient: { intensity: 0.55 } },
    },
    xAxis3D: { type: "category", data: xc, name: (data.xAxisName as string) || "时间" },
    yAxis3D: {
      type: "category",
      data: yc,
      name: (data.yAxisName as string) || "财务指标",
      axisLabel: { interval: 0, rotate: 20, textStyle: { fontSize: 10 } },
    },
    zAxis3D: { type: "value", name: (data.zAxisName as string) || "数值(%)", max: zMax * 1.15 },
    series: [
      ...surfaceSeries,
      ...outlineSeries,
      ...baseSeries,
    ],
  };
}
