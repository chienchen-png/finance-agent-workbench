/** NavSidebar — 全局左侧导航栏（阶段 7：多页面 + 项目 ⋮ 菜单）。
 *
 * 结构：上=工作台/AI配置；中=项目列表（⋮ 菜单：删除/创建副本）；下=集成应用
 * 导航：onNavigate(view)；项目操作：onDeleteProject/onDuplicateProject
 */

import { useState, useRef } from "react";
import {
  LayoutDashboard,
  Settings,
  FolderKanban,
  AppWindow,
  Plus,
  ChevronDown,
  MoreHorizontal,
  Copy,
  Trash2,
  Pencil,
  Workflow,
} from "lucide-react";
import type { Project } from "../lib/api";
import { deleteProject, duplicateProject, updateProject } from "../lib/api";

export type View = "chat" | "ai-config" | "dashboard" | "app-sales-check" | "app-finmod";

interface NavItem {
  id: string;
  label: string;
  icon: React.ReactNode;
  view: View;
}

const TOP_NAV: NavItem[] = [
  { id: "dashboard", label: "工作台总览", icon: <LayoutDashboard size={16} />, view: "dashboard" },
  { id: "ai-config", label: "AI 功能配置", icon: <Settings size={16} />, view: "ai-config" },
];

const APP_NAV: NavItem[] = [
  // 阶段 7.9.9 修复：集成应用用独立 view（此前与工作台总览同为 dashboard，
  // 导致点击时两处同时高亮）
  // 2026-08-20：集成应用一改名为「数据核对与校验」（设计文档 v1.0）
  { id: "app-sales-check", label: "数据核对与校验", icon: <AppWindow size={16} />, view: "app-sales-check" },
  // 2026-08-21：集成应用二「财务建模与分析」（P1 元数据层）
  { id: "app-finmod", label: "财务建模与分析", icon: <AppWindow size={16} />, view: "app-finmod" },
];

export default function NavSidebar({
  projects,
  activeProjectId,
  activeView,
  onSelectProject,
  onNewProject,
  onNavigate,
  onDeleteProject,
  onDuplicateProject,
  onRenameProject,
}: {
  projects: Project[];
  activeProjectId: string | null;
  activeView: View;
  onSelectProject: (id: string) => void;
  onNewProject: () => void;
  onNavigate: (v: View) => void;
  onDeleteProject: (id: string) => void;
  onDuplicateProject: (p: Project) => void;
  onRenameProject: (id: string, name: string) => void;
}) {
  const [projectsOpen, setProjectsOpen] = useState(true);
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  // 阶段 7.9.5：项目内联重命名（ChatGPT/Codex 式）
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameVal, setRenameVal] = useState("");
  const renameDoneRef = useRef(false);

  // 阶段 7.9.5：启动重命名
  function startRename(p: Project) {
    setRenameVal(p.name);
    setRenamingId(p.id);
    setMenuFor(null);
    renameDoneRef.current = false;
  }

  // 阶段 7.9.5：确认（Enter/失焦）
  async function commitRename(p: Project) {
    if (renameDoneRef.current) return;
    renameDoneRef.current = true;
    const name = renameVal.trim();
    setRenamingId(null);
    if (!name || name === p.name) return;
    try {
      await updateProject(p.id, { name });
      onRenameProject(p.id, name);
    } catch (e) {
      alert(`重命名失败: ${(e as Error).message}`);
    }
  }

  // 阶段 7.9.5：取消（Esc）
  function cancelRename() {
    if (renameDoneRef.current) return;
    renameDoneRef.current = true;
    setRenamingId(null);
  }

  const renderItem = (item: NavItem) => (
    <button
      key={item.id}
      onClick={() => onNavigate(item.view)}
      className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] transition-colors ${
        activeView === item.view
          ? "bg-zinc-300 text-zinc-900"
          : "text-zinc-600 hover:bg-zinc-200 hover:text-zinc-800"
      }`}
    >
      <span className="text-zinc-400">{item.icon}</span>
      <span className="truncate">{item.label}</span>
    </button>
  );

  async function handleDelete(p: Project) {
    if (!confirm(`确定删除项目「${p.name}」？其对话、数据库数据将一并删除（不影响原始文件）。`)) return;
    setBusy(p.id);
    try {
      await deleteProject(p.id);
      onDeleteProject(p.id);
    } catch (e) {
      alert(`删除失败: ${(e as Error).message}`);
    } finally {
      setBusy(null);
      setMenuFor(null);
    }
  }

  async function handleDuplicate(p: Project) {
    setBusy(p.id);
    try {
      const copy = await duplicateProject(p.id);
      onDuplicateProject(copy);
      alert(`已创建副本「${copy.name}」`);
    } catch (e) {
      alert(`创建副本失败: ${(e as Error).message}`);
    } finally {
      setBusy(null);
      setMenuFor(null);
    }
  }

  return (
    <aside className="flex w-56 shrink-0 flex-col border-r border-zinc-200 bg-zinc-100">
      {/* 顶部：Logo（阶段 7.9.11.6：图标居左 + 文字相对整个标题栏居中——
          比 flex-1 text-center 更靠左、更贴近图标） */}
      <div className="relative flex items-center border-b border-zinc-200 px-3 py-3">
        <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-zinc-900 text-white">
          <Workflow size={14} strokeWidth={2} />
        </div>
        <span className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 whitespace-nowrap text-sm font-semibold text-zinc-800">
          Finance Agent
        </span>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 py-2">
        {/* 上：工作台 / AI 配置 */}
        <div className="space-y-0.5">{TOP_NAV.map(renderItem)}</div>

        {/* 中：项目列表 */}
        <div className="mt-4">
          <div className="flex items-center justify-between px-2 pb-1">
            <button
              className="flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-zinc-500 hover:text-zinc-700"
              onClick={() => setProjectsOpen((o) => !o)}
            >
              <ChevronDown
                size={12}
                className={`transition-transform ${projectsOpen ? "" : "-rotate-90"}`}
              />
              项目
            </button>
            <button
              className="rounded p-0.5 text-zinc-500 hover:bg-zinc-200 hover:text-zinc-700"
              onClick={onNewProject}
              title="新建项目"
            >
              <Plus size={14} />
            </button>
          </div>
          {projectsOpen && (
            <div className="space-y-0.5">
              {projects.map((p) => (
                <div
                  key={p.id}
                  className={`group relative flex items-center rounded-md transition-colors ${
                    // 阶段 7.9.9 修复：项目高亮仅限 chat 视图（否则切到 AI 配置/
                    // 工作台/集成应用时项目列表仍保持深色，造成多处高亮）
                    activeProjectId === p.id && activeView === "chat" ? "bg-zinc-300" : "hover:bg-zinc-200"
                  }`}
                >
                  <button
                    onClick={() => { onSelectProject(p.id); onNavigate("chat"); }}
                    onKeyDown={(e) => { if (e.key === "F2") { e.preventDefault(); startRename(p); } }}
                    className="flex min-w-0 flex-1 items-center gap-2 px-2 py-1.5 text-left text-[13px] transition-colors"
                  >
                    <FolderKanban size={14} className="shrink-0 text-zinc-400" />
                    {renamingId === p.id ? (
                      <input
                        autoFocus
                        value={renameVal}
                        onChange={(e) => setRenameVal(e.target.value)}
                        onFocus={(e) => e.target.select()}
                        onClick={(e) => e.stopPropagation()}
                        onKeyDown={(e) => {
                          e.stopPropagation();
                          if (e.key === "Enter") commitRename(p);
                          else if (e.key === "Escape") cancelRename();
                        }}
                        onBlur={() => commitRename(p)}
                        className="min-w-0 flex-1 rounded border border-blue-500 px-1 py-0.5 text-[13px] text-zinc-800 outline-none"
                      />
                    ) : (
                      <span className="truncate">{p.name}</span>
                    )}
                  </button>
                  {/* ⋮ 菜单按钮 */}
                  <button
                    onClick={(e) => { e.stopPropagation(); setMenuFor(menuFor === p.id ? null : p.id); }}
                    className="mr-1 rounded p-0.5 text-zinc-400 opacity-0 transition-opacity hover:bg-white/50 hover:text-zinc-700 group-hover:opacity-100"
                    title="项目操作"
                  >
                    <MoreHorizontal size={14} />
                  </button>
                  {menuFor === p.id && (
                    <div
                      className="absolute right-1 top-full z-50 w-40 rounded-md border border-zinc-200 bg-white py-1 shadow-xl"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <MenuItem
                        icon={<Pencil size={13} />}
                        label="重命名"
                        disabled={busy === p.id}
                        onClick={() => startRename(p)}
                      />
                      <MenuItem
                        icon={<Copy size={13} />}
                        label="创建副本"
                        disabled={busy === p.id}
                        onClick={() => handleDuplicate(p)}
                      />
                      <MenuItem
                        icon={<Trash2 size={13} />}
                        label="删除项目"
                        danger
                        disabled={busy === p.id}
                        onClick={() => handleDelete(p)}
                      />
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 下：集成应用（阶段 5 预留） */}
        <div className="mt-4">
          <div className="px-2 pb-1 text-[11px] font-medium uppercase tracking-wide text-zinc-500">
            集成应用
          </div>
          <div className="space-y-0.5">{APP_NAV.map(renderItem)}</div>
        </div>
      </nav>
    </aside>
  );
}

function MenuItem({ icon, label, onClick, danger, disabled }: {
  icon: React.ReactNode; label: string; onClick: () => void; danger?: boolean; disabled?: boolean;
}) {
  return (
    <button
      className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-[12.5px] ${
        disabled ? "cursor-not-allowed text-zinc-300" : danger ? "text-red-600 hover:bg-red-50" : "text-zinc-700 hover:bg-zinc-100"
      }`}
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
    >
      {icon}
      <span className="truncate">{label}</span>
    </button>
  );
}
