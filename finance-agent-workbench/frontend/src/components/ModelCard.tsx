/** ModelCard — 财务建模「模型卡」（P1 元数据层，2026-08-21）。

 * 卡片展示模型元信息（编号/名称/分类），点击展开加载并渲染详情：
 * 目的 / 关键公式（KaTeX $$）/ 变量含义表 / 适用场景 / 注意事项，
 * 底部可折叠「查看完整文档」（raw markdown）。
 *
 * 与需求文档 §5.2「ModelCard 模型卡」对齐：点击展开详情（来自 references）；
 * A-G 分类分组由外层（FinModAppPage）负责；勾选状态角标为 P3 预留。
 */

import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronRight, AlertTriangle, FileText, CheckSquare, Square } from "lucide-react";
import type { FinmodModelMeta, FinmodModelDetail } from "../lib/api";
import { finmodModelDetail } from "../lib/api";
import MarkdownBlock, { FormulaList } from "./MarkdownBlock";
import LoadingState from "./LoadingState";

const CATEGORY_COLORS: Record<string, string> = {
  A: "bg-blue-50 text-blue-700 border-blue-200",
  B: "bg-sky-50 text-sky-700 border-sky-200",
  C: "bg-emerald-50 text-emerald-700 border-emerald-200",
  D: "bg-violet-50 text-violet-700 border-violet-200",
  E: "bg-amber-50 text-amber-700 border-amber-200",
  F: "bg-rose-50 text-rose-700 border-rose-200",
  G: "bg-teal-50 text-teal-700 border-teal-200",
};

interface Props {
  meta: FinmodModelMeta;
  expanded: boolean;
  onToggle: () => void;
  /** 已选状态（P2 建模方向勾选） */
  selected?: boolean;
  /** 勾选回调（P2：步骤 3 模型库补充勾选；不传则无勾选框） */
  onSelect?: () => void;
}

export default function ModelCard({ meta, expanded, onToggle, selected, onSelect }: Props) {
  const [detail, setDetail] = useState<FinmodModelDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [showRaw, setShowRaw] = useState(false);
  // 已加载标记：避免重新展开时重复请求（loading 不进依赖数组，
  // 否则 effect 重跑时 cleanup 置 cancelled，fetch 结果被丢弃）
  const loadedRef = useRef(false);

  // 展开时按需加载详情（一次加载后缓存于组件 state）
  useEffect(() => {
    if (!expanded || detail || loadedRef.current) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    finmodModelDetail(meta.id)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((e) => {
        if (!cancelled) setError((e as Error).message || "详情加载失败");
      })
      .finally(() => {
        loadedRef.current = true;
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [expanded, meta.id, detail]);

  const catColor = CATEGORY_COLORS[meta.category] || "bg-zinc-50 text-zinc-700 border-zinc-200";

  return (
    <div
      className={`rounded-lg border transition-colors ${
        expanded ? "border-blue-300 bg-white shadow-sm" : "border-zinc-200 bg-white hover:border-zinc-300"
      }`}
    >
      {/* 卡片头部（点击展开/收起；有勾选回调时头部左侧为勾选框） */}
      <div className="flex items-center gap-2.5 px-3 py-2.5">
        {onSelect && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onSelect();
            }}
            title={selected ? "取消选择" : "选择此模型"}
            className="shrink-0 text-blue-600 hover:text-blue-500"
          >
            {selected ? <CheckSquare size={17} /> : <Square size={17} className="text-zinc-300" />}
          </button>
        )}
        <button onClick={onToggle} className="flex min-w-0 flex-1 items-center gap-2.5 text-left">
          <span
            className={`inline-flex h-7 min-w-7 shrink-0 items-center justify-center rounded-md border px-1.5 text-[12px] font-bold ${catColor}`}
          >
            {meta.code}
          </span>
          <span className="flex-1 truncate text-[13.5px] font-medium text-zinc-800">{meta.name}</span>
          {selected && (
            <span className="shrink-0 rounded-full bg-blue-600 px-2 py-0.5 text-[10px] font-medium text-white">
              已选
            </span>
          )}
          <span className="shrink-0 text-zinc-400">
            {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
          </span>
        </button>
      </div>

      {/* 展开详情 */}
      {expanded && (
        <div className="border-t border-zinc-100 px-4 py-3">
          {loading && (
            <div className="flex items-center gap-2 py-4 text-[13px] text-zinc-400">
              <LoadingState label="正在加载模型详情…" />
            </div>
          )}
          {error && (
            <div className="flex items-center gap-2 rounded-md bg-red-50 px-3 py-2 text-[13px] text-red-600">
              <AlertTriangle size={14} />
              {error}
            </div>
          )}
          {detail && (
            <div className="space-y-3 text-[13px] leading-relaxed text-zinc-700">
              {/* 目的 */}
              {detail.purpose && (
                <div>
                  <div className="mb-1 text-[12px] font-semibold text-zinc-500">目的</div>
                  <MarkdownBlock text={detail.purpose} />
                </div>
              )}
              {/* 关键公式（KaTeX） */}
              {detail.formulas.length > 0 && (
                <div>
                  <div className="mb-1 text-[12px] font-semibold text-zinc-500">关键公式</div>
                  <FormulaList formulas={detail.formulas} />
                </div>
              )}
              {/* 变量含义表 */}
              {detail.variables.length > 0 && (
                <div>
                  <div className="mb-1 text-[12px] font-semibold text-zinc-500">变量含义</div>
                  <div className="overflow-x-auto rounded-md border border-zinc-200">
                    <table className="w-full border-collapse text-[12.5px]">
                      <thead>
                        <tr>
                          {Object.keys(detail.variables[0]).map((h) => (
                            <th key={h} className="border-b border-zinc-200 bg-zinc-50 px-2 py-1.5 text-left font-medium text-zinc-600">
                              {h}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {detail.variables.map((row, i) => (
                          <tr key={i} className="border-b border-zinc-100 last:border-b-0">
                            {Object.values(row).map((v, j) => (
                              <td key={j} className="px-2 py-1.5">{v}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
              {/* 适用场景 */}
              {detail.scenarios.length > 0 && (
                <div>
                  <div className="mb-1 text-[12px] font-semibold text-zinc-500">适用场景</div>
                  <ul className="list-disc space-y-0.5 pl-5">
                    {detail.scenarios.map((s, i) => (
                      <li key={i}>{s}</li>
                    ))}
                  </ul>
                </div>
              )}
              {/* 注意事项 */}
              {detail.notes.length > 0 && (
                <div>
                  <div className="mb-1 text-[12px] font-semibold text-zinc-500">注意事项</div>
                  <ul className="list-disc space-y-0.5 pl-5">
                    {detail.notes.map((s, i) => (
                      <li key={i}>{s}</li>
                    ))}
                  </ul>
                </div>
              )}
              {/* 完整文档折叠 */}
              <button
                onClick={() => setShowRaw((v) => !v)}
                className="flex items-center gap-1.5 rounded-md px-2 py-1 text-[12px] text-blue-600 hover:bg-blue-50"
              >
                <FileText size={13} />
                {showRaw ? "收起完整文档" : "查看完整文档"}
              </button>
              {showRaw && (
                <div className="rounded-md border border-zinc-200 bg-zinc-50 p-3">
                  <MarkdownBlock text={detail.raw} />
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
