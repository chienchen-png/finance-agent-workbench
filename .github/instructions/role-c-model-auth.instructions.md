---
applyTo: "finance-agent-workbench/routes/models.py,finance-agent-workbench/routes/workspace.py,finance-agent-workbench/routes/context.py,finance-agent-workbench/storage/model_store.py,finance-agent-workbench/agent/llm_client.py,finance-agent-workbench/agent/agent_config.py,finance-agent-workbench/agent/smol_model.py,finance-agent-workbench/agent/model_resolver.py,finance-agent-workbench/routes/auth.py,finance-agent-workbench/frontend/src/pages/AiConfigPage.tsx,finance-agent-workbench/frontend/src/pages/LoginPage.tsx,finance-agent-workbench/frontend/src/components/ModelPicker.tsx,finance-agent-workbench/frontend/src/components/ModelIcon.tsx,finance-agent-workbench/frontend/src/components/ModelCard.tsx,finance-agent-workbench/frontend/src/components/NewProjectDialog.tsx"
---

# 【领地守卫】角色 C — 模型与鉴权

> **这些文件归「角色 C」负责。如果你不是角色 C，请不要修改本领地内的文件。**

如果你是被用户直接指派来改这些文件的，请先确认用户已与角色 C 协调，并在 PR 中说明原因。

---

## 本领地负责的问题

| 编号 | 问题 | 核心 |
| :--- | :--- | :--- |
| **1** | 模型配置问题联动 | 模型配置在各页面 / 运行链路中的联动一致性 |
| **5** | 登陆页面问题 | ⚠️ 见下方「重要前提」 |

---

## ⚠️ 重要前提：问题 5 现状

**经全库检索确认：本项目当前不存在任何登录 / 鉴权代码。**

- 前端：无登录页、无 token 校验、无路由守卫
- 后端：无 auth 路由、无密码校验、无会话鉴权
- `app.py` 的页面路由（`/`、`/projects`、`/workspace`、`/ai-config`）全部直接 `return _serve_spa()`，**无守卫**
- 全库 `session` 关键词都指 `app_sessions` 表（**软件打开时长统计**，非鉴权）
- 全库 `token` 关键词都指 **LLM token 计费**，非登录凭证

> **因此问题 5 不是 bug 修复，而是「从零新增功能」**，工作量与其它 6 项不可比。
> **开工前必须先与用户确认**：是否确实要做登录功能？还是此项误列？
> 若是内网单机部署，登录可能并非必需 —— 先问清楚再动手。

---

## 核心入口（改之前先定位）

| 场景 | 文件 | 函数 / 字段 |
| :--- | :--- | :--- |
| 模型 CRUD | `routes/models.py` | `/api/models/test`、`/providers`、`_build_chat_url`、`_provider_payload`、`_model_payload` |
| 模型存储 | `storage/model_store.py` | — |
| **联动核心** | `routes/workspace.py` | `_build_llm_client()`(L143-227，4 级 fallback)、`_resolve_context_window()`(L41) |
| LLM 出口 | `agent/llm_client.py` | `LLMClient.__init__(api_url, api_key, model)`、`chat_stream`、`_build_body`（三家差异兼容）、`from_env()` |
| 模型配置模型 | `agent/agent_config.py` | `AgentConfig.default_model`、`from_db_row`、`to_dict` |
| smolagents 适配 | `agent/smol_model.py` | `FinanceModel` |
| thinking 特判 | `agent/core.py` | `_model_id`(L259/292)、`glm` 前缀判断(L380/512/593) |
| 上下文占用 | `routes/context.py` | `/api/context/stats` |
| 前端配置页 | `pages/AiConfigPage.tsx` | — |
| 统一选择器 | `components/ModelPicker.tsx` | 被多个页面共用 |

---

## 本领地特别规则

1. **`agent/llm_client.py` 是全站唯一 LLM 出口，被角色 B 的报告链路依赖。**
   修改 `_build_body` 的请求体结构会影响**所有**报告质量。
   → 改动后必须在 PR 里说明**影响的调用方**，并请角色 B 回归报告功能。

2. **`_build_llm_client` 目前在 `routes/apps.py`（角色 B 领地）里。**
   这是最大的领地交叉点。Phase 0 解耦时把它抽为 `agent/model_resolver.py`，此后完全归本领地。
   **解耦完成前，改它必须走协调流程。**

3. **三家供应商差异是「特性」不是「冗余」。**
   `_build_body` 里 deepseek/glm/qwen 的 thinking 参数差异、`glm` 前缀特判，
   都是为规避真实 400 错误而存在的。**禁止为「精简」而合并它们**（问题 4 的常见误伤）。

4. **`from_env()` 是兜底路径，不是死代码。** 禁止删除。

5. **改模型配置必须实际测试连接。**
   不要只看代码逻辑。请实际调用 `/api/models/test` 并贴出响应。

---

## 若确认要做登录功能（问题 5）

**新增文件（本领地）**：
- `routes/auth.py` — 新 Blueprint
- `frontend/src/pages/LoginPage.tsx` — 登录页
- `storage/schema.sql` — 新增用户表（⚠️ **改动前须与角色 A 协调**，见下）

**需要改别人文件的地方 —— 一律走协调，不要自行修改**：

| 需要改的文件 | 归属 | 处理方式 |
| :--- | :--- | :--- |
| `finance-agent-workbench/app.py` → `create_app()` 加鉴权守卫 | 角色 A | **请求角色 A 代为添加**（约定：`create_app()` 内改动统一由 A 执行） |
| `finance-agent-workbench/config/settings.py` → 新增登录相关配置 | 角色 A | 同上 |
| `finance-agent-workbench/storage/schema.sql` → 新增用户表 | 角色 A | 同上 |
| `finance-agent-workbench/frontend/src/lib/api.ts` → 新增 auth 接口 | 公用地雷 | 按 `CONTRIBUTING.md` 第 4 节的接口文件规范提交 |

> **原则**：新功能通过「新增文件 + 请求共享文件领地主代为挂接」实现，
> 而不是三人都去改 `app.py`。
