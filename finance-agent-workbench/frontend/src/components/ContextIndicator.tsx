/** ContextIndicator — 上下文圆环指示（阶段 7.8 重构 / 阶段 7.9.2 精简）。
 *
 * 样式（对标主流产品圆环进度惯例）：
 * - 浅灰底环 + 深色弧线（stroke-dasharray 按百分比）
 * - **纯圆环，中心无数字**（精简；百分比在 tooltip/详情弹窗查看）
 * - 颜色基调灰色系；≥80% 转红、60-80% 转琥珀（预警微变色）
 * 位置：Composer 输入框右端（flex 项，不再 absolute 悬浮）
 * 交互：悬停 tooltip（X / Y token），点击弹出详情（消息数 + 清空确认）。
 * 对接：/api/context/stats + /api/workspace/context/reset
 */

import { useEffect, useRef, useState } from "react";

interface ContextStats {
  current_tokens: number;
  effective_budget: number;
  usage_pct: number;
  message_count: number;
}

const RING_SIZE = 18;
const STROKE = 2.5;
const RADIUS = (RING_SIZE - STROKE) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

export default function ContextIndicator({ projectId, onCleared }: { projectId: string; onCleared?: () => void }) {
  const [stats, setStats] = useState<ContextStats | null>(null);
  const [open, setOpen] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  async function load() {
    try {
      const resp = await fetch(`/api/context/stats?project_id=${encodeURIComponent(projectId)}`);
      const json = await resp.json();
      if (json?.data) setStats(json.data);
    } catch { /* 静默 */ }
  }

  useEffect(() => {
    load();
    timerRef.current = setInterval(load, 2000); // 2 秒轮询（复用事件流节奏）
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [projectId]);

  async function handleClear() {
    if (!confirm("确定要清空所有对话上下文吗？此操作不可撤销。")) return;
    try {
      await fetch("/api/workspace/context/reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: projectId }),
      });
      await load();
      setOpen(false);
      // 阶段 7.9：通知 ChatPage 重新加载对话历史（否则前端仍显示旧记录）
      onCleared?.();
    } catch (e) {
      alert(`清空失败: ${(e as Error).message}`);
    }
  }

  const pct = Math.min(100, Math.max(0, stats?.usage_pct ?? 0));
  // 灰色基调；预警微变色
  const arcColor = pct >= 80 ? "#dc2626" : pct >= 60 ? "#d97706" : "#3f3f46";
  const arcLen = (pct / 100) * CIRCUMFERENCE;
  const tokens = stats?.current_tokens ?? 0;
  const budget = stats?.effective_budget ?? 0;

  return (
    <div className="relative flex items-center self-center">
      {open && (
        <>
          <div className="fixed inset-0 z-20" onClick={() => setOpen(false)} />
          <div className="absolute bottom-full right-0 z-30 mb-2 w-52 rounded-lg border border-zinc-200 bg-white p-3 shadow-xl">
            <div className="mb-1 text-[12px] font-medium text-zinc-700">对话上下文</div>
            <div className="mb-2 text-[11px] text-zinc-500">
              已用 {tokens.toLocaleString()} / {budget.toLocaleString()} token（{Math.round(pct)}%）
              <br />
              共 {stats?.message_count ?? 0} 条消息
            </div>
            <div className="mb-2 h-1.5 w-full overflow-hidden rounded-full bg-zinc-100">
              <div
                className="h-full rounded-full transition-all"
                style={{ width: `${pct}%`, backgroundColor: arcColor }}
              />
            </div>
            <button
              onClick={handleClear}
              className="w-full rounded-md border border-red-200 bg-red-50 px-2 py-1 text-[11px] text-red-600 hover:bg-red-100"
            >
              清空上下文
            </button>
          </div>
        </>
      )}
      <button
        onClick={() => setOpen((o) => !o)}
        title={`上下文：${tokens.toLocaleString()} / ${budget.toLocaleString()} token（${Math.round(pct)}%）`}
        className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full transition-transform hover:scale-110"
      >
        <svg width={RING_SIZE} height={RING_SIZE} viewBox={`0 0 ${RING_SIZE} ${RING_SIZE}`} className="-rotate-90">
          {/* 浅灰底环 */}
          <circle
            cx={RING_SIZE / 2} cy={RING_SIZE / 2} r={RADIUS}
            fill="none" stroke="#e4e4e7" strokeWidth={STROKE}
          />
          {/* 深色弧（百分比占比，无中心数字） */}
          {pct > 0 && (
            <circle
              cx={RING_SIZE / 2} cy={RING_SIZE / 2} r={RADIUS}
              fill="none" stroke={arcColor} strokeWidth={STROKE}
              strokeLinecap="round"
              strokeDasharray={`${arcLen} ${CIRCUMFERENCE}`}
            />
          )}
        </svg>
      </button>
    </div>
  );
}
