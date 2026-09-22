/** chartSvg — P6 报告交付：离屏 echarts(svg) 实例 → SVG 字符串。
 *
 * 复用 DownloadPanel.saveSvg 的核心逻辑（离屏重建 renderer:svg 实例 →
 * 隐藏 dataZoom slider → renderToSVGString），供步骤 7 批量图表落盘调用。
 * - 2D：支持（文本/形状全矢量）
 * - 3D：echarts-gl 基于 WebGL canvas，无法矢量导出 → 返回 null（前端降级跳过/PNG）
 */

import * as echarts from "echarts";
import "echarts-gl";

/** 等待一帧重绘（setTimeout 而非 rAF——headless/后台 tab 下 rAF 可能不触发） */
function nextFrame(): Promise<void> {
  return new Promise((r) => setTimeout(r, 60));
}

/** 对实例设置 dataZoom slider 可见性（导出净化：SVG 不含滑块条） */
async function hideSliders(inst: echarts.ECharts): Promise<void> {
  const full = inst.getOption() as { dataZoom?: Array<Record<string, unknown>> };
  const dz = full.dataZoom;
  if (!Array.isArray(dz) || !dz.some((d) => d.type === "slider")) return;
  inst.setOption({ dataZoom: dz.map((d) => (d.type === "slider" ? { show: false } : {})) });
  await nextFrame();
  await nextFrame();
}

/** 是否 3D 模板（WebGL，无法 SVG 导出） */
export function is3DTemplate(template: string): boolean {
  return String(template).toLowerCase().includes("3d") ||
    ["scatter3d", "bar3d", "surface", "line3d"].some((k) => String(template).toLowerCase().includes(k));
}

/** 离屏渲染 option → SVG 字符串（2D）。3D 或失败返回 null。 */
export async function renderOptionToSvg(
  option: Record<string, unknown>,
  opts: { width?: number; height?: number } = {},
): Promise<string | null> {
  const series = ((option.series as Array<Record<string, unknown>>) || []);
  if (series.some((s) => String(s.type).toLowerCase().includes("3d"))) {
    return null; // 3D：WebGL 无法 SVG 导出
  }
  const host = document.createElement("div");
  host.style.cssText =
    `position:absolute;left:-9999px;top:0;width:${opts.width || 900}px;height:${opts.height || 520}px;background:#fff`;
  document.body.appendChild(host);
  let svg = "";
  try {
    const inst = echarts.init(host, null, { renderer: "svg" } as never);
    try {
      inst.setOption(option as echarts.EChartsOption, true);
      inst.resize();
      await nextFrame();
      await nextFrame();
      await hideSliders(inst); // 关键：隐藏 dataZoom slider（否则滑块条会画进 SVG）
      svg = inst.renderToSVGString();
    } finally {
      inst.dispose();
    }
  } catch {
    svg = "";
  } finally {
    host.remove();
  }
  return svg.trim() ? svg : null;
}

/** 文件名净化（去掉 Windows 非法字符） */
export function sanitizeFileName(name: string): string {
  return name.replace(/[\\/:*?"<>|]/g, "_").trim() || "chart";
}

/** 离屏渲染 option → base64 PNG（3D 图降级截图：canvas renderer + getDataURL）。
 *  2D 也支持（兜底）；失败返回 null。 */
export async function renderOptionToPng(
  option: Record<string, unknown>,
  opts: { width?: number; height?: number } = {},
): Promise<string | null> {
  const host = document.createElement("div");
  host.style.cssText =
    `position:absolute;left:-9999px;top:0;width:${opts.width || 900}px;height:${opts.height || 520}px;background:#fff`;
  document.body.appendChild(host);
  try {
    const inst = echarts.init(host, null, { renderer: "canvas" } as never);
    try {
      inst.setOption(option as echarts.EChartsOption, true);
      inst.resize();
      await nextFrame();
      await nextFrame();
      await hideSliders(inst);
      const url = inst.getDataURL({
        type: "png",
        pixelRatio: 2,
        backgroundColor: "#fff",
      } as never);
      const b64 = String(url).split(",")[1] || "";
      return b64 || null;
    } finally {
      inst.dispose();
    }
  } catch {
    return null;
  } finally {
    host.remove();
  }
}
