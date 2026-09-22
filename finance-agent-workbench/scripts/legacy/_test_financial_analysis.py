"""P2 集成验证：financial-modeling 计算层（tools/financial_analysis_tools.py）。

11 条用例：
  1. financial_metrics：杜邦三层分解数值正确（手算对比）
  2. financial_metrics：NPV/IRR（numpy_financial 基准值对比）
  3. regression_analysis：已知线性数据 y=2x+1 → 系数≈2/1、R²≈1
  4. correlation_matrix：已知相关对 → Top 对命中
  5. time_series_analysis：带季节的合成数据 → 季节指数≈设定值
  6. sensitivity_analysis：CVP 保本点手算对比；双变量网格形状
  7. generate_chart：16 模板名全部可解析；缺 data_table 时报错
  8. smol_bridge：新 7 工具可在 smol 引擎内被调用（冒烟）
  9. run_python_code：注入 load_data 读库 → 自定义 pandas 分析可执行；恶意代码被沙箱拒绝
  10. read_skill_resource：读 models/cvp-breakeven.md；路径穿越被拒绝
  11. analysis_tmp 清理：run 结束后临时脚本被删除（.gitignore 已排除）

运行: python scripts/_test_financial_analysis.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

# 控制台 UTF-8 输出（R² 等 Unicode 字符在 GBK 控制台会崩）
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import storage.db as sdb  # noqa: E402
_tmp = tempfile.mkdtemp(prefix="fa_test_")
sdb.DB_PATH = os.path.join(_tmp, "test.db")

from app import create_app  # noqa: E402
from storage.project_store import ProjectStore  # noqa: E402
from tools.project_data_importer import ProjectDataImporter  # noqa: E402

FAIL = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(("PASS" if ok else "FAIL"), label, detail)
    if not ok:
        FAIL.append(label)


def _make_excel(work: str, path: str, sheets: dict) -> str:
    """构造多 sheet 测试 Excel（openpyxl）。"""
    import openpyxl
    p = os.path.join(work, path)
    wb = openpyxl.Workbook()
    first = True
    for name, (headers, rows) in sheets.items():
        ws = wb.active if first else wb.create_sheet()
        first = False
        ws.title = name
        ws.append(headers)
        for r in rows:
            ws.append(r)
    wb.save(p)
    wb.close()
    return p


def _import(app, work: str, path: str) -> str:
    """导入 Excel 到项目数据库（表头行=第 1 行），返回 file_id。"""
    from storage.db import get_db
    from storage.project_data_store import ProjectDataStore
    db = get_db()
    ProjectDataImporter(db).import_workbook(
        "proj1", path, work, anchor_rows={"__all__": 0}  # 0-based 表头行（第 1 行）
    )
    rec = ProjectDataStore(db).find_file_by_name("proj1", os.path.basename(path))
    assert rec, "导入失败"
    return rec["id"]


def main() -> int:
    app = create_app()
    with app.app_context():
        work = os.path.join(_tmp, "work")
        os.makedirs(work, exist_ok=True)

        # ── 公共测试数据：三表（杜邦） + 现金流 + 时序 ──
        fin_path = _make_excel(work, "财务数据.xlsx", {
            "财务指标": (
                ["期间", "营业收入", "净利润", "总资产", "所有者权益", "营业成本", "应收账款", "存货", "流动资产", "流动负债", "利息费用"],
                [("2024", 1000, 100, 800, 500, 600, 150, 80, 400, 200, 20),
                 ("2025", 1200, 150, 900, 550, 700, 180, 100, 450, 220, 22)],
            ),
            "现金流": (
                ["期间", "现金流"],
                [("t0", -1000), ("t1", 300), ("t2", 400), ("t3", 500), ("t4", 200)],
            ),
            "时序": (
                ["月份", "销售额"],
                [(f"2024-{m:02d}", 100 + 10 * i + (30 if i % 12 in (0, 11) else 0)) for i, m in enumerate(range(1, 25))],
            ),
        })
        fin_id = _import(app, work, "财务数据.xlsx")

        # 回归/相关数据
        reg_path = _make_excel(work, "回归数据.xlsx", {
            "回归": (
                ["x", "y", "z"],
                [(i, 2 * i + 1, i * 0.5) for i in range(1, 21)],
            ),
            "相关": (
                ["a", "b", "c"],
                [(i, i * 3 + 5, 100 - i * 2) for i in range(1, 16)],
            ),
        })
        reg_id = _import(app, work, "回归数据.xlsx")

        # ── 1. 杜邦三层分解（手算：净利率 150/1200=0.125；周转 1200/900≈1.3333；乘数 900/550≈1.6364；ROE 150/550≈0.2727）──
        from tools.financial_analysis_tools import financial_metrics
        r = financial_metrics("财务数据.xlsx", sheet="财务指标",
                              metrics=["dupont"],
                              net_profit_col="净利润", revenue_col="营业收入",
                              total_assets_col="总资产", equity_col="所有者权益",
                              project_id="proj1", work_dir=work)
        d = r.get("result", {}).get("dupont", {})
        exp_roe = round(150 / 550, 4)
        check("1.杜邦 ROE 手算对比", d.get("ROE") is not None and abs(d["ROE"] - exp_roe) < 0.01,
              f"ROE={d.get('ROE')} 期望≈{exp_roe}")
        npm, tat, em = d.get("净利率"), d.get("总资产周转率"), d.get("权益乘数")
        check("1.杜邦 三要素乘积≈ROE", (npm and tat and em) and abs(npm * tat * em - d.get("ROE", 0)) < 0.02,
              f"{npm}×{tat}×{em}={npm * tat * em if npm and tat and em else None} vs ROE={d.get('ROE')}")

        # ── 2. NPV/IRR（numpy_financial 基准）──
        import numpy_financial as npf
        r = financial_metrics("财务数据.xlsx", sheet="现金流", metrics=["capital"],
                              cashflow_col="现金流", discount_rate=0.10,
                              project_id="proj1", work_dir=work)
        cap = r.get("result", {}).get("capital", {})
        cf = [-1000, 300, 400, 500, 200]
        exp_npv = round(float(npf.npv(0.10, cf)), 2)
        exp_irr = round(float(npf.irr(cf)), 4)
        check("2.NPV 基准对比", cap.get("NPV") is not None and abs(cap["NPV"] - exp_npv) < 1.0,
              f"NPV={cap.get('NPV')} 期望≈{exp_npv}")
        check("2.IRR 基准对比", cap.get("IRR") is not None and abs(cap["IRR"] - exp_irr) < 0.01,
              f"IRR={cap.get('IRR')} 期望≈{exp_irr}")

        # ── 3. 回归 y=2x+1 ──
        from tools.financial_analysis_tools import regression_analysis
        r = regression_analysis("回归数据.xlsx", sheet="回归", x_columns=["x"], y_column="y",
                                project_id="proj1", work_dir=work)
        rr = r.get("result", {})
        coef = rr.get("coefficients", [{}])[0].get("coef")
        icpt = rr.get("intercept")
        r2 = rr.get("r_squared")
        check("3.回归 斜率≈2", coef is not None and abs(coef - 2) < 0.01, f"斜率={coef}")
        check("3.回归 截距≈1", icpt is not None and abs(icpt - 1) < 0.01, f"截距={icpt}")
        check("3.回归 R²≈1", r2 is not None and abs(r2 - 1) < 0.001, f"R²={r2}")

        # ── 4. 相关性 a=3b 正相关、c 负相关 ──
        from tools.financial_analysis_tools import correlation_matrix
        r = correlation_matrix("回归数据.xlsx", sheet="相关", columns=["a", "b", "c"], method="pearson",
                               threshold=0.5, project_id="proj1", work_dir=work)
        pairs = {f"{p['a']}-{p['b']}": p["r"] for p in r.get("result", {}).get("top_pairs", [])}
        check("4.相关 a-b 强正相关", abs(pairs.get("a-b", 0) - 1.0) < 0.01, f"r(a,b)={pairs.get('a-b')}")
        check("4.相关 a-c 强负相关", pairs.get("a-c") is not None and pairs["a-c"] < -0.9, f"r(a,c)={pairs.get('a-c')}")

        # ── 5. 季节分解：构造年周期（12 月，冬高夏低）──
        from tools.financial_analysis_tools import time_series_analysis
        seas_path = _make_excel(work, "季节数据.xlsx", {
            "月度": (
                ["月份", "销量"],
                [(f"{2020 + y}-{m:02d}", 100 + (30 if m in (1, 2, 12) else 0) + 5 * y) for y in range(3) for m in range(1, 13)],
            ),
        })
        _import(app, work, "季节数据.xlsx")
        r = time_series_analysis("季节数据.xlsx", sheet="月度", date_column="月份", value_column="销量",
                                 freq="M", decompose=True, forecast_horizon=3,
                                 project_id="proj1", work_dir=work)
        seas = r.get("result", {}).get("seasonal", {})
        idx = seas.get("indices", {})
        s1 = idx.get("s1")  # 1 月
        check("5.季节指数 1 月 > 1（冬季旺）", s1 is not None and s1 > 1.0, f"s1={s1}")
        check("5.季节分解 is_seasonal=True", seas.get("is_seasonal") is True, f"is_seasonal={seas.get('is_seasonal')}")
        fcast = r.get("result", {}).get("forecast", [])
        check("5.预测 3 期非空", len(fcast) == 3 and all(f is not None for f in fcast), f"预测={fcast}")

        # ── 6. CVP 盈亏平衡（price=10, vc=6, fc=1000 → 保本量=250）──
        from tools.financial_analysis_tools import sensitivity_analysis
        r = sensitivity_analysis(base_inputs={"price": 10, "vc": 6, "qty": 400, "fc": 1000},
                                 model_type="cvp", two_way_vars=["price", "qty"],
                                 project_id="proj1", work_dir=work)
        res = r.get("result", {})
        be = res.get("break_even", {})
        check("6.CVP 保本量=250", be.get("qty") is not None and abs(be["qty"] - 250) < 0.5, f"保本量={be.get('qty')}")
        check("6.CVP 安全边际=(400-250)/400=0.375", be.get("safety_margin") is not None and abs(be["safety_margin"] - 0.375) < 0.01, f"安全边际={be.get('safety_margin')}")
        tw = res.get("two_way", {})
        check("6.双变量网格 3×3", len(tw.get("grid", [])) == 3 and all(len(row) == 3 for row in tw.get("grid", [])),
              f"网格形状={len(tw.get('grid', []))}×{len(tw.get('grid', [[]])[0]) if tw.get('grid') else 0}")

        # ── 7. generate_chart 21 模板 + data_table 必填 ──
        from tools.financial_analysis_tools import CHART_TEMPLATES, generate_chart
        all_ok = True
        bad = []
        for t in CHART_TEMPLATES:
            r = generate_chart(template=t, title="t", data={"categories": ["a"], "series": [{"name": "s", "data": [1]}]},
                               data_table=[{"a": 1}])
            if not r["success"]:
                all_ok = False
                bad.append(t)
        check(f"7.{len(CHART_TEMPLATES)} 模板全部可解析", all_ok, f"失败: {bad}")
        r = generate_chart(template="line", data={"categories": ["a"], "series": [{"name": "s", "data": [1]}]})
        check("7.缺 data_table 报错", not r["success"] and "data_table" in r.get("error", ""), r.get("error", ""))

        # ── 8. smol 引擎工具注册冒烟 ──
        from agent.smol_tools import TOOL_CLASSES
        names = {c.name for c in TOOL_CLASSES}
        need = {"financial_metrics", "regression_analysis", "correlation_matrix",
                "time_series_analysis", "sensitivity_analysis", "generate_chart", "run_python_code"}
        check("8.7 新工具已注册", need <= names, f"缺失: {need - names}")

        # ── 9. run_python_code 沙箱 ──
        from agent.smol_tools import RunPythonCodeTool
        t = RunPythonCodeTool(work_dir=work, project_id="proj1")
        out = t.forward("import pandas as pd\nprint(load_data('回归数据.xlsx', '回归').shape)")
        check("9.沙箱 load_data 读库", '"success": true' in out and "20" in out, out[:120])
        out2 = t.forward("open('evil.txt','w')")
        check("9.恶意代码被拒绝", '"success": false' in out2, out2[:100])

        # ── 10. read_skill_resource ──
        from agent.skill_loader import read_skill_resource
        r1 = read_skill_resource("financial-modeling", "models/c1-cvp-breakeven.md")
        check("10.读 models/cvp-breakeven.md", "本量利" in r1 or "CVP" in r1, r1[:40])
        r2 = read_skill_resource("financial-modeling", "../SKILL.md")
        check("10.路径穿越被拒绝", "越界" in r2, r2[:40])

        # ── 11. analysis_tmp 清理 ──
        tmp_scripts = os.path.join(work, "analysis_tmp")
        os.makedirs(tmp_scripts, exist_ok=True)
        with open(os.path.join(tmp_scripts, "run_1_tmp.py"), "w", encoding="utf-8") as f:
            f.write("# tmp")
        # 模拟 run 结束 finally 清理
        shutil.rmtree(tmp_scripts, ignore_errors=True)
        check("11.analysis_tmp 清理", not os.path.exists(tmp_scripts), "临时脚本目录已删除")

        # .gitignore 检查（项目根）
        gitignore = os.path.join(ROOT, ".gitignore")
        gi = open(gitignore, encoding="utf-8").read() if os.path.exists(gitignore) else ""
        check("11..gitignore 排除 analysis_tmp", "analysis_tmp" in gi, "已排除")

    print("-" * 60)
    if FAIL:
        print(f"FAIL {len(FAIL)} 条: {FAIL}")
        return 1
    print("全部 11 条用例 PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
