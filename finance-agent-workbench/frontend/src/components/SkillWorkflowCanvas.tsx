/** SkillWorkflowCanvas — Skill 工作流可视化画布（v7：严格复刻 Beautiful UI Flowchart）。
 *
 * 数据驱动：从 SKILL.md 解析出的步骤数组渲染为「垂直流程」节点。
 * v7（2026-08-20）：严格照抄 Beautiful UI Flowchart 的布局与视觉——
 *  - 节点容器 items-start（pill 左对齐悬空在卡片上方，线在 x=中心垂直，
 *    线与 pill/卡片互不重叠）——修复 v6 的堆叠 bug
 *  - 连线锚点 = 卡片底部中心 → 下一卡片顶部中心（PILL_OFFSET=30 精确对应
 *    卡片顶部，线不碰 pill）
 *  - 分支卡片组独立绝对定位居中（不塞进主节点容器，避免 flex 嵌套错乱）
 *  - 卡片 = 图标方块（mix(hue,12) 浅色底）+ 标题 + 摘要，圆角 12px 柔和阴影
 * v6：pill 标签 + 图标卡片（线连 pill 中心导致堆叠，已弃）
 * v5：多路径分支；v4：编号矩形 + 箭头连线 + 可拖动。
 */

import { useLayoutEffect, useRef, useState } from "react";

const PAD_Y = 24;            // 顶部留白
const ROW_GAP = 64;          // 步骤间垂直间距（Beautiful UI 64）
const PILL_OFFSET = 30;      // pill(22) + gap(8) → 卡片顶部偏移（Beautiful UI 30）
const BRANCH_GAP = 12;       // 分支卡片组内间距
const BRANCH_PAD = 18;       // 分支组与主卡片间距
const BRANCH_H = 52;         // 分支卡片估算高（连线用；2026-08-20 删描述行后收紧）

interface FlowStep {
  n: number;
  title: string;
  summary: string;
  branch_point?: boolean;
  branches?: { key: string; title: string; summary: string }[];
}

/* 步骤色系（主色） */
const STEP_HUES = [
  "#2563eb", "#7c3aed", "#0d9488", "#ea580c",
  "#db2777", "#4f46e5", "#059669", "#d97706",
];

const BRANCH_HUES = ["#0ea5e9", "#8b5cf6", "#10b981", "#f43f5e"];

/* 主色 + 两位透明度 → rgba（参考 Beautiful UI mix(hue, pct, base)） */
const tint = (hex: string, a: string) => `${hex}${a}`;

/* 图标方块（参考 Beautiful UI StepBody：mix(hue,12) 底 + 主色图标 + 1px ring） */
function StepIcon({ hue }: { hue: string }) {
  return (
    <span
      className="flex size-9 shrink-0 items-center justify-center rounded-[8px]"
      style={{
        background: tint(hue, "1f"),
        color: hue,
        boxShadow: `0 0 0 1px ${tint(hue, "33")}`,
      }}
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 6h16M4 12h10M4 18h7" />
      </svg>
    </span>
  );
}

export default function SkillWorkflowCanvas({ steps }: { steps: FlowStep[] }) {
  const canvasRef = useRef<HTMLDivElement>(null);
  const nodeRefs = useRef(new Map<number, HTMLElement>());
  const [width, setWidth] = useState(0);
  const [heights, setHeights] = useState<Record<number, number>>({});
  const [offsets, setOffsets] = useState<Record<number, { dx: number; dy: number }>>({});
  const [selected, setSelected] = useState<number | null>(null);
  const drag = useRef<{
    id: number;
    startX: number;
    startY: number;
    baseDx: number;
    baseDy: number;
    moved: boolean;
  } | null>(null);

  /* 测量节点高度 + 画布宽度 */
  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const measure = () => {
      setWidth(canvas.clientWidth);
      setHeights((prev) => {
        const next = { ...prev };
        let changed = false;
        nodeRefs.current.forEach((el, id) => {
          const h = el.offsetHeight;
          if (h && Math.abs(h - (next[id] ?? 0)) > 0.5) {
            next[id] = h;
            changed = true;
          }
        });
        return changed ? next : prev;
      });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(canvas);
    nodeRefs.current.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, [steps.length]);

  if (!steps.length) {
    return (
      <div className="flex h-28 items-center justify-center rounded-lg border border-dashed border-zinc-300 text-[12px] text-zinc-400">
        该 Skill 未定义结构化步骤
      </div>
    );
  }

  const cw = width || 560;
  const nodeW = Math.min(420, cw * 0.9);
  const n = steps.length;

  /* 卡片高 = 容器高（pill+卡片） - PILL_OFFSET */
  const cardH = (i: number) => Math.max(40, (heights[steps[i].n] ?? 90) - PILL_OFFSET);
  const hasBr = (i: number) => !!(steps[i].branch_point && steps[i].branches?.length);
  const brCount = (i: number) => (hasBr(i) ? steps[i].branches!.length : 0);

  /* 每步块高 = PILL_OFFSET + 卡片高 + (分支组) */
  const blockHs = steps.map((_, i) =>
    PILL_OFFSET + cardH(i) + (hasBr(i) ? BRANCH_PAD + BRANCH_H : 0),
  );
  const ys: number[] = [];
  steps.forEach((_, i) => {
    ys[i] = i === 0 ? PAD_Y : ys[i - 1] + blockHs[i - 1] + ROW_GAP;
  });
  const canvasH = ys[n - 1] + blockHs[n - 1] + PAD_Y;

  const place = (i: number) => {
    const cx = cw / 2 + (offsets[steps[i].n]?.dx ?? 0);
    const top = ys[i] + (offsets[steps[i].n]?.dy ?? 0);
    return { cx, top }; // top = 容器顶（pill 顶）
  };

  /* 连线锚点（Beautiful UI anchors）：卡片顶部 / 卡片底部 */
  const cardTopY = (i: number) => place(i).top + PILL_OFFSET;
  const cardBotY = (i: number) => cardTopY(i) + cardH(i);

  /* 正交折线（WPS 流程图风格）：
   * 起点 → 垂直段 → 水平段 → 垂直段 → 终点（全部直线，无曲线）
   * from = {x,y}（卡片底中心） to = {x,y}（下一卡片顶中心）
   * 中继 y = 两点垂直中点 */
  const ortho = (from: { x: number; y: number }, to: { x: number; y: number }) => {
    const midY = from.y + (to.y - from.y) / 2;
    return `M ${from.x} ${from.y} L ${from.x} ${midY} L ${to.x} ${midY} L ${to.x} ${to.y}`;
  };

  /* 分支正交折线（WPS 分支画法）：
   * 分支点卡片底中心 → 垂直向下到中继高度 → 水平展开到分支入口 x →
   * 垂直向下到分支卡片顶 */
  const branchOrtho = (midX: number, fromY: number, midY: number, toX: number, toY: number) => {
    return `M ${midX} ${fromY} L ${midX} ${midY} L ${toX} ${midY} L ${toX} ${toY}`;
  };

  /* 分支卡片组几何（独立定位，不塞进主容器） */
  const branchGeom = (i: number) => {
    if (!hasBr(i)) return null;
    const { cx } = place(i);
    const bc = brCount(i);
    const brW = Math.min(150, (nodeW - (bc - 1) * BRANCH_GAP) / bc);
    const groupW = bc * brW + (bc - 1) * BRANCH_GAP;
    const gLeft = cx - groupW / 2;
    const gTop = cardBotY(i) + BRANCH_PAD;
    return {
      bc, brW, groupW, gLeft, gTop,
      pts: steps[i].branches!.map((_, bi) => ({
        x: gLeft + bi * (brW + BRANCH_GAP) + brW / 2,
        y: gTop,
      })),
    };
  };

  /* 拖动 */
  const onPointerDown = (i: number) => (e: React.PointerEvent<HTMLDivElement>) => {
    if ((e.target as Element).closest("[data-nodrag]")) return;
    const off = offsets[steps[i].n];
    drag.current = {
      id: steps[i].n,
      startX: e.clientX,
      startY: e.clientY,
      baseDx: off?.dx ?? 0,
      baseDy: off?.dy ?? 0,
      moved: false,
    };
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };

  const onPointerMove = (i: number) => (e: React.PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d || d.id !== steps[i].n) return;
    const dx = d.baseDx + e.clientX - d.startX;
    const dy = d.baseDy + e.clientY - d.startY;
    if (!d.moved && Math.hypot(dx - d.baseDx, dy - d.baseDy) < 3) return;
    d.moved = true;
    const baseCx = cw / 2;
    const baseTop = ys[i];
    const cx = Math.min(Math.max(baseCx + dx, nodeW / 2 + 10), cw - nodeW / 2 - 10);
    const top = Math.min(Math.max(baseTop + dy, 6), canvasH - blockHs[i] - 6);
    setOffsets((cur) => ({ ...cur, [steps[i].n]: { dx: cx - baseCx, dy: top - baseTop } }));
  };

  const onPointerUp = () => {
    if (drag.current?.moved) setTimeout(() => (drag.current = null), 0);
    else drag.current = null;
  };

  const wasDragged = () => drag.current?.moved === true;

  return (
    <div
      ref={canvasRef}
      className="relative w-full select-none overflow-hidden rounded-xl border border-zinc-200 bg-zinc-50/60"
      style={{
        height: canvasH,
        backgroundImage: "radial-gradient(#d4d4d8 1px, transparent 1.25px)",
        backgroundSize: "22px 22px",
        backgroundPosition: "center",
      }}
    >
      {/* 连接线（WPS 流程图风格正交折线：垂直→水平→垂直，全部直线） */}
      <svg width={cw} height={canvasH} className="pointer-events-none absolute inset-0">
        {/* 主步骤 → 下一主步骤（正交折线；分支点不画直连） */}
        {steps.slice(1).map((s, i) => {
          if (hasBr(i)) return null;
          const lit = selected === steps[i].n || selected === s.n;
          const hue = STEP_HUES[(s.n - 1) % STEP_HUES.length];
          return (
            <path
              key={`${steps[i].n}-${s.n}`}
              d={ortho({ x: place(i).cx, y: cardBotY(i) }, { x: place(i + 1).cx, y: cardTopY(i + 1) })}
              fill="none"
              stroke={lit ? hue : "#a1a1aa"}
              strokeWidth={lit ? 2 : 1.5}
              className="transition-[stroke,stroke-width] duration-150"
            />
          );
        })}
        {/* 分支点：卡片底中心伸出小段 → 水平展开 → 垂直下到各分支卡片顶；
            分支底 → 水平汇聚 → 垂直下到下一主卡片顶（WPS 标准画法） */}
        {steps.map((s, i) => {
          const g = branchGeom(i);
          if (!g) return null;
          const nodes: React.ReactNode[] = [];
          const gx = place(i).cx;
          const fromY = cardBotY(i);
          // 中继高度：卡片底 与 分支卡片顶 的中间（水平展开处）
          const branchMidY = fromY + (g.gTop - fromY) / 2;
          // 1) 分支点卡片底 → 各分支卡片顶（三段正交）
          g.pts.forEach((p, bi) => {
            nodes.push(
              <path
                key={`br-${s.n}-${bi}`}
                d={branchOrtho(gx, fromY, branchMidY, p.x, p.y)}
                fill="none"
                stroke={BRANCH_HUES[bi % BRANCH_HUES.length]}
                strokeWidth="1.4"
                className="transition-[stroke,stroke-width] duration-150"
              />
            );
          });
          // 2) 各分支底 → 下一主卡片顶（汇聚正交）
          if (i + 1 < n) {
            const nextTop = cardTopY(i + 1);
            const nextCx = place(i + 1).cx;
            const nextMidY = (g.gTop + BRANCH_H + nextTop) / 2;
            g.pts.forEach((p, bi) => {
              nodes.push(
                <path
                  key={`brd-${s.n}-${bi}`}
                  d={branchOrtho(p.x, p.y + BRANCH_H, nextMidY, nextCx, nextTop)}
                  fill="none"
                  stroke={BRANCH_HUES[bi % BRANCH_HUES.length] + "99"}
                  strokeWidth="1.2"
                  className="transition-[stroke,stroke-width] duration-150"
                />
              );
            });
          }
          return nodes;
        })}
      </svg>

      {/* 主节点：pill 左悬 + 卡片（items-start，pill 不与中心线重叠） */}
      {steps.map((s, i) => {
        const { cx, top } = place(i);
        const hue = STEP_HUES[(s.n - 1) % STEP_HUES.length];
        const active = selected === s.n;
        return (
          <div
            key={s.n}
            ref={(el) => {
              if (el) nodeRefs.current.set(s.n, el);
              else nodeRefs.current.delete(s.n);
            }}
            onPointerDown={onPointerDown(i)}
            onPointerMove={onPointerMove(i)}
            onPointerUp={onPointerUp}
            onDoubleClick={() =>
              setOffsets((cur) => {
                const next = { ...cur };
                delete next[s.n];
                return next;
              })
            }
            className="absolute flex -translate-x-1/2 touch-none flex-col items-start"
            style={{ left: cx, top, width: nodeW, zIndex: drag.current?.id === s.n ? 3 : 1, cursor: "grab" }}
            title="拖动节点调整布局；双击复位"
          >
            {/* pill（参考 Beautiful UI Trigger/If-Else，左对齐悬空） */}
            <button
              type="button"
              onClick={() => {
                if (wasDragged()) return;
                setSelected(active ? null : s.n);
              }}
              aria-pressed={active}
              className="inline-flex h-5.5 items-center rounded-[6px] px-2 text-[11px] font-semibold transition-colors duration-100"
              style={{
                background: tint(hue, "14"),
                color: hue,
                boxShadow: active ? `inset 0 0 0 1.5px ${hue}` : `inset 0 0 0 1px ${tint(hue, "40")}`,
              }}
            >
              {s.branch_point ? `★ 步骤 ${s.n} · 分支` : `步骤 ${s.n}`}
            </button>

            {/* 卡片（参考 Beautiful UI StepBody：图标方块 + 标题 + 摘要） */}
            <button
              type="button"
              onClick={() => {
                if (wasDragged()) return;
                setSelected(active ? null : s.n);
              }}
              aria-pressed={active}
              className="mt-1.5 w-full cursor-pointer rounded-[12px] bg-white text-left outline-none
                transition-shadow duration-150"
              style={{
                boxShadow: active
                  ? `0 0 0 1.5px ${hue}, 0 2px 10px rgba(0,0,0,0.045)`
                  : "0 1px 3px rgba(0,0,0,0.06), 0 0 0 1px rgba(228,228,231,0.7)",
              }}
            >
              <div className="flex items-center gap-3 px-3.5 py-3">
                <StepIcon hue={hue} />
                <span className="min-w-0 text-left">
                  <span className="block truncate text-[13px] font-semibold text-zinc-800">
                    {s.title}
                  </span>
                  {s.summary && (
                    <span className="mt-0.5 block truncate text-[11.5px] leading-snug text-zinc-500">
                      {s.summary}
                    </span>
                  )}
                </span>
              </div>
            </button>
          </div>
        );
      })}

      {/* 分支卡片组（独立绝对定位居中，不塞进主容器——避免 flex 嵌套堆叠） */}
      {steps.map((s, i) => {
        const g = branchGeom(i);
        if (!g) return null;
        return (
          <div
            key={`brg-${s.n}`}
            data-nodrag
            className="absolute flex -translate-x-1/2 items-stretch gap-3"
            style={{ left: place(i).cx, top: g.gTop, width: g.groupW }}
          >
            {s.branches!.map((b, bi) => {
              const bhue = BRANCH_HUES[bi % BRANCH_HUES.length];
              return (
                <div
                  key={`${s.n}-${b.key}`}
                  className="flex min-w-0 flex-1 flex-col justify-center rounded-[10px] border border-dashed px-2 py-1"
                  style={{ borderColor: tint(bhue, "55"), background: tint(bhue, "0a") }}
                >
                  <span
                    className="mb-0.5 inline-flex w-fit items-center rounded-[6px] px-1.5 py-px text-[9px] font-semibold"
                    style={{ background: tint(bhue, "1a"), color: bhue }}
                  >
                    {b.key}
                  </span>
                  <span className="break-words text-[9.5px] font-semibold leading-snug" style={{ color: bhue }}>
                    {b.title}
                  </span>
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}
