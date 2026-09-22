/** ChartRenderer — ECharts 图表渲染组件（financial-modeling skill 图表层，P3）。
 *
 * 解析对话流中的 ```chart-json 代码块：
 *   { template, title, option, data_table, chart_id }
 * 通过 chart-templates 注册表组装 option（只信任模板产出），
 * 渲染 ECharts + 「查看数据表」折叠区（§6 协议：图表必须有数据基础）。
 *
 * 容错：非法 JSON / 未知模板 → 显示原始 JSON + 错误提示。
 */

import { useLayoutEffect, useEffect, useMemo, useRef, useState } from "react";
import * as echarts from "echarts";
// echarts-gl（P6-②）：注册 3D 图表（scatter3D/bar3D）到 echarts 实例
import "echarts-gl";
import { ChevronDown, ChevronUp, Table as TableIcon, Download as DownloadIcon } from "lucide-react";
import { buildChartOption, resolveTemplate, CHART_VARIANT_NAMES } from "./chart-templates";
import { sciValue, zoom2D, hasZoom, AXIS_NOTE } from "./chart-templates/axis";
import { attachPieViewControl, isPieTemplate, PIE_NOTE, THREE_D_NOTE } from "./chart-templates/view-control";
import DownloadPanel from "./DownloadPanel";
import LoadingState from "./LoadingState";
import PythonImageLightbox from "./PythonImageLightbox";
import { finmodPyChart } from "../lib/api";

export interface ChartSpec {
  chart_id?: string;
  template: string;
  title?: string;
  option?: Record<string, unknown>;
  data_table?: Record<string, unknown>[];
}

function isChartSpec(v: unknown): v is ChartSpec {
  if (!v || typeof v !== "object") return false;
  const o = v as Record<string, unknown>;
  return typeof o.template === "string";
}

/** v6.9-2：走 Python(mplot3d) 生成 PNG 的 3D 模板（echarts-gl 无法复刻瀑布填充面） */
const PY3D_TEMPLATES = new Set(["waterfall3d", "bar3d", "scatter3d"]);

export default function ChartRenderer({ spec }: { spec: unknown }) {
  const elRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const detachPie = useRef<(() => void) | null>(null);
  const [showTable, setShowTable] = useState(false);
  const [showDownload, setShowDownload] = useState(false);
  const [error, setError] = useState("");
  // 图表渲染完成标志：完成前图表区显示像素网格加载动画「AI 正在绘制图表…」
  const [ready, setReady] = useState(false);

  const parsed = isChartSpec(spec) ? spec : null;
  const tplName = parsed?.template || "";
  const resolved = useMemo(() => resolveTemplate(tplName), [tplName]);
  // 模板/变体不存在 → 错误（模板即约束，不渲染未知模板）
  useEffect(() => {
    if (parsed && !resolved) {
      setError(`未知图表模板「${tplName}」；可用: ${CHART_VARIANT_NAMES.join(", ")}`);
    } else {
      setError("");
    }
  }, [parsed, tplName, resolved]);

  // 组装 option：优先模板 build（合法），无模板时回退 spec.option
  const option = useMemoChart(parsed);

  // P6-⑥：按图型决定说明行（2D 缩放提示 / 饼图自定义交互 / 3D 视角）
  const isPie = isPieTemplate(tplName);
  const is3dTemplate = tplName.startsWith("scatter3d") || tplName.startsWith("bar3d") || tplName.startsWith("surface3d");
  // v6.9-2：Python 3D 模板（echarts-gl 无法复刻瀑布填充面 → 由 mplot3d 画 PNG）
  const isPy3d = !!(resolved && PY3D_TEMPLATES.has(resolved.tpl.name));
  const showNote = isPie ? true : is3dTemplate ? true : hasZoom(option || {});
  const noteText = isPie ? PIE_NOTE : is3dTemplate ? THREE_D_NOTE : AXIS_NOTE;

  // 挂载 ECharts（useLayoutEffect：等容器有尺寸后再 init，避免 width=0 导致 painter 缺失）
  useLayoutEffect(() => {
    if (isPy3d) return; // Python 3D 图走 <img>，不实例化 ECharts
    if (!elRef.current || !option) return;
    let disposed = false;
    let ro: ResizeObserver | null = null;
    let rafId = 0;
    // 重新渲染（option 变化）→ 先回到加载态
    setReady(false);

    const tryInit = () => {
      if (disposed || !elRef.current || chartRef.current) return;
      const w = elRef.current.clientWidth;
      const h = elRef.current.clientHeight;
      if (w < 10 || h < 10) {
        // 容器无尺寸 → 等下一次观察
        return;
      }
      try {
        // preserveDrawingBuffer: 保留 WebGL 缓冲（3D 图 echarts-gl），供下载面板 canvas 合成截取
        const inst = echarts.init(elRef.current, null, { preserveDrawingBuffer: true } as never);
        chartRef.current = inst;
        // 调试：确认实例创建成功
        console.log("[ChartRenderer] echarts init ok", w, h, !!inst);
        console.log("[ChartRenderer] option keys:", option ? Object.keys(option) : "NULL", "| has series:", !!(option as Record<string, unknown>)?.series);
        inst.setOption(option as echarts.EChartsOption, true);
        inst.resize();
        // P6-⑥：饼图无 dataZoom → 挂自定义视图交互（滚轮缩放 radius + 拖拽平移 center）
        if (isPieTemplate(tplName)) {
          detachPie.current = attachPieViewControl(inst);
        }
        setError("");
        console.log("[ChartRenderer] setOption ok, canvas:", !!elRef.current.querySelector("canvas"));
        // 渲染完成：短暂延迟让首帧绘制出来，再隐藏加载动画（用 setTimeout 而非 rAF——headless/后台 tab rAF 可能不触发）
        setTimeout(() => { if (!disposed) setReady(true); }, 60);
      } catch (e) {
        console.error("[ChartRenderer] init/setOption failed:", e);
        setError(`图表渲染失败: ${(e as Error).message}`);
        setReady(true); // 出错时不再显示加载动画（显示错误信息）
      }
    };

    // 首次尝试
    tryInit();
    // 若容器尚未有尺寸，用 ResizeObserver 等待布局完成
    if (!chartRef.current) {
      ro = new ResizeObserver(() => tryInit());
      ro.observe(elRef.current);
    }

    const onResize = () => chartRef.current?.resize();
    window.addEventListener("resize", onResize);
    rafId = requestAnimationFrame(tryInit);

    return () => {
      disposed = true;
      cancelAnimationFrame(rafId);
      window.removeEventListener("resize", onResize);
      ro?.disconnect();
      detachPie.current?.();
      detachPie.current = null;
      chartRef.current?.dispose();
      chartRef.current = null;
    };
  }, [option, isPy3d]);

  if (!parsed) {
    return (
      <div className="my-2 rounded-lg border border-red-200 bg-red-50 p-3">
        <div className="mb-1 text-[11px] font-semibold text-red-600">图表解析失败（非法 chart-json）</div>
        <pre className="max-h-40 overflow-auto whitespace-pre-wrap font-mono text-[10.5px] text-red-500">
          {JSON.stringify(spec, null, 2)}
        </pre>
      </div>
    );
  }

  // v6.9-2：Python 3D 图（瀑布/柱状/散点）——由 mplot3d 生成 PNG，<img> 展示
  if (isPy3d && resolved) {
    return (
      <div className="my-3 overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-sm">
        {/* 标题栏（紧凑） */}
        <div className="flex items-center gap-1.5 border-b border-zinc-100 px-2.5 py-1">
          <span className="shrink-0 rounded bg-blue-50 px-1.5 py-0.5 text-[9.5px] font-semibold text-blue-600">
            {resolved.display}
          </span>
          <span className="min-w-0 flex-1 truncate text-[12px] font-semibold text-zinc-800">
            {parsed.title || resolved.tpl.zh || "图表"}
          </span>
          {parsed.data_table && parsed.data_table.length > 0 && (
            <button
              onClick={() => setShowTable((s) => !s)}
              className="flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-[10.5px] text-zinc-500 ring-1 ring-zinc-200 transition-colors hover:bg-zinc-50 hover:text-zinc-700"
            >
              <TableIcon size={11} />
              数据表 ({parsed.data_table.length})
              {showTable ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
            </button>
          )}
        </div>

        {/* Python 3D 图 + 加载态 */}
        <div className="relative">
          <Python3DImage template={resolved.tpl.name} spec={parsed} onError={setError} />
        </div>

        {/* 说明行 */}
        <div className="border-t border-zinc-100 bg-zinc-50/40 px-2.5 py-1 text-[10px] leading-relaxed text-zinc-400">
          由 Python(mplot3d) 生成 · 立体图为静态图片样例（点击放大/下载，不支持拖动缩放）
        </div>

        {/* 数据表折叠区（§6 协议：图表必须有数据基础） */}
        {showTable && parsed.data_table && parsed.data_table.length > 0 && (
          <div className="border-t border-zinc-100 bg-zinc-50/60 px-2 py-1.5">
            <div className="overflow-auto">
              <table className="w-full border-collapse text-[10.5px]">
                <thead>
                  <tr>
                    {Object.keys(parsed.data_table[0]).map((k) => (
                      <th key={k} className="border border-zinc-200 bg-zinc-100 px-1.5 py-0.5 text-left font-medium text-zinc-600">
                        {k}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {parsed.data_table.map((row, i) => (
                    <tr key={i} className={i % 2 ? "bg-zinc-50" : ""}>
                      {Object.values(row).map((v, j) => (
                        <td key={j} className="border border-zinc-200 px-1.5 py-0.5 text-zinc-600">
                          {String(v ?? "")}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="my-3 overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-sm">
      {/* 标题栏（紧凑） */}
      <div className="flex items-center gap-1.5 border-b border-zinc-100 px-2.5 py-1">
        <span className="shrink-0 rounded bg-blue-50 px-1.5 py-0.5 text-[9.5px] font-semibold text-blue-600">
          {resolved?.display || tplName}
        </span>
        <span className="min-w-0 flex-1 truncate text-[12px] font-semibold text-zinc-800">
          {parsed.title || resolved?.tpl.zh || "图表"}
        </span>
        {/* 下载按钮（P6-③）：2D 直接截，3D 先调角度再截 */}
        <button
          onClick={() => setShowDownload(true)}
          title="下载图表（SVG 矢量 / HTML 交互）"
          className="flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-[10.5px] text-zinc-500 ring-1 ring-zinc-200 transition-colors hover:bg-zinc-50 hover:text-blue-600"
        >
          <DownloadIcon size={11} />
          下载
        </button>
        {parsed.data_table && parsed.data_table.length > 0 && (
          <button
            onClick={() => setShowTable((s) => !s)}
            className="flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-[10.5px] text-zinc-500 ring-1 ring-zinc-200 transition-colors hover:bg-zinc-50 hover:text-zinc-700"
          >
            <TableIcon size={11} />
            数据表 ({parsed.data_table.length})
            {showTable ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
          </button>
        )}
      </div>

      {/* 图表区：ECharts 容器底层 + 像素网格加载动画覆盖层（渲染完成前显示） */}
      {error ? (
        <div className="p-3 text-[11px] text-red-500">{error}</div>
      ) : (
        <>
          <div className="relative h-72 w-full">
            {/* ECharts 画布（底层） */}
            <div ref={elRef} className="absolute inset-0" />
            {/* 加载动画覆盖层：告诉用户 AI 正在绘制；渲染完成后淡出 */
            /* pointer-events-none + opacity-0 + invisible：淡出后不遮挡图表交互、
               且文本彻底隐藏（读屏/文本选择不可见） */}
            <div
              className={`absolute inset-0 z-10 flex items-center justify-center bg-white transition-opacity duration-300 ${
                ready ? "invisible pointer-events-none opacity-0" : "opacity-100"
              }`}
              aria-hidden={ready}
            >
              <LoadingState label="AI 正在绘制图表…" />
            </div>
          </div>
          {/* P6-⑤⑥：按图型显示说明行（2D 滑块 / 饼图缩放平移 / 3D 视角） */}
          {showNote && (
            <div className="border-t border-zinc-100 bg-zinc-50/40 px-2.5 py-1 text-[10px] leading-relaxed text-zinc-400">
              {noteText}
            </div>
          )}
        </>
      )}

      {/* 数据表折叠区（§6 协议：图表必须有数据基础） */}
      {showTable && parsed.data_table && parsed.data_table.length > 0 && (
        <div className="border-t border-zinc-100 bg-zinc-50/60 px-2 py-1.5">
          <div className="overflow-auto">
            <table className="w-full border-collapse text-[10.5px]">
              <thead>
                <tr>
                  {Object.keys(parsed.data_table[0]).map((k) => (
                    <th key={k} className="border border-zinc-200 bg-zinc-100 px-1.5 py-0.5 text-left font-medium text-zinc-600">
                      {k}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {parsed.data_table.map((row, i) => (
                  <tr key={i} className={i % 2 ? "bg-zinc-50" : ""}>
                    {Object.values(row).map((v, j) => (
                      <td key={j} className="border border-zinc-200 px-1.5 py-0.5 text-zinc-600">
                        {String(v ?? "")}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {/* 下载面板（P6-③）：模态，3D 可旋转调角度 */}
      {showDownload && parsed && option && (
        <DownloadPanel
          spec={parsed}
          option={option}
          onClose={() => setShowDownload(false)}
        />
      )}
    </div>
  );
}

/** 2D 增强（P6-③ 轴优化 / v6.3 无滑块）：对后端 generate_chart 产出的 option 统一注入
 *  - value 轴 axisLabel.formatter = sciValue（≥1e4 科学计数法，避免长数字截断）
 *  - dataZoom = zoom2D（v6.3：仅 inside 无感交互——滚轮缩放 + 拖拽平移，
 *    无可见上下/左右拖动条，图表展示即最终版本）
 * 3D 图（含 grid3D）与饼图（无坐标轴，走自定义交互）跳过，避免 dataZoom 冲突。 */
function enhance2D(opt: Record<string, unknown>): Record<string, unknown> {
  const raw = opt.series;
  const series = Array.isArray(raw) ? raw : raw ? [raw as Record<string, unknown>] : [];
  const is3d = series.some((s) => String(s?.type).toLowerCase().includes("3d")) || !!opt.grid3D;
  const isPie = series.some((s) => String(s?.type).toLowerCase() === "pie");
  const out: Record<string, unknown> = { ...opt };

  const injectAxis = (a: unknown) => {
    if (Array.isArray(a)) {
      a.forEach(injectAxis);
      return;
    }
    if (a && typeof a === "object") {
      const ax = a as Record<string, unknown>;
      if (ax.type === "value") {
        const al =
          ax.axisLabel && typeof ax.axisLabel === "object"
            ? { ...(ax.axisLabel as Record<string, unknown>) }
            : {};
        if (!al.formatter) al.formatter = sciValue;
        ax.axisLabel = al;
      }
    }
  };
  injectAxis(out.xAxis);
  injectAxis(out.yAxis);

  if (Array.isArray(out.parallelAxis)) {
    (out.parallelAxis as Array<Record<string, unknown>>).forEach((a) => {
      const al =
        a.axisLabel && typeof a.axisLabel === "object"
          ? { ...(a.axisLabel as Record<string, unknown>) }
          : {};
      if (!al.formatter) al.formatter = sciValue;
      a.axisLabel = al;
    });
  }

  if (!is3d && !isPie && !out.dataZoom) {
    // v6.3：无 dataZoom → 注入 zoom2D（仅 inside，无可见滑块）
    out.dataZoom = zoom2D();
  }
  return out;
}

/** 组装图表 option：优先 spec.option（后端 generate_chart 已用模板组装出完整 ECharts option）；
 * 无 option 时回退模板 build（从 spec 的 option.data 提取数据）。
 * 用 useMemo 同步计算（避免 effect 链导致的时序问题）。 */
function useMemoChart(spec: ChartSpec | null) {
  return useMemo<Record<string, unknown> | null>(() => {
    if (!spec) return null;
    const opt = spec.option as Record<string, unknown> | undefined;
    // 1) 后端产物：spec.option 是完整 ECharts option（含 series 或 xAxis/yAxis/radar）→ 2D 增强
    if (opt && (Array.isArray(opt.series) || opt.xAxis || opt.radar)) {
      return enhance2D(opt);
    }
    // 2) 回退：模板 build（从 option.data / categories / series 提取数据）
    const data = (opt?.data as Record<string, unknown>) || {
      categories: (opt?.categories as string[]) || [],
      series: (opt?.series as unknown[]) || [],
    };
    return buildChartOption(spec.template, data as never, spec.title, undefined);
  }, [spec]);
}

/** v6.9-2：Python 3D 图 <img> 渲染。从 spec.option._py_data（后端 generate_chart
 * 对 3D 模板注入的原始数据）提取 → 调 /api/apps/finmod/py-chart → 显示 base64 PNG。 */
function Python3DImage({
  template,
  spec,
  onError,
}: {
  template: string;
  spec: ChartSpec;
  onError: (msg: string) => void;
}) {
  const [b64, setB64] = useState("");
  const [loading, setLoading] = useState(true);

  // 提取后端注入的原始 3D 数据（x/y 类别 + 三元组）
  const pyData = useMemo(() => {
    const opt = spec.option as Record<string, unknown> | undefined;
    const injected = opt?._py_data as Record<string, unknown> | undefined;
    if (injected) return injected;
    // 兜底：从 spec.option.data 提取（模板 build 路径）
    const d = (opt?.data as Record<string, unknown>) || {};
    return d as Record<string, unknown>;
  }, [spec]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setB64("");
    finmodPyChart(template, pyData)
      .then((r) => {
        if (!alive) return;
        if (r.success && r.b64) setB64(r.b64);
        else onError(r.note || "生成失败");
      })
      .catch((e) => {
        if (alive) onError((e as Error).message);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [template, pyData, onError]);

  if (loading && !b64) {
    return (
      <div className="flex h-72 w-full items-center justify-center">
        <LoadingState label="Python 3D 图生成中…" />
      </div>
    );
  }
  if (!b64) {
    return <div className="p-3 text-[11px] text-red-500">Python 3D 图生成失败</div>;
  }
  // 兜底：静态 PNG + 点击放大
  const fname = `${spec.title || template}.png`;
  return (
    <div className="flex h-72 w-full items-center justify-center overflow-hidden bg-white">
      <PythonImageLightbox b64={b64} filename={fname} alt={spec.title || template}>
        <img
          src={`data:image/png;base64,${b64}`}
          alt={spec.title || template}
          className="max-h-full w-auto max-w-full object-contain"
          onError={() => onError("Python 3D 图片加载失败")}
        />
      </PythonImageLightbox>
    </div>
  );
}
