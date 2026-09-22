/** bar3d 三维柱状图模板（P6-②）
 *  - bar3d  三维柱状（柱高 = 值，柱色随高度深浅渐变，可拖拽旋转/滚轮缩放）
 *
 * ⚠️ v6.9 退役说明：本模板实际渲染已改走 **Python(mplot3d)**（`tools/finmod_py_charts.py`
 * → `/api/apps/finmod/py-chart` → base64 PNG）。本 build 函数仅保留用于模板注册表
 * resolveTemplate/variant 解析 + 后端骨架兼容；前端对 `bar3d` 已全部走 Python 分支。
 * 数据结构：
 *   data.categories = [x类别]    如部门
 *   data.series 多组或单组：
 *     series[0].data = [[xIdx, yIdx, zVal], ...]  或
 *     {xCategories, yCategories, data: [[xIdx,yIdx,zVal],...]}（更清晰）
 *   data.color_scheme = 配色方案
 */
import type { EChartsOption } from "echarts";
import type { ChartData } from "./index";
import { schemeColors } from "./colors";

export function buildBar3d(data: ChartData, _title?: string): EChartsOption {
  const s0 = data.series?.[0];
  // 支持两种输入：
  //  A. xCategories/yCategories + data: [[xIdx,yIdx,z],...]
  //  B. categories 单维 + data: [[xIdx,yIdx,z],...]
  const xc = (data.xCategories as string[]) || (data.categories as string[]) || [];
  const yc = (data.yCategories as string[]) || ["Q1", "Q2", "Q3", "Q4"];
  const cells = (s0?.data || []) as [number, number, number][];
  const scheme = (data.color_scheme as string) || "auto";
  const shades = schemeColors(scheme as never, 6);

  const zs = cells.map((c) => c[2] ?? 0);
  const zMin = zs.length ? Math.min(...zs) : 0;
  const zMax = zs.length ? Math.max(...zs) : 1;

  return {
    tooltip: {
      formatter: (p: { value: number[] }) =>
        `${xc[p.value[0]] ?? "X${" + p.value[0] + "}"}<br>${yc[p.value[1]] ?? "Y${" + p.value[1] + "}"}<br>值: ${p.value[2]}`,
    } as never,
    grid3D: {
      boxWidth: 150,
      boxDepth: 80,
      boxHeight: 100,
      axisLine: { lineStyle: { color: "#a1a1aa" } },
      splitLine: { lineStyle: { color: "#e4e4e7" } },
      axisPointer: { lineStyle: { color: "#71717a" } },
      // 可拖拽旋转 + 滚轮缩放 + 右键/中键拖拽平移（P6-② 旋转缩放；P6-⑥ 平移）
      viewControl: {
        alpha: 25,
        beta: -25,
        distance: 240,
        rotateSensitivity: 2,
        zoomSensitivity: 2,
        panSensitivity: 1,
        autoRotate: false,
      },
      light: { main: { intensity: 1.3 }, ambient: { intensity: 0.5 } },
    },
    xAxis3D: { type: "category", data: xc, name: (data.xAxisName as string) || "X" },
    yAxis3D: { type: "category", data: yc, name: (data.yAxisName as string) || "Y" },
    zAxis3D: { type: "value", name: (data.zAxisName as string) || "值" },
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
        type: "bar3D",
        data: cells as never,
        shading: "lambert", // 光照着色立体感
        bevelSize: 0.5,
        label: { show: false },
        itemStyle: { opacity: 0.95, borderColor: "#18181b", borderWidth: 0.4 },
      } as never,
    ],
  };
}
