/** view-control — 饼图/环形图自定义视图交互（P6-⑥）
 *
 * 饼图无坐标轴，dataZoom 无效 → 用 echarts getZr() 手动实现：
 *  - 滚轮：缩放 radius（放大/缩小饼图）
 *  - 拖拽：平移 center（移动饼图中心位置）
 *
 * 2D 图走 dataZoom（滚轮缩放+滑块平移）、3D 图走 viewControl（旋转+缩放+平移），
 * 此工具只服务 pie 系（无原生视图交互的图型）。
 */

type ECharts = import("echarts").ECharts;

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const pct = (s: string): number => parseFloat(s);

interface PieState {
  radius: [string, string];
  center: [string, string];
}

/** 读取当前 series[0] 的 radius/center（兼容字符串或数组） */
function readSeries(chart: ECharts): PieState | null {
  const opt = chart.getOption();
  const s = (opt.series as Array<Record<string, unknown>> | undefined)?.[0];
  if (!s) return null;
  const r = s.radius as string | string[] | undefined;
  const radius: [string, string] = Array.isArray(r)
    ? [String(r[0] ?? "50%"), String(r[1] ?? "60%")]
    : [String(r ?? "60%"), String(r ?? "60%")];
  const c = (s.center as string[] | undefined) || ["50%", "50%"];
  return { radius, center: [String(c[0]), String(c[1])] };
}

/** 挂载饼图视图交互。返回解绑函数（组件卸载时调用）。 */
export function attachPieViewControl(
  chart: ECharts,
  opts?: { minRadius?: number; maxRadius?: number },
): () => void {
  const minR = opts?.minRadius ?? 8;
  const maxR = opts?.maxRadius ?? 90;
  const zr = chart.getZr();
  let dragging = false;
  let lastX = 0;
  let lastY = 0;

  /** 局部更新 series[0] 的 radius/center（merge 模式只改这两个字段，不重置用户缩放状态） */
  const write = (patch: { radius?: [string, string]; center?: [string, string] }) => {
    chart.setOption({ series: [{ ...patch }] as never });
  };

  const onMouseDown = (e: { offsetX: number; offsetY: number }) => {
    dragging = true;
    lastX = e.offsetX;
    lastY = e.offsetY;
  };

  const onMouseMove = (e: { offsetX: number; offsetY: number }) => {
    if (!dragging) return;
    const dx = e.offsetX - lastX;
    const dy = e.offsetY - lastY;
    lastX = e.offsetX;
    lastY = e.offsetY;
    const st = readSeries(chart);
    if (!st) return;
    const width = chart.getWidth() || 1;
    const height = chart.getHeight() || 1;
    const cx = pct(st.center[0]) + (dx / width) * 100;
    const cy = pct(st.center[1]) + (dy / height) * 100;
    write({ center: [clamp(cx, 0, 100) + "%", clamp(cy, 0, 100) + "%"] });
  };

  const onMouseUp = () => {
    dragging = false;
  };

  const onWheel = (e: { deltaY?: number; wheelDelta?: number }) => {
    const delta = e.deltaY ?? -(e.wheelDelta ?? 0);
    const st = readSeries(chart);
    if (!st) return;
    const factor = delta > 0 ? 0.92 : 1.08;
    const gap = pct(st.radius[1]) - pct(st.radius[0]);
    const r0 = clamp(pct(st.radius[0]) * factor, minR, maxR);
    // 保持内外半径比例（gap 不变）
    const finalR1 = clamp(r0 + gap, minR, maxR);
    write({ radius: [`${r0}%`, `${finalR1}%`] });
  };

  zr.on("mousedown", onMouseDown as never);
  zr.on("mousemove", onMouseMove as never);
  zr.on("mouseup", onMouseUp as never);
  zr.on("wheel", onWheel as never);

  return () => {
    zr.off("mousedown", onMouseDown as never);
    zr.off("mousemove", onMouseMove as never);
    zr.off("mouseup", onMouseUp as never);
    zr.off("wheel", onWheel as never);
  };
}

/** 判断模板是否为饼图系（无原生视图交互，需自定义） */
export function isPieTemplate(template: string): boolean {
  return template.startsWith("pie");
}

/** 饼图说明文案（显示在图下方） */
export const PIE_NOTE =
  "注：饼图可滚轮缩放（放大/缩小），按住鼠标拖动可移动饼图中心位置；数值超过 4 位采用科学计数法（如 1.6e8 = 1.6×10⁸）。";

/** 3D 图说明文案 */
export const THREE_D_NOTE =
  "注：3D 图可拖拽旋转视角、滚轮缩放、按住右键（或中键）拖动平移场景；数值超过 4 位采用科学计数法（如 1.6e8 = 1.6×10⁸）。";
