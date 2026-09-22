/** GuideCard — 财务建模「引导卡」（P2 引导引擎，2026-08-21 初版）。
 *
 * 渲染 AI 引导输出的方向建议（FinmodDirection）。勾选框 + 模型名 + 理由 +
 * 「教学」折叠区（白话讲解 + KaTeX 公式）。
 *
 * UI 设计 v2（2026-08-23）：从「左边 4px 彩色色带 + 高饱和徽章」改为
 * 「极简高端卡片」——①去掉左侧强调色带，改用选中时的细腻描边 + 浅蓝底淡入；
 * ②模型编码改用细体灰度编号 + 竖线分隔（克制）；③完备性徽章改低调圆点 + 中性文字；
 * ④推荐图表改中文标签；⑤加大留白、边框更细（border-zinc-100）。
 */

import { useState } from "react";
import { CheckSquare, Square, ChevronDown, BookOpen, BarChart3, Circle } from "lucide-react";
import type { FinmodDirection } from "../lib/api";
import MarkdownBlock from "./MarkdownBlock";

/** 推荐图表模板 → 中文（精简，未列出的回退为模板名） */
const CHART_ZH: Record<string, string> = {
  line: "折线图", bar: "柱状图", pie: "饼图",
  scatter: "散点图", radar: "雷达图", heatmap: "热力图", waterfall: "瀑布图",
  boxplot: "箱线图", treemap: "矩形树图", gauge: "仪表图", dualaxis: "双轴图",
};

interface Props {
  direction: FinmodDirection;
  selected: boolean;
  onToggle: () => void;
  /** 推荐次序（0 起）；保留以兼容调用方（不再用于色带） */
  index?: number;
}

export default function GuideCard({ direction, selected, onToggle, index: _index = 0 }: Props) {
  const [teachingOpen, setTeachingOpen] = useState(false);
  const vc = direction.var_coverage;
  // 完备性结论（text 优先用后端 suggestion；zinc 主色，不喧宾夺主）
  const readinessText = vc ? (
    vc.ready
      ? (vc.derivable?.length
          ? `变量已齐 · ${vc.derivable.length} 项可派生`
          : `变量已齐 · ${vc.input_vars} 项`)
      : `缺 ${vc.missing} 项${vc.derivable?.length ? `、${vc.derivable.length} 项可派生` : ""}`
  ) : null;

  return (
    <div
      className={`rounded-xl border bg-white transition-all duration-200 ${
        selected
          ? "border-blue-200 bg-blue-50/30 shadow-[0_1px_6px_rgba(37,99,235,0.08)]"
          : "border-zinc-100 hover:border-zinc-200 hover:bg-zinc-50/40"
      }`}
    >
      {/* 卡片主体（勾选 + 模型名 + 理由） */}
      <div className="flex items-start gap-3 px-4 py-3.5">
        <button
          onClick={onToggle}
          title={selected ? "取消选择" : "选择此模型"}
          className={`mt-0.5 shrink-0 transition-colors ${selected ? "text-blue-600" : "text-zinc-300 hover:text-zinc-400"}`}
        >
          {selected ? <CheckSquare size={18} /> : <Square size={18} />}
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2.5">
            {/* 模型编码：细体灰度编号 + 竖线分隔 */}
            <span className="shrink-0 font-mono text-[11px] font-medium uppercase tracking-wide text-zinc-400">
              {direction.code}
            </span>
            <span className="h-3.5 w-px shrink-0 bg-zinc-200" />
            <h3 className="truncate text-[13.5px] font-semibold text-zinc-900">{direction.name}</h3>
            {/* 数据完备性：低调圆点 + 中性文字 */}
            {readinessText && (
              <span className="ml-1 inline-flex shrink-0 items-center gap-1.5 text-[11px] text-zinc-400">
                <Circle size={6} className={vc!.ready ? "fill-emerald-400 text-emerald-400" : "fill-amber-400 text-amber-400"} />
                {readinessText}
              </span>
            )}
            {/* 推荐图表 chips（中文，低调） */}
            {direction.recommended_charts.length > 0 && (
              <span className="ml-auto flex shrink-0 items-center gap-1">
                <BarChart3 size={12} className="text-zinc-300" />
                {direction.recommended_charts.slice(0, 3).map((c) => (
                  <span key={c} className="rounded-md bg-zinc-100/80 px-1.5 py-0.5 text-[10.5px] text-zinc-500">
                    {CHART_ZH[c] || c}
                  </span>
                ))}
              </span>
            )}
          </div>
          {direction.reason && (
            <p className="mt-1.5 text-[12.5px] leading-[1.7] text-zinc-500">{direction.reason}</p>
          )}
          {/* 缺失变量提示（v3.3：可派生 → 无需补数据；真正缺失 → 显示建议补什么） */}
          {vc && (() => {
            const derivable = vc.derivable || [];
            const trulyDetails = vc.truly_missing_details || [];
            const trulyNames = vc.truly_missing || [];
            const ready = vc.ready;
            return (
              <div className="mt-2 rounded-lg border border-zinc-100 bg-zinc-50/60 px-3 py-2 text-[11.5px] leading-relaxed text-zinc-500">
                {derivable.length > 0 && (
                  <span>
                    {derivable.slice(0, 5).join("、")}
                    {derivable.length > 5 ? " 等" : ""} 可由已有列派生；
                  </span>
                )}
                {trulyDetails.length > 0 ? (
                  <span>
                    需补：{trulyDetails.slice(0, 3).map((d) => d.var_name).join("、")}
                    {trulyDetails.length > 3 ? ` 等 ${trulyDetails.length} 项` : ""}
                  </span>
                ) : (
                  trulyNames.length > 0 && (
                    <span>
                      需补：{trulyNames.slice(0, 5).join("、")}
                      {trulyNames.length > 5 ? ` 等 ${trulyNames.length} 项` : ""}
                    </span>
                  )
                )}
                {derivable.length === 0 && trulyNames.length === 0 && ready && (
                  <span>{vc.suggestion || "数据完备"}</span>
                )}
              </div>
            );
          })()}
          {/* 教学折叠区 */}
          <button
            onClick={() => setTeachingOpen((o) => !o)}
            className="mt-2.5 flex items-center gap-1.5 rounded-md px-0 py-1 text-[12px] font-medium text-zinc-500 transition-colors hover:text-zinc-700"
          >
            <BookOpen size={13} />
            {teachingOpen ? "收起" : "这模型在分析啥？"}
            <ChevronDown size={12} className={`transition-transform ${teachingOpen ? "rotate-180" : ""}`} />
          </button>
          {teachingOpen && direction.teaching && (
            <div className="mt-2 rounded-lg border border-zinc-100 bg-zinc-50/60 px-3 py-2.5">
              <MarkdownBlock text={direction.teaching} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
