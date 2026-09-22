# 图表模板：treemap（矩形树图）

## 用途

> **复杂度档位：L2 中等**（P6-①：多维变量 + 色彩/大小编码，财务最常用）

展示多层占比结构（矩形面积 = 数值），适合科目/部门层级占比。

## 典型场景
- 部门/科目预算结构（B1）
- 产品线 → 子产品 → 明细三层占比（C4）
- 费用科目层级构成

## 数据结构
```json
{
  "series": [
    {
      "name": "预算结构",
      "data": [
        { "name": "销售部", "value": 100, "children": [
          { "name": "A组", "value": 60 }, { "name": "B组", "value": 40 }
        ] },
        { "name": "研发部", "value": 80 }
      ]
    }
  ]
}
```
- data 为**树形嵌套**（name/value/children），面积按 value 占比
- 支持任意层级（children 递归）

## 变体清单（P5-③，template 传 `类型-变体` 名）

| 变体 | 图表 | 选型 |
|------|------|------|
| `treemap` / `treemap-simple` | 矩形树图（默认） | 多层占比一目了然 |
| `treemap-drilldown` | 下钻矩形树 | leafDepth=1 逐层下钻，层级多时 |

> 借鉴官方示例：treemap-simple / treemap-drilldown。

## 选型建议
- 层级 ≤ 3 且要整体看 → treemap
- 层级 > 3 或节点多 → treemap-drilldown（逐层下钻）
- 只看一层占比 → pie 更直观

## 注意事项
- 数据 ≤ 200 点；节点名过长自动截断
- 面积为 0 的节点不显示
