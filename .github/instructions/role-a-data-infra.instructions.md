---
applyTo: "finance-agent-workbench/tools/table_layout_detector.py,finance-agent-workbench/tools/project_data_importer.py,finance-agent-workbench/tools/project_data_tools.py,finance-agent-workbench/tools/formula_fallback.py,finance-agent-workbench/tools/excel_tools.py,finance-agent-workbench/routes/project_data.py,finance-agent-workbench/app.py,finance-agent-workbench/config/**,finance-agent-workbench/requirements.txt,finance-agent-workbench/frontend/vite.config.ts,finance-agent-workbench/frontend/package.json,finance-agent-workbench/frontend/src/components/AppDataPanel.tsx,finance-agent-workbench/frontend/src/components/DataPanel.tsx,finance-agent-workbench/scripts/**"
---

# 【领地守卫】角色 A — 数据与基础设施

> **这些文件归「角色 A」负责。如果你不是角色 A，请不要修改本领地内的文件。**

如果你是被用户直接指派来改这些文件的，请先确认用户已与角色 A 协调，并在 PR 中说明原因。

---

## 本领地负责的问题

| 编号 | 问题 | 核心 |
| :--- | :--- | :--- |
| **2** | 数据识别准确性问题 | Excel 表头识别、字段类型推断、锚定确认 |
| **6** | 部署上线问题 | 启动方式、端口、构建配置、打包分发 |

---

## 核心入口（改之前先定位）

| 场景 | 文件 | 函数 / 常量 |
| :--- | :--- | :--- |
| 表头 / 版面识别 | `tools/table_layout_detector.py` | `detect_layout()`、`Layout`、`audit_and_correct`、`_keyword_hits`、`_type_distribution` |
| 识别阈值调参 | `tools/table_layout_detector.py` | `MAX_SCAN_ROWS=20`、`HEADER_MIN_FILL=0.5`、`CONFIDENCE_OK=0.7` |
| 导入落库 | `tools/project_data_importer.py` | `ProjectDataImporter`、`NeedAnchorError`、`_sanitize_column`、`_promote_type` |
| 导入入口 | `tools/project_data_tools.py` | `import_excel_to_db(header_row=...)`、`_valid_columns` |
| 公式兜底重算 | `tools/formula_fallback.py` | `formula_fallback_rows` |
| 导入 API | `routes/project_data.py` | `/import`、`/import/anchor`、`/import/status`、`/<id>/index` |
| 部署启动 | `app.py` | `__main__` 段、`--port` 参数 |
| 部署配置 | `config/settings.py` | `HOST`、`PORT`、`DEBUG`、`DATA_DIR`、`FRONTEND_DIST_DIR` |
| 前端构建 | `frontend/vite.config.ts` | `base: "/static/app/"` |

---

## 本领地特别规则

1. **`_valid_columns` 被 `tools/reconcile_tool.py`（角色 B 领地）import。**
   修改它的**签名或返回值结构**属于破坏性变更 —— 必须先与角色 B 协调。

2. **`app.py` 有第二个主人（潜在冲突）。**
   若「问题 5（登录页面）」确认要做，登录守卫也要动 `app.py` 的 `create_app()`。
   → 规则：**`create_app()` 内的改动统一由角色 A 执行**，其他角色以「新增独立模块」方式提供实现。

3. **识别准确性的改动必须用真实样例验证。**
   项目里 `test-fixtures/phase5/` 已被 gitignore（含业务数据），
   验证请用自备样例，并在 PR 里报出**具体数值**（如「识别正确率从 X/10 提升到 Y/10」），
   不要只说「更准了」。

4. **禁止放宽 `NeedAnchorError` 的触发条件来「让导入更顺畅」。**
   它是防止表头误判的安全阀，放宽等于把错误数据静默导入。

---

## 本领地内可自由重构的文件

以下文件**未被其他领地 import**，可自由重构：
`tools/table_layout_detector.py`、`tools/formula_fallback.py`、`routes/project_data.py`、
`frontend/src/components/AppDataPanel.tsx`、`frontend/src/components/DataPanel.tsx`

> ⚠️ 重构 `TableLayout` / `Layout` 的字段名会牵连 `tools/project_data_importer.py`，属领地内，但仍需一并改完再提交。
