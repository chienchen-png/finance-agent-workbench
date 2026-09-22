/** SkillConfigPanel — Skill 配置面板（2026-08-19 新增，v2 布局重构）。
 *
 * 纯静态展示（用户无修改权限）。布局 = 左侧紧凑目录导航 + 右侧统一详情页：
 * - 左：skill 目录（VS Code 式列表项：图标 + 名称 + 步骤数角标，选中蓝色左边条）
 * - 右：详情页（单一大容器：header 名称/可调用/描述 + 触发词 chips + 分隔线
 *       + 工作流可视化 + 分隔线 + 约束）
 * 后期新增 skill：`.github/skills/<name>/SKILL.md` 加目录即自动出现在左侧。
 *
 * 数据源：/api/skills（列表）+ /api/skills/<name>（详情）。
 */

import { useCallback, useEffect, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { BookOpen, Layers, ShieldAlert, Workflow } from "lucide-react";
import {
  fetchSkills, fetchSkillDetail,
  type SkillSummary, type SkillDetail,
} from "../lib/api";
import SkillWorkflowCanvas from "./SkillWorkflowCanvas";

/* 图表模板英文 → 中文（能力全景面向用户展示，直观看出能画哪些图） */
const CHART_ZH: Record<string, string> = {
  line: "折线图", bar: "柱状图", pie: "饼图",
  scatter: "散点图", heatmap: "热力图", waterfall: "瀑布图", radar: "雷达图",
  boxplot: "箱线图", histogram: "直方图", tornado: "龙卷风图", funnel: "漏斗图",
  "dual-axis": "双轴图", sunburst: "旭日图", sankey: "桑基图", gauge: "仪表图",
  treemap: "矩形树图", graph: "关系网络图", parallel: "平行坐标图",
  "error-bar": "误差棒图", calendar: "日历图", scatter3d: "3D 散点图",
  bar3d: "3D 柱状图", "histogram-4grid": "联动直方图",
};

export default function SkillConfigPanel() {
  const [skills, setSkills] = useState<SkillSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<SkillDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");

  // 加载 skill 目录（懒加载，切到 Tab 时触发）
  const loadList = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const { skills: list } = await fetchSkills();
      setSkills(list);
      if (list.length > 0) setSelected((cur) => cur || list[0].name);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadList(); }, [loadList]);

  // 选中变化 → 加载详情
  useEffect(() => {
    if (!selected) return;
    setDetailLoading(true);
    setDetail(null);
    fetchSkillDetail(selected)
      .then(setDetail)
      .catch((e) => setError((e as Error).message))
      .finally(() => setDetailLoading(false));
  }, [selected]);

  if (loading) return <div className="text-[13px] text-zinc-400">加载 Skill 配置中…</div>;
  if (error) return <div className="text-[13px] text-red-500">{error}</div>;
  if (skills.length === 0) {
    return (
      <div className="mx-auto max-w-3xl rounded-lg border border-dashed border-zinc-300 p-10 text-center text-[13px] text-zinc-400">
        暂无 Skill。可在 <code className="font-mono">.github/skills/</code> 目录新增 SKILL.md。
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-4xl gap-5">
      {/* ── 左：紧凑目录导航 ── */}
      <div className="w-44 shrink-0">
        <div className="mb-2 flex items-center gap-1.5 px-1 text-[12px] font-semibold text-zinc-500">
          <BookOpen size={13} className="text-blue-600" />
          Skill
          <span className="ml-auto rounded-full bg-zinc-100 px-1.5 py-px text-[10px] font-normal text-zinc-400">
            {skills.length}
          </span>
        </div>
        <nav className="space-y-0.5">
          {skills.map((s) => {
            const active = selected === s.name;
            return (
              <button
                key={s.name}
                onClick={() => setSelected(s.name)}
                title={s.description}
                className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors ${
                  active
                    ? "bg-blue-50 text-blue-700 ring-1 ring-inset ring-blue-200"
                    : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-800"
                }`}
              >
                <BookOpen size={13} className={active ? "text-blue-600" : "text-zinc-400"} />
                <span className="min-w-0 flex-1 truncate font-mono text-[12px] font-medium">
                  {s.name}
                </span>
                <span className={`shrink-0 rounded px-1 text-[9.5px] ${active ? "bg-blue-100 text-blue-700" : "bg-zinc-100 text-zinc-400"}`}>
                  {s.step_count}步
                </span>
              </button>
            );
          })}
        </nav>
      </div>

      {/* ── 右：详情页（单一大容器） ── */}
      <div className="min-w-0 flex-1">
        {detailLoading && <div className="text-[13px] text-zinc-400">加载 Skill 详情…</div>}
        {!detailLoading && detail && (
          <div className="rounded-xl border border-zinc-200 bg-white">
            {/* header */}
            <div className="border-b border-zinc-100 p-5">
              <div className="flex items-center gap-2">
                <span className="rounded-md bg-blue-50 px-2.5 py-1 font-mono text-[13px] font-semibold text-blue-700">
                  {detail.name}
                </span>
                {detail.user_invocable && (
                  <span className="rounded-full bg-green-50 px-2 py-0.5 text-[10px] text-green-700">
                    可调用
                  </span>
                )}
                <span className="ml-auto rounded-full bg-zinc-100 px-2 py-0.5 text-[10px] text-zinc-500">
                  {detail.steps.length} 步
                </span>
              </div>
              {detail.description && (
                <p className="mt-2 text-[12.5px] leading-relaxed text-zinc-600">{detail.description}</p>
              )}
              {/* 触发词 chips（直观展示；description 已去掉末尾重复的触发词列表） */}
              {detail.trigger_words.length > 0 && (
                <div className="mt-3 flex flex-wrap items-center gap-1.5">
                  <span className="text-[11px] text-zinc-400">触发词：</span>
                  {detail.trigger_words.map((w) => (
                    <span key={w} className="rounded-full bg-amber-50 px-2 py-0.5 text-[10.5px] text-amber-700 ring-1 ring-amber-200">
                      {w.replace(/[。，、]+$/, "")}
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* 能力全景（模型矩阵 / 图表能力；两者皆空则不显示） */}
            {detail.capabilities &&
              (detail.capabilities.models.length > 0 || detail.capabilities.charts.length > 0) && (
              <div className="border-b border-zinc-100 p-5">
                <div className="mb-3 flex items-center gap-1.5 text-[12.5px] font-semibold text-zinc-700">
                  <Layers size={13} className="text-indigo-600" />
                  能力全景
                </div>
                {/* 模型矩阵 */}
                {detail.capabilities.models.length > 0 && (
                  <div className="mb-4">
                    <div className="mb-2 text-[11px] font-medium text-zinc-500">模型矩阵（{detail.capabilities.models.reduce((a, m) => a + m.count, 0)} 个）</div>
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4">
                      {detail.capabilities.models.map((m) => (
                        <div key={m.category} className="group rounded-lg border border-zinc-200 bg-zinc-50/50 p-2 transition-colors hover:border-indigo-200 hover:bg-indigo-50/40">
                          <div className="flex items-center gap-1.5">
                            <span className="flex size-4 items-center justify-center rounded bg-indigo-600 text-[9.5px] font-bold text-white">
                              {m.category}
                            </span>
                            <span className="min-w-0 flex-1 truncate text-[11px] font-semibold text-zinc-700">{m.name}</span>
                            <span className="shrink-0 text-[9.5px] text-zinc-400">{m.count}</span>
                          </div>
                          <div className="mt-1 flex flex-wrap gap-1">
                            {m.items.slice(0, 3).map((it) => (
                              <span key={it} className="truncate rounded bg-white px-1 py-px text-[9px] text-zinc-500 ring-1 ring-zinc-200" style={{ maxWidth: "100%" }}>
                                {it}
                              </span>
                            ))}
                            {m.items.length > 3 && (
                              <span className="text-[9px] text-zinc-400">+{m.items.length - 3}</span>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {/* 图表能力（中文名，面向用户直观展示） */}
                {detail.capabilities.charts.length > 0 && (
                  <div>
                    <div className="mb-2 text-[11px] font-medium text-zinc-500">可绘制图表（{detail.capabilities.charts.length} 种）</div>
                    <div className="flex flex-wrap gap-1.5">
                      {detail.capabilities.charts.map((c) => (
                        <span key={c} className="rounded-md bg-rose-50 px-2 py-0.5 text-[10.5px] text-rose-700 ring-1 ring-rose-200">
                          {CHART_ZH[c] || c}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* 工作流可视化 */}
            <div className="border-b border-zinc-100 p-5">
              <div className="mb-3 flex items-center gap-1.5 text-[12.5px] font-semibold text-zinc-700">
                <Workflow size={13} className="text-blue-600" />
                工作流
                {detail.steps.some((s) => s.branch_point) && (
                  <span className="ml-1 rounded-full bg-amber-50 px-1.5 py-px text-[9.5px] font-normal text-amber-700 ring-1 ring-amber-200">
                    多路径分支
                  </span>
                )}
              </div>
              <SkillWorkflowCanvas steps={detail.steps} />
            </div>

            {/* 约束 */}
            {detail.constraints && (
              <div className="p-5">
                <div className="mb-2 flex items-center gap-1.5 text-[12.5px] font-semibold text-zinc-700">
                  <ShieldAlert size={13} className="text-amber-600" />
                  约束
                </div>
                <div className="prose-sm text-[12.5px] leading-relaxed text-zinc-600 [&_ul]:list-disc [&_ul]:pl-4 [&_li]:my-1">
                  <Markdown remarkPlugins={[remarkGfm]}>{detail.constraints}</Markdown>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
