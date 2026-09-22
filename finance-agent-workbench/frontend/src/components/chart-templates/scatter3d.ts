/** scatter3d 三维散点图模板（P6-②）
 *  - scatter3d  三维散点（气泡颜色深浅 = 第 3 维，可拖拽旋转/滚轮缩放）
 *
 * ⚠️ v6.9 退役说明：本模板实际渲染已改走 **Python(mplot3d)**（`tools/finmod_py_charts.py`
 * → `/api/apps/finmod/py-chart` → base64 PNG）。本 build 函数仅保留用于模板注册表
 * resolveTemplate/variant 解析 + 后端骨架兼容；前端对 `scatter3d` 已全部走 Python 分支。
 * 数据结构：
 *   series[0].data = [[x, y, z], ...]  三元组（如 [收入, 利润率, 周转率]）
 *   data.axisNames = [x名, y名, z名]   坐标轴名（可选）
 *   data.color_scheme = "blues" | "greens" | ... | "auto"  配色方案（P6-②）
 */
import type { EChartsOption } from "echarts";
import type { ChartData } from "./index";
import { schemeColors } from "./colors";

export function buildScatter3d(data: ChartData, _title?: string): EChartsOption {
  const s0 = data.series?.[0];
  const pts = (s0?.data || []) as [number, number, number][];
  const axisNames = (data.axisNames as string[]) || ["X", "Y", "Z"];
  const scheme = (data.color_scheme as string) || "auto";
  const shades = schemeColors(scheme as never, 6);

  const zs = pts.map((p) => p[2] ?? 0);
  const zMin = zs.length ? Math.min(...zs) : 0;
  const zMax = zs.length ? Math.max(...zs) : 1;

  return {
    tooltip: {
      formatter: (p: { value: number[] }) =>
        `${axisNames[0]}: ${p.value[0]}<br>${axisNames[1]}: ${p.value[1]}<br>${axisNames[2]}: ${p.value[2]}`,
    } as never,
    grid3D: {
      boxWidth: 120,
      boxDepth: 120,
      boxHeight: 90,
      axisLine: { lineStyle: { color: "#a1a1aa" } },
      splitLine: { lineStyle: { color: "#e4e4e7" } },
      axisPointer: { lineStyle: { color: "#71717a" } },
      // 可拖拽旋转 + 滚轮缩放 + 右键/中键拖拽平移（P6-② 旋转缩放；P6-⑥ 平移）
      viewControl: {
        alpha: 22,
        beta: -30,
        distance: 220,
        rotateSensitivity: 2,
        zoomSensitivity: 2,
        panSensitivity: 1,
        autoRotate: false,
      },
      light: { main: { intensity: 1.2 }, ambient: { intensity: 0.5 } },
    },
    xAxis3D: { type: "value", name: axisNames[0] },
    yAxis3D: { type: "value", name: axisNames[1] },
    zAxis3D: { type: "value", name: axisNames[2] },
    visualMap: {
      show: true,
      dimension: 2,
      min: zMin,
      max: zMax,
      left: 16,
      bottom: 16,
      text: ["高", "低"],
      textStyle: { color: "#71717a" },
      inRange: { color: shades },
    },
    series: [
      {
        type: "scatter3D",
        data: pts as never,
        symbolSize: 8,
        itemStyle: { opacity: 0.9 },
        emphasis: { itemStyle: { opacity: 1 }, label: { show: false } },
      } as never,
    ],
  };
}
