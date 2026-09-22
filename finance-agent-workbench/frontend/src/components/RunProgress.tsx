/** RunProgress — 运行任务状态行（项目架构文档 4.2；Phase 17 P12 借鉴 Task Rows）。
 *
 * 任务运行时在 Composer 上方显示：步骤信息 + 已用工具数徽标 + 进度条。
 * 2026-08-20：smolagents 动态规划无法预知总步数——
 *   - total > 0（有计划解析出估计值）→ 显示「第 N/约M 步」+ 百分比条
 *   - total <= 0（无计划）→ 显示「步骤 N」+ 不确定进度条（流动动画），
 *     不再显示误导性的「第 N/N 步」（此前 total 恒等于 current）。
 * 运行结束自动消失，不占常驻空间。
 */

import { CheckCircle2, Loader2 } from "lucide-react";

export default function RunProgress({
  current,
  total,
  label,
  toolsDone,
}: {
  current: number;
  total: number;
  label: string;
  toolsDone?: number;  // Phase 17 P12：已完成的工具数徽标
}) {
  if (total <= 0 && current <= 0) return null;
  const known = total > 0;
  const pct = known ? Math.min(100, Math.round((current / total) * 100)) : 0;

  return (
    <div className="mx-auto mb-2 max-w-3xl">
      <div className="flex items-center gap-2 rounded-md border border-blue-100 bg-blue-50 px-3 py-1.5">
        <Loader2 size={13} className="animate-spin text-blue-600" />
        <span className="text-[12px] text-blue-700">
          {known
            ? `第 ${current}/${total} 步 · ${label}`
            : `步骤 ${current} · ${label}`}
          {known && total > 0 && (
            <span className="ml-1 text-[10px] text-blue-400">（约）</span>
          )}
        </span>
        {!!toolsDone && toolsDone > 0 && (
          <span className="flex items-center gap-0.5 rounded-full bg-green-50 px-1.5 py-px text-[10px] font-medium text-green-600">
            <CheckCircle2 size={10} />
            {toolsDone} 工具完成
          </span>
        )}
        <div className="ml-auto h-1 w-24 overflow-hidden rounded-full bg-blue-100">
          {known ? (
            <div
              className="h-full rounded-full bg-blue-600 transition-all"
              style={{ width: `${pct}%` }}
            />
          ) : (
            /* 不确定进度：流动动画条（dynamic planning，总步数未知） */
            <div className="indeterminate-bar h-full w-full rounded-full" />
          )}
        </div>
      </div>
    </div>
  );
}
