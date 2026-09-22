"""阶段 3 端到端：/run 执行链路产出图表 option 是否含官方级优化。"""
import sys, json
sys.path.insert(0, r"d:\Finance Recon Agent\finance-agent-workbench")
from app import create_app

c = create_app().test_client()
project_id = "80658bea48c74b16983c5a4c614376ad"

# 1) 用真实项目跑一个 run（D4 同比环比，2 张图 bar + line）
r = c.post("/api/apps/finmod/run", json={
    "project_id": project_id,
    "file_name": "销售提成汇总表2021-2026 0722.xlsx",
    "sheet_name": "汇总表",
    "model_ids": ["d4-yoy-mom"],
    "mappings": {
        "d4-yoy-mom": {
            "current": {"mapped_col": "2025年回款"},
            "prev": {"mapped_col": "2024年回款"},
            "ratio": {"mapped_col": "2025年回款"},
        }
    },
    "chart_manifest": [
        {"id": "c1", "template": "bar", "variant": "bar", "name": "年度回款对比"},
        {"id": "c2", "template": "line", "variant": "line", "name": "回款趋势"},
    ],
})
d = r.get_json()
if not d.get("success"):
    print("run FAIL:", d.get("message", d))
    sys.exit(1)
charts = d["data"].get("charts") or []
print(f"run OK, {len(charts)} 张图")
for ch in charts:
    opt = ch.get("option") or {}
    series = opt.get("series")
    has_anim = opt.get("animationDuration") == 1500
    n = 0
    if isinstance(series, list) and series and isinstance(series[0], dict):
        n = len(series[0].get("data") or [])
    print(f"  {ch.get('template'):8s} 数据量={n} 动画={has_anim}")
    # 图表数据适配：模板类型 shape
    print(f"    shape keys: {list((ch.get('data') or {}).keys())[:4]}")
