/** AiConfigPage — AI 功能配置页（阶段 7.8 重构 + 2026-08-19 Skill Tab）。
 *
 * 功能（三个子导航）：
 * - 模型配置：供应商卡片列表，卡片内嵌模型（编辑/删除/设默认/添加）
 * - 智能体配置：通用智能体能力 + 工具罗列（纯静态展示，不可操控）
 * - Skill 配置：Skill 目录静态展示（职责/工作流可视化/约束，不可操控）
 * 对接：/api/models/* + /api/agents/<id>/tools + /api/skills/*
 */

import { useCallback, useEffect, useState } from "react";
import {
  Plus, Pencil, Trash2, RefreshCw, Server, Cpu, Plug, Sparkles, Star, BookOpen,
} from "lucide-react";
import {
  listProviders, createProvider, updateProvider, deleteProvider,
  createModel, updateModel, deleteModel, testModelConnection, fetchOptions,
  fetchAgent, fetchAgentTools,
  type Provider, type ModelRecord, type AgentDetail, type ToolCategory,
} from "../lib/api";
import ModelIcon, { MODEL_ICON_LIBRARY, matchModelIcon } from "../components/ModelIcon";
import SkillConfigPanel from "../components/SkillConfigPanel";

// ---------- 供应商表单 ----------

interface ProviderForm {
  name: string;
  api_url: string;
  api_key: string;
  description: string;
}

interface ModelForm {
  name: string;
  type: string;
  capabilities: string;
  context_window: number;
  is_default: boolean;
  icon: string;
}

const EMPTY_PROVIDER: ProviderForm = { name: "", api_url: "", api_key: "", description: "" };
const EMPTY_MODEL: ModelForm = { name: "", type: "chat", capabilities: "", context_window: 200000, is_default: false, icon: "" };

export default function AiConfigPage() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [modelsByProvider, setModelsByProvider] = useState<Record<string, ModelRecord[]>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<"models" | "agent" | "skills">("models");
  // 智能体配置（只读展示）
  const [agentDetail, setAgentDetail] = useState<AgentDetail | null>(null);
  const [toolCatalog, setToolCatalog] = useState<ToolCategory[]>([]);
  // Skill 面板刷新：key 递增强制重挂载（2026-08-20：刷新按钮按 tab 分派）
  const [skillRefreshKey, setSkillRefreshKey] = useState(0);
  // 弹窗状态
  const [providerDialog, setProviderDialog] = useState<{ editing: Provider | null; form: ProviderForm } | null>(null);
  const [modelDialog, setModelDialog] = useState<{ providerId: string; editing: ModelRecord | null; form: ModelForm } | null>(null);
  const [testState, setTestState] = useState<{ loading: boolean; result: string; isError: boolean }>({ loading: false, result: "", isError: false });

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [ps, opts] = await Promise.all([listProviders(), fetchOptions()]);
      setProviders(ps);
      // 按 provider_id 分组模型（/api/options 提供全量）
      const map: Record<string, ModelRecord[]> = {};
      for (const p of ps) {
        map[p.id] = [];
      }
      for (const m of opts.models) {
        if (!map[m.provider_id]) map[m.provider_id] = [];
        map[m.provider_id].push(m);
      }
      setModelsByProvider(map);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  // 加载智能体配置（只读展示，默认取第一个智能体）
  const loadAgent = useCallback(async (agentId?: string) => {
    try {
      const opts = await fetchOptions();
      const target = agentId || opts.agents[0]?.id;
      if (!target) return;
      const [detail, tools] = await Promise.all([
        fetchAgent(target),
        fetchAgentTools(target),
      ]);
      setAgentDetail(detail.agent);
      setToolCatalog(tools.catalog || []);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // 切到智能体 Tab 时加载数据（懒加载）
  useEffect(() => {
    if (activeTab === "agent") loadAgent();
  }, [activeTab, loadAgent]);

  // ---------- 模型操作：设为默认 ----------

  async function handleSetDefaultModel(m: ModelRecord) {
    try {
      await updateModel(m.id, { is_default: 1 });
      await load();
    } catch (e) {
      alert(`设置默认模型失败: ${(e as Error).message}`);
    }
  }

  // ---------- 供应商操作 ----------

  async function handleSaveProvider() {
    if (!providerDialog) return;
    try {
      if (providerDialog.editing) {
        await updateProvider(providerDialog.editing.id, providerDialog.form);
      } else {
        await createProvider(providerDialog.form);
      }
      setProviderDialog(null);
      await load();
    } catch (e) {
      alert(`保存供应商失败: ${(e as Error).message}`);
    }
  }

  async function handleDeleteProvider(p: Provider) {
    if (!confirm(`确定删除供应商「${p.name}」？其下所有模型将一并删除。`)) return;
    try {
      await deleteProvider(p.id);
      await load();
    } catch (e) {
      alert(`删除失败: ${(e as Error).message}`);
    }
  }

  async function handleTestConnection() {
    if (!providerDialog) return;
    setTestState({ loading: true, result: "", isError: false });
    try {
      const r = await testModelConnection({
        api_url: providerDialog.form.api_url,
        api_key: providerDialog.form.api_key,
        model: "test",
      });
      setTestState({ loading: false, result: r.message, isError: false });
    } catch (e) {
      setTestState({ loading: false, result: (e as Error).message, isError: true });
    }
  }

  // ---------- 模型操作 ----------

  async function handleSaveModel() {
    if (!modelDialog) return;
    try {
      const form = modelDialog.form;
      if (modelDialog.editing) {
        await updateModel(modelDialog.editing.id, { ...form, is_default: form.is_default ? 1 : 0 });
      } else {
        await createModel(modelDialog.providerId, { ...form, is_default: form.is_default ? 1 : 0 });
      }
      setModelDialog(null);
      await load();
    } catch (e) {
      alert(`保存模型失败: ${(e as Error).message}`);
    }
  }

  async function handleDeleteModel(m: ModelRecord) {
    if (!confirm(`确定删除模型「${m.name}」？`)) return;
    try {
      await deleteModel(m.id);
      await load();
    } catch (e) {
      alert(`删除失败: ${(e as Error).message}`);
    }
  }

  // ---------- 渲染 ----------

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      {/* 头部 */}
      <div className="border-b border-zinc-200 bg-white px-6 py-4">
        <h1 className="text-lg font-semibold text-zinc-800">AI 功能配置</h1>
        <p className="mt-0.5 text-[12.5px] text-zinc-500">配置模型供应商与模型，供对话引擎调用</p>
      </div>

      {/* Tab */}
      <div className="flex gap-1 border-b border-zinc-200 bg-white px-6">
        <TabBtn active={activeTab === "models"} onClick={() => setActiveTab("models")} icon={<Cpu size={13} />} label="模型配置" />
        <TabBtn active={activeTab === "agent"} onClick={() => setActiveTab("agent")} icon={<Sparkles size={13} />} label="智能体配置" />
        <TabBtn active={activeTab === "skills"} onClick={() => setActiveTab("skills")} icon={<BookOpen size={13} />} label="Skill 配置" />
        <div className="ml-auto flex items-center gap-1 pb-2 pt-1.5">
          <button
            className="rounded p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600"
            onClick={() => {
              if (activeTab === "models") load();
              else if (activeTab === "agent") loadAgent();
              else setSkillRefreshKey((k) => k + 1);
            }}
            title="刷新"
          >
            <RefreshCw size={14} />
          </button>
          {activeTab === "models" && (
            <button
              onClick={() => setProviderDialog({ editing: null, form: { ...EMPTY_PROVIDER } })}
              title="新增供应商"
              className="rounded p-1.5 text-blue-600 hover:bg-blue-50"
            >
              <Plus size={15} />
            </button>
          )}
        </div>
      </div>

      {/* 内容 */}
      <div className="flex-1 overflow-y-auto p-6">
        {loading && <div className="text-[13px] text-zinc-400">加载中…</div>}
        {error && <div className="text-[13px] text-red-500">{error}</div>}

        {!loading && !error && activeTab === "models" && (
          <div className="mx-auto max-w-3xl space-y-2">
            {providers.length === 0 && (
              <div className="rounded-lg border border-dashed border-zinc-300 p-8 text-center text-[13px] text-zinc-400">
                暂无供应商，点击右上角「＋」添加
              </div>
            )}
            {providers.map((p) => (
              <div key={p.id} className="rounded-lg border border-zinc-200 bg-white p-4">
                {/* 供应商头部：编辑/删除 */}
                <div className="flex items-center gap-2">
                  <Server size={15} className="text-blue-600" />
                  <span className="text-[13.5px] font-medium text-zinc-800">{p.name}</span>
                  <span className={`rounded-full px-2 py-0.5 text-[10px] ${p.status === "available" ? "bg-green-50 text-green-700" : "bg-amber-50 text-amber-700"}`}>
                    {p.status === "available" ? "可用" : p.status}
                  </span>
                  <div className="ml-auto flex gap-1">
                    <button className="rounded p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600" title="编辑供应商" onClick={() => setProviderDialog({ editing: p, form: { name: p.name, api_url: p.api_url, api_key: p.api_key, description: p.description || "" } })}>
                      <Pencil size={13} />
                    </button>
                    <button className="rounded p-1.5 text-zinc-400 hover:bg-red-50 hover:text-red-600" title="删除供应商" onClick={() => handleDeleteProvider(p)}>
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>
                <div className="mt-1 truncate font-mono text-[11px] text-zinc-400">{p.api_url}</div>
                {/* 卡片内嵌模型列表（每行可编辑/删除/设默认） */}
                <div className="mt-2 space-y-1 border-t border-zinc-100 pt-2">
                  {(modelsByProvider[p.id] || []).map((m) => (
                    <div key={m.id} className="flex items-center gap-2 rounded px-2 py-1 text-[12px] text-zinc-600 hover:bg-zinc-50">
                      <ModelIcon name={m.name} icon={m.icon} size={12} />
                      <span className="font-medium text-zinc-700">{m.name}</span>
                      {m.is_default === 1 && <span className="rounded bg-blue-50 px-1.5 text-[10px] text-blue-700">默认</span>}
                      <span className="text-[10px] text-zinc-400">{m.capabilities || m.type} · {m.context_window} ctx</span>
                      <div className="ml-auto flex gap-0.5">
                        <button
                          className="rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600"
                          title="设为默认模型"
                          disabled={m.is_default === 1}
                          onClick={() => handleSetDefaultModel(m)}
                        >
                          <Star size={12} className={m.is_default === 1 ? "text-blue-600" : ""} />
                        </button>
                        <button
                          className="rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600"
                          title="编辑模型"
                          onClick={() => setModelDialog({ providerId: p.id, editing: m, form: { name: m.name, type: m.type, capabilities: m.capabilities, context_window: m.context_window, is_default: m.is_default === 1, icon: m.icon || "" } })}
                        >
                          <Pencil size={12} />
                        </button>
                        <button className="rounded p-1 text-zinc-400 hover:bg-red-50 hover:text-red-600" title="删除模型" onClick={() => handleDeleteModel(m)}>
                          <Trash2 size={12} />
                        </button>
                      </div>
                    </div>
                  ))}
                  {(modelsByProvider[p.id] || []).length === 0 && (
                    <div className="text-[11px] text-zinc-400">该供应商暂无模型，点击下方添加</div>
                  )}
                  <button
                    onClick={() => setModelDialog({ providerId: p.id, editing: null, form: { ...EMPTY_MODEL } })}
                    className="flex items-center gap-1 rounded px-2 py-1 text-[11px] text-blue-600 hover:bg-blue-50"
                  >
                    <Plus size={11} /> 添加模型
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {!loading && !error && activeTab === "agent" && (
          <AgentConfigPanel detail={agentDetail} catalog={toolCatalog} />
        )}

        {activeTab === "skills" && (
          <SkillConfigPanel key={skillRefreshKey} />
        )}
      </div>

      {/* 供应商弹窗 */}
      {providerDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={() => setProviderDialog(null)}>
          <div className="w-96 rounded-xl border border-zinc-200 bg-white p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="mb-4 text-[14px] font-semibold text-zinc-800">
              {providerDialog.editing ? "编辑供应商" : "新建供应商"}
            </h3>
            <FormField label="名称" value={providerDialog.form.name} onChange={(v) => setProviderDialog({ ...providerDialog, form: { ...providerDialog.form, name: v } })} placeholder="如 DeepSeek / 内网代理" />
            <FormField label="API 地址" value={providerDialog.form.api_url} onChange={(v) => setProviderDialog({ ...providerDialog, form: { ...providerDialog.form, api_url: v } })} placeholder="https://api.deepseek.com" />
            <FormField label="API Key" value={providerDialog.form.api_key} onChange={(v) => setProviderDialog({ ...providerDialog, form: { ...providerDialog.form, api_key: v } })} placeholder="sk-..." type="password" />
            <FormField label="描述（可选）" value={providerDialog.form.description} onChange={(v) => setProviderDialog({ ...providerDialog, form: { ...providerDialog.form, description: v } })} placeholder="备注" />
            <div className="mt-2 flex items-center gap-2">
              <button
                onClick={handleTestConnection}
                disabled={testState.loading}
                className="flex items-center gap-1 rounded-md border border-zinc-300 px-3 py-1.5 text-[12px] text-zinc-600 hover:bg-zinc-100 disabled:opacity-50"
              >
                <Plug size={12} /> {testState.loading ? "测试中…" : "测试连接"}
              </button>
              {testState.result && (
                <span className={`text-[11px] ${testState.isError ? "text-red-500" : "text-green-600"}`}>
                  {testState.isError ? "✗ " : "✓ "}{testState.result.slice(0, 40)}
                </span>
              )}
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button className="rounded-md px-4 py-1.5 text-[13px] text-zinc-600 hover:bg-zinc-100" onClick={() => setProviderDialog(null)}>取消</button>
              <button
                onClick={handleSaveProvider}
                disabled={!providerDialog.form.name || !providerDialog.form.api_url}
                className="rounded-md bg-blue-600 px-4 py-1.5 text-[13px] text-white hover:bg-blue-500 disabled:opacity-40"
              >
                保存
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 模型弹窗 */}
      {modelDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={() => setModelDialog(null)}>
          <div className="w-96 rounded-xl border border-zinc-200 bg-white p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="mb-4 text-[14px] font-semibold text-zinc-800">
              {modelDialog.editing ? "编辑模型" : "添加模型"}
            </h3>
            <FormField label="模型名称" value={modelDialog.form.name} onChange={(v) => setModelDialog({ ...modelDialog, form: { ...modelDialog.form, name: v } })} placeholder="如 deepseek-chat / glm-4" />
            <label className="mb-1 block text-[12px] font-medium text-zinc-600">图标</label>
            {/* 图标网格选择器——输入名称自动匹配高亮，点选覆盖，选中变蓝即表达状态 */}
            <div className="mb-3">
              <div className="flex flex-wrap gap-1.5">
                {MODEL_ICON_LIBRARY.map((ic) => {
                  const autoMatched = !modelDialog.form.icon && matchModelIcon(modelDialog.form.name) === ic.file;
                  const selected = modelDialog.form.icon === ic.file;
                  return (
                    <button
                      key={ic.file}
                      type="button"
                      title={ic.label}
                      onClick={(e) => {
                        e.stopPropagation();
                        setModelDialog({
                          ...modelDialog,
                          form: {
                            ...modelDialog.form,
                            icon: selected ? "" : ic.file, // 再点一次取消（回退自动）
                          },
                        });
                      }}
                      className={`flex items-center gap-1 rounded-md border px-1.5 py-1 transition-colors ${
                        selected
                          ? "border-blue-500 bg-blue-50"
                          : autoMatched
                            ? "border-blue-300 bg-blue-50/50 hover:bg-blue-50"
                            : "border-zinc-200 hover:bg-zinc-50"
                      }`}
                    >
                      <ModelIcon name={ic.label} icon={ic.file} size={16} />
                      <span className={`text-[10px] ${selected ? "text-blue-700" : autoMatched ? "text-blue-600" : "text-zinc-500"}`}>
                        {ic.label}
                      </span>
                      {autoMatched && !selected && (
                        <span className="rounded bg-blue-600 px-1 text-[8px] text-white">自动</span>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>
            <label className="mb-1 block text-[12px] font-medium text-zinc-600">类型</label>
            <select
              value={modelDialog.form.type}
              onChange={(e) => setModelDialog({ ...modelDialog, form: { ...modelDialog.form, type: e.target.value } })}
              className="mb-3 w-full rounded-md border border-zinc-300 px-3 py-2 text-[13px] text-zinc-800 outline-none focus:border-blue-500"
            >
              <option value="chat">chat（对话）</option>
              <option value="embedding">embedding（嵌入）</option>
              <option value="reranker">reranker（排序）</option>
            </select>
            <FormField label="能力（逗号分隔）" value={modelDialog.form.capabilities} onChange={(v) => setModelDialog({ ...modelDialog, form: { ...modelDialog.form, capabilities: v } })} placeholder="对话,工具" />
            <FormField label="上下文窗口" value={String(modelDialog.form.context_window)} onChange={(v) => setModelDialog({ ...modelDialog, form: { ...modelDialog.form, context_window: Number(v) || 0 } })} placeholder="200000" />
            <label className="mb-3 flex items-center gap-2 text-[12.5px] text-zinc-700">
              <input
                type="checkbox"
                checked={modelDialog.form.is_default}
                onChange={(e) => setModelDialog({ ...modelDialog, form: { ...modelDialog.form, is_default: e.target.checked } })}
                className="h-3.5 w-3.5 rounded border-zinc-300"
              />
              设为默认模型
            </label>
            <div className="flex justify-end gap-2">
              <button className="rounded-md px-4 py-1.5 text-[13px] text-zinc-600 hover:bg-zinc-100" onClick={() => setModelDialog(null)}>取消</button>
              <button
                onClick={handleSaveModel}
                disabled={!modelDialog.form.name}
                className="rounded-md bg-blue-600 px-4 py-1.5 text-[13px] text-white hover:bg-blue-500 disabled:opacity-40"
              >
                保存
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------- 子组件 ----------

function TabBtn({ active, onClick, icon, label }: { active: boolean; onClick: () => void; icon: React.ReactNode; label: string }) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1.5 border-b-2 px-3 pb-2 pt-1 text-[13px] transition-colors ${
        active ? "border-blue-600 text-blue-700" : "border-transparent text-zinc-500 hover:text-zinc-700"
      }`}
    >
      {icon}
      {label}
    </button>
  );
}

function FormField({ label, value, onChange, placeholder, type }: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string; type?: string;
}) {
  return (
    <>
      <label className="mb-1 block text-[12px] font-medium text-zinc-600">{label}</label>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        type={type || "text"}
        placeholder={placeholder}
        className="mb-3 w-full rounded-md border border-zinc-300 px-3 py-2 text-[13px] text-zinc-800 outline-none focus:border-blue-500"
      />
    </>
  );
}

// ---------- 智能体配置面板（只读展示，不可操控） ----------

function AgentConfigPanel({ detail, catalog }: { detail: AgentDetail | null; catalog: ToolCategory[] }) {
  if (!detail) {
    return <div className="text-[13px] text-zinc-400">加载智能体配置中…</div>;
  }
  const wf = detail.workflow || {};
  const cp = detail.context_policy || {};
  return (
    <div className="mx-auto max-w-3xl space-y-4">
      {/* 概览 */}
      <div className="rounded-lg border border-zinc-200 bg-white p-4">
        <div className="flex items-center gap-2">
          <Sparkles size={16} className="text-blue-600" />
          <span className="text-[14px] font-semibold text-zinc-800">{detail.name || "通用智能体"}</span>
          <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[10px] text-blue-700">v{detail.version || "1.0.0"}</span>
          <span className="ml-auto rounded-full bg-green-50 px-2 py-0.5 text-[10px] text-green-700">启用</span>
        </div>
        {detail.description && <p className="mt-2 text-[12.5px] leading-relaxed text-zinc-500">{detail.description}</p>}
      </div>

      {/* 工作流策略 */}
      <div className="rounded-lg border border-zinc-200 bg-white p-4">
        <div className="mb-2 text-[12.5px] font-semibold text-zinc-700">工作流策略</div>
        <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-[12px] text-zinc-600">
          <InfoRow label="执行模式" value={wf.mode === "guided_execution" ? "引导式执行" : String(wf.mode || "-")} />
          <InfoRow label="最大迭代" value={wf.max_iterations ? String(wf.max_iterations) : "无上限"} />
          <InfoRow label="计划审批" value={wf.require_plan_approval ? "需要" : "不需要"} />
          <InfoRow label="执行前澄清" value={wf.require_clarification_before_execution ? "需要" : "不需要"} />
          <InfoRow label="自动自审" value={wf.require_self_audit ? "开启" : "关闭"} />
          <InfoRow label="上下文预算" value={String(wf.context_token_budget ?? "-")} />
        </div>
      </div>

      {/* 上下文策略 */}
      <div className="rounded-lg border border-zinc-200 bg-white p-4">
        <div className="mb-2 text-[12.5px] font-semibold text-zinc-700">上下文策略</div>
        <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-[12px] text-zinc-600">
          <InfoRow label="文件引用" value={cp.file_reference ? "开启" : "关闭"} />
          <InfoRow label="对话记忆" value={cp.conversation_memory ? "开启" : "关闭"} />
          <InfoRow label="工具结果注入" value={cp.tool_result_injection ? "开启" : "关闭"} />
          <InfoRow label="历史轮数" value={String(cp.max_history_turns ?? "-")} />
          <InfoRow label="最大上下文文件" value={String(cp.max_context_files ?? "-")} />
        </div>
      </div>

      {/* 工具罗列 */}
      <div className="rounded-lg border border-zinc-200 bg-white p-4">
        <div className="mb-2 flex items-center gap-1.5 text-[12.5px] font-semibold text-zinc-700">
          <WrenchIcon />
          工具罗列
          <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-[10px] font-normal text-zinc-500">
            {catalog.reduce((n, g) => n + g.tools.length, 0)} 个
          </span>
        </div>
        {catalog.length === 0 && <div className="text-[12px] text-zinc-400">暂无工具数据</div>}
        {catalog.map((g) => (
          <div key={g.category} className="mb-3">
            <div className="mb-1 text-[11px] font-medium text-zinc-500">{g.category}（{g.tools.length}）</div>
            <div className="space-y-0.5">
              {g.tools.map((t) => (
                <div key={t.name} className="flex items-baseline gap-2 rounded px-2 py-0.5 text-[12px] hover:bg-zinc-50">
                  <code className="shrink-0 font-mono text-[11px] font-medium text-blue-700">{t.name}</code>
                  <span className="min-w-0 flex-1 leading-snug text-zinc-500">{t.description}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between border-b border-zinc-50 py-1">
      <span className="text-zinc-400">{label}</span>
      <span className="font-medium text-zinc-700">{value}</span>
    </div>
  );
}

function WrenchIcon() {
  return (
    <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-zinc-400">
      <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
    </svg>
  );
}
