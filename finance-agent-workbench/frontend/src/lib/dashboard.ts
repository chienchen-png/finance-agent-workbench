/** dashboard.ts — 工作台总览（Dashboard / 数据大屏）API 封装 + 类型（D3+）。
 *
 * 对应后端：`routes/dashboard.py` → `GET /api/dashboard/summary`
 * 设计文档：`docs/工作台总览设计方案.md` §3.1（字段与后端一一对应）。
 */

import { request } from "./api";

// =====================================================================
// 类型定义（严格对齐后端 summary 返回结构）
// =====================================================================

export interface DashboardStatus {
  backend_ok: boolean;
  default_model: string;
  model_provider_count: number;
  available_model_count: number;
  skill_count: number;
}

export interface DashboardProjectRecent {
  id: string;
  name: string;
  description: string | null;
  default_model: string | null;
  updated_at: string;
  run_count: number;
}

export interface DashboardProjects {
  total: number;
  app_count: number;
  recent: DashboardProjectRecent[];
}

export interface DashboardApp {
  id: string;
  name: string;
  desc: string;
  runs: number;
  duration_sec: number;
}

export interface DashboardUsage {
  today_duration_sec: number;
  yesterday_duration_sec: number;
  today_runs: number;
  yesterday_runs: number;
  today_success: number;
  today_failed: number;
  avg_duration_sec: number;
  avg_runs_per_day: number;
  sessions_7d: number;
}

export interface TimeTrendPoint {
  day: string;          // "2026-08-23"
  duration_sec: number;
  sessions: number;
}

export interface ActiveHourPoint {
  hour: number;         // 0-23
  sessions: number;
  duration_sec: number;
}

export interface RunStatusPoint {
  status: string;
  count: number;
}

export interface ActivityItem {
  ts: string;
  type: "run" | "log";
  title: string;
  status: string;        // success / failed / running / waiting_for_user 等
  run_id: string | null;
  project_id: string | null;
  duration_sec: number | null;
  detail: string;
}

export interface DashboardSummary {
  ts: string;
  status: DashboardStatus;
  projects: DashboardProjects;
  apps: DashboardApp[];
  usage: DashboardUsage;
  time_trend: TimeTrendPoint[];
  active_hours: ActiveHourPoint[];
  run_status: RunStatusPoint[];
  activity: ActivityItem[];
  errors_today: number;
}

// =====================================================================
// API
// =====================================================================

/** 拉取工作台总览聚合数据（一次性返回大屏全部数据）。 */
export function fetchDashboardSummary(days = 7, limit = 10): Promise<DashboardSummary> {
  return request<DashboardSummary>(
    `/api/dashboard/summary?days=${days}&limit=${limit}`,
  );
}
