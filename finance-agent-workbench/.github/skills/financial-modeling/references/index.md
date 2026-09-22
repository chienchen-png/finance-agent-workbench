# financial-modeling references 索引

本目录存放财务建模 Skill 的 L2 按需加载资源。SKILL.md 只含索引；需要某模型/图表的细节时用 `read_skill_resource("financial-modeling", "<相对路径>")` 读取。

## 全局规范

| 文件 | 内容 |
|------|------|
| `chart-style.md` | **财务图表风格规范**（2026-08-21 新增，借鉴 figures4papers 设计理论）：字体/配色/轴线/布局/编码/打印交付 10 条复现规则；所有图表模板共用，AI 生成图表时按此收敛风格 |

## models/（32 个模型规则/公式/背景）

| 编号 | 文件 | 模型 |
|------|------|------|
| A1 | `models/a1-three-statement.md` | 三表联动模型 |
| A2 | `models/a2-income-forecast.md` | 利润表预测模型 |
| A3 | `models/a3-cashflow-forecast.md` | 现金流量表预测模型 |
| A4 | `models/a4-consolidation.md` | 多单元合并汇总模型 |
| B1 | `models/b1-budget.md` | 年度预算模型 |
| B2 | `models/b2-rolling-forecast.md` | 滚动预测模型 |
| B3 | `models/b3-sales-forecast.md` | 销售预测模型 |
| B4 | `models/b4-cost-budget.md` | 成本费用预算模型 |
| C1 | `models/c1-cvp-breakeven.md` | 本量利/盈亏平衡模型 |
| C2 | `models/c2-contribution-margin.md` | 边际贡献分析 |
| C3 | `models/c3-cost-variance.md` | 成本差异分析 |
| C4 | `models/c4-product-profitability.md` | 产品线盈利分析 |
| D1 | `models/d1-dupont.md` | 杜邦分析 |
| D2 | `models/d2-financial-ratios.md` | 财务比率体系（五维） |
| D3 | `models/d3-budget-variance.md` | 预算差异分析 |
| D4 | `models/d4-yoy-mom.md` | 同比/环比/结构分析 |
| D5 | `models/d5-leverage.md` | 经营/财务/总杠杆 |
| E1 | `models/e1-npv-irr.md` | NPV/IRR/回收期/获利指数 |
| E2 | `models/e2-wacc.md` | WACC 估算 |
| E3 | `models/e3-sensitivity.md` | 敏感性分析 |
| E4 | `models/e4-scenario.md` | 情景分析 |
| E5 | `models/e5-project-breakeven.md` | 项目盈亏平衡 |
| E6 | `models/e6-equipment-replacement.md` | 设备更新决策 |
| F1 | `models/f1-cash-cycle.md` | 现金预算/现金周期 |
| F2 | `models/f2-aging-analysis.md` | 应收账款账龄分析 |
| F3 | `models/f3-inventory-turnover.md` | 存货周转与持有成本 |
| F4 | `models/f4-wcr.md` | 营运资金需求测算 |
| G1 | `models/g1-descriptive-stats.md` | 描述性统计 |
| G2 | `models/g2-correlation.md` | 相关性分析 |
| G3 | `models/g3-regression.md` | 回归分析 |
| G4 | `models/g4-time-series-decompose.md` | 时间序列分解 |
| G5 | `models/g5-forecasting.md` | 预测（移动平均/指数平滑/外推） |

## charts/（16 个图表模板选型，含 P5-② 变体 + P6 复杂度档位）

| 模板 | 文件 | 图表 | 典型用途 | 复杂度 | 变体（`模板-变体`） |
|------|------|------|---------|:------:|---------------------|
| line | `charts/line.md` | 折线图 | 趋势/对比 | **L1** | multi-x / simple |
| bar | `charts/bar.md` | 柱状图 | 对比/排名 | **L1** | simple / negative / line / fancy |
| pie | `charts/pie.md` | 饼图/环形图 | 占比 | **L1** | donut / simple / half-donut / rounded / nested |
| scatter | `charts/scatter.md` | 散点图（+回归线） | 相关/回归 | **L2** | simple / effect / regression |
| heatmap | `charts/heatmap.md` | 热力图 | 相关矩阵/双变量敏感性 | **L2** | simple / discrete / calendar |
| waterfall | `charts/waterfall.md` | 瀑布图 | 差异桥接 | **L2** | simple / bar |
| radar | `charts/radar.md` | 雷达图 | 多维指标对比 | **L2** | simple / multi |
| boxplot | `charts/boxplot.md` | 箱线图 | 分布对比 | **L2** | simple / multi |
| histogram | `charts/histogram.md` | 直方图 | 分布形态 | **L2** | — |
| tornado | `charts/tornado.md` | 龙卷风图 | 敏感性排序 | **L2** | — |
| funnel | `charts/funnel.md` | 漏斗图 | 转化/流程 | **L1** | simple / compare |
| dual-axis | `charts/dual-axis.md` | 双轴组合图 | 实际 vs 预算 | **L2** | — |
| sunburst | `charts/sunburst.md` | 旭日图 | 多层占比 | **L2** | — |
| sankey | `charts/sankey.md` | 桑基图 | 资金流向 | **L2** | simple / vertical |
| gauge | `charts/gauge.md` | 仪表盘 | KPI 达成 | **L1** | simple / progress / stage |
| treemap | `charts/treemap.md` | 矩形树图（P5-③） | 多层占比 | **L2** | simple / drilldown |
| graph | `charts/graph.md` | 关系图（P5-③） | 资金往来网络 | **L2** | force / circle |
| parallel | `charts/parallel.md` | 平行坐标（P5-③） | 多维对比 | **L2** | — |
| error-bar | `charts/error-bar.md` | 误差条/区间（P5-③） | 预测置信区间 | **L2** | bar / range |
| calendar | `charts/calendar.md` | 日历热力（P5-③） | 每日回款/支出 | **L2** | simple / year |
| scatter3d | `charts/scatter3d.md` | 三维散点（P6-②，**v6.9 Python 生成**） | 三变量关系，静态 PNG | **L3** | — |
| bar3d | `charts/bar3d.md` | 三维柱状（P6-②，**v6.9 Python 生成**） | 三维结构对比，静态 PNG | **L3** | — |
| histogram-4grid | `charts/histogram-4grid.md` | 联动直方图（P6-②） | 散点+双向分箱联动 | **L3** | — |
| waterfall3d | `charts/waterfall3d.md` | 3D 瀑布（v6.9 **Python 生成**） | 多指标并排填充面，静态 PNG | **L3** | — |

> **复杂度档位（P6-①）**：L1 简单（单/双变量平面图，直观快速）/ L2 中等（多维变量 + 色彩编码，财务最常用）/ L3 复杂（3D 空间图 / 多表联动，P6-② 启用）。AI 在步骤 5 先 ask_user 选档，再按档收窄模板。
> **配色方案（P6-②）**：generate_chart data 传 color_scheme（auto/blues/greens/reds/oranges/purples/blacks）。
> **3D 模板（scatter3d/bar3d/waterfall3d，v6.9 起）**：由 Python(mplot3d) 生成 PNG（前端自动调 `/api/apps/finmod/py-chart`），非旋转/缩放交互、不支持矢量导出；数据格式与 echarts-gl 版一致。
