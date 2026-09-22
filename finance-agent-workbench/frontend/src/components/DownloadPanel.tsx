/** DownloadPanel — 图表下载面板（P6-③ / 2026-08-21 改造）
 *
 * 模态面板：复用图表 option 重建实例。
 *  - 2D 图：静态预览 + 保存 SVG（矢量，文本可编辑；renderer:svg 离屏重建）
 *  - 3D 图：可拖拽旋转/滚轮缩放预览 → 调好角度 → 保存 HTML（echarts-gl 为
 *    WebGL 渲染，无法矢量导出 SVG；仅保留交互式 HTML）
 *  - 通用：保存独立 HTML（chart-json + 内嵌 echarts/echarts-gl，保留交互）
 *
 * 注：已移除 PNG 截图（位图不可编辑、放大模糊）；导出仅 SVG + HTML 两种。
 */

import { useLayoutEffect, useRef, useState } from "react";
import * as echarts from "echarts";
import "echarts-gl";
import { X, Download, FileCode2, FileDown } from "lucide-react";
import { hasZoom, AXIS_NOTE } from "./chart-templates/axis";
import { attachPieViewControl, isPieTemplate, PIE_NOTE, THREE_D_NOTE } from "./chart-templates/view-control";
import type { ChartSpec } from "./ChartRenderer";

interface Props {
  spec: ChartSpec;
  option: Record<string, unknown>;
  onClose: () => void;
}

function is3D(opt: Record<string, unknown>): boolean {
  const s = (opt.series as Array<Record<string, unknown>>) || [];
  return s.some((x) => String(x.type).toLowerCase().includes("3d"));
}

/** 触发浏览器下载 */
function triggerDownload(dataUrl: string, filename: string) {
  const a = document.createElement("a");
  a.href = dataUrl;
  a.download = filename;
  a.click();
}

/** 生成独立 HTML（内嵌 echarts + echarts-gl，保留交互/3D 旋转） */
function buildStandaloneHtml(option: Record<string, unknown>, title: string): string {
  const optionJson = JSON.stringify(option);
  const note = hasZoom(option) ? AXIS_NOTE : "";
  // 注：运行时从 dist 取 echarts 脚本太复杂，这里用 CDN 引用 + 提示（离线环境用户可替换为本地）
  return `<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${title}</title>
<style>
  html,body{height:100%;margin:0;background:#fff;font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
  #chart{width:100%;height:calc(100% - 28px)}
  #note{height:28px;line-height:28px;padding:0 12px;font-size:11px;color:#71717a;background:#fafafa;border-top:1px solid #f0f0f0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
</style>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.6.0/dist/echarts.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/echarts-gl@2.1.0/dist/echarts-gl.min.js"></script>
</head>
<body>
<div id="chart"></div>
<div id="note">${note}</div>
<script>
var chart = echarts.init(document.getElementById('chart'));
chart.setOption(${optionJson});
window.addEventListener('resize', function(){chart.resize();});
</script>
</body>
</html>`;
}

export default function DownloadPanel({ spec, option, onClose }: Props) {
  const boxRef = useRef<HTMLDivElement>(null);
  const instRef = useRef<echarts.ECharts | null>(null);
  const detachPie = useRef<(() => void) | null>(null);
  const [err, setErr] = useState("");
  const [downloaded, setDownloaded] = useState("");
  const is3d = is3D(option);
  const isPie = isPieTemplate(spec.template);
  const is3dTemplate = spec.template.startsWith("scatter3d") || spec.template.startsWith("bar3d") || spec.template.startsWith("surface3d");
  // 说明行：饼图 → PIE_NOTE；3D → THREE_D_NOTE；2D（有 dataZoom）→ AXIS_NOTE
  const showNote = isPie ? true : is3dTemplate ? true : hasZoom(option);
  const noteText = isPie ? PIE_NOTE : is3dTemplate ? THREE_D_NOTE : AXIS_NOTE;

  // 在面板容器中重建图表实例（独立实例，可继续旋转）
  useLayoutEffect(() => {
    if (!boxRef.current) return;
    let disposed = false;
    let ro: ResizeObserver | null = null;
    let rafId = 0;

    const tryInit = () => {
      if (disposed || !boxRef.current || instRef.current) return;
      const w = boxRef.current.clientWidth;
      const h = boxRef.current.clientHeight;
      if (w < 10 || h < 10) return;
      try {
        // preserveDrawingBuffer: 保留 WebGL 缓冲，供 getDataURL/canvas 合成截取（3D 图必需）
        const inst = echarts.init(boxRef.current, null, { preserveDrawingBuffer: true } as never);
        instRef.current = inst;
        inst.setOption(option as echarts.EChartsOption, true);
        inst.resize();
        // P6-⑥：饼图挂自定义视图交互（滚轮缩放 + 拖拽平移中心），下载前可调位置/大小
        if (isPieTemplate(spec.template)) {
          detachPie.current = attachPieViewControl(inst);
        }
        setErr("");
      } catch (e) {
        setErr(`预览渲染失败: ${(e as Error).message}`);
      }
    };

    tryInit();
    if (!instRef.current) {
      ro = new ResizeObserver(() => tryInit());
      ro.observe(boxRef.current);
    }
    rafId = requestAnimationFrame(tryInit);
    const onResize = () => instRef.current?.resize();
    window.addEventListener("resize", onResize);

    return () => {
      disposed = true;
      cancelAnimationFrame(rafId);
      window.removeEventListener("resize", onResize);
      ro?.disconnect();
      detachPie.current?.();
      detachPie.current = null;
      instRef.current?.dispose();
      instRef.current = null;
    };
  }, [option]);

  /** 等待一帧重绘（用 setTimeout 而非 rAF——headless/后台 tab 下 rAF 可能不触发） */
  const nextFrame = () => new Promise<void>((r) => setTimeout(r, 60));

  /** 对指定实例设置 slider dataZoom 可见性（纯函数：预览/离屏 SVG 实例共用）。
   *  导出净化：SVG 不含两侧滑块条（仅 2D 图有 slider；离屏实例无交互，直接隐藏） */
  const applySlidersVisible = async (inst: echarts.ECharts | null, visible: boolean) => {
    if (!inst) return;
    const full = inst.getOption() as { dataZoom?: Array<Record<string, unknown>> };
    const dz = full.dataZoom;
    if (!Array.isArray(dz) || !dz.some((d) => d.type === "slider")) return;
    inst.setOption({
      dataZoom: dz.map((d) => (d.type === "slider" ? { show: visible } : {})),
    });
    await nextFrame();
    await nextFrame();
  };

  /** 临时隐藏/恢复预览实例 slider（预览区继续可用） */
  const setSlidersVisible = (visible: boolean) => applySlidersVisible(instRef.current, visible);

  /** 保存 SVG（矢量）：离屏重建 renderer:svg 实例 → renderToSVGString
   *  - 2D：支持（文本/形状全矢量，论文/报告可无损缩放、可编辑）
   *  - 3D：echarts-gl 基于 WebGL canvas，无法矢量导出 → 提示改用 HTML */
  const saveSvg = async () => {
    if (is3d) {
      setErr("3D 图基于 WebGL 渲染，不支持矢量 SVG 导出；请用「保存 HTML」保留交互。");
      return;
    }
    if (!instRef.current) {
      setErr("图表未就绪，请稍候");
      return;
    }
    try {
      // 净化：导出前临时隐藏预览实例的 slider 滑块条
      await setSlidersVisible(false);
      try {
        // 离屏 SVG 实例（不干扰预览实例的旋转/缩放状态）
        const host = document.createElement("div");
        host.style.cssText = "position:absolute;left:-9999px;top:0;width:900px;height:520px;background:#fff";
        document.body.appendChild(host);
        let svg = "";
        try {
          const inst = echarts.init(host, null, { renderer: "svg" } as never);
          inst.setOption(option as echarts.EChartsOption, true);
          inst.resize();
          await nextFrame();
          await nextFrame();
          // 关键：隐藏离屏 SVG 实例的 dataZoom slider（否则滑块条会画进 SVG）
          await applySlidersVisible(inst, false);
          svg = inst.renderToSVGString();
          inst.dispose();
        } finally {
          host.remove();
        }
        if (!svg.trim()) throw new Error("SVG 为空");
        const blob = new Blob([svg], { type: "image/svg+xml;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const name = (spec.title || spec.template || "chart").replace(/[\\/:*?"<>|]/g, "_");
        triggerDownload(url, `${name}.svg`);
        URL.revokeObjectURL(url);
        setDownloaded("SVG 已保存 ✓（矢量，文本可编辑，可无损缩放）");
        setErr("");
      } finally {
        // 恢复滑块显示（预览继续可用）
        await setSlidersVisible(true);
      }
    } catch (e) {
      setErr(`SVG 保存失败: ${(e as Error).message}`);
    }
  };

  const saveHtml = () => {
    try {
      const html = buildStandaloneHtml(option, spec.title || spec.template || "chart");
      const blob = new Blob([html], { type: "text/html;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const name = (spec.title || spec.template || "chart").replace(/[\\/:*?"<>|]/g, "_");
      triggerDownload(url, `${name}.html`);
      URL.revokeObjectURL(url);
      setDownloaded("HTML 已保存 ✓（双击打开保留交互/3D 旋转）");
      setErr("");
    } catch (e) {
      setErr(`HTML 保存失败: ${(e as Error).message}`);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="w-full max-w-2xl overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 头部 */}
        <div className="flex items-center gap-2 border-b border-zinc-100 px-4 py-2.5">
          <Download size={14} className="text-blue-600" />
          <span className="text-[13px] font-semibold text-zinc-800">下载图表</span>
          <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] text-zinc-500">
            {spec.template}
          </span>
          <span className="min-w-0 flex-1 truncate text-[11.5px] text-zinc-500">{spec.title}</span>
          <button onClick={onClose} className="flex h-6 w-6 items-center justify-center rounded-md text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600">
            <X size={14} />
          </button>
        </div>

        {/* 预览区 */}
        <div className="p-4">
          <div className="mb-1.5 flex items-center justify-between">
            <span className="text-[11px] text-zinc-500">
              {is3d ? "3D 图：可拖拽旋转 / 滚轮缩放，调好角度后再保存" : "2D 预览（所见即所得）"}
            </span>
            {is3d && (
              <span className="rounded-full bg-amber-50 px-1.5 py-0.5 text-[9.5px] text-amber-700 ring-1 ring-amber-200">
                可旋转
              </span>
            )}
          </div>
          {err ? (
            <div className="flex h-72 items-center justify-center text-[11px] text-red-500">{err}</div>
          ) : (
            <div ref={boxRef} className="h-72 w-full rounded-lg border border-zinc-200 bg-white" />
          )}
          {/* P6-⑤：科学计数法 + 滑块操作说明（2D 图显示在预览下方小字） */}
          {showNote && !err && (
            <div className="mt-1.5 rounded border border-zinc-100 bg-zinc-50/40 px-2.5 py-1 text-[10px] leading-relaxed text-zinc-400">
              {noteText}
            </div>
          )}
        </div>

        {/* 底部操作 */}
        <div className="flex items-center justify-between border-t border-zinc-100 bg-zinc-50/60 px-4 py-2.5">
          <span className="text-[10.5px] text-emerald-600">{downloaded}</span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => void saveSvg()}
              disabled={is3d}
              title={is3d ? "3D 图基于 WebGL，无法矢量导出" : "保存矢量 SVG（文本可编辑）"}
              className={`flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-[12px] font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-zinc-300`}
            >
              <FileDown size={13} />
              保存 SVG
            </button>
            <button
              onClick={saveHtml}
              className="flex items-center gap-1.5 rounded-lg bg-zinc-800 px-3 py-1.5 text-[12px] font-medium text-white transition-colors hover:bg-zinc-900"
            >
              <FileCode2 size={13} />
              保存 HTML
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
