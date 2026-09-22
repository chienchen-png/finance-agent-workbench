# 图表模板：graph（关系图）

## 用途

> **复杂度档位：L2 中等**（P6-①：多维变量 + 色彩/大小编码，财务最常用）

展示实体间关系网络（节点 + 连线），适合资金往来、科目关联、客户-合同网络。

## 典型场景
- 客户 ↔ 销售人员的回款关系网络
- 科目之间的勾稽/流转关系
- 关联公司资金往来

## 数据结构
```json
{
  "categories": ["客户", "内部"],
  "nodes": [
    { "name": "A公司", "category": 0, "value": 100 },
    { "name": "销售部", "category": 1, "value": 180 }
  ],
  "links": [
    { "source": "A公司", "target": "销售部", "value": 100 }
  ]
}
```
- nodes[].name 唯一；category 对应 categories 索引（分类着色）
- links 的 source/target 引用节点 name；value 为关系强度（线宽）

## 变体清单（P5-③，template 传 `类型-变体` 名）

| 变体 | 图表 | 选型 |
|------|------|------|
| `graph` / `graph-force` | 力导向图（默认） | 网络关系自动布局 |
| `graph-circle` | 环形关系图 | 环形布局，层级环/环形对比 |

> 借鉴官方示例：graph-force / graph-circular-layout。

## 选型建议
- 节点 ≤ 30 且关系复杂 → graph（力导向可拖拽）
- 有明确层级/环形结构 → graph-circle
- 只想看两两关系 → scatter 或 heatmap 更简洁

## 注意事项
- 节点 ≤ 50；关系过多时标签重叠（可关 label）
- 同 name 节点必须唯一（否则连线错乱）
