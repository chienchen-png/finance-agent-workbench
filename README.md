# Finance Agent Workbench · 财务智能体工作台

> 面向财务人员的**本地离线**智能体工作台：用自然语言下达财务任务，AI 读取 Excel → 导入 SQLite 数据平面 → 核对分析 → 审批后写回原文件，全程可视、可审计、可追溯。

**核心定位**：不是通用聊天机器人，而是 **「Excel 数据核对 + 受控写回」的垂直自动化平台**，并演进为 **「对话 + 集成应用」双形态**——对话承接长尾自由任务，集成应用以向导方式固化高频流程。

- 后端约 **15,000 行 Python**，**60+ REST API**，**39 个智能体工具**
- 前端 React SPA（Vite），构建产物由 Flask 托管
- **完全离线 / 内网部署**，依赖全部本地化（见 `offline_packages/`）

---

## 一、核心特性

### 1. 数据平面为中心，Excel 100% 保真

```
Excel (.xlsx/.xls)  ──import──▶  SQLite 数据平面 (data_* 表)
                                        │
                          AI 核对 / 分析 / 修改（只在库内操作）
                                        ▼
                                 变更日志 project_data_changes
                                        │
                          导出（precise 精确回写）──▶  Excel + .bak 备份
```

**SQLite 数据平面是唯一事实源**，AI 永远只在库内操作；Excel 仅在「导入（读）」和「写回（补丁式）」时被接触——因此 **格式 / 公式 / 合并单元格在未改动区域 100% 保留**。

### 2. 受控写回与审计闭环

- 所有写操作（`update_rows` / `insert_rows` / `delete_rows`）先入**字段级变更日志**
- 前端「待写回 / 写回记录」两个 Tab 可视化审计
- 写回前自动备份 `.bak`，写回后记录 `writeback_history`

### 3. 集成应用（隐藏项目组件架构）

每个 AI 集成应用**本质上是「一套前端页面 + 一个隐藏项目」**，复用主工作台的项目 / 存储 / 文件 / 前端基础设施：

| 应用 | 说明 | 形态 |
| :--- | :--- | :--- |
| **① 数据核对与校验** | data-reconcile skill 固化为 6 步向导：确定性核对（秒级）+ 一次 LLM 生成报告、多轮审计循环、**确定性写回 Excel** | 可写回 |
| **② 财务建模与分析** | financial-modeling skill 固化为 4 步向导：32 个财务模型 + 24 类图表模板、变量映射、AI 撰写券商研报风格报告 | 纯只读分析 |

一个集成应用 = 三件套：

| 组成 | 说明 |
| :--- | :--- |
| 隐藏项目 | `projects` 表一条 `__app_*` 前缀记录，`GET /api/projects` 默认过滤 |
| 绑定项目目录 | `data/app-workspaces/<app>/` 专属产物目录 |
| 绑定项目数据库 | 统一 `data/app.db`，按 `project_id` 隔离 |

> **为什么巧妙**：修 bug = 改前端页面（`frontend/src/pages/*AppPage.tsx`）+ 后端几个端点（`routes/apps.py`），不必重构框架。

### 4. 渐进式 Skill 加载（省算力）

对齐 VS Code Copilot 的三层模型，按需加载：

| 层级 | 内容 | 加载时机 |
| :--- | :--- | :--- |
| **L0** | `.github/agent.md` | 常驻系统提示词 |
| **L1** | `SKILL.md` | 任务匹配时按需注入 |
| **L2** | `references/` 资源 | 工具调用时读取 |

配套优化：数据索引按需化（省约 92% token）、简单任务跳过规划、确定性计算交给 `reconcile_variables` 工具。

### 5. 图表与公式

- **ECharts 5** 渲染，24 类模板 + 变体体系（2D 可交互：拖拽缩放、dataZoom、下载）
- 3D 图（waterfall3d / bar3d / scatter3d）由 **Python matplotlib(mplot3d)** 生成静态 PNG（点击放大 / 下载）
- **KaTeX** 数学公式渲染
- 图表交付仅 **SVG（2D 矢量）+ HTML（交互 / 3D）**

### 6. 文件预览与文档导出

- 双击文件按类型分流：Markdown（Vditor 即时渲染）/ PDF / 图片 / 文本 / Office（本地打开）
- 新标签页全屏预览
- **Pandoc** 导出 Word（支持 GB/T 7713 学位论文排版模板），PDF 走浏览器打印

---

## 二、技术栈

| 领域 | 技术 | 版本 |
| :--- | :--- | :--- |
| 后端框架 | Flask | 3.1.3 |
| 数据库 | SQLite（WAL 模式，单文件 `data/app.db`） | 内置 |
| 智能体引擎 | smolagents `ToolCallingAgent` | ≥1.26.0 |
| Excel 读写 | openpyxl / xlrd / xlwt / xlutils / formulas | — |
| 数据分析 | numpy / pandas / scipy / matplotlib / plotly | — |
| 前端框架 | React + TypeScript | 18.3 / 5.6 |
| 构建工具 | Vite | 6.x |
| 样式 | Tailwind CSS | 4.x |
| 对话 UI | @assistant-ui/react | 0.8 |
| 图表 | ECharts + echarts-gl + echarts-stat | 5.6 |
| 编辑器 | Vditor（Markdown，内网化） | 3.11.3 |
| 公式渲染 | KaTeX | 0.16 |
| 文档导出 | Pandoc | 3.10.2 |

**支持的大模型**：DeepSeek / 智谱 GLM / 通义千问 / 本地模型（思考强度统一 `medium`，本地模型不传思考参数以避免 400）。

---

## 三、目录结构

```
finance-agent-workbench/
├── app.py                  # Flask 应用入口（应用工厂 + 会话计时器生命周期）
├── requirements.txt
├── config/                 # settings.py 全局配置
├── routes/                 # REST API 层（Flask Blueprint）
│   ├── projects.py         #   项目管理
│   ├── project_data.py     #   数据平面（导入 / 查询 / 变更 / 写回）
│   ├── files.py            #   文件浏览 / 预览 / 导出
│   ├── agents.py           #   智能体运行
│   ├── apps.py             #   集成应用端点（*_bp）
│   ├── dashboard.py        #   工作台总览聚合
│   └── ...
├── agent/                  # 智能体引擎
│   ├── smol_engine.py      #   smolagents 编排
│   ├── smol_bridge.py      #   引擎桥接
│   ├── context_manager.py  #   上下文压缩与管理
│   ├── tool_registry.py    #   工具注册表
│   ├── skill_loader.py     #   Skill 三层渐进加载
│   └── approval/           #   写操作审批
├── tools/                  # 39 个智能体工具实现
├── storage/                # SQLite 存储层
│   ├── db.py               #   连接与建表
│   ├── schema.sql          #   表结构
│   ├── tmp_db.py           #   临时库快照（核对/写回隔离，不污染主库）
│   └── *_store.py          #   项目/数据/运行/会话/Token 等各域存储
├── skills/                 # Skill 定义（data-reconcile 等）
├── .github/                # agent.md（L0 常驻）+ skills（L1 按需）
├── frontend/               # React SPA 源码
│   └── src/pages/          #   含 *AppPage.tsx 集成应用前端页
├── static/                 # 前端构建产物 + 第三方库（KaTeX / Mermaid）
├── templates/              # Jinja 模板
├── scripts/                # 构建 / 校验 / 软著材料脚本
├── docs/                   # 架构文档 + 函数与变量总文档
│   ├── 项目架构文档.md      #   ★ 唯一权威架构说明
│   └── 函数与变量总文档.md  #   全部函数 / 变量索引
├── offline_packages/       # 离线安装包（wheel，供无网环境 pip install）
└── data/                   # 运行时数据（SQLite / 工作区，不入库）
```

---

## 四、快速开始

### 环境要求

- **Python 3.11+**（本项目开发环境为 3.14）
- Windows / Linux（当前主要在 Windows 内网环境验证）

### 1. 安装后端依赖

```bash
cd finance-agent-workbench

# 有网
pip install -r requirements.txt

# 无网 / 内网（使用随仓库提供的离线包）
pip install --no-index --find-links=offline_packages -r requirements.txt
```

### 2. 构建前端（必需）

`frontend/dist/` 是 **Flask 运行时托管的前端产物**（见 `config/settings.py` 的 `FRONTEND_DIST_DIR`）。它属于构建产物、不在本仓库中，因此**首次运行前必须构建一次**：

```bash
cd finance-agent-workbench/frontend
npm install
npm run build      # 产物输出到 frontend/dist，由 Flask 直接托管
```

> 本项目为内网离线场景，第三方前端资源已内网化（如 `frontend/public/vditor/` 为 Vditor 包根结构的本地副本，构建时会被复制进产物），`options.cdn` 指向本地路径，无需访问公网 CDN。

### 3. 启动

```bash
cd finance-agent-workbench
python app.py
```

浏览器打开 `http://127.0.0.1:8080`，在「AI 配置」页填入大模型 API Key 后即可使用。

### 4. 导出 Word（可选）

Pandoc 可执行文件因超过 GitHub 单文件上限未纳入仓库，如需 Word 导出请自行下载：

> https://github.com/jgm/pandoc/releases

放置到 `offline_packages/pandoc/pandoc.exe`。

---

## 五、设计铁律

项目累积了一套强制工程约束，落位于 `.github/agent.md`：

- **铁律 0**：架构改动必须同步更新 `docs/项目架构文档.md`
- **铁律 00**：工作流必须落位 `agent.md` / `SKILL.md`，不得散落在代码注释
- **铁律 000**：符号引用前必须核对 `docs/函数与变量总文档.md`，防引用错误
- **唯一事实源**：SQLite 数据平面；Excel 只在导入 / 写回时接触
- **限定工作目录**：所有工具调用在工作目录边界内，写操作带审批

---

## 六、说明

- 本项目为**内网离线部署**设计，不在公网暴露服务。
- 仓库**不包含**任何真实业务数据、用户文件与运行时数据库（`data/`、测试夹具中的业务样本均在 `.gitignore` 中排除）。
- `docs/项目架构文档.md` 是理解本项目的第一入口，其中「隐藏项目组件」一节是看懂集成应用架构的关键。
