---
applyTo: "finance-agent-workbench/routes/apps.py,finance-agent-workbench/routes/files.py,finance-agent-workbench/routes/finmod_refs.py,finance-agent-workbench/tools/reconcile_tool.py,finance-agent-workbench/tools/finmod_eval.py,finance-agent-workbench/tools/finmod_merge.py,finance-agent-workbench/tools/finmod_prep.py,finance-agent-workbench/tools/finmod_py_charts.py,finance-agent-workbench/tools/_finmod_models.py,finance-agent-workbench/tools/financial_analysis_tools.py,finance-agent-workbench/frontend/src/pages/DataCheckAppPage.tsx,finance-agent-workbench/frontend/src/pages/FinModAppPage.tsx,finance-agent-workbench/frontend/src/components/ReconWizard.tsx,finance-agent-workbench/frontend/src/components/ChartPreview.tsx,finance-agent-workbench/frontend/src/components/ChartRenderer.tsx,finance-agent-workbench/frontend/src/components/MarkdownEditor.tsx,finance-agent-workbench/frontend/src/hooks/**"
---

# 【领地守卫】角色 B — 报告链路

> **这些文件归「角色 B」负责。如果你不是角色 B，请不要修改本领地内的文件。**

如果你是被用户直接指派来改这些文件的，请先确认用户已与角色 B 协调，并在 PR 中说明原因。

---

## 本领地负责的问题

| 编号 | 问题 | 核心 |
| :--- | :--- | :--- |
| **3** | 数据核对报告问题 | recon 应用的核对报告质量 |
| **7** | 报告问题 | finmod 报告生成 / 导出 Word / 排版 |

> 这两个问题**共处同一个 3050 行文件 `routes/apps.py`**，因此必须由同一人负责。

---

## 核心入口（改之前先定位）

| 场景 | 文件 | 函数 |
| :--- | :--- | :--- |
| **核对报告** | `routes/apps.py` | `REPORT_SYSTEM`(L144)、`_fallback_report`(L224)、`_build_report_user_content`(L279)、`_tool_to_recon`(L323)、`_chat_complete` |
| 核对引擎 | `tools/reconcile_tool.py` | `reconcile_variables` |
| 核对端点 | `routes/apps.py` | `recon_verify` / `recon_audit` / `recon_writeback` |
| **建模报告** | `routes/apps.py` | `finmod_export_md`(L2878)、`finmod_export_docx`(L2941)、`_fallback_md_report` |
| 建模执行 | `routes/apps.py` | `finmod_run`(L2220)、`finmod_analyze`(L2489) |
| 模型 / 图表元数据 | `routes/finmod_refs.py` | 32 模型 + 24 图表的解析 |
| **通用 md→Word** | `routes/files.py` | `export_docx`(L519)、`_find_pandoc` |
| 前端核对页 | `pages/DataCheckAppPage.tsx` | — |
| 前端建模页 | `pages/FinModAppPage.tsx` | 步骤 4（报告） |

---

## 本领地特别规则

1. **`routes/apps.py` 是最危险的共享文件。**
   Phase 0 解耦完成后，它会拆为 `routes/recon.py` + `routes/finmod.py` + `routes/_llm_report.py`。
   在拆分完成前，**任何其他人改动它都必须先找角色 B**。

2. **下列函数是「模型领地」在本文档内的飞地**（归角色 C）：
   - `_build_llm_client`（L207，4 级 fallback 解析模型）
   - `_resolve_model_ref`（L963）

   → **规则**：这些函数若需改动，由**角色 C 提供改法**，角色 B 代为落地；
   或在 Phase 0 中把它们抽出为 `agent/model_resolver.py`，此后完全归角色 C。

3. **`_valid_columns` 从 `tools/project_data_tools.py`（角色 A 领地）import。**
   **禁止**在 `reconcile_tool.py` 里复制一份 —— 会立即产生逻辑分叉。
   需要变更时走协调流程。

4. **报告质量改动必须给出前后对比。**
   不要只说「报告更好了」。请在 PR 里贴**同一份输入数据**在改动前后的报告片段对比。

5. **`_fallback_report` / `_fallback_md_report` 是降级路径，不是死代码。**
   它们在没有 LLM 可用时兜底。**禁止为了「精简」而删除**（问题 4 的常见误伤）。

---

## 前端报告排版

| 文件 | 职责 |
| :--- | :--- |
| `components/MarkdownEditor.tsx` | Vditor 封装，含「导出 Word / PDF」 |
| `components/MarkdownBlock.tsx` | 只读 Markdown 渲染 |
| `components/FileEditor.tsx` | ⚠️ **不属于本领地**，由角色 B 与 A 共用区，改动前须协调 |

**排版规范**依据 `finance-agent-workbench/docs/格式.md`（GB/T 7713 学位论文规范），
Word 导出用 `--reference-doc=offline_packages/pandoc/reference-template.docx`。
