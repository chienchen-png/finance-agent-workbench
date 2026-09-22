/** StatCard — 工作台总览数字指标卡（D4）。
 *
 * 设计文档：`docs/工作台总览设计方案.md` §2.2 ③ / §4.3
 * - 大数字（tabular-nums 等宽）+ 子信息 + 图标
 * - 数字从 0 递增动画（requestAnimationFrame，D6 预留；此处已实现）
 * - 可选点击跳转（onClick）
 */

import { useEffect, useRef, useState, type ReactNode } from "react";

/** 数字递增动画：从 0 → value（约 500ms 缓出）。 */
function useCountUp(value: number, duration = 500): number {
  const [display, setDisplay] = useState(0);
  const fromRef = useRef(0);

  useEffect(() => {
    const from = fromRef.current;
    const to = value;
    if (from === to) return;
    const start = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const p = Math.min((now - start) / duration, 1);
      // easeOutCubic
      const eased = 1 - Math.pow(1 - p, 3);
      const cur = Math.round(from + (to - from) * eased);
      setDisplay(cur);
      if (p < 1) {
        raf = requestAnimationFrame(tick);
      } else {
        fromRef.current = to;
      }
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value, duration]);

  return display;
}

export default function StatCard({
  icon,
  label,
  value,
  sub,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  sub?: string;
  onClick?: () => void;
}) {
  const numeric = /^-?\d+$/.test(value);
  const shown = useCountUp(numeric ? Number(value) : 0);

  const content = (
    <>
      <div className="flex items-center gap-1.5 text-[12px] text-zinc-500">
        <span className="text-blue-500">{icon}</span>
        {label}
      </div>
      <div className="mt-2 text-[22px] font-semibold tabular-nums text-zinc-800">
        {numeric ? shown : value}
      </div>
      {sub && <div className="mt-0.5 truncate text-[11px] text-zinc-400">{sub}</div>}
    </>
  );

  const cls =
    "min-w-[170px] flex-1 basis-[180px] rounded-xl border border-zinc-200 bg-white p-5 shadow-sm transition-shadow hover:shadow-md";

  if (onClick) {
    return (
      <button onClick={onClick} className={`${cls} text-left`}>
        {content}
      </button>
    );
  }
  return <div className={cls}>{content}</div>;
}
