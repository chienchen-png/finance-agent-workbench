/** LoadingState — 像素网格加载器（长任务执行中）。
 *
 * 移植自 Beautiful UI 的 Loading State（zinc 色板适配）：
 *   Drive — 方形格子，chevron 波前向右推进（两波并行）
 *   Dots  — 同波前，圆形格子（★ 默认：点状动画）
 *   Orbit — 彗星沿网格外圈环绕
 * 配 shimmer 标签 + 等宽计时器；尊重 prefers-reduced-motion。
 *
 * 用法（AI 加载统一用点状动画）：
 *   <LoadingState label="AI 正在识别最契合的变量列…" />
 *   <LoadingState label="AI 正在校验…" variant="Orbit" />
 */

import { useEffect, useState } from "react";

/* chevron 波前延迟（3×3 网格，向右下推进） */
const chevron = Array.from({ length: 9 }, (_, i) => {
  const r = Math.floor(i / 3), c = i % 3;
  return (c + Math.abs(r - 1)) * 90;
});

/* Orbit 环绕顺序（外圈一圈） */
const ORBIT_ORDER = [0, 1, 2, 5, 8, 7, 6, 3];
const orbit = Array.from({ length: 9 }, (_, i) => {
  const k = ORBIT_ORDER.indexOf(i);
  return k === -1 ? null : k * 110;
});

const PATTERNS: Record<string, { delays: (number | null)[]; dur: number; round: boolean }> = {
  Drive: { delays: chevron, dur: 650, round: false },
  Dots: { delays: chevron, dur: 650, round: true },
  Orbit: { delays: orbit, dur: 950, round: false },
};

function LoaderGrid({
  delays,
  dur,
  round,
}: {
  delays: (number | null)[];
  dur: number;
  round: boolean;
}) {
  return (
    <span aria-hidden className="grid shrink-0 grid-cols-[repeat(3,4px)] gap-[1.5px]">
      {delays.map((delay, index) => (
        <span
          key={index}
          className={`size-[4px] rounded-[1px] bg-zinc-900 ${round ? "rounded-full" : ""}`}
          style={{
            opacity: delay === null ? 0.07 : 0.15,
            animation: delay === null ? "none" : `pixel-on ${dur}ms ease-in-out ${delay}ms infinite`,
          }}
        />
      ))}
    </span>
  );
}

function useElapsed() {
  const [ds, setDs] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setDs((d) => d + 1), 100);
    return () => clearInterval(t);
  }, []);
  const total = ds / 10;
  if (total < 60) return `${total.toFixed(1)}s`;
  return `${Math.floor(total / 60)}m ${(total % 60).toFixed(1)}s`;
}

export default function LoadingState({
  label,
  variant = "Dots",  // 默认点状动画（全应用 AI 加载统一）
  compact = false,
}: {
  label?: string;
  variant?: string;
  /** compact：仅网格（按钮内/行内用），无标签与计时器 */
  compact?: boolean;
}) {
  const elapsed = useElapsed();
  const resolvedLabel = label ?? "处理中";
  const { delays, dur, round } = PATTERNS[variant] ?? PATTERNS.Dots;

  if (compact) {
    return (
      <span role="status" aria-live="polite" className="inline-flex items-center">
        <LoaderGrid delays={delays} dur={dur} round={round} />
      </span>
    );
  }

  return (
    <div role="status" aria-live="polite" className="flex w-fit items-center gap-2.5">
      <LoaderGrid delays={delays} dur={dur} round={round} />
      <span className="shimmer-text text-[13px] font-medium">{resolvedLabel}</span>
      <span className="font-mono text-[12px] text-zinc-400 tabular-nums">{elapsed}</span>
    </div>
  );
}
