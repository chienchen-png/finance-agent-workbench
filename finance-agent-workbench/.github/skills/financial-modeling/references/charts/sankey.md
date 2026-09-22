# 图表模板：sankey（桑基图）

## 用途

> **复杂度档位：L2 中等**（P6-①：多维变量 + 色彩/大小编码，财务最常用）

展示流量/资金在节点间的流向与规模（进阶）。

## 典型场景
- 资金流向：收入来源 → 用途
- 成本流向：成本中心 → 产品
- 客户 → 产品 → 渠道 流量

## 数据结构
```json
{
  "nodes": [
    { "name": "收入A" }, { "name": "收入B" },
    { "name": "成本X" }, { "name": "利润" }
  ],
  "links": [
    { "source": "收入A", "target": "成本X", "value": 300 },
    { "source": "收入B", "target": "成本X", "value": 200 },
    { "source": "收入A", "target": "利润", "value": 100 }
  ]
}
```
- nodes：节点名数组；links：source → target → value（流量）

## 选型建议
- 流向/流量 → sankey
- 阶段递减 → funnel
- 简单占比 → pie

## 变体清单（P5-②，template 传 `类型-变体` 名）

| 变体 | 图表 | 选型 |
|------|------|------|
| `sankey` / `sankey-simple` | 水平桑基（默认） | 资金/流量流向 |
| `sankey-vertical` | 垂直桑基 | 上下层级（预算科目树） |

> 借鉴官方示例：sankey-energy（水平）/ sankey-vertical（垂直）。

## 注意事项
- 节点 ≤ 20 个（过多图乱）
- 流入 = 流出（守恒），数值需一致
- 进阶模板，仅在用户明确需要时使用
