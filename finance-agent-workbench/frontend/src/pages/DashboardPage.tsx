/** DashboardPage — 工作台总览（Dashboard）主页面（2026-08-24 精简调整）。
 *
 * 设计文档：`docs/工作台总览设计方案.md`（v1.3 + 2026-08-24 调整）
 * 结构：
 *   ① 顶栏（标题 + 状态徽标 + 时钟 + 刷新）
 *   → 欢迎大字（一行标题，无容器背景）
 *   → ② 关键指标行（6 卡）
 *   → ③ 分析与分布区（3 卡）
 *   → ④ 联动区（最近项目 + 应用入口）
 * 已按用户要求移除：最近活动流（ActivityRow）。
 * 后端 `GET /api/dashboard/summary` 为数据源。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  RefreshCw, Server, Cpu, FolderKanban, AppWindow, Clock3, Play,
  AlertTriangle,
} from "lucide-react";
import {
  fetchDashboardSummary,
  type DashboardSummary,
  type DashboardStatus,
} from "../lib/dashboard";
import StatCard from "../components/dashboard/StatCard";
import TimeTrendChart from "../components/dashboard/TimeTrendChart";
import ActiveHoursChart from "../components/dashboard/ActiveHoursChart";
import AppEntryCard from "../components/dashboard/AppEntryCard";

// =====================================================================
// 工具
// =====================================================================

/** 秒 → 「Xh Ym」/「Xm Ys」/「Ys」。 */
export function formatDuration(sec: number): string {
  if (!sec || sec <= 0) return "0s";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

/** 相对时间。 */
function formatRelative(ts: string): string {
  const t = new Date(ts).getTime();
  if (Number.isNaN(t)) return ts;
  const diff = Date.now() - t;
  const min = Math.floor(diff / 60000);
  if (min < 1) return "刚刚";
  if (min < 60) return `${min} 分钟前`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} 小时前`;
  const day = Math.floor(hr / 24);
  if (day < 7) return `${day} 天前`;
  return ts.slice(0, 10);
}

/** 当前时间（本地，顶栏时钟）。 */
function nowClock(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

/** 状态徽标：后端在线 / 今日错误（2026-08-24：模型统计徽标已删，标题栏不展示模型数）。 */
function StatusBadges({ status, errorsToday }: { status: DashboardStatus | null; errorsToday: number }) {
  const backendOk = status?.backend_ok ?? false;
  return (
    <div className="flex items-center gap-2">
      <span
        className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${
          backendOk ? "bg-emerald-50 text-emerald-600" : "bg-red-50 text-red-600"
        }`}
      >
        <Server size={11} />
        {backendOk ? "运行中" : "服务离线"}
      </span>
      {errorsToday > 0 && (
        <span className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2 py-0.5 text-[11px] font-medium text-red-600">
          <AlertTriangle size={11} />
          今日 {errorsToday} 错误
        </span>
      )}
    </div>
  );
}

// =====================================================================
// ② 关键指标行（5 卡）
// =====================================================================

function MetricRow({ data, onNavigate }: {
  data: DashboardSummary | null;
  onNavigate: (view: string) => void;
}) {
  const u = data?.usage;
  const cards = [
    { icon: <Cpu size={15} />, label: "可调用模型", value: data ? String(data.status.available_model_count) : "—", sub: data ? `默认：${data.status.default_model || "无"}` : "", onClick: () => onNavigate("ai-config") },
    { icon: <FolderKanban size={15} />, label: "项目", value: data ? String(data.projects.total) : "—", sub: data ? `应用 ${data.projects.app_count} 个` : "", onClick: () => onNavigate("chat") },
    { icon: <AppWindow size={15} />, label: "应用", value: data ? String(data.projects.app_count) : "—", sub: data ? `共 ${data.apps.length} 类` : "", onClick: () => document.getElementById("dashboard-links")?.scrollIntoView({ behavior: "smooth" }) },
    { icon: <Clock3 size={15} />, label: "今日使用时长", value: data ? formatDuration(u?.today_duration_sec ?? 0) : "—", sub: data ? `昨日 ${formatDuration(u?.yesterday_duration_sec ?? 0)}` : "", onClick: undefined },
    { icon: <Play size={15} />, label: "今日运行次数", value: data ? String(u?.today_runs ?? 0) : "—", sub: data ? `成功 ${u?.today_success ?? 0} / 失败 ${u?.today_failed ?? 0}` : "", onClick: undefined },
  ];
  return (
    <div className="flex flex-wrap gap-5">
      {cards.map((c) => (
        <StatCard key={c.label} icon={c.icon} label={c.label} value={c.value} sub={c.sub} onClick={c.onClick} />
      ))}
    </div>
  );
}

// =====================================================================
// ③ 分析与分布区（2 卡）
// =====================================================================

function AnalysisRow({ data }: { data: DashboardSummary | null }) {
  const trend = data?.time_trend ?? [];
  const hours = data?.active_hours ?? [];
  const hasTrend = trend.some((t) => t.duration_sec > 0 || t.sessions > 0);
  const hasHours = hours.some((h) => h.sessions > 0);
  return (
    <div className="flex flex-wrap justify-center gap-4">
      <div className="w-full max-w-[520px] flex-1 basis-[420px] rounded-xl border border-zinc-200 bg-white p-5 shadow-sm">
        <h3 className="text-[13px] font-medium text-zinc-700">7 日使用时长趋势</h3>
        <div className="mt-3">
          {!data ? <div className="flex h-40 items-center justify-center text-[12px] text-zinc-400">加载中…</div>
            : !hasTrend ? <div className="flex h-40 items-center justify-center text-[12px] text-zinc-400">还没有打开记录，去发起一次任务或刷新页面吧</div>
            : <TimeTrendChart trend={trend} />}
        </div>
      </div>
      <div className="w-full max-w-[520px] flex-1 basis-[420px] rounded-xl border border-zinc-200 bg-white p-5 shadow-sm">
        <h3 className="text-[13px] font-medium text-zinc-700">活跃时段分布</h3>
        <div className="mt-3">
          {!data ? <div className="flex h-40 items-center justify-center text-[12px] text-zinc-400">加载中…</div>
            : !hasHours ? <div className="flex h-40 items-center justify-center text-[12px] text-zinc-400">还没有打开记录</div>
            : <ActiveHoursChart hours={hours} />}
        </div>
      </div>
    </div>
  );
}

// =====================================================================
// ④ 联动区（最近项目 + 应用入口）
// =====================================================================

function LinkRow({ data, onNavigate, onSelectProject }: {
  data: DashboardSummary | null;
  onNavigate: (view: string) => void;
  onSelectProject: (pid: string) => void;
}) {
  const recent = data?.projects.recent ?? [];
  return (
    <div id="dashboard-links" className="grid gap-5 lg:grid-cols-2">
      <div className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm">
        <h3 className="text-[13px] font-medium text-zinc-700">最近项目</h3>
        <div className="mt-3">
          {recent.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-6 text-center">
              <p className="text-[12px] text-zinc-400">还没有项目</p>
              <button
                onClick={() => onNavigate("chat")}
                className="rounded-lg border border-zinc-200 px-3 py-1 text-[12px] text-zinc-600 transition-colors hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700"
              >
                ＋ 去新建项目
              </button>
            </div>
          ) : (
            <ul className="space-y-1">
              {recent.slice(0, 5).map((p) => (
                <li key={p.id}>
                  <button
                    onClick={() => onSelectProject(p.id)}
                    className="flex w-full items-center justify-between rounded-lg px-2 py-1.5 text-left text-[13px] text-zinc-600 transition-colors hover:bg-blue-50 hover:text-blue-700"
                  >
                    <span className="truncate">{p.name}</span>
                    <span className="ml-2 shrink-0 text-[11px] text-zinc-400">{p.run_count} 次运行</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <div className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm">
        <h3 className="text-[13px] font-medium text-zinc-700">应用入口</h3>
        <div className="mt-3 space-y-2">
          {(data?.apps ?? []).map((a) => (
            <AppEntryCard
              key={a.id}
              id={a.id}
              name={a.name}
              desc={a.desc}
              runs={a.runs}
              durationSec={a.duration_sec}
              onNavigate={onNavigate}
            />
          ))}
          {(data?.apps ?? []).length === 0 && (
            <div className="py-6 text-center text-[12px] text-zinc-400">暂无应用</div>
          )}
        </div>
      </div>
    </div>
  );
}

// =====================================================================
// 主页面
// =====================================================================

export default function DashboardPage({
  onNavigate,
  onSelectProject,
}: {
  onNavigate: (view: string) => void;
  onSelectProject: (pid: string) => void;
}) {
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [clock, setClock] = useState(nowClock());
  const mounted = useRef(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const d = await fetchDashboardSummary(7, 10);
      setData(d);
    } catch (e) {
      setError((e as Error).message || "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  // 挂载时自动刷新一次（打开/切回工作台总览页）
  useEffect(() => {
    if (!mounted.current) {
      mounted.current = true;
      void load();
    }
  }, [load]);

  // 顶栏时钟（1s 刷新，仅本地展示）
  useEffect(() => {
    const t = setInterval(() => setClock(nowClock()), 1000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      {/* ① 顶栏：标题 + 状态徽标 + 时间 + 刷新 */}
      <div className="border-b border-zinc-200 bg-white px-6 py-4">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <h1 className="text-lg font-semibold text-zinc-800">工作台总览</h1>
          </div>
          <div className="flex items-center gap-2">
            <StatusBadges status={data?.status ?? null} errorsToday={data?.errors_today ?? 0} />
            <span className="hidden text-[12px] tabular-nums text-zinc-400 md:inline">{clock}</span>
            <span className="hidden text-[12px] text-zinc-400 md:inline">·</span>
            <span className="hidden text-[11px] text-zinc-400 md:inline">
              {data ? `最后刷新 ${formatRelative(data.ts)}` : ""}
            </span>
            {/* 刷新按钮（简约图标式，仿 AI 功能配置） */}
            <button
              onClick={() => void load()}
              disabled={loading}
              title="刷新"
              className="rounded p-1.5 text-zinc-400 transition-colors hover:bg-zinc-100 hover:text-zinc-600 disabled:opacity-50"
            >
              <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
            </button>
          </div>
        </div>
      </div>

      {/* 内容区：加大页边距与元素间距（与其他页面观感一致，缓解密集感） */}
      <div className="flex-1 space-y-6 overflow-y-auto px-8 py-7">
        {error && (
          <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-600">
            <AlertTriangle size={14} />
            加载失败：{error}
            <button onClick={() => void load()} className="ml-auto text-[12px] font-medium underline">重试</button>
          </div>
        )}
        {!error && !data && loading && (
          <div className="flex items-center justify-center py-16 text-[13px] text-zinc-400">
            <RefreshCw size={14} className="mr-2 animate-spin" /> 加载中…
          </div>
        )}

        {/* 欢迎标题：一行大字（无容器背景），与下方留白更大 */}
        <div className="px-1 pt-1">
          <h2 className="text-[26px] font-semibold tracking-tight text-zinc-800">
            您好，我能为您做些什么？
          </h2>
        </div>

        {/* ② 关键指标行（5 卡，点击联动：模型→AI配置 / 项目→对话 / 应用→联动区） */}
        <MetricRow data={data} onNavigate={onNavigate} />
        {/* ③ 分析与分布区（3 卡） */}
        <AnalysisRow data={data} />
        {/* ④ 联动区（2 卡） */}
        <LinkRow data={data} onNavigate={onNavigate} onSelectProject={onSelectProject} />
      </div>
    </div>
  );
}
