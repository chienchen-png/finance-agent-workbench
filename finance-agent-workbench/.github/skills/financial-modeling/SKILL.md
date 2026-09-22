---
name: financial-modeling
description: "财务建模分析。当用户要求基于财务数据做建模、分析、预测、评估、出图表，或询问财务模型公式/变量含义/原理时使用。触发词：财务建模、建模、预测、预算、盈亏平衡、本量利、敏感性、情景分析、杜邦、财务比率、相关性、回归、趋势分析、NPV、IRR、折现、估值、分析图表、画图、图表、讲解、介绍、公式、含义、原理、怎么算、是什么。"
user-invocable: true
---
# 财务建模 Skill

## 职责

完成一次「财务建模分析/讲解」：识别模式 →
（模式 A 输出数据需求清单 | 模式 B 选主题 → 数据准备 → 统计/建模 →
图表建议（先表后图）→ 确认渲染 → 报告 + 可选导出脚本 | 模式 C 输出公式讲解）。
面向公司内部分析，不涉及外部投资/量化投资。

## 公式输出规范（重要）

- **所有公式一律用 `$$...$$` 包裹**（LaTeX，前端 KaTeX 渲染）；行内公式也用 `$$`（如 `$$r$$` 为折现率）
- **禁止用单 `$` 写公式**（前端已禁用单 `$`，且 `$` 是货币符号，如 `$100万` 会被误判）
- **中文文字必须用 `\text{中文}` 包裹**（KaTeX 数学模式默认不接受裸中文，如 `$$\frac{\text{净利润}}{\text{营业收入}}$$`；或优先用字母变量如 `$$ROE = \frac{NP}{R}$$`）
- 货币金额用普通文本，不用 `$` 包裹
- 公式后必须附**变量含义表**（变量/含义/单位）

## 模型索引（A-G，共 32 个；细节用 read_skill_resource 按需读取）

- **A 报表预测**：A1 三表联动 / A2 利润表预测 / A3 现金流预测 / A4 合并汇总
- **B 预算预测**：B1 年度预算 / B2 滚动预测 / B3 销售预测 / B4 成本预算
- **C 成本盈利**：C1 本量利/盈亏平衡 / C2 边际贡献 / C3 成本差异 / C4 产品线盈利
- **D 绩效比率**：D1 杜邦 / D2 五维比率 / D3 预算差异 / D4 同比环比 / D5 杠杆
- **E 资本决策**：E1 NPV/IRR/回收期 / E2 WACC / E3 敏感性 / E4 情景 / E5 项目盈亏平衡 / E6 设备更新
- **F 营运资金**：F1 现金周期 / F2 账龄 / F3 存货周转 / F4 WCR
- **G 统计量化**：G1 描述统计 / G2 相关性 / G3 回归 / G4 时序分解 / G5 预测
- 需要某模型的**规则/公式/背景/参数** → `read_skill_resource("financial-modeling", "models/<编号>.md")`

## 图表模板索引（共 24 类型；选型表用 read_skill_resource 按需读取）

line / bar / pie / scatter / heatmap / waterfall / radar /
boxplot / histogram / tornado / funnel / dual-axis / sunburst / sankey / gauge /
treemap / graph / parallel / error-bar / calendar /
scatter3d / bar3d / histogram-4grid / waterfall3d

- **变体选型**（P5：generate_chart 的 template 传 `类型-变体`，如 `bar-line`；默认变体=纯类型名）：
  line（simple/multi-x）· bar（simple/negative/line/fancy）·
  pie（donut 默认/simple/half-donut/rounded/nested）· scatter（effect/regression）·
  heatmap（simple/discrete/calendar）· waterfall（simple/bar）· radar（simple/multi）· boxplot（simple/multi）·
  funnel（simple/compare）· sankey（simple/vertical）· gauge（simple/progress/stage）·
  treemap（simple/drilldown）· graph（force/circle）· error-bar（bar/range）· calendar（simple/year）·
  **3D/联动（P6-②，L3 档）**：scatter3d · bar3d · histogram-4grid · waterfall3d
- **选型规则（AI 依据「分析方向 + 数据特征 + 现有资源」推荐；含适用点/变量点/优势点）**：
  - `bar`（分组柱状）：1 类目 × N 数值系列并排 → 多口径对比；`bar-simple` 单系列；`bar-negative` 盈亏正负；`bar-line` 柱(量)+线(率) 双轴；`bar-fancy` 多年柱+趋势线
  - `line`（多维折线）：时间 × 多系列 → 趋势+极值/平均线；`line-simple` 单系列；`line-multi-x` 跨期同期对比（双 x 轴）
  - 判断口诀：**看关系用 bar（横向对比）、看趋势用 line（纵向时间）、看结构用 pie/sankey、看分布用 histogram/boxplot、看变量关系用 scatter/heatmap**
- **3D 模板渲染说明（v6.9 起）**：`scatter3d`/`bar3d`/`waterfall3d` 三个 3D 模板**由 Python(mplot3d)
  生成 PNG**（前端自动调 `/api/apps/finmod/py-chart` 渲染，无需 AI 介入）。AI 只需正常
  `generate_chart("waterfall3d", {...})` 提交数据，前端识别 3D 模板后自动走 Python。数据格式
  与 echarts-gl 版一致（xCategories/yCategories + series[0].data=[[xIdx,yIdx,zVal],…]）；
  **图内不加数据标题**（容器标题栏已展示表名），3D 图不支持矢量导出（仅 PNG）。
- **配色方案（P6-②）**：generate_chart 的 data 传 `color_scheme`（"auto"=不限制/"blues"等主色系=同色系深浅渐变）；前端 colors.ts 自动生成
- **官方级图表（阶段 3，v2.6 新增）**：图表输出自动对齐 ECharts 官方示例观感（数据增长动画 + 渐变 + 大数据量），AI 侧额外遵守：
  - **数据量 ≥ 12 点**（月/期/项），少于 8 点要横向扩展维度（如按产品/区域拆列），避免"空旷单薄"——官方示例数据量丰富才好看
  - **大数据量（>12 类）** 优先 `dataZoom` 变体（line/bar 自带缩放），标签自动降采样不贴死
  - **优先官方级变体**：bar→（默认分组）、line→（默认多维）、pie→donut（环形）、scatter→effect（涟漪）、radar→multi（多系列）、gauge→progress（进度环）——与官方代表图观感一致
  - **禁止给 AI 生成最小示例数据**（4-5 点）；真实数据不足时用明细粒度（按季度→按月/按客户/按产品）展开
- 需要某模板的**数据结构/选型建议** → `read_skill_resource("financial-modeling", "charts/<模板名>.md")`；**3D 模板**（waterfall3d/bar3d/scatter3d）已改 Python 生成，模板文档已在 v6.9 更新为 Python 说明
- **全局风格规范（P7 新增）**：字体/配色/轴线/标注/导出等 10 条复现规则 → `read_skill_resource("financial-modeling", "chart-style.md")`；
  **导出**：2D 图 → SVG（矢量）/HTML；**3D 图（scatter3d/bar3d/waterfall3d）→ 仅 PNG**（Python 生成，不支持矢量导出）；**所有图表内不含数据大标题**（容器标题栏已展示表名）

## 分析工具（L1 预写，优先调用；不满足才 L2）

financial_metrics（比率/杜邦/资本预算）/ regression_analysis / correlation_matrix /
time_series_analysis / sensitivity_analysis / generate_chart（图表）

> L1 无对应 → `run_python_code` 现场写代码（临时脚本 analysis_tmp/，完成后删除）

## 流程（多路径分支，★=分支点）

### 步骤 1：识别模式（A 数据需求 / B 已有数据 / C 知识讲解）

- 用户**询问模型公式/变量含义/原理**（如「DCF 公式是什么」「杜邦分析怎么算」）→ **模式 C**：跳到步骤 1C
- 用户有明确建模诉求但**无数据** → **模式 A**：直接输出数据需求清单
  （字段名/类型/示例/用途/建议图表），可附待填模板表格，**到此结束**（不建模）
- 用户**已提供数据**（@file: 或已导入）→ **模式 B**，继续以下步骤

### 步骤 1C：知识讲解（模式 C，只读 references 不建模）

- 定位用户询问的模型 → `read_skill_resource("financial-modeling", "models/<编号>.md")` 读取
- 输出讲解：**公式（`$$` LaTeX）** + **变量含义表**（变量/含义/单位）+ 适用场景 + 计算示例（可手工数字示例）
- **不读库、不调用分析工具、不产出图表**；用户后续要求"用我的数据算"再转模式 B

### 步骤 2：数据准备 → 变量定位（产出「变量集」）

- 若文件已在项目数据库 → **直接复用库内数据**（list_data_files/get_table_index 确认字段），不重复导入
- 未导入 → 用 import_excel_to_db 导入（含 @file: 引用但库中已有 → 直接复用）
- **变量定位（精确到列）**：确认目标变量列（收入/成本/现金流/期间/维度列），
  产出变量集 `{file, sheet, variables: {收入: "列名", ...}}`，ask_user 确认字段映射
- **数据源统一是项目数据库**：后续所有分析工具从库内读表（内部 pandas 计算），不直读 Excel

### 步骤 3：主题确认（★ 分支点 1：多选路径，必问 ask_user）

- AI 基于数据建议 1-3 个建模主题（从模型索引 A-G 选型，注明理由）
- **候选模型细节 → read_skill_resource("financial-modeling", "models/<编号>.md")** 按需读取规则/公式/参数
- ask_user **多选**（可单选/组合）；用户也可自定义

#### 分支 3a：单模型聚焦

- 选定 1 个模型 → 按该模型方法执行（读对应 models/<编号>.md）

#### 分支 3b：多模型综合分析

- 选定 2+ 模型 → 各模型并行分析 → 步骤 6 综合结论与交叉发现

### 步骤 4：分析执行（★ 分支点 2：按模型类型分派）

- **先做数据体检**：table_stats 输出均值/中位/极值/缺失（JSON 摘要）；correlation_matrix 预筛变量关系
- **AI 只读索引与结果摘要，不读全量数据**（工具内部 pandas 计算）
- 按所选模型类型走对应分支；工具调用总量 ≤ 10 次（各分支共享预算）

#### 分支 4a：绩效比率类（D1-D5）

- financial_metrics → 五维比率/杜邦/预算差异/杠杆 → radar/waterfall

#### 分支 4b：统计建模类（G1-G5）

- regression_analysis / correlation_matrix / time_series_analysis → scatter/heatmap/line

#### 分支 4c：资本决策类（E1-E6）

- financial_metrics（NPV/IRR/回收期）+ sensitivity_analysis → tornado/heatmap

#### 分支 4d：成本盈利类（C1-C4）

- sensitivity_analysis（CVP/盈亏平衡）+ financial_metrics → waterfall/bar
- **L1 无对应工具的长尾需求 → 降级 L2 run_python_code**：现场写 pandas 代码
  （用 load_data 读库内 DataFrame），一次调用返回结果；代码不进 LLM 上下文
  - ⚠ **数据已自动清洗**：load_data 返回的 DataFrame 已自动把占位符
    （"empty"/"None"/""）转 NaN、数值列自动 to_numeric——**禁止再写清洗代码**
    （replace/to_numeric/apply 转换），直接 pd 计算即可；避免反复清洗浪费轮次
- 每个结论必须给出计算依据与数值；**禁止用 run_command 跑分析脚本**

### 步骤 5：图表产出（★ 分支点 3：按分析类型选模板，先表后图必问确认）

- **① 复杂度分级（必问 ask_user select）**：先问用户绘图复杂程度，三档：
  - **L1 简单**：单/双变量平面图 → line / bar / pie（基础变体），直观快速
  - **L2 中等**：多维变量 + 色彩/大小编码 → heatmap / radar / dual-axis / scatter-effect / bar-stacked / boxplot / histogram（P5 变体）
  - **L3 复杂**：3D 空间图 / 多表联动 → scatter3d / bar3d / histogram-4grid / waterfall3d（P6/P7 新增）
  - 用户未明确偏好时：**默认 L2 中等**（财务分析最常用，多维但不过度炫技）
- **② 配色方案（P6-② 必问 ask_user select）**：
  - **1. 不限制**：AI 按财务场景合理配色（默认 auto，多系列蓝橙主色）
  - **2. 渐变色**：选一个主色系（蓝色系/绿色系/红色系/橙色系/紫色系/黑灰色系），整图用它深浅变化
    → ask_user select 选主色系 → generate_chart data 传 color_scheme（如 "blues"）
  - **3. 自定义主题色**：用户给主色 hex（如 #1a73e8）→ 自动生成同色系深浅
- **③ 按档位收窄模板候选**：只从档位内模板选择，禁止跨档（L1 任务不画 3D，L3 任务不退化为单变量柱状图）
- **④ 每个候选图表先给 markdown 数据表 + 图表类型说明**（模板名/用途/可读性）
- **⑤ ask_user 确认**：哪些图表要渲染？是否调整类型/口径？
- **⑥ 确认后调用 generate_chart**（template + data + data_table），把 markdown_block 嵌入正文
- **禁止在用户确认前输出 chart-json**；每个图表必须带数据表与数据口径说明（§6 协议）

#### 分支 5a：绩效/对比类模板

- radar（五维/杜邦，multi 多系列）/ waterfall（预算差异）/ bar（rounded 圆角/horizontal 排名）/ dual-axis / gauge（KPI 达成，progress/stage）

#### 分支 5b：统计/关系类模板

- scatter（regression 回归线）/ heatmap（相关矩阵，discrete 离散）/ line（趋势，area 面积/forecast 预测虚线）/
  boxplot（multi 多组）/ histogram / parallel（多维对比）/ error-bar（预测区间，range 区间带）

#### 分支 5c：资本决策类模板

- tornado（敏感性）/ heatmap（双变量网格）/ bar（情景对比）/ error-bar（NPV 区间）

#### 分支 5d：成本/构成类模板

- waterfall（差异桥）/ bar-stacked（结构）/ pie（占比，half-donut 半环/rounded 圆角）/ funnel（转化）/ treemap（多层占比，drilldown 下钻）

### 步骤 6：报告整合（多分支汇总）

- 完整中文分析报告：建模主题/模型选型（含多模型组合）/各分支关键发现/图表/数据表/局限与假设
- **多模型综合（3b）时**：汇总各分支 + 交叉发现（如杜邦与敏感性联动）
- 报告直接在对话流输出（markdown），禁止 write_file 生成报告文件
- **可选**：ask_user 确认后导出分析脚本到 `analysis_scripts/<主题>_<时间戳>.py`
  （write_file，正式交付物；区别于 analysis_tmp/ 临时脚本），
  报告内告知完整路径（用户可复用/审阅）；默认不导出（临时脚本已删除）

## 财务建模与分析报告模板（R5.1，2026-08-23 降 AI 味 + 券商研报结构）

> 集成应用「财务建模与分析」的 `export-md` 报告生成遵循此模板。核心原则：
> **券商研究所研报结构 + 客观陈述 + 简约精简**——针对单一分析主题，不铺陈、不炫技、
> 不堆形容词。先结论后论证，每条结论有数值依据。

### 报告骨架（确定性章节，AI 填充；结论先行）

```markdown
# 标题（一句话点题，无修饰，如：回款提成盈利能力与杠杆水平分析）
> 分析日期 / 数据范围 / 文件数

## 一、执行摘要
- 基于什么背景，我们基于什么方法，用了哪些数据，经过什么分析得到哪些结果？严谨科学的论文摘要风格，可引用关键数据

## 二、数据来源
- 2.1 数据来源/规模（行数/文件数/期间）+ 核心统计表（均值/极值）
- 2.2 变量映射口径 + 派生变量 + 假设与缺失说明

## 三、建模与分析
3.1 “模型一：xxxx"
- 方法简述（所选模型 + 目的，1-2 句，不展开教学）
- 发现 1：判断 → 数值依据 → 图 X（每发现 3-5 行）
- 发现 2 / 发现 3：……
- 交叉/异常观察（如有）
3.2 “模型二：xxxx"

## 四、结论与建议
- 4.1 可执行建议（具体到动作/口径，2-4 条）
- 4.2 风险提示（数据局限/假设/合规边界）
```

### 降 AI 味用语规范（硬性，报告最重要的观感要求）

| 维度                  | 禁止                                                   | 替代                                               |
| --------------------- | ------------------------------------------------------ | -------------------------------------------------- |
| **比喻/象征**   | 「宛如」「犹如」「筑起护城河」「引擎」「灯塔」「征途」 | 直接陈述事实                                       |
| **华丽形容词**  | 「卓越」「显著」「璀璨」「稳健前行」「赋能」「助力」   | 用具体数值 + 「较为/相对」克制修饰                 |
| **感叹/排比**   | 感叹号「！」、排比句、对仗                             | 客观陈述句                                         |
| **引号/破折号** | 滥用「」强调、过度使用「——」插入语                   | 直接写，不用引号包裹普通词                         |
| **营销动词**    | 「发力」「打造」「抢占」「引领」                       | 「增加」「优化」「调整」                           |
| **空泛结论**    | 「总体向好」「值得关注」「表现亮眼」                   | 必须带数值：「ROE 12.5%，较上期提升 1.2 个百分点」 |
| **主观夸张**    | 「非常」「极其」「大幅」（无对比时）                   | 有对比才用：「同比增长 8%」「环比下降 3%」         |

**其他观感要求**：

- **先判断后论证**：每条观点/发现先给结论一句话，再给依据（数据/图），不绕弯
- **数据锚定**：所有定性词必须伴随具体数值（均值/比率/变化幅度）
- **克制表达**：用「较为」「相对」「存在」「我们判断」代替「非常」「明显」「显然」
- **面向单点分析**：不写宏观综述、不写行业全貌，只聚焦本次分析主题，简洁凝练

### 报告书写规范

- 所有公式用 `$$...$$`；中文用 `\text{}`；禁用单 `$`（货币金额用普通文本）
- 图表用相对路径 `![图](assets/xxx.svg)`；每张图正文必须有解读（图 X 显示……）
- **图表构成由内容决定**：用户勾选的图是「优先建议」，AI 可据报告内容增减；
  每张图必须有正文解读，最终图表数量与叙事匹配

## 约束

- **只读计算**：本 skill 的工具不写库不改数（update_rows/delete_rows 禁止，
  除非用户明确要求把预测值写回）
- **核心计算工具调用 ≤ 10 次**；ask_user/list_data_files/get_table_index/图表生成不计入
- **交互必问（铁律）**：步骤 3 主题多选确认、步骤 5 复杂度分级（L1/L2/L3）
  与配色方案确认是**必问步骤**——必须用 ask_user 弹窗询问用户，
  禁止因效率/调用次数考虑跳过；ask_user 交互不计入调用限制
- 每次图表必须先行数据表（§6 协议），无数据表不出图
- 图表只能用 generate_chart 选模板生成，禁止手写任意 option（除 option_overrides）
- 面向公司内部分析，不涉及外部投资/量化投资分析（触发时说明边界并引导）
- 用 ask_user 交互，不臆测用户意图；假设缺失时明确说明（如折现率默认 10%）
