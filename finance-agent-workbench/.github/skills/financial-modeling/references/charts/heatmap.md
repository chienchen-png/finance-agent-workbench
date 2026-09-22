# 图表模板：heatmap（热力图）

## 用途

> **复杂度档位：L2 中等**（P6-①：多维变量 + 色彩/大小编码，财务最常用）

用颜色深浅展示矩阵数据：相关矩阵、双变量敏感性网格。

## 典型场景
- 相关矩阵可视化（G2）
- 双变量敏感性网格（销量 × 单价 → NPV）（E3）
- 月份 × 产品 收入热度

## 数据结构
```json
{
  "xCategories": ["单价1", "单价2", "单价3"],
  "yCategories": ["销量1", "销量2", "销量3"],
  "series": [
    { "name": "NPV", "data": [[0, 0, 100], [0, 1, 120], [1, 0, 110], "..."] }
  ]
}
```
- data 每项 [xIndex, yIndex, value]（ECharts 热力图格式）
- 相关矩阵时：x/yCategories 为变量名，value 为 r

## 选型建议
- 矩阵型数据 → heatmap
- 两变量敏感性 → heatmap（颜色=结果）
- 变量关系散点 → scatter

## 变体清单（P5-②，template 传 `类型-变体` 名）

| 变体 | 图表 | 选型 |
|------|------|------|
| `heatmap` / `heatmap-simple` | 连续色热力（默认） | 相关矩阵/双变量敏感性 |
| `heatmap-discrete` | 离散热力 | 4 段离散色阶（等级/评分） |
| `heatmap-calendar` | 日历热力 | 按日期分布（data.calendarRange=[start,end]）|

> 借鉴官方示例：heatmap-cartesian（矩阵）/ heatmap-piecewise（离散）/ calendar-heatmap（日历）。

## 注意事项
- 建议开 visualMap 连续色带（红=高，蓝=低）
- 单元格 > 400 时考虑降采样
