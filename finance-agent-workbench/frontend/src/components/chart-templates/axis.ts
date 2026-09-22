/** axis — 2D 图通用轴工具（P6-③ 优化 / v6.3 无滑块缩放） */

/** 科学计数法格式化（|v| ≥ 1e4 → m.eN；否则原样/两位小数） */
export function sciValue(v: number): string {
  if (!Number.isFinite(v)) return String(v);
  const abs = Math.abs(v);
  if (abs >= 10000) {
    const exp = Math.floor(Math.log10(abs));
    const mant = v / Math.pow(10, exp);
    const m = Math.abs(mant - Math.round(mant)) < 1e-6 ? String(Math.round(mant)) : mant.toFixed(1);
    return `${m}e${exp}`;
  }
  if (Math.abs(v - Math.round(v)) < 1e-9) return String(Math.round(v));
  return String(Number(v.toFixed(2)));
}

/** value 轴 label formatter（科学计数法） */
export const valueAxisLabel = { formatter: sciValue };

/**
 * 2D 通用 dataZoom（v6.3：**仅 inside 无感交互，无可见滑块**）：
 *  - x 轴：绘图区内滚轮缩放 + 拖拽平移（居中调整）
 *  - y 轴：绘图区内拖拽平移（上下调整）
 * 用户要求图表展示即最终版本——**去掉上下/左右拖动条**（slider），
 * 保留滚轮缩放与拖拽平移的无感交互（鼠标悬停图内即可操作）。
 */
export function zoom2D(): NonNullable<import("echarts").EChartsOption["dataZoom"]> {
  return [
    { type: "inside", xAxisIndex: 0, start: 0, end: 100, zoomOnMouseWheel: true, moveOnMouseMove: true, moveOnMouseWheel: false },
    { type: "inside", yAxisIndex: 0, zoomOnMouseWheel: false, moveOnMouseWheel: false, moveOnMouseMove: true },
  ];
}

/** 仅横轴缩放/滑动（horizontal bar / tornado 等 y 为类别轴时），无可见滑块 */
export function zoomXOnly(): NonNullable<import("echarts").EChartsOption["dataZoom"]> {
  return [
    { type: "inside", xAxisIndex: 0, start: 0, end: 100, zoomOnMouseWheel: true, moveOnMouseMove: true, moveOnMouseWheel: false },
  ];
}

/** 判断 option 是否配置了 dataZoom（inside 无感缩放）→ 前端据此显示操作提示 */
export function hasZoom(opt: Record<string, unknown>): boolean {
  const dz = opt.dataZoom;
  if (Array.isArray(dz)) return dz.length > 0;
  return Boolean(dz);
}

/** 图表说明文案（科学计数法 + 操作提示），2D 图渲染后显示在图下方 */
export const AXIS_NOTE =
  "注：坐标轴数值超过 4 位采用科学计数法，如 1.6e8 表示 1.6×10⁸（160,000,000）；" +
  "图表可滚轮缩放（鼠标悬停图内滚动）与拖拽平移（按住图内拖动调整位置）。";
