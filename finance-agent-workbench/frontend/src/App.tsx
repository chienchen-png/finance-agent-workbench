import { useEffect, useState } from "react";
import { FolderOpen } from "lucide-react";
import NavSidebar from "./layout/NavSidebar";
import ChatPage from "./pages/ChatPage";
import AiConfigPage from "./pages/AiConfigPage";
import DataCheckAppPage from "./pages/DataCheckAppPage";
import FinModAppPage from "./pages/FinModAppPage";
import DashboardPage from "./pages/DashboardPage";
import PreviewPage from "./pages/PreviewPage";
import NewProjectDialog from "./components/NewProjectDialog";
import type { Project, ModelOption, AgentOption, Provider } from "./lib/api";
import { listProjects, createProject, fetchOptions, listProviders } from "./lib/api";

type View = "chat" | "ai-config" | "dashboard" | "app-sales-check" | "app-finmod";

/** D7：解析 URL 的 preview 参数（预览标签页模式）。返回 null 表示非预览。 */
function readPreviewParams(): { projectId: string; filePath: string } | null {
  const q = new URLSearchParams(window.location.search);
  if (q.get("preview") !== "1") return null;
  const projectId = q.get("project_id") || "";
  const filePath = q.get("path") || "";
  if (!projectId || !filePath) return null;
  return { projectId, filePath };
}

/** 应用根布局：左侧全局导航栏 + 主内容区（Codex 风格） */
export default function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [activeProject, setActiveProject] = useState<Project | null>(null);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [agents, setAgents] = useState<AgentOption[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [view, setView] = useState<View>("dashboard"); // 2026-08-24：应用首页 = 工作台总览（刷新默认进入）
  const [showNew, setShowNew] = useState(false);
  const [loading, setLoading] = useState(true);
  const preview = readPreviewParams(); // D7：预览标签页模式（只读，无需 setter）

  async function loadProjects() {
    try {
      const list = await listProjects();
      // 2026-08-20：过滤集成应用的隐藏项目（__app_ 前缀），不污染项目列表
      const visible = list.filter((p) => !p.name.startsWith("__app_"));
      setProjects(visible);
      // 自动选中第一个【可见】项目（不能用未过滤的 list——
      // __app_ 隐藏项目排在前面，会选中导致刷新后进入神秘聊天页）
      if (!activeProject && visible.length) {
        setActiveProject(visible[0]);
      }
    } catch (e) {
      console.error("加载项目失败", e);
    }
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [list, opts, ps] = await Promise.all([listProjects(), fetchOptions(), listProviders()]);
        if (cancelled) return;
        // 过滤集成应用的隐藏项目（__app_ 前缀）
        const visible = list.filter((p) => !p.name.startsWith("__app_"));
        setProjects(visible);
        setModels(opts.models);
        setAgents(opts.agents);
        setProviders(ps);
        // 只从【可见】项目中选择默认（避免选中 __app_ 隐藏项目）
        if (visible.length) setActiveProject(visible[0]);
      } catch (e) {
        console.error("初始化失败", e);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  async function handleNewProject(name: string, workDir: string, defaultModel: string) {
    try {
      const p = await createProject({
        name,
        work_dir: workDir,
        default_model: defaultModel || undefined,
      });
      await loadProjects();
      setActiveProject(p);
      setShowNew(false);
    } catch (e) {
      alert(`新建失败: ${(e as Error).message}`);
    }
  }

  const chatModels = models.filter((m) => m.type === "chat");
  void chatModels; // 保留：未来用于模型徽标选项

  if (loading && !preview) {
    return <div className="flex h-full items-center justify-center text-zinc-400">加载中…</div>;
  }

  // D7：预览标签页模式——全屏渲染 PreviewPage，不显示侧栏/主布局
  if (preview) {
    return (
      <PreviewPage
        projectId={preview.projectId}
        filePath={preview.filePath}
      />
    );
  }

  return (
    <div className="flex h-full overflow-hidden">
      <NavSidebar
        projects={projects}
        activeProjectId={activeProject?.id || null}
        activeView={view}
        onSelectProject={(id) => { setActiveProject(projects.find((p) => p.id === id) || null); setView("chat"); }}
        onNewProject={() => setShowNew(true)}
        onNavigate={setView}
        onDeleteProject={async (id) => {
          setProjects((ps) => ps.filter((p) => p.id !== id));
          if (activeProject?.id === id) setActiveProject(null);
        }}
        onDuplicateProject={(p) => setProjects((ps) => [...ps, p])}
        onRenameProject={(id, name) => {
          setProjects((ps) => ps.map((p) => (p.id === id ? { ...p, name } : p)));
          setActiveProject((prev) => (prev?.id === id ? { ...prev, name } : prev));
        }}
      />
      {view === "ai-config" && (
        <AiConfigPage />
      )}
      {view === "dashboard" && (
        <DashboardPage
          onNavigate={(v) => setView(v as View)}
          onSelectProject={(pid) => {
            const p = projects.find((x) => x.id === pid) || null;
            setActiveProject(p);
            setView("chat");
          }}
        />
      )}
      {view === "app-sales-check" && activeProject && (
        <DataCheckAppPage
          project={activeProject}
          models={models}
          agents={agents}
          providers={providers}
          defaultModel={activeProject.default_model || models.find((m) => m.is_default)?.name || models[0]?.name || ""}
        />
      )}
      {view === "app-sales-check" && !activeProject && (
        <div className="fade-in-up flex flex-1 flex-col items-center justify-center gap-4">
          <FolderOpen size={32} strokeWidth={1.5} className="text-zinc-400" />
          <div className="text-center">
            <p className="text-[15px] font-medium text-zinc-700">还没有打开项目</p>
            <p className="mt-1 text-[13px] text-zinc-400">数据核对需要项目数据库，请先选择或新建一个项目</p>
          </div>
        </div>
      )}
      {view === "app-finmod" && activeProject && (
        <FinModAppPage
          project={activeProject}
          models={models}
          agents={agents}
          providers={providers}
          defaultModel={activeProject.default_model || models.find((m) => m.is_default)?.name || models[0]?.name || ""}
        />
      )}
      {view === "app-finmod" && !activeProject && (
        <div className="fade-in-up flex flex-1 flex-col items-center justify-center gap-4">
          <FolderOpen size={32} strokeWidth={1.5} className="text-zinc-400" />
          <div className="text-center">
            <p className="text-[15px] font-medium text-zinc-700">还没有打开项目</p>
            <p className="mt-1 text-[13px] text-zinc-400">财务建模需要项目数据库，请先选择或新建一个项目</p>
          </div>
        </div>
      )}
      {view === "chat" && activeProject && (
        <ChatPage
          project={activeProject}
          models={models}
          agents={agents}
          providers={providers}
          defaultModel={activeProject.default_model || models.find((m) => m.is_default)?.name || models[0]?.name || ""}
          onModelChange={(modelId) => {
            // 持久化到本地 activeProject（存唯一 model.id），保证刷新/重进仍生效
            setActiveProject((p) => (p ? { ...p, default_model: modelId } : p));
          }}
        />
      )}
      {view === "chat" && !activeProject && (
        <div className="fade-in-up flex flex-1 flex-col items-center justify-center gap-4">
          {/* 阶段 7.9.11.2：与 ChatPage 空状态统一——单色线性图标，弃蓝紫渐变块 */}
          <FolderOpen size={32} strokeWidth={1.5} className="text-zinc-400" />
          <div className="text-center">
            <p className="text-[15px] font-medium text-zinc-700">还没有打开项目</p>
            <p className="mt-1 text-[13px] text-zinc-400">从左侧选择项目，或新建一个开始</p>
          </div>
          <button
            onClick={() => setShowNew(true)}
            className="rounded-lg bg-blue-600 px-5 py-2 text-[13px] font-medium text-white shadow-sm transition-colors hover:bg-blue-500"
          >
            ＋ 新建项目
          </button>
        </div>
      )}
      {showNew && (
        <NewProjectDialog
          onCancel={() => setShowNew(false)}
          onCreate={handleNewProject}
        />
      )}
    </div>
  );
}
