/** NewProjectDialog — 新建项目弹窗（阶段 7.8 增强；7.9.8 Windows 风格选择器）。
 *
 * 改动：
 * - 工作目录必填（+「选择文件夹」按钮 → 自研 Windows 11 风格 DirectoryPicker：
 *   左侧此电脑侧栏 + 顶部导航面包屑 + 目录网格，交互对齐系统对话框）
 * - 默认模型下拉（数据源 /api/options，chat 模型）
 * 对接 /api/projects POST（routes/projects.py create_project，已支持 default_model）。
 */

import { useEffect, useRef, useState } from "react";
import { FolderOpen, ChevronDown } from "lucide-react";
import { fetchOptions, type ModelOption } from "../lib/api";
import ModelIcon from "./ModelIcon";
import DirectoryPicker from "./DirectoryPicker";

export default function NewProjectDialog({
  onCancel,
  onCreate,
}: {
  onCancel: () => void;
  onCreate: (name: string, workDir: string, defaultModel: string) => void;
}) {
  const [name, setName] = useState("");
  const [workDir, setWorkDir] = useState("");
  const [defaultModel, setDefaultModel] = useState("");
  const [models, setModels] = useState<ModelOption[]>([]);
  // 阶段 7.9.8：自研 Windows 风格目录选择器开关
  const [picking, setPicking] = useState(false);
  // 默认模型自定义下拉（阶段 7.9.2：显示模型官方 logo）
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const modelMenuRef = useRef<HTMLDivElement>(null);

  const currentModel = models.find((m) => m.id === defaultModel) || null;

  // 点击外部关闭模型下拉
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (modelMenuRef.current && !modelMenuRef.current.contains(e.target as Node)) {
        setModelMenuOpen(false);
      }
    };
    window.addEventListener("click", handler);
    return () => window.removeEventListener("click", handler);
  }, []);

  // 加载 chat 模型列表，默认选中全局默认（存唯一 model.id）
  useEffect(() => {
    fetchOptions()
      .then((opts) => {
        const chat = opts.models.filter((m) => m.type === "chat");
        setModels(chat);
        const def = chat.find((m) => m.is_default === 1);
        setDefaultModel(def?.id || chat[0]?.id || "");
      })
      .catch(() => { /* 静默：无模型时不阻止创建 */ });
  }, []);

  function handleBrowse() {
    // 阶段 7.9.8：打开自研 Windows 风格目录选择器
    setPicking(true);
  }

  const canSubmit = name.trim() !== "" && workDir.trim() !== "";

  const submit = () => {
    if (!canSubmit) return;
    onCreate(name.trim(), workDir.trim(), defaultModel);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={onCancel}>
      <div
        className="w-96 rounded-xl border border-zinc-200 bg-white p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="mb-4 text-[15px] font-semibold text-zinc-800">新建项目</h2>
        <label className="mb-2 block text-[12px] font-medium text-zinc-600">项目名称 <span className="text-red-500">*</span></label>
        <input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
          placeholder="例如：2026 销售提成核对"
          className="mb-3 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm text-zinc-800 outline-none focus:border-blue-500"
        />
        <label className="mb-2 block text-[12px] font-medium text-zinc-600">工作目录 <span className="text-red-500">*</span></label>
        <div className="mb-3 flex gap-2">
          <input
            value={workDir}
            onChange={(e) => setWorkDir(e.target.value)}
            placeholder="如 test-fixtures/phase5 或绝对路径"
            className="min-w-0 flex-1 rounded-md border border-zinc-300 px-3 py-2 text-sm text-zinc-800 outline-none focus:border-blue-500"
          />
          <button
            type="button"
            onClick={handleBrowse}
            title="选择文件夹（Windows 风格对话框）"
            className="flex shrink-0 items-center gap-1 rounded-md border border-zinc-300 px-2.5 text-[12px] text-zinc-600 hover:bg-zinc-100"
          >
            <FolderOpen size={13} /> 选择文件夹
          </button>
        </div>
        {!workDir.trim() && <p className="-mt-1.5 mb-3 text-[11px] text-zinc-400">工作目录为必填项，可手动输入或点击「浏览」选择</p>}
        <label className="mb-2 block text-[12px] font-medium text-zinc-600">默认模型</label>
        <div className="relative mb-4" ref={modelMenuRef}>
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); setModelMenuOpen((o) => !o); }}
            className="flex w-full items-center gap-2 rounded-md border border-zinc-300 px-3 py-2 text-sm text-zinc-800 outline-none focus:border-blue-500"
          >
            {currentModel ? (
              <>
                <ModelIcon name={currentModel.name} icon={currentModel.icon} size={14} />
                <span className="flex-1 truncate text-left">{currentModel.name}</span>
              </>
            ) : (
              <span className="flex-1 text-left text-zinc-400">（无可用模型）</span>
            )}
            <ChevronDown size={13} className="text-zinc-400" />
          </button>
          {modelMenuOpen && (
            <div className="absolute left-0 top-full z-50 mt-1 max-h-56 w-full overflow-y-auto rounded-md border border-zinc-200 bg-white py-1 shadow-xl">
              {models.length === 0 && (
                <div className="px-3 py-2 text-[12px] text-zinc-400">（无可用模型）</div>
              )}
              {models.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  onClick={(e) => { e.stopPropagation(); setDefaultModel(m.id); setModelMenuOpen(false); }}
                  className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-[13px] hover:bg-zinc-100 ${
                    m.id === defaultModel ? "bg-blue-50 text-blue-700" : "text-zinc-700"
                  }`}
                >
                  <ModelIcon name={m.name} icon={m.icon} size={14} />
                  <span className="flex-1 truncate">{m.name}</span>
                  {m.is_default === 1 && <span className="rounded bg-blue-50 px-1.5 text-[10px] text-blue-600">默认</span>}
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="flex justify-end gap-2">
          <button
            onClick={onCancel}
            className="rounded-md px-4 py-2 text-sm text-zinc-600 hover:bg-zinc-100"
          >
            取消
          </button>
          <button
            onClick={submit}
            disabled={!canSubmit}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-500 disabled:opacity-40"
          >
            创建
          </button>
        </div>
      </div>
      {/* 阶段 7.9.8：自研 Windows 11 风格目录选择器 */}
      {picking && (
        <DirectoryPicker
          onSelect={(path) => { setWorkDir(path); setPicking(false); }}
          onCancel={() => setPicking(false)}
        />
      )}
    </div>
  );
}

