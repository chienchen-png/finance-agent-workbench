/** ChartLibrary — 财务建模「图表库」（P1 元数据层，2026-08-21；v6.8 面向用户可视化）。
 *
 * 24 图表模板按复杂度档位 L1/L2/L3 分档 tab 浏览；每卡点击展开：
 *   - **模板预览**：该模板最终效果（示例数据，真实 ECharts 渲染，变体可切换所见即所得）
 *   - **示例数据**：示例数据表（sampleDataToRows 由 sampleDataFor 同源转换）
 *   - **选型参考**（折叠，AI/进阶）：典型场景 / 选型建议 / 注意事项 / 完整文档
 * 面向用户直观选择为主：只展示「本模板最终长什么样」，不区分官方/自研（v6.8 移除官方图）。
 *
 * 与需求文档 §5.2「ChartLibrary 图表库抽屉」对齐：L1/L2/L3 分档 tab + 模板卡；
 * 勾选功能为 P4 图表配置预留（P1 只做浏览展开）。
 */

import { useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronRight, AlertTriangle, FileText, CheckSquare, Square, Wrench } from "lucide-react";
import type { FinmodChartDetail, FinmodChartMeta } from "../lib/api";
import { finmodChartDetail } from "../lib/api";
import MarkdownBlock from "./MarkdownBlock";
import LoadingState from "./LoadingState";
import ChartPreview, { sampleDataToRows } from "./ChartPreview";
import { resolveTemplate } from "./chart-templates";

/** 档位配色（L1 简单 → 绿，L2 中等 → 蓝，L3 复杂 → 紫） */
const LEVEL_STYLE: Record<string, { tab: string; badge: string }> = {
  L1: {
    tab: "data-[active=true]:bg-emerald-600 data-[active=true]:text-white",
    badge: "bg-emerald-50 text-emerald-700 border-emerald-200",
  },
  L2: {
    tab: "data-[active=true]:bg-blue-600 data-[active=true]:text-white",
    badge: "bg-blue-50 text-blue-700 border-blue-200",
  },
  L3: {
    tab: "data-[active=true]:bg-violet-600 data-[active=true]:text-white",
    badge: "bg-violet-50 text-violet-700 border-violet-200",
  },
};

interface Props {
  /** meta 返回的 chart_levels（L1/L2/L3 分组） */
  chartLevels: { key: string; label: string; charts: FinmodChartMeta[] }[];
  /** 是否空数据（meta 加载失败/未就绪） */
  empty?: boolean;
  /** 勾选模式（P4：步骤 5 微观勾选启用） */
  selectable?: boolean;
  /** 已选模板集（variant 名） */
  selectedSet?: Set<string>;
  /** 勾选回调（template, name, level） */
  onSelect?: (template: string, name: string, level: string) => void;
}

export default function ChartLibrary({ chartLevels, empty, selectable, selectedSet, onSelect }: Props) {
  const [activeLevel, setActiveLevel] = useState<string>("L2");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [details, setDetails] = useState<Record<string, FinmodChartDetail>>({});
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [showRaw, setShowRaw] = useState<Record<string, boolean>>({});
  // v6.3：每模板当前预览变体（完整模板名，如 line-smooth）；默认主变体
  const [variantId, setVariantId] = useState<Record<string, string>>({});
  const loadingRef = useRef<Record<string, boolean>>({});

  const activeGroup = useMemo(
    () => chartLevels.find((g) => g.key === activeLevel),
    [chartLevels, activeLevel],
  );

  /** 变体中文名（前端模板注册表解析；未知则显示原名） */
  function variantLabel(tpl: string): string {
    const r = resolveTemplate(tpl);
    if (r) return r.variant.zh;
    return tpl;
  }

  async function loadDetail(id: string) {
    if (details[id] || loadingRef.current[id]) return;
    loadingRef.current[id] = true;
    setLoadingId(id);
    try {
      const d = await finmodChartDetail(id);
      setDetails((prev) => ({ ...prev, [id]: d }));
    } catch (e) {
      setErrors((prev) => ({ ...prev, [id]: (e as Error).message || "加载失败" }));
    } finally {
      loadingRef.current[id] = false;
      setLoadingId(null);
    }
  }

  function toggle(id: string) {
    if (expandedId === id) {
      setExpandedId(null);
    } else {
      setExpandedId(id);
      void loadDetail(id);
    }
  }

  if (empty || !chartLevels.length) {
    return (
      <div className="rounded-lg border border-dashed border-zinc-300 bg-zinc-50 px-4 py-8 text-center text-[13px] text-zinc-400">
        图表模板目录暂不可用，请稍后重试
      </div>
    );
  }

  return (
    <div>
      {/* 档位 tab */}
      <div className="mb-3 flex flex-wrap gap-1.5">
        {chartLevels.map((g) => {
          const st = LEVEL_STYLE[g.key] || LEVEL_STYLE.L2;
          return (
            <button
              key={g.key}
              data-active={activeLevel === g.key}
              onClick={() => setActiveLevel(g.key)}
              className={`rounded-full px-3 py-1 text-[12px] font-medium transition-colors ${
                activeLevel === g.key
                  ? st.tab
                  : "border border-zinc-200 bg-white text-zinc-500 hover:bg-zinc-100"
              }`}
            >
              {g.key} {g.label}
              <span className="ml-1 opacity-70">{g.charts.length}</span>
            </button>
          );
        })}
      </div>

      {/* 模板卡列表 */}
      <div className="space-y-2">
        {(activeGroup?.charts || []).map((chart) => {
          const st = LEVEL_STYLE[chart.level] || LEVEL_STYLE.L2;
          const expanded = expandedId === chart.id;
          const detail = details[chart.id];
          const loading = loadingId === chart.id;
          const err = errors[chart.id];
          const variants = chart.variants || [];
          return (
            <div
              key={chart.id}
              className={`rounded-lg border transition-colors ${
                expanded ? "border-blue-300 bg-white shadow-sm" : "border-zinc-200 bg-white hover:border-zinc-300"
              }`}
            >
              <div className="flex items-center px-3">
                {selectable && onSelect && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      // v6.12：勾选携带「当前预览的具体变体」（用户在前面看到哪个变体就选哪个）
                      onSelect(variantId[chart.id] || chart.id, chart.name, chart.level);
                    }}
                    title={selectedSet?.has(chart.id) ? "取消选择" : "加入图表清单"}
                    className="mr-1 shrink-0 text-blue-600 hover:text-blue-500"
                  >
                    {selectedSet?.has(chart.id)
                      ? <CheckSquare size={17} />
                      : <Square size={17} className="text-zinc-300" />}
                  </button>
                )}
                <button
                  onClick={() => toggle(chart.id)}
                  className="flex min-w-0 flex-1 items-center gap-2.5 py-2.5 text-left"
                >
                  <span
                    className={`inline-flex shrink-0 items-center rounded-md border px-1.5 py-0.5 text-[11px] font-bold ${st.badge}`}
                  >
                    {chart.level}
                  </span>
                  <span className="flex-1 truncate text-[13.5px] font-medium text-zinc-800">
                    {chart.name}
                    <span className="ml-1.5 font-mono text-[11px] text-zinc-400">{chart.id}</span>
                  </span>
                  {variants.length > 0 && (
                    <span className="hidden shrink-0 max-w-[45%] items-center gap-1 overflow-hidden sm:flex">
                      {variants.slice(0, 3).map((v) => (
                        <span key={v} className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-[10px] text-zinc-500">
                          {v}
                        </span>
                      ))}
                      {variants.length > 3 && (
                        <span className="text-[10px] text-zinc-400">+{variants.length - 3}</span>
                      )}
                    </span>
                  )}
                  <span className="shrink-0 text-zinc-400">
                    {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                  </span>
                </button>
              </div>

              {expanded && (
                <div className="border-t border-zinc-100 px-4 py-3">
                  {loading && (
                    <div className="flex items-center gap-2 py-4 text-[13px] text-zinc-400">
                      <LoadingState label="正在加载模板详情…" />
                    </div>
                  )}
                  {err && (
                    <div className="flex items-center gap-2 rounded-md bg-red-50 px-3 py-2 text-[13px] text-red-600">
                      <AlertTriangle size={14} />
                      {err}
                    </div>
                  )}
                  {!loading && !err && (
                    <div>
                      {/* 一句话用途（无 markdown 符号） */}
                      {detail?.purpose && (
                        <div className="mb-2 text-[12.5px] leading-relaxed text-zinc-500">
                          {detail.purpose.replace(/[#*`>\[\]()]+/g, "").trim()}
                        </div>
                      )}
                      {/* 变体切换：点击即换预览图与示例数据 */}
                      {variants.length > 1 && (
                        <div className="mb-2 flex flex-wrap items-center gap-1">
                          <span className="mr-0.5 text-[11px] font-medium text-zinc-400">变体：</span>
                          {variants.map((v) => {
                            const cur = variantId[chart.id] || chart.id;
                            const active = v === cur;
                            return (
                              <button
                                key={v}
                                onClick={() => setVariantId((prev) => ({ ...prev, [chart.id]: v }))}
                                className={`rounded-full px-2 py-0.5 text-[11px] transition-colors ${
                                  active
                                    ? "bg-blue-600 text-white"
                                    : "border border-zinc-200 bg-white text-zinc-500 hover:bg-zinc-100"
                                }`}
                              >
                                {variantLabel(v)}
                              </button>
                            );
                          })}
                        </div>
                      )}
                      {/* 主区：模板预览全宽大图（v6.8 仅展示本模板最终效果）+ 示例数据表下方 */}
                      <div className="space-y-3">
                        <div className="min-w-0">
                          <div className="mb-1 flex items-center justify-between">
                            <span className="flex items-center gap-1.5 text-[11px] font-semibold text-zinc-500">
                              <Wrench size={12} className="text-blue-500" />
                              模板预览
                              {variants.length > 1 && (
                                <span className="rounded bg-blue-50 px-1.5 py-0.5 font-mono text-[10px] text-blue-600">
                                  {variantLabel(variantId[chart.id] || chart.id)}
                                </span>
                              )}
                            </span>
                            <span className="text-[10px] text-zinc-300">此即最终图表效果（示例数据）</span>
                          </div>
                          <ChartPreview template={variantId[chart.id] || chart.id} height={320} />
                        </div>
                        <div className="min-w-0">
                          <div className="mb-1 text-[11px] font-semibold text-zinc-400">示例数据</div>
                          <SampleDataTable template={variantId[chart.id] || chart.id} />
                        </div>
                      </div>
                      {/* 选型参考（折叠，AI/进阶指导；面向用户默认不展开文字内容） */}
                      {detail && (
                        <details className="mt-2 rounded-md border border-zinc-200 bg-zinc-50/60">
                          <summary className="cursor-pointer select-none px-3 py-2 text-[12px] font-medium text-zinc-500 hover:text-blue-600">
                            选型参考 · 场景 / 建议 / 注意事项
                          </summary>
                          <div className="space-y-3 border-t border-zinc-200 px-3 py-3 text-[12.5px] leading-relaxed text-zinc-600">
                            {detail.scenarios.length > 0 && (
                              <div>
                                <div className="mb-1 text-[11px] font-semibold text-zinc-400">典型场景</div>
                                <ul className="list-disc space-y-0.5 pl-5">
                                  {detail.scenarios.map((s, i) => <li key={i}>{s}</li>)}
                                </ul>
                              </div>
                            )}
                            {detail.selection.length > 0 && (
                              <div>
                                <div className="mb-1 text-[11px] font-semibold text-zinc-400">选型建议</div>
                                <ul className="list-disc space-y-0.5 pl-5">
                                  {detail.selection.map((s, i) => <li key={i}>{s}</li>)}
                                </ul>
                              </div>
                            )}
                            {detail.notes.length > 0 && (
                              <div>
                                <div className="mb-1 text-[11px] font-semibold text-zinc-400">注意事项</div>
                                <ul className="list-disc space-y-0.5 pl-5">
                                  {detail.notes.map((s, i) => <li key={i}>{s}</li>)}
                                </ul>
                              </div>
                            )}
                            <button
                              onClick={() => setShowRaw((prev) => ({ ...prev, [chart.id]: !prev[chart.id] }))}
                              className="flex items-center gap-1.5 rounded-md px-1 py-0.5 text-[11.5px] text-blue-600 hover:bg-blue-50"
                            >
                              <FileText size={12} />
                              {showRaw[chart.id] ? "收起完整文档" : "查看完整文档"}
                            </button>
                            {showRaw[chart.id] && (
                              <div className="rounded-md border border-zinc-200 bg-white p-3">
                                <MarkdownBlock text={detail.raw} />
                              </div>
                            )}
                          </div>
                        </details>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** 示例数据表（v6.3：图表库展开时展示，与示例图同源 sampleDataFor）。
 * 全宽表格 + 内部滚动（数据多时不撑破卡片）。 */
function SampleDataTable({ template }: { template: string }) {
  const { columns, rows } = useMemo(() => sampleDataToRows(template), [template]);
  return (
    <div className="max-h-60 overflow-auto rounded-md border border-zinc-200 bg-white">
      <table className="w-full border-collapse text-[12px]">
        <thead className="sticky top-0 bg-zinc-50">
          <tr>
            {columns.map((c) => (
              <th key={c} className="border-b border-zinc-200 px-2 py-1 text-left font-medium text-zinc-500">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className={i % 2 ? "bg-zinc-50/60" : ""}>
              {r.map((v, j) => (
                <td key={j} className="border-b border-zinc-100 px-2 py-1 text-zinc-600 last:border-b-0">
                  {v}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
