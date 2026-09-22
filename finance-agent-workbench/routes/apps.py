"""apps.py — 集成应用专用 API（混合模式：确定性核对 + 一次 LLM 报告）。

背景（2026-08-20）：
  数据核对与校验应用原链路 = smolagents Agent 全程编排（多轮思考/规划/转述），
  核对耗时分钟级、token 消耗高、差异表还依赖 LLM 转述 JSON（会失败）。

  改进为「混合模式」：
    1. 确定性核对：后端直接调用 reconcile_variables（纯 Python 计算，秒级）
    2. 一次 LLM 调用：只把「参数 + 差异摘要」喂给模型，生成归因/报告文案
    3. 差异表数据 = 工具直出 JSON（100% 可靠），不再依赖 LLM 复述

  重构第一步（2026-08-20）：
    - 每次执行使用独立临时数据库（storage/tmp_db.py）：上传 Excel 导入临时库，
      核对/审计/修改全在临时库进行，不污染主库，Excel 重新识别
    - reconcile_variables 增加轮次感知（audit_mode）：未匹配记录升级为待审计项
      （总表独有/分表独有/一对多模糊），支持多轮核对闭环
    - 新 API：POST /api/apps/recon/verify（创建临时库+首轮核对）、
      POST /api/apps/recon/audit（提交审计决策+下一轮核对）

  报告输出：LLM 生成 Markdown 报告；模型不可用时降级为确定性摘要报告。
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from flask import Blueprint

from agent.llm_client import LLMClient
from routes import finmod_refs
from routes._utils import error, payload, success
from storage.db import get_db
from storage.model_store import ModelStore
from storage.project_data_store import ProjectDataStore
from storage.project_store import ProjectStore
from storage.tmp_db import TmpRun, get_run, register_run, unregister_run
from tools.reconcile_tool import _valid_columns, reconcile_variables

logger = logging.getLogger(__name__)

apps_bp = Blueprint("apps_api", __name__, url_prefix="/api/apps")

# 差异表展示上限（与前端一致）
MAX_DIFFS = 500


# ----------------------------------------------------------------------
# 工具：列名相似度匹配（依据表金额列自动解析）
# ----------------------------------------------------------------------

def _norm(s: str) -> str:
    return (
        str(s)
        .replace(" ", "")
        .replace("_", "")
        .replace("-", "")
        .replace("（", "")
        .replace("）", "")
        .replace("(", "")
        .replace(")", "")
        .lower()
    )


def _similar(a: str, b: str) -> bool:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    return na == nb or na in nb or nb in na


def _match_amount_col(store: ProjectDataStore, project_id: str,
                      base_file: str, detail_file: str, target_col: str) -> str | None:
    """在依据表中找与分表核对变量（target_col）同名或相似的金额列。

    target_col 是分表字段名；依据表列名可能不同（如「兑现销售提成金额_2025年一季度」
    vs「个人提成金额_元」）。优先同名，其次归一化相似。找不到返回 None。
    """
    for sh in _file_sheets(store, project_id, base_file):
        cols1 = _valid_columns(sh)
        if target_col in cols1:
            return target_col
        for c in cols1:
            if _similar(c, target_col):
                return c
    return None


def _file_sheets(store: ProjectDataStore, project_id: str,
                 file: str) -> list[dict]:
    """返回文件的所有 sheet 记录（无则空列表）。"""
    try:
        file_rec = store.find_file_by_name(project_id, file)
        if not file_rec:
            return []
        return store.list_sheets(file_rec["id"]) or []
    except Exception:  # noqa: BLE001
        return []


def _pick_base_sheet(store: ProjectDataStore, project_id: str,
                     base_file: str, match_keys: list[str],
                     src_col: str) -> str:
    """为依据表选择核对用的 sheet。

    多 sheet 文件（如销售提成汇总表：说明/汇总表/2024年/2025年…）：
    - 跳过「说明」类 sheet；
    - 优先选同时含「匹配键 k1」与「金额列」的 sheet；
    - 候选按行数降序，选行数最多的（数据主体 sheet）。
    """
    best = ""
    best_rows = -1
    for sh in _file_sheets(store, project_id, base_file):
        name = sh.get("sheet_name") or ""
        if "说明" in name or "目录" in name or "封面" in name:
            continue
        cols = set(_valid_columns(sh))
        if match_keys and match_keys[0] not in cols:
            continue  # 无匹配键 → 非数据主体 sheet
        # 兼容：金额列可能不在本 sheet（分年度拆分），但匹配键在即视为候选
        rows = int(sh.get("row_count") or sh.get("total_rows") or 0)
        if rows > best_rows:
            best_rows = rows
            best = name
    if best:
        return best
    # 兜底：返回首个非「说明」sheet
    for sh in _file_sheets(store, project_id, base_file):
        name = sh.get("sheet_name") or ""
        if "说明" not in name and "目录" not in name:
            return name
    return ""


# ----------------------------------------------------------------------
# 工具：LLM 报告生成
# ----------------------------------------------------------------------

REPORT_SYSTEM = (
    "你是「数据核对与校验」集成应用的报告撰写 AI。\n"
    "输入是确定性核对引擎输出的差异数据与核对参数，请据此撰写专业的中文核对报告。\n"
    "只输出报告本身，不要任何多余解释、不要客套。\n\n"
    "报告结构（Markdown）：\n"
    "1. 核对信息（依据表/分表/匹配键/核对变量/容差/匹配不上处理）\n"
    "2. 总览（OK/A1/A2/B/C 计数）\n"
    "3. 差异明细表（Markdown 表格：级别/关键值/依据金额/目标金额/差异/原因，只列有差异的行）\n"
    "4. 原因分类（按 reason 汇总各类条数）\n"
    "5. 修改方案（按级别给出处理建议：A 类自动填充/修正，B 类人工逐条确认，C 类人工复核）\n\n"
    "金额保留两位小数并加千分位；使用中文。"
)


def _chat_complete(client: LLMClient, messages: list[dict],
                   temperature: float = 0.2, max_tokens: int = 6000,
                   retries: int = 1,
                   thinking: bool | None = None,
                   reasoning_effort: str | None = None) -> str:
    """流式收集一次 chat 调用的完整输出文本（失败重试）。

    deepseek-v4-flash 等推理模型（思考模式）会把正文放进 `reasoning_content`
    而 `content` 为空/极短——只读 `delta` 会拿到空内容导致「AI 匹配不可用」。
    这里同时采集 `delta`（正文优先）与 `reasoning_delta`（正文缺失时的兜底）；
    并对 deepseek 系默认关闭思考（实测关思考后 content 正常返回完整答案）。
    """
    # deepseek 系推理模型默认思考易致 content 为空/乱码 → 关思考取完整正文
    model_name = str(getattr(client, "model", "") or "").lower()
    if thinking is None and "deepseek" in model_name:
        thinking = False
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            buf: list[str] = []
            reason_buf: list[str] = []
            for chunk in client.chat_stream(messages, temperature=temperature,
                                            max_tokens=max_tokens,
                                            thinking=thinking,
                                            reasoning_effort=reasoning_effort):
                d = chunk.get("delta") or ""
                if d:
                    buf.append(d)
                # 正文缺失时回退 reasoning_content（推理模型把答案放这里）
                if not buf:
                    r = chunk.get("reasoning_delta") or ""
                    if r:
                        reason_buf.append(r)
                if chunk.get("finish_reason"):
                    break
            # 正文优先；正文为空但理清了内容（深思考模型）则用 reasoning 兜底
            text = "".join(buf) or "".join(reason_buf)
            if text.strip():
                return text
            last_err = ValueError("模型返回空内容")
        except Exception as e:  # noqa: BLE001
            last_err = e
            logger.warning("LLM 报告生成第 %d 次失败: %s", attempt + 1, e)
            continue
    raise last_err  # type: ignore[misc]


def _build_llm_client(model_id: str) -> LLMClient | None:
    """从模型配置构建 LLMClient；失败返回 None（降级为确定性报告）。"""
    try:
        from routes.workspace import _build_llm_client as _ws_client
        return _ws_client(ModelStore(get_db()), model_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("构建 LLM 客户端失败: %s", e)
        return None


def _fmt_amount(v: Any) -> str:
    if v is None or v == "" or v == "-":
        return "—"
    try:
        return f"{float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v)


def _fallback_report(params: dict, result: dict) -> str:
    """模型不可用时的确定性降级报告（纯 Markdown 摘要）。"""
    s = result.get("summary", {})
    mk = params.get("matchKeys") or {}
    keys = [mk.get("k1") or "", mk.get("k2On") and mk.get("k2") or "",
            mk.get("k3On") and mk.get("k3") or ""]
    keys = [k for k in keys if k]
    lines = [
        "## 核对报告（确定性引擎 · 未接入 AI 归因）",
        "",
        "### 核对信息",
        f"- 依据表：{params.get('baseFile')}",
        f"- 分表：{params.get('detailFile')}",
        f"- 匹配键：{' > '.join(keys) if keys else '—'}",
        f"- 核对变量：{(params.get('variables') or [])[0] or '—'}",
        f"- 依据表金额列：{params.get('baseAmountCol') or '（自动匹配）'}",
        f"- 容差：{params.get('tolerance')} 元",
        "",
        "### 总览",
        f"| 级别 | 数量 | 说明 |",
        f"|---|---|---|",
        f"| OK | {s.get('ok', 0)} | 一致 |",
        f"| A1 | {s.get('a1', 0)} | 漏填缺失（应填充） |",
        f"| A2 | {s.get('a2', 0)} | 小额误差（应修正） |",
        f"| B | {s.get('b', 0)} | 待确认 |",
        f"| C | {s.get('c', 0)} | 无法匹配（人工复核） |",
        f"| 合计 | {s.get('total', 0)} | 依据表行数 |",
        "",
        "### 差异明细",
        "",
    ]
    diffs = result.get("differences", [])[:50]
    if diffs:
        lines.append("| 级别 | 关键值 | 依据金额 | 目标金额 | 差异 | 原因 |")
        lines.append("|---|---|---|---|---|---|")
        for d in diffs:
            lines.append(
                f"| {d.get('level', 'B')} | {d.get('key1', '—')} "
                f"| {_fmt_amount(d.get('source_amount'))} | {_fmt_amount(d.get('target_amount'))} "
                f"| {_fmt_amount(d.get('diff'))} | {d.get('reason', '—')} |"
            )
    else:
        lines.append("（无差异记录）")
    unmatched = result.get("unmatched", [])[:20]
    if unmatched:
        lines.append("")
        lines.append("### 无法匹配（C 类）")
        for u in unmatched:
            lines.append(f"- {u.get('key', '—')}：{u.get('reason', '')}")
    lines.append("")
    lines.append("> 注：当前模型不可用，本报告由核对引擎直接生成；如需 AI 归因与修改方案，请检查模型配置后重新核对。")
    return "\n".join(lines)


def _build_user_content(params: dict, result: dict) -> str:
    """组装用户消息：核对参数 + 差异摘要（差异 JSON 截断控制 token）。"""
    mk = params.get("matchKeys") or {}
    keys = [mk.get("k1") or "", mk.get("k2On") and mk.get("k2") or "",
            mk.get("k3On") and mk.get("k3") or ""]
    keys = [k for k in keys if k]
    s = result.get("summary", {})
    action_raw = params.get("unmatchedAction") or "list"
    action_label = {
        "list": "A. 列清单供人工复核",
        "fallback": "B. 按（人员+客户）降级匹配",
        "mark": "C. 全部标记无法匹配",
    }.get(action_raw, f"自定义：{action_raw}")
    lines = [
        "## 核对参数（用户向导已确认）",
        f"- 依据表：{params.get('baseFile')}",
        f"- 分表：{params.get('detailFile')}",
        f"- 匹配键层级：{' > '.join(keys) if keys else '—'}",
        f"- 核对变量（分表字段）：{(params.get('variables') or [])[0] or '—'}",
        f"- 依据表金额列：{params.get('baseAmountCol') or '（自动匹配）'}",
        f"- 容差：{params.get('tolerance')} 元",
        f"- 匹配不上处理：{action_label}",
        f"- 差异自动处理：{'开启（A 类自动写回）' if params.get('autoFix') else '关闭（仅报告不写回）'}",
        "",
        "## 核对结果总览",
        f"总计 {s.get('total', 0)} 行，匹配 {s.get('matched', 0)}；"
        f"OK {s.get('ok', 0)}，A1 {s.get('a1', 0)}，A2 {s.get('a2', 0)}，"
        f"B {s.get('b', 0)}，C {s.get('c', 0)}。",
        "",
        "## 差异明细（JSON，供撰写报告；全部非 OK 差异）",
        json.dumps(
            {
                "differences": result.get("differences", []),
                "unmatched": result.get("unmatched", []),
            },
            ensure_ascii=False,
        )[:12000],
    ]
    return "\n".join(lines)


# ----------------------------------------------------------------------
# 工具：工具输出 → 前端 reconData 结构
# ----------------------------------------------------------------------

def _tool_to_recon(result: dict) -> dict:
    """把 reconcile_variables 输出转成前端 ReconData 结构（差异表直出）。"""
    s = result.get("summary", {})
    diffs: list[dict] = []
    for d in result.get("differences", []):
        key1 = d.get("key1") or ""
        key2 = d.get("key2") or ""
        diffs.append({
            "level": (d.get("level") or "B").upper(),
            "contract": str(key1),
            "person": str(key2) if key2 and key2 != key1 else "",
            "client": "",
            "base_amount": d.get("source_amount"),
            "target_amount": d.get("target_amount"),
            "diff": d.get("diff"),
            "reason": d.get("reason") or "",
            "suggestion": "",
        })
    for u in result.get("unmatched", []):
        diffs.append({
            "level": "C",
            "contract": str(u.get("key") or ""),
            "person": "",
            "client": "",
            "base_amount": None,
            "target_amount": None,
            "diff": None,
            "reason": u.get("reason") or "目标表无对应记录",
            "suggestion": "",
        })
    return {
        "summary": {
            "ok": int(s.get("ok") or 0),
            "a1": int(s.get("a1") or 0),
            "a2": int(s.get("a2") or 0),
            "b": int(s.get("b") or 0),
            "c": int(s.get("c") or 0),
        },
        "diffs": diffs[:MAX_DIFFS],
    }


# ----------------------------------------------------------------------
# 工具：临时库数据准备（主库 → 临时库复制）
# ----------------------------------------------------------------------

def _copy_project_data_to_tmp(main_db: Any, tmp_db: Any, project_id: str) -> None:
    """把主库中某项目的数据平面（文件/sheets/变更日志 + 数据表）复制到临时库。

    应用执行要求：所有核对/审计/修改在独立临时库进行（不污染主库）。
    这里从主库复制已导入的文件记录与数据表到临时库——临时库作为本次执行
    的私有快照；对数据的任何修改只发生在临时库，最后回写 Excel。
    """
    # 注意：ProjectDataStore.list_sheets 会把 headers_json 解析为 headers 列表，
    # 直接查原始表行（headers_json 保持 JSON 字符串）才能正确复制。
    file_rows = main_db.execute(
        "SELECT * FROM project_data_files WHERE project_id = ?", (project_id,)
    ).fetchall()

    for fr in file_rows:
        fid = fr["id"]
        tmp_db.execute(
            "INSERT OR IGNORE INTO project_data_files (id, project_id, source_path,"
            " file_name, file_hash, format, sheet_count, total_rows, status,"
            " error_message, meta_json, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                fid, fr["project_id"], fr["source_path"] or "",
                fr["file_name"] or "", fr["file_hash"] or "",
                fr["format"] or "", fr["sheet_count"] or 0,
                fr["total_rows"] or 0, fr["status"] or "done",
                fr["error_message"], fr["meta_json"],
                fr["created_at"] or "", fr["updated_at"] or "",
            ),
        )
        # 复制 sheets 记录（直接查原始行，保留 headers_json 字符串）
        sheet_rows = main_db.execute(
            "SELECT * FROM project_data_sheets WHERE file_id = ? ORDER BY sheet_index",
            (fid,),
        ).fetchall()
        for sh in sheet_rows:
            tmp_db.execute(
                "INSERT OR IGNORE INTO project_data_sheets (id, file_id, sheet_name,"
                " sheet_index, table_name, row_count, col_count, headers_json)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (
                    sh["id"], sh["file_id"], sh["sheet_name"] or "",
                    sh["sheet_index"] or 0, sh["table_name"] or "",
                    sh["row_count"] or 0, sh["col_count"] or 0,
                    sh["headers_json"],
                ),
            )
            # 复制数据表：从主库读行 → 写入临时库（跨连接无法 CREATE AS SELECT）
            table_name = sh["table_name"]
            if not table_name:
                continue
            tmp_db.execute(f'DROP TABLE IF EXISTS "{table_name}"')
            col_rows = main_db.execute(
                f'PRAGMA table_info("{table_name}")'
            ).fetchall()
            cols = [c["name"] for c in col_rows]
            rows = main_db.execute(f'SELECT * FROM "{table_name}"').fetchall()
            if not cols:
                continue
            col_list = ", ".join(f'"{c}"' for c in cols)
            tmp_db.execute(f'CREATE TABLE "{table_name}" ({col_list})')
            if rows:
                placeholders = ", ".join("?" for _ in cols)
                tmp_db.executemany(
                    f'INSERT INTO "{table_name}" ({col_list}) VALUES ({placeholders})',
                    [tuple(r[c] for c in cols) for r in rows],
                )
    tmp_db.commit()


def _resolve_verify_params(params: dict, store: ProjectDataStore,
                          project_id: str) -> dict:
    """从向导参数解析核对参数（匹配键/金额列/sheet），供 verify/audit 共用。"""
    mk = params.get("matchKeys") or {}
    match_keys = [mk.get("k1") or "", mk.get("k2On") and mk.get("k2") or "",
                  mk.get("k3On") and mk.get("k3") or ""]
    match_keys = [k for k in match_keys if k]
    variables = params.get("variables") or []
    target_col = variables[0] if variables else ""
    if not target_col:
        raise ValueError("缺少核对变量（variables）")
    try:
        tolerance = float(params.get("tolerance") or 1)
    except (TypeError, ValueError):
        tolerance = 1.0
    action_raw = params.get("unmatchedAction") or "list"
    unmatched_action = "fallback_person_customer" if action_raw == "fallback" else "list"

    base_file = params.get("baseFile") or ""
    detail_file = params.get("detailFile") or ""
    if not base_file or not detail_file:
        raise ValueError("缺少依据表/分表")

    # 依据表金额列：优先用向导显式选择（baseAmountCol）；未提供时自动匹配
    src_col = (params.get("baseAmountCol") or "").strip() or None
    if not src_col:
        src_col = _match_amount_col(store, project_id, base_file, detail_file, target_col)
    if src_col is None:
        raise ValueError(f"无法在依据表中找到与核对变量「{target_col}」匹配的金额列，请检查参数")
    amount_col = f"{src_col}->{target_col}" if src_col != target_col else target_col

    # 依据表 sheet 自动选择（跳过说明页，取含匹配键的数据主体 sheet）
    base_sheet = _pick_base_sheet(store, project_id, base_file, match_keys, src_col)
    return {
        "base_file": base_file,
        "detail_file": detail_file,
        "base_sheet": base_sheet,
        "match_keys": match_keys,
        "amount_col": amount_col,
        "tolerance": tolerance,
        "unmatched_action": unmatched_action,
        "src_col": src_col,
    }


def _project(project_id: str) -> dict | None:
    """查询项目（含 work_dir）。"""
    if not project_id:
        return None
    return ProjectStore(get_db()).get_by_id(project_id)


# ----------------------------------------------------------------------
# API：校验（确定性核对 + 一次 LLM 报告）
# ----------------------------------------------------------------------

@apps_bp.post("/recon/verify")
def recon_verify():
    p = payload()
    project_id = p.get("project_id") or ""
    model_id = p.get("model_id") or ""
    params = p.get("params") or {}
    if not project_id:
        return error("缺少 project_id")

    # 解析核对参数（主库用于解析列名/sheet，临时库用于实际核对）
    main_store = ProjectDataStore(get_db())
    try:
        rp = _resolve_verify_params(params, main_store, project_id)
    except ValueError as e:
        return error(str(e))

    # 1) 创建本次执行临时库 + 复制数据快照
    run = TmpRun.create()
    register_run(run.run_id, run)
    try:
        _copy_project_data_to_tmp(get_db(), run.db, project_id)
        tmp_store = ProjectDataStore(run.db)

        # 2) 确定性核对（轮次感知：未匹配 → 审计项）
        result = reconcile_variables(
            file1=rp["base_file"],
            file2=rp["detail_file"],
            sheet1=rp["base_sheet"],
            match_keys=rp["match_keys"],
            amount_col=rp["amount_col"],
            tolerance=rp["tolerance"],
            unmatched_action=rp["unmatched_action"],
            project_id=project_id,
            merge_sheets2=True,
            db_override=run.db,
            audit_mode=True,
        )
        if not result.get("success"):
            return error(result.get("error") or "核对失败")

        # 3) 一次 LLM 调用生成报告（模型不可用 → 确定性降级报告）
        report = ""
        client = _build_llm_client(model_id)
        if client:
            try:
                report = _chat_complete(
                    client,
                    [
                        {"role": "system", "content": REPORT_SYSTEM},
                        {"role": "user", "content": _build_user_content(params, result)},
                    ],
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("LLM 报告生成失败，降级为确定性报告: %s", e)
        if not report.strip():
            report = _fallback_report(params, result)

        recon_data = _tool_to_recon(result)
        audit_items = result.get("audit_items", [])
        return success({
            "run_id": run.run_id,
            "runId": run.run_id,
            "report": report,
            "reconData": recon_data,
            # 审计清单全量返回（前端逐条决策分页展示；差异表仍截断 MAX_DIFFS）
            "auditItems": audit_items,
            "raw": {
                "summary": result.get("summary"),
                "amount_col": result.get("amount_col"),
                "match_keys": result.get("match_keys"),
            },
        })
    except Exception as e:  # noqa: BLE001
        unregister_run(run.run_id)
        run.cleanup()
        logger.exception("recon/verify 失败")
        return error(f"核对执行失败: {e}")


# ----------------------------------------------------------------------
# API：审计决策提交 + 下一轮核对（多轮核对闭环）
# ----------------------------------------------------------------------

# ----------------------------------------------------------------------
# 工具：确定性写回 Excel（临时库 store + 变更日志，复用精确回写引擎）
# ----------------------------------------------------------------------

def _writeback_export(store: ProjectDataStore, project_id: str,
                      file_name: str, work_dir: str) -> dict:
    """把临时库中某文件的变更日志精确回写到源 Excel（复用 _export_precise）。

    与 tools.export_project_data 等价，但使用传入的（临时库）store ——
    写回发生在本次执行的临时库快照，变更日志记录在临时库 project_data_changes。
    """
    from tools.project_data_tools import (
        _export_precise, detect_real_format,
        ensure_file_writable, load_writer,
    )
    from tools.project_data_importer import _resolve_work_path, sha256_file

    file_rec = store.find_file_by_name(project_id, file_name)
    if not file_rec:
        return {"success": False, "error": f"项目数据库中未找到数据文件「{file_name}」"}
    full_path = _resolve_work_path(work_dir, file_rec["source_path"])
    if not os.path.isfile(full_path):
        return {"success": False, "error": f"源文件不存在: {file_rec['source_path']}"}
    lock_err = ensure_file_writable(full_path)
    if lock_err:
        return lock_err
    real_fmt = detect_real_format(full_path)
    if real_fmt not in ("xlsx", "xls"):
        return {"success": False,
                "error": f"文件实际为 {real_fmt}（非 Excel 二进制），无法安全原地写回"}
    writer = load_writer(full_path, real_fmt)
    try:
        written = _export_precise(writer, store, file_rec)
        writer.save()
    finally:
        writer.close()
    store.update_file(file_rec["id"], file_hash=sha256_file(full_path))
    return {
        "success": True,
        "file": file_rec["file_name"],
        "written_cells": written,
        "message": f"已精确回写 {written} 个单元格到「{file_rec['file_name']}」",
    }


@apps_bp.post("/recon/writeback")
def recon_writeback():
    """确定性写回（2026-08-21 修复）：勾选差异 → 临时库 update_rows → 精确回写 Excel。

    背景：写回原走 LLM Agent 编排（update_rows/export_project_data 工具链），
    模型不可用或未按指令执行时写回失败且无落盘。本次改为与校验一致的确定性
    路径：后端直接对勾选差异执行 A1/A2 写回（B/C 跳过），记录变更日志，
    再精确回写 Excel —— 不依赖 LLM，秒级完成。
    """
    p = payload()
    run_id = (p.get("run_id") or "").strip()
    project_id = (p.get("project_id") or "").strip()
    params = p.get("params") or {}
    diffs = p.get("diffs") or []
    run = get_run(run_id) if run_id else None
    if not run:
        return error("运行不存在或已清理（请重新校验后再写回）", 404)
    project = _project(project_id)
    if not project:
        return error("项目不存在", 404)

    from tools.project_data_tools import _change_log
    tmp_store = ProjectDataStore(run.db)
    try:
        rp = _resolve_verify_params(params, tmp_store, project_id)
    except ValueError as e:
        return error(str(e))
    tgt_col = rp["amount_col"].split("->")[-1].strip()
    k0 = rp["match_keys"][0] if rp["match_keys"] else ""
    if not tgt_col or not k0:
        return error("写回参数不完整（缺少金额列或匹配键）")

    written_rows = 0
    skipped = 0
    missed: list[str] = []
    for d in diffs:
        level = (d.get("level") or "").upper()
        # 仅 A 类（漏填/小额误差）确定性自动写回；B/C 需人工，跳过
        if level not in ("A1", "A2"):
            skipped += 1
            continue
        contract = (d.get("contract") or "").strip()
        new_val = d.get("base_amount")
        if not contract or new_val is None:
            missed.append(f"{level}「{contract or '无匹配键值'}」金额 {new_val if new_val is not None else '—'}")
            skipped += 1
            continue
        # merge_sheets2 场景：分表按人员拆分多 sheet，遍历全部 sheet 定位。
        # 🔴 不能用 tools.update_rows（内部绑主库 _store()）—— 直接用临时库
        #    store 更新数据表 + 手动记录变更日志（写回只发生在临时库快照）。
        done = False
        for sh in _file_sheets(tmp_store, project_id, rp["detail_file"]):
            cols = _valid_columns(sh)
            if k0 not in cols or tgt_col not in cols:
                continue
            table_name = sh.get("table_name") or ""
            if not table_name:
                continue
            prior = tmp_store.fetch_rows(table_name, [tgt_col], {k0: contract})
            if not prior:
                continue
            tmp_store.update_rows(
                table_name, {k0: contract}, {tgt_col: new_val},
                extra_cols=[k0],
            )
            headers = [h["name"] for h in (sh.get("headers") or [])]
            for old in prior:
                _change_log(
                    tmp_store, sh["file_id"], sh["sheet_name"],
                    row_index=old["id"], op_type="update",
                    columns=[tgt_col],
                    old_values={tgt_col: old.get(tgt_col)},
                    new_values={tgt_col: new_val},
                    sheet_headers=headers,
                    key_value=old.get(k0),
                )
            written_rows += len(prior)
            done = True
        if not done:
            missed.append(contract)
    run.commit()

    export_result = _writeback_export(
        tmp_store, project_id, rp["detail_file"], project["work_dir"] or "",
    )

    mk = params.get("matchKeys") or {}
    keys = [mk.get("k1") or "", mk.get("k2On") and mk.get("k2") or "",
            mk.get("k3On") and mk.get("k3") or ""]
    keys = [k for k in keys if k]
    lines = [
        "## 修改报告",
        "",
        "### 本次写回（确定性引擎 · 直接执行）",
        f"- 已写回：**{written_rows}** 行（A1 漏填/ A2 误差自动填充）",
        f"- 跳过：{skipped} 条（B 待确认 / C 无法匹配需人工，本轮不自动修改）",
    ]
    if missed:
        lines.append(f"- 未定位到分表行（跳过）：{len(missed)} 条（如 {'、'.join(missed[:5])}{'…' if len(missed) > 5 else ''}）")
    if export_result.get("success"):
        lines.append(f"- Excel 回写：✅ {export_result.get('message', '')}")
    else:
        lines.append(f"- Excel 回写：⚠️ {export_result.get('error', '失败')}（数据已写入临时库，可稍后重试导出）")
    lines.append("")
    lines.append(f"- 核对参数：依据表 {params.get('baseFile')} → 分表 {params.get('detailFile')}；")
    lines.append(f"  匹配键 {' > '.join(keys) if keys else '—'}；核对变量 {tgt_col}；容差 {rp['tolerance']} 元")
    return success({
        "written": written_rows,
        "skipped": skipped,
        "export": export_result,
        "report": "\n".join(lines),
    })


@apps_bp.post("/recon/audit")
def recon_audit():
    p = payload()
    run_id = p.get("run_id") or ""
    project_id = p.get("project_id") or ""
    params = p.get("params") or {}
    # 审计决策：[{key, side, decision}] decision ∈
    #   base 侧: "补录到分表" / "忽略(总表误记)" / "挂起"
    #   detail 侧: "补录到总表" / "忽略(分表误记)" / "挂起"
    #   ambiguous 侧: "确认对应关系" / "挂起"
    decisions = p.get("decisions") or []
    if not run_id or not project_id:
        return error("缺少 run_id/project_id")

    run = get_run(run_id)
    if not run:
        return error("临时库不存在或已过期，请重新核对")
    tmp_store = ProjectDataStore(run.db)

    try:
        rp = _resolve_verify_params(params, tmp_store, project_id)

        # 应用审计决策：非「挂起」的决策写入 run.decisions（key = "side:key"），
        # 下一轮核对用 skip_keys 排除已决策项（决策即生效：不再计入未匹配/审计）。
        applied = 0
        for dec in decisions:
            key = (dec.get("key") or "").strip()
            side = (dec.get("side") or "").strip()
            decision = (dec.get("decision") or "").strip()
            if not key or not decision or decision == "挂起":
                continue
            # 校验 side 合法性
            if side not in ("base", "detail", "ambiguous"):
                continue
            run.decisions[f"{side}:{key}"] = decision
            applied += 1

        # 下一轮核对：skip_keys = 全部已决策项（含历史轮次）
        skip_keys = list(run.decisions.keys())
        result = reconcile_variables(
            file1=rp["base_file"],
            file2=rp["detail_file"],
            sheet1=rp["base_sheet"],
            match_keys=rp["match_keys"],
            amount_col=rp["amount_col"],
            tolerance=rp["tolerance"],
            unmatched_action=rp["unmatched_action"],
            project_id=project_id,
            merge_sheets2=True,
            db_override=run.db,
            audit_mode=True,
            skip_keys=skip_keys,
        )
        if not result.get("success"):
            return error(result.get("error") or "核对失败")

        recon_data = _tool_to_recon(result)
        return success({
            "run_id": run.run_id,
            "runId": run.run_id,
            "reconData": recon_data,
            "auditItems": result.get("audit_items", []),
            "raw": {"summary": result.get("summary")},
            "applied": applied,
            "remaining": len(result.get("audit_items", [])),
        })
    except Exception as e:  # noqa: BLE001
        logger.exception("recon/audit 失败")
        return error(f"审计处理失败: {e}")


# ======================================================================
# 应用二「财务建模与分析」— P1 元数据层（2026-08-21）
# ======================================================================
# 命名空间 /api/apps/finmod：从 financial-modeling skill references 解析
# 模型目录/详情 + 图表模板目录/详情（静态缓存，不依赖 LLM）。
# P1 交付 3 端点；P2 引导引擎 / P3 变量映射 / P4 图表配置 /
# P5 执行引擎 / P6 报告交付 在后续阶段追加到本命名空间。

finmod_bp = Blueprint("finmod_api", __name__, url_prefix="/api/apps/finmod")


@finmod_bp.get("/meta")
def finmod_meta():
    """模型目录（32 个 A-G 分类）+ 图表目录（24 模板 L1/L2/L3 档位）。"""
    try:
        return success(finmod_refs.get_meta())
    except Exception as e:  # noqa: BLE001
        logger.exception("finmod/meta 失败")
        return error(f"元数据加载失败: {e}")


@finmod_bp.get("/models/<model_id>")
def finmod_model_detail(model_id: str):
    """单模型详情（目的/公式/变量表/适用场景）——<id> 经 references 映射解析。

    支持 id 形态：a1-three-statement（完整文件名）或 a1（编号前缀）。
    """
    try:
        data = finmod_refs.get_model_detail(model_id)
    except Exception as e:  # noqa: BLE001
        logger.exception("finmod/models/%s 失败", model_id)
        return error(f"模型详情解析失败: {e}")
    if data is None:
        return error(f"未找到模型「{model_id}」；可用编号见 /finmod/meta", 404)
    return success(data)


@finmod_bp.get("/charts/<chart_id>")
def finmod_chart_detail(chart_id: str):
    """单图表模板详情（用途/数据结构/选型建议/变体）。"""
    try:
        data = finmod_refs.get_chart_detail(chart_id)
    except Exception as e:  # noqa: BLE001
        logger.exception("finmod/charts/%s 失败", chart_id)
        return error(f"图表详情解析失败: {e}")
    if data is None:
        return error(f"未找到图表模板「{chart_id}」；可用模板见 /finmod/meta", 404)
    return success(data)


# ======================================================================
# 应用二 finmod — P2 引导引擎（2026-08-21）
# ======================================================================
# 建议型引导（需求文档 §2.1）：用户诉求 + 数据列名索引 ──LLM──▶ 结构化建议
# JSON ──前端──▶ 引导卡（可增删改）──▶ 配置清单。
# 原则 R1：LLM 只输出建议 JSON，永不执行计算/写文件/调工具。
# 全流程 LLM 调用预算：引导 1-2 次 + 报告 1 次 = 2-3 次。

# 引导 System prompt（输出严格 JSON，单引号容错解析 + 失败重试 1 次 + 降级）
GUIDE_SYSTEM = (
    "你是「财务建模与分析」集成应用的引导 AI，面向无财务基础的业务人员。\n"
    "你只输出建议（JSON），绝不执行任何计算、不读取数据、不调用工具。\n"
    "根据用户的一句话诉求与数据文件列名索引，推荐 1-3 个最适合的财务模型，\n"
    "并给出白话教学文案。\n\n"
    "硬性规则：\n"
    "1. 模式 mode 由系统判定给出（消息中标注），你必须原样使用，不得更改\n"
    "2. directions 的 model_id 必须从「模型目录」中选择（用完整 id 如 d1-dupont，\n"
    "   或编号如 D1），不得虚构不存在的模型\n"
    "3. teaching 教学文案：用大白话解释该模型是干什么的、为什么适合用户诉求、\n"
    "   会用用户文件的哪些列（引用具体列名）、关键公式（$$ LaTeX 块级，中文用 \\text{} 包裹）\n"
    "4. reason 推荐理由：像同事在茶水间闲聊一样口语化，1-2 句。必须引用用户诉求\n"
    "   或数据文件中的具体列名/sheet 名/数值作依据；禁止空泛总结（如\"可以全面分析\"）；\n"
    "   禁止连接词（首先/其次/此外/综上/同时）；禁止营销动词（快速/直接锁定/深度/\n"
    "   全面/助力/赋能/一步到位）；不用感叹号，不用排比句式\n"
    "5. recommended_charts：从「图表模板」中选择 1-3 个模板名（如 radar/tornado/line）\n"
    "6. 模式 A（无数据）：只填 data_needs（每条含 字段/类型/示例/用途/建议图表），directions 可为空\n"
    "7. 模式 C（无诉求）：directions 与 data_needs 都为空，explanation 给出讲解引导文案。\n"
    "   explanation 必须用 markdown 分点排版：每个「步骤/建议/示例」用 `- ` 开头单独一行，\n"
    "   数字序号（如 1）2）3））也一律换行成为独立列表项，禁止把多句话挤成一行大段文本；\n"
    "   可适当用 **加粗** 突出关键词。\n\n"
    "输出严格 JSON（不要 markdown 代码块围栏，不要多余文字）：\n"
    "{\n"
    '  "mode": "A" | "B" | "C",\n'
    '  "directions": [{"model_id": "...", "reason": "...", "teaching": "...", "recommended_charts": ["radar"]}],\n'
    '  "data_needs": [{"field": "...", "type": "数值|文本|日期", "example": "...", "purpose": "...", "suggested_chart": "..."}],\n'
    '  "explanation": "模式 C 讲解文案或整体引导说明"\n'
    "}"
)


def _detect_mode(goal: str, has_data: bool) -> str:
    """确定性模式判定（需求文档 §3.3，LLM 不可覆盖）。

    A 数据需求：有目标 + 无数据；B 已有数据：有目标 + 已上传；C 知识讲解：无目标。
    """
    if not (goal or "").strip():
        return "C"
    return "B" if has_data else "A"


def _build_files_index(store: ProjectDataStore, project_id: str) -> list[dict]:
    """数据文件列名索引摘要（列名+类型+行数，不读全量数据）。

    每个文件取前 3 个 sheet（按行数降序取数据主体），每 sheet 输出
    列名（含类型）摘要。LLM 输入用，token 可控。
    """
    out: list[dict] = []
    try:
        files = store.list_files(project_id) or []
    except Exception:  # noqa: BLE001
        return out
    for f in files:
        if f.get("status") != "done":
            continue
        sheets = (f.get("sheets") or [])[:3]
        items = []
        for sh in sheets:
            # headers = [{name, type}, ...]（list_files 已解析 headers_json）
            headers = sh.get("headers") or []
            items.append({
                "sheet": sh.get("sheet_name") or "",
                "rows": sh.get("row_count") or 0,
                "columns": [
                    {"name": h.get("name") or "", "type": h.get("type") or ""}
                    for h in headers
                ],
            })
        if items:
            out.append({
                "file": f.get("file_name") or "",
                "total_rows": f.get("total_rows") or 0,
                "sheets": items,
            })
    return out


def _model_catalog_text() -> str:
    """模型目录摘要文本（编号 + 名称 + 分类），供 LLM 选择 directions。"""
    meta = finmod_refs.get_meta()
    lines = []
    for cat in meta["model_categories"]:
        names = "、".join(f"{m['code']} {m['name']}" for m in cat["models"])
        lines.append(f"{cat['key']} {cat['label']}：{names}")
    return "\n".join(lines)


def _chart_catalog_text() -> str:
    """图表模板目录摘要文本（模板名 + 中文名 + 档位），供 LLM 推荐图表。"""
    meta = finmod_refs.get_meta()
    parts = []
    for g in meta["chart_levels"]:
        ids = "、".join(f"{c['id']}({c['name']})" for c in g["charts"])
        parts.append(f"{g['key']} {g['label']}：{ids}")
    return "\n".join(parts)


def _resolve_model_ref(ref: str) -> dict | None:
    """把 LLM 输出的模型引用（编号 D1 / 完整 id d1-dupont）归一化为 meta。"""
    raw = (ref or "").strip().lower()
    if not raw:
        return None
    for m in finmod_refs.scan_models():
        if m["code"].lower() == raw or m["id"].lower() == raw:
            return m
    return None


def _build_guide_user_content(goal: str, mode: str, files_index: list[dict]) -> str:
    lines = [
        f"系统判定模式：{mode}（{'有目标+有数据' if mode == 'B' else '有目标+无数据' if mode == 'A' else '无目标，讲解' }）",
        "",
        f"用户诉求：{goal or '（未提供——用户只想了解财务模型知识，请输出模式 C 讲解引导）'}",
        "",
    ]
    if files_index:
        lines.append("数据文件列名索引（只读列名/类型，不读数据）：")
        for f in files_index:
            lines.append(f"- 文件「{f['file']}」（共 {f['total_rows']} 行）")
            for sh in f["sheets"]:
                cols = "、".join(f"{c['name']}({c['type']})" for c in sh["columns"])
                lines.append(f"  - sheet「{sh['sheet']}」（{sh['rows']} 行）：{cols or '（无列）'}")
    else:
        lines.append("数据文件：无（用户尚未上传数据文件）")
    lines.append("")
    lines.append("模型目录（directions 从这里选）：")
    lines.append(_model_catalog_text())
    lines.append("")
    lines.append("图表模板（recommended_charts 从这里选）：")
    lines.append(_chart_catalog_text())
    return "\n".join(lines)


def _parse_guide_json(text: str) -> dict | None:
    """解析 LLM 输出 JSON（剥 markdown 围栏 + smol_model 单引号容错）。

    兼容三种形态：纯 JSON / Python 单引号 dict / ```json 围栏包裹。
    """
    if not (text or "").strip():
        return None
    import re as _re
    cleaned = text.strip()
    # 剥掉 ```json ... ``` 围栏
    if cleaned.startswith("```"):
        cleaned = _re.sub(r"^```[^\n]*\n", "", cleaned)
        cleaned = _re.sub(r"\n?```\s*$", "", cleaned)
    try:
        from agent.smol_model import _extract_top_block, _py_dict_to_json
        # 1) 直接解析（合法 JSON 或经单引号容错）
        fixed = _py_dict_to_json(cleaned)
        obj = json.loads(fixed, strict=False)
        if isinstance(obj, dict):
            return obj
    except Exception:  # noqa: BLE001
        pass
    try:
        # 2) 顶层块兜底（原文含前后说明文字时提取 {..}）
        blob = _extract_top_block(cleaned)
        obj = json.loads(blob, strict=False)
        if isinstance(obj, dict):
            return obj
    except Exception:  # noqa: BLE001
        pass
    return None


def _normalize_ai_mappings(obj: dict, models: list[dict]) -> list[dict]:
    """容错：LLM 未按标准 {"mappings":[...]} 输出时，识别替代结构并归一化为标准 mappings。

    deepseek 系模型常输出：
      - {"matched_columns": {"产品收入_i": "销售收入金额_含税_元", ...}}
      - {"column_mapping": {...}} / {"columns": {...}} / {"推荐列": {...}} / {"建议": {...}}
      - 值可能是列名（str）或 {mapped_col|column|建议列|推荐列: 列名, ...}。

    返回 [{model_id, var_name, mapped_col, confidence, reason, candidates}]。
    无法识别的变量名直接跳过；mapped_col 为空仍返回（confidence 低，提示用户）。
    """
    if not isinstance(obj, dict):
        return []
    # 1. 变量名→列名 的映射（从多个候选 key 提取）
    var2col: dict[str, str] = {}
    for key in ("matched_columns", "column_mapping", "columns", "column_map",
                "推荐列", "建议列", "映射", "mapping", "recommend", "建议"):
        blob = obj.get(key)
        if isinstance(blob, dict):
            for vn, val in blob.items():
                if isinstance(val, str):
                    var2col[str(vn)] = val
                elif isinstance(val, dict):
                    col = val.get("mapped_col") or val.get("column") or \
                          val.get("建议列") or val.get("推荐列") or val.get("col")
                    if isinstance(col, str) and col:
                        var2col[str(vn)] = col
    if not var2col:
        return []

    # 2. 用基座模型变量对齐 var_name（含正则识别率/占比等词），生成标准 mappings
    out: list[dict] = []
    for m in models:
        mid = m.get("model_id") or ""
        for v in m.get("variables") or []:
            vn = str(v.get("var_name") or "")
            if v.get("direction") not in ("input",):
                continue
            mapped = var2col.get(vn) or var2col.get(f"{vn}（{v.get('var_meaning')}）")
            if not mapped and v.get("var_meaning"):
                # 含义/单位后缀容错（如 「产品收入_i（第 i 产品线收入）」）
                for k in var2col:
                    if k.startswith(vn):
                        mapped = var2col[k]
                        break
            conf = 0.5 if mapped else 0.3
            out.append({
                "model_id": mid, "var_name": vn, "mapped_col": mapped or "",
                "confidence": conf, "reason": "", "candidates": [],
            })
    return out


def _finmod_guide(project_id: str, model_id: str, goal: str,
                  file_names: list[str] | None = None) -> dict:
    """引导编排器：诉求 + 列名索引 → 建议 JSON（含降级）。"""
    store = ProjectDataStore(get_db())
    files_index = _build_files_index(store, project_id)
    mode = _detect_mode(goal, bool(files_index))

    client = _build_llm_client(model_id)
    if not client:
        # 降级：LLM 不可用 → 前端提示手动路径（模式仍确定性判定）
        return {
            "success": False,
            "mode": mode,
            "message": "AI 引导不可用（模型不可用或未配置），可手动进入模型库选择模型",
            "directions": [],
            "data_needs": [],
        }

    content = _build_guide_user_content(goal, mode, files_index)
    raw = ""
    last_err: Exception | None = None
    for attempt in range(2):  # 失败重试 1 次
        try:
            raw = _chat_complete(
                client,
                [
                    {"role": "system", "content": GUIDE_SYSTEM},
                    {"role": "user", "content": content},
                ],
                temperature=0.3,
                max_tokens=4000,
            )
            break
        except Exception as e:  # noqa: BLE001
            last_err = e
            logger.warning("finmod guide 第 %d 次调用失败: %s", attempt + 1, e)
    if not raw.strip():
        logger.warning("finmod guide 输出为空: %s", last_err)
        return {
            "success": False,
            "mode": mode,
            "message": "AI 引导不可用（模型返回为空），可手动进入模型库选择模型",
            "directions": [],
            "data_needs": [],
        }

    obj = _parse_guide_json(raw) or {}
    # 模式以确定性判定为准（LLM 的 mode 字段忽略）
    directions: list[dict] = []
    for d in obj.get("directions") or []:
        if not isinstance(d, dict):
            continue
        meta = _resolve_model_ref(str(d.get("model_id") or ""))
        if not meta:
            continue
        # v2.7 数据完备性：模式 B（有数据）时计算模型变量覆盖度，
        # 让步骤 2 就能看到「这个模型需要哪些变量、数据里缺什么」
        var_coverage: dict = {}
        if mode == "B":
            var_coverage = _model_var_coverage(store, project_id, meta["id"],
                                               file_names=file_names)
        directions.append({
            "model_id": meta["id"],
            "code": meta["code"],
            "name": meta["name"],
            "reason": str(d.get("reason") or ""),
            "teaching": str(d.get("teaching") or ""),
            "recommended_charts": [str(c) for c in (d.get("recommended_charts") or []) if c],
            "var_coverage": var_coverage,
        })
    data_needs: list[dict] = []
    for n in obj.get("data_needs") or []:
        if not isinstance(n, dict):
            continue
        data_needs.append({
            "field": str(n.get("field") or ""),
            "type": str(n.get("type") or ""),
            "example": str(n.get("example") or ""),
            "purpose": str(n.get("purpose") or ""),
            "suggested_chart": str(n.get("suggested_chart") or ""),
        })
    return {
        "success": True,
        "mode": mode,
        "goal": goal,
        "message": "AI 建议已生成",
        "directions": directions,
        "data_needs": data_needs,
        "explanation": str(obj.get("explanation") or ""),
    }


# v3.2 统一完备性口径：可派生变量识别（内置财务词库 + 数值列兜底）
# 「可派生」= 缺失变量虽无同名列，但能由已有数值列运算得到（如 占比=分项/合计、
#   同比=本年/上年-1、率/比率/周转/差异/杠杆 等结果指标），无需用户补数据。
_DERIVABLE_VAR_RE = re.compile(
    r"(率$|比率|占比|周转|差异|偏差|盈亏|保本|平衡点|边际贡献|杠杆|倍数|"
    r"环比|同比|同期|对比期|累计|系数|指数值|预测值|结果|区间|网格|情景|净利$)"
)


def _is_derivable_var(v: dict, cols: list[str], num_col_names: list[str]) -> bool:
    """判断未匹配的 input 变量是否「可派生」——由已有数值列/同名列运算可得。"""
    vn = str(v.get("var_name") or "")
    meaning = str(v.get("var_meaning") or "")
    return bool(_DERIVABLE_VAR_RE.search(vn) or _DERIVABLE_VAR_RE.search(meaning))


# v3.4 内置派生公式库：为 derivable 变量生成候选公式（确定性，无 LLM）。
# 基于变量名/含义 + 可用数值列，返回 `{formula, based_on, note}` 或 None。
# 实际执行物化走 tools/finmod_eval.py 白名单（MEAN/STD/GROUPBY/LAG/PCT_CHANGE 等）。
def _derive_formula(v: dict, num_col_names: list[str]) -> dict | None:
    """为可派生变量生成候选公式（v3.4 内置公式库）。

    常见场景：
      - 占比/率：`占比 = 分项 / 合计`、`率 = 分子 / 分母`（取语义匹配的前 2 数值列）
      - 差异/偏差：`差异 = 实际 - 预算`
      - 环比/同比：`同比 = PCT_CHANGE(列, 1)`（时序）
    关键约束：候选列必须与变量语义有词级匹配（如「占比」→含「占比/比例」列），
    否则返回 None（避免用不相关列生成错误公式，如用「销售额计算比例」算杜邦指标）。
    """
    vn = str(v.get("var_name") or "")
    meaning = str(v.get("var_meaning") or "")
    blob = f"{vn} {meaning}"
    cols = [c for c in num_col_names if _num_reliable(c)]

    def _semantic_match(keywords: list[str]) -> list[str]:
        """候选列里含语义关键词的列（按出现顺序）。"""
        return [c for c in cols if any(k in c for k in keywords)]

    # 占比/率（分子/分母）——语义词：占比/比例/份额/比率（不含「周转率」等量词）
    if re.search(r"(占比|比例|份额|比率)", blob):
        seg = _semantic_match(["占比", "比例", "份额", "比率"])
        rate = _semantic_match(["占比", "比例", "份额", "比率", "率"])
        base = seg or rate
        if base:
            if len(base) >= 2:
                return {"formula": f"{vn}={base[0]}/{base[1]}", "based_on": base[:2],
                        "note": f"由 {base[0]} ÷ {base[1]} 计算"}
            if len(base) == 1:
                return {"formula": f"{vn}={base[0]}/SUM({base[0]})", "based_on": [base[0]],
                        "note": f"由 {base[0]} 占比计算"}
    # 差异/偏差（实际-预算）——语义词：实际/预算/标准/计划
    if re.search(r"(差异|偏差)", blob):
        pairs = _semantic_match(["实际", "预算", "标准", "计划", "本期", "上期", "去年"])
        if len(pairs) >= 2:
            return {"formula": f"{vn}={pairs[0]}-{pairs[1]}", "based_on": pairs[:2],
                    "note": f"由 {pairs[0]} − {pairs[1]} 计算"}
    # 环比/同比/变化率（时序）——时间列
    if re.search(r"(环比|同比|变化率|增长率|增速)", blob):
        time_cols = _semantic_match(["回款", "收入", "金额", "销售", "提成"])
        if time_cols:
            return {"formula": f"{vn}=PCT_CHANGE({time_cols[0]},1)", "based_on": [time_cols[0]],
                    "note": f"由 {time_cols[0]} 环比变化计算"}
    # v3.4 兜底：率/周转/占比类指标——用财务量级列作候选（分子/分母），生成候选公式。
    # 注：候选列可能不完全精准（如杜邦「总资产周转率」数据里无总资产列），
    # 仅作 AI 建议，用户可在步骤 3 调整；note 标注「候选，可调整」。
    if re.search(r"(周转|率$|比率|占比|倍数|系数)", blob):
        fin = _finance_numeric_cols(cols)  # 优先财务量级列
        pool = fin or [c for c in cols if _num_reliable(c)]
        if len(pool) >= 2:
            return {"formula": f"{vn}={pool[0]}/{pool[1]}", "based_on": pool[:2],
                    "note": f"候选：{pool[0]} ÷ {pool[1]}（可调整）"}
        if pool:
            return {"formula": f"{vn}={pool[0]}/SUM({pool[0]})", "based_on": [pool[0]],
                    "note": f"候选：{pool[0]} 占比（可调整）"}
    return None


def _numeric_candidate_cols(cols_info: list[dict]) -> list[str]:
    """宽松的数值列候选：int/float/num 类型 + 财务量级词列（金额/回款/收入/成本等）。

    该文件导入常把数值列标成 text（列名含 金额/回款/收入 等），故两类都纳入，
    供 _assess_readiness 可派生判定与 varmap-suggest 派生公式生成复用。
    """
    names = [c["name"] for c in cols_info]
    out = []
    for c in cols_info:
        typ = str(c.get("type") or "").lower()
        if any(k in typ for k in ("int", "float", "num")):
            out.append(c["name"])
    fin_words = ("金额", "回款", "收入", "成本", "费用", "销售额", "货款", "利润", "提成")
    for n in names:
        if n not in out and any(k in n for k in fin_words) and _num_reliable(n):
            out.append(n)
    return out


def _num_reliable(col: str) -> bool:
    """列名是否可能是可靠数值列（排除序数列/名称/时间/明显非数值名）。"""
    if not col:
        return False
    if any(k in col for k in ("序号", "编号", "名称", "方式", "渠道", "状态",
                              "备注", "说明", "时间", "日期", "年月", "季度",
                              "Id", "ID", "id", "序", "列号")):
        return False
    return True


def _finance_numeric_cols(cols: list[str]) -> list[str]:
    """筛选适合做派生的财务量级数值列：优先金额/回款/收入/成本/费用/销售额等。

    用量级词（金额/回款/收入/成本/费用/销售额/货款/利润）优先，避免误用
    「比例/名称/时间」类列（如 提成比例、销售额计算比例、提成项目名称）。
    """
    finance_words = ("金额", "回款", "收入", "成本", "费用", "销售额", "货款", "利润", "毛利")
    fin = [c for c in cols if any(k in c for k in finance_words)]
    # 排除比例性列（销售额计算比例/提成比例等），它们不是量级列
    fin = [c for c in fin if not any(k in c for k in ("比例", "比率", "率"))]
    if fin:
        return fin
    # 兜底：排除比例/名称/时间后的其余列
    excluded = ("比例", "比率", "率", "名称", "时间", "日期", "方式", "状态", "编号")
    return [c for c in cols if _num_reliable(c) and not any(k in c for k in excluded)]


def _assess_readiness(store: ProjectDataStore, project_id: str,
                      model_id: str,
                      file_names: list[str] | None = None) -> dict:
    """统一口径的模型完备性评估（v3.2，步骤 1/2/3 共用，替代宽松 _model_var_coverage）。

    用「精确映射」口径（与 _finmod_varmap 一致），并把未匹配变量拆成两类：
      - derivable：可由已有数值列派生的缺失变量（占比/率/同比/周转/结果指标…）
      - truly_missing：既无同名列、也无法派生的变量 → 才真正需要补数据
    R1：file_names 传入（多文件）时按多文件合并列索引评估。
    返回：
      ready / matched / missing / derivable / truly_missing /
      statistic / input_vars / missing_names（= truly_missing 变量名，兼容旧前端）/
      suggestion（人类可读结论）/ has_file
    """
    try:
        files = store.list_files(project_id) or []
        if not files:
            return {"ready": False, "matched": 0, "missing": 0, "derivable": [],
                    "truly_missing": [], "statistic": 0, "input_vars": 0,
                    "missing_names": [], "has_file": False, "suggestion": "无数据文件"}
        if file_names:
            target_files = [f for f in file_names if f]
        else:
            target_files = [next((f["file_name"] for f in files if f.get("status") == "done"),
                                 files[0]["file_name"])]
        file_name = target_files[0]
        if len(target_files) > 1:
            from tools.finmod_merge import collect_all_columns
            col_idx = collect_all_columns(store, project_id, target_files)
            cols_info = col_idx["cols_info"]
            all_cols = col_idx["all_cols"]
            num_col_names = _numeric_candidate_cols(cols_info)
            period_cols = col_idx["period_cols"]
        else:
            cols_info = _sheet_columns(store, project_id, file_name)
            all_cols = [c["name"] for c in cols_info]
            num_col_names = _numeric_candidate_cols(cols_info)
            period_cols = [c["name"] for c in cols_info if _is_period_col(c)]
        result = _finmod_varmap(store, project_id, file_name, "", [model_id],
                                file_names=list(target_files))
        model = result["models"][0] if result.get("models") else None
        if not model:
            return {"ready": False, "matched": 0, "missing": 0, "derivable": [],
                    "truly_missing": [], "statistic": 0, "input_vars": 0,
                    "missing_names": [], "has_file": True, "suggestion": "模型未找到"}
        variables = model["variables"]
        input_vars = [v for v in variables if v["direction"] == "input"]
        statistic_n = sum(1 for v in variables if v["direction"] == "statistic")
        derivable: list[str] = []
        truly_missing: list[str] = []
        derivable_details: list[dict] = []
        truly_details: list[dict] = []
        matched = 0
        for v in input_vars:
            vn = str(v.get("var_name") or "")
            vt = str(v.get("var_type") or "numeric")
            detail = {"var_name": vn, "meaning": str(v.get("var_meaning") or ""),
                      "unit": str(v.get("var_unit") or ""), "var_type": vt}
            if v.get("status") == "matched":
                matched += 1
                continue
            # 精确口径未匹配 → 拆分类：可派生（正则命中 且 内置公式库能生成公式）
            # 仅正则命中但数据无对应基础列（如杜邦指标在提成表无净利润/总资产）
            # → 归为真正缺失，避免用不相关列生成错误公式。
            if _is_derivable_var(v, all_cols, num_col_names):
                if _derive_formula(v, num_col_names):
                    derivable.append(vn)
                    derivable_details.append(detail)
                    continue
            truly_missing.append(vn)
            truly_details.append(detail)
        missing = len(truly_missing)
        # suggestion 人类可读结论
        if not input_vars:
            suggestion = "模型自动计算，无需外部变量"
        elif matched == len(input_vars):
            suggestion = "可直接建模，AI 已自动映射"
        elif derivable and not truly_missing:
            suggestion = f"缺 {len(derivable)} 个（均可用已有列派生），可直接建模"
        elif derivable:
            suggestion = (f"缺 {len(truly_missing)} 个需补数据 + "
                          f"{len(derivable)} 个可派生；AI 将自动派生")
        else:
            suggestion = f"缺 {len(truly_missing)} 个数据，建议补充"
        return {
            "ready": not truly_missing,
            "matched": matched,
            "missing": missing,
            "derivable": derivable,
            "truly_missing": truly_missing,
            "derivable_details": derivable_details,   # v3.3 可派生变量详情（供简历派生公式）
            "truly_missing_details": truly_details,   # v3.3 真缺变量详情（含义/单位 → 建议补什么）
            "statistic": statistic_n,
            "input_vars": len(input_vars),
            "missing_names": truly_missing,  # 兼容旧前端（缺真正数据才提示补）
            "has_file": True,
            "suggestion": suggestion,
            "files": target_files,  # R1：参与完备性评估的文件列表
        }
    except Exception:  # noqa: BLE001
        return {"ready": False, "matched": 0, "missing": 0, "derivable": [],
                "truly_missing": [], "statistic": 0, "input_vars": 0,
                "missing_names": [], "has_file": False, "suggestion": "完备性评估失败"}


def _model_var_coverage(store: ProjectDataStore, project_id: str,
                        model_id: str,
                        file_names: list[str] | None = None) -> dict:
    """模型变量 × 数据列 → 覆盖度（v3.2 统一口径，委托 _assess_readiness）。

    v2.7 宽松口径（numeric 变量有数值列即"已齐"）会导致 D4 等模型误报"变量已齐"、
    步骤 3 却强制映射引擎不用的变量。v3.2 改为统一精确口径（_assess_readiness），
    并把缺失拆成 derivable（可派生）/truly_missing（真缺），前端可更准确提示。
    保持旧字段（matched/missing/statistic/input_vars/missing_names/has_file）兼容，
    并新增 ready/derivable/truly_missing/suggestion。
    """
    return _assess_readiness(store, project_id, model_id, file_names=file_names)


@finmod_bp.post("/guide")
def finmod_guide():
    """引导引擎：诉求 + 列名索引 → 建议 JSON（方向/数据需求/讲解，1-2 次调用）。

    body: {project_id, model_id, goal, file_names?: []}
    R1：file_names 传入时完备性校验按多文件评估。
    """
    p = payload()
    project_id = (p.get("project_id") or "").strip()
    model_id = (p.get("model_id") or "").strip()
    goal = (p.get("goal") or "").strip()
    file_names = p.get("file_names") or []
    if isinstance(file_names, str):
        file_names = [file_names]
    file_names = [f for f in file_names if f]
    if not project_id:
        return error("缺少 project_id")
    try:
        result = _finmod_guide(project_id, model_id, goal, file_names=file_names or None)
    except Exception as e:  # noqa: BLE001
        logger.exception("finmod/guide 失败")
        return error(f"引导失败: {e}")
    if not result.get("success"):
        # 降级不视为 HTTP 错误：返回 success=false + 前端提示手动路径
        return success(result, status_code=200)
    return success(result)


# ======================================================================
# 应用二 finmod — P3 变量映射（2026-08-21）
# ======================================================================
# 需求文档 §四 步骤 4：AI 预填映射（模型所需变量 + 文件列名相似度匹配）+
# 派生变量表达式（_finmod_eval 求值）+ 期间列识别。
# 全部确定性（无 LLM），预填映射相似度匹配、派生求值走 _finmod_eval。


def _sheet_columns(store: ProjectDataStore, project_id: str,
                   file_name: str, sheet_name: str = "") -> list[dict]:
    """文件某 sheet 的列清单 [{name, type, excel_col}]（sheet 缺省取首个数据主体）。"""
    file_rec = store.find_file_by_name(project_id, file_name)
    if not file_rec:
        raise ValueError(f"未找到数据文件「{file_name}」")
    sheets = store.list_sheets(file_rec["id"]) or []
    if not sheets:
        raise ValueError(f"文件「{file_name}」没有工作表")
    if sheet_name:
        sheet = next((s for s in sheets if s.get("sheet_name") == sheet_name), None)
        if sheet is None:
            raise ValueError(f"未找到工作表「{sheet_name}」")
    else:
        sheet = next(
            (s for s in sheets if not any(k in (s.get("sheet_name") or "")
                                          for k in ("说明", "目录", "封面"))),
            sheets[0],
        )
    headers = sheet.get("headers") or []
    return [h for h in headers if h.get("name")]


def _is_period_col(col: dict) -> bool:
    """期间列识别（日期类型 / 列名含日期/时间/年/月/期间关键词）。"""
    name = str(col.get("name") or "")
    typ = str(col.get("type") or "").lower()
    if "date" in typ or "datetime" in typ or "time" in typ:
        return True
    return any(k in name for k in ("日期", "时间", "期间", "月份", "年月", "年度"))


def _suggest_col_mapping(var_name: str, all_cols: list[str]) -> str:
    """模型变量名 → 列名相似度匹配（精确 > 归一化包含）。"""
    if var_name in all_cols:
        return var_name
    for c in all_cols:
        if _similar(c, var_name):
            return c
    # 变量名含单位后缀变体（如 净利润(万元) → 净利润）
    return ""


def _finmod_varmap(store: ProjectDataStore, project_id: str,
                   file_name: str, sheet_name: str,
                   model_ids: list[str],
                   file_names: list[str] | None = None) -> dict:
    """模型所需变量 × 文件列名 → 预填映射建议（确定性相似度匹配 + 方向/类型）。

    v2.0 V1：variables 增加 direction（input/statistic/output）+ var_type（numeric/category/period）。
      - direction=input：需用户映射列（字符串相似度预填）
      - direction=statistic：统计量（n/x̄/s/CV），不映射列，`suggested_mode=statistic`（V2 AI 绑定函数）
      - direction=output：模型输出参数，不映射（展示说明）

    R1 多文件（2026-08-23）：`file_names` 传入时，用 `finmod_merge.collect_all_columns`
    合并多文件列名索引（all_cols 并集 + period_cols），变量映射对**所有文件**生效。
    兼容旧调用：`file_names` 为空且 `file_name` 给定时走原单文件逻辑。

    Returns:
        {
          file(s), sheet, all_cols, period_cols,
          file_of_col: {col: files},   # R1：每列来源文件（多文件时）
          models: [{model_id, code, name, variables: [
              {var_name, var_meaning, var_unit, direction, var_type,
               mapped_col, status, suggested_mode}
          ]}]
        }
    """
    # R1：多文件列索引合并
    from tools.finmod_merge import collect_all_columns
    multi = file_names and len(file_names) > 0
    if multi:
        col_idx = collect_all_columns(store, project_id, file_names, sheet_name)
        all_cols = col_idx["all_cols"]
        period_cols = col_idx["period_cols"]
        file_of_col = {c["name"]: c["files"] for c in col_idx["cols_info"]}
    else:
        cols_info = _sheet_columns(store, project_id, file_name, sheet_name)
        all_cols = [c["name"] for c in cols_info]
        period_cols = [c["name"] for c in cols_info if _is_period_col(c)]
        file_of_col = {c["name"]: [file_name] for c in cols_info}
    models_out: list[dict] = []
    for mid in model_ids:
        detail = finmod_refs.get_model_detail(mid)
        if not detail:
            continue
        variables = detail.get("variables") or []
        vars_out: list[dict] = []
        for v in variables:
            var_name = str(v.get("var_name") or "").strip()
            if not var_name:
                continue
            direction = str(v.get("direction") or "input")
            var_type = str(v.get("var_type") or "numeric")
            mapped = ""
            status = "missing"
            suggested_mode = "direct"
            if direction == "input":
                mapped = _suggest_col_mapping(var_name, all_cols)
                status = "matched" if mapped else "missing"
                # 类型感知：numeric 变量优先数值列（列名相似 + 数值列优先）；period 只接受期间列
                if not mapped and var_type == "period":
                    mapped = period_cols[0] if period_cols else ""
                    status = "matched" if mapped else "missing"
            elif direction == "statistic":
                # 统计量变量：不映射列；由 AI/前端绑定统计函数 + 来源列（V2）
                suggested_mode = "statistic"
                status = "statistic"  # 展示为「自动统计」而非缺失
            else:  # output
                suggested_mode = "output"
                status = "output"
            vars_out.append({
                "var_name": var_name,
                "var_meaning": str(v.get("var_meaning") or ""),
                "var_unit": str(v.get("var_unit") or ""),
                "direction": direction,
                "var_type": var_type,
                "mapped_col": mapped,
                "status": status,
                "suggested_mode": suggested_mode,
            })
        models_out.append({
            "model_id": detail["id"],
            "code": detail["code"],
            "name": detail["name"],
            "variables": vars_out,
        })
    return {
        "file": file_name,
        "files": file_names if multi else [file_name],
        "file_of_col": file_of_col,  # R1：列 → 来源文件列表（多文件时）
        "sheet": sheet_name,
        "all_cols": all_cols,
        "period_cols": period_cols,
        "models": models_out,
    }


@finmod_bp.post("/varmap")
def finmod_varmap():
    """变量预填映射：模型所需变量 × 文件列名 → 建议（确定性，无 LLM）。

    body: {project_id, file_name?, file_names?: [], sheet_name?, model_ids: []}
    R1：传 file_names[] 时做多文件列索引合并（对所有文件映射）。
    """
    p = payload()
    project_id = (p.get("project_id") or "").strip()
    file_name = (p.get("file_name") or "").strip()
    file_names = p.get("file_names") or []
    if isinstance(file_names, str):
        file_names = [file_names]
    file_names = [f for f in file_names if f]
    # 兼容：单文件传 file_name → 归一化为 file_names
    if not file_names and file_name:
        file_names = [file_name]
    model_ids = p.get("model_ids") or []
    if not project_id:
        return error("缺少 project_id")
    if not file_names:
        return error("缺少 file_name/file_names")
    if not model_ids:
        return error("缺少 model_ids")
    try:
        store = ProjectDataStore(get_db())
        result = _finmod_varmap(store, project_id, file_names[0],
                                (p.get("sheet_name") or ""), list(model_ids),
                                file_names=list(file_names))
        # 统计缺失（只统计 direction=input 的变量；statistic/output 不算缺失）
        input_vars = [v for m in result["models"] for v in m["variables"]
                      if v["direction"] == "input"]
        missing = sum(1 for v in input_vars if v["status"] == "missing")
        statistic_n = sum(1 for m in result["models"] for v in m["variables"]
                          if v["direction"] == "statistic")
        result["missing_count"] = missing
        result["input_count"] = len(input_vars)
        result["statistic_count"] = statistic_n
        result["file_count"] = len(file_names)
        result["message"] = (
            f"共 {len(input_vars)} 个输入变量，{missing} 个未匹配"
            f"（可手动选列或派生）" + (f"；{statistic_n} 个统计量将自动计算" if statistic_n else "")
            + (f"；解析 {len(file_names)} 个文件" if len(file_names) > 1 else "")
        )
        return success(result)
    except Exception as e:  # noqa: BLE001
        logger.exception("finmod/varmap 失败")
        return error(f"变量映射失败: {e}")


# ======================================================================
# 应用二 finmod — V2 AI 变量匹配（2026-08-21）
# ======================================================================
# 需求：模型变量与表中列不一定完美对上 → AI 识别最契合列（LLM 1 次调用，
# 读列名+类型+样本值；输出映射 + 置信度 + 理由 + 统计量绑定）。LLM 不可用
# 降级回 `_finmod_varmap` 确定性字符串相似度（confidence 全「中」）。

VAR_MAP_SYSTEM = (
    "你是「财务建模与分析」集成应用的变量匹配 AI。\n"
    "根据模型的变量定义与数据文件列名索引，为每个【输入变量】推荐最契合的数据列。\n"
    "你只输出建议 JSON，绝不执行任何计算。\n\n"
    "硬性规则：\n"
    "1. 每个 input 变量输出一条 mapping：{model_id, var_name, mapped_col, confidence, reason, candidates}\n"
    "2. 匹配优先：精确列名 > 语义相近（如「业务员」↔「销售人员」）> 归一化包含；\n"
    "   列名无法匹配时给 candidates（top3 最可能列），mapped_col 留空\n"
    "3. 类型约束：金额/数值变量只匹配数值列；维度/分类变量只匹配文本列；\n"
    "   期间变量只匹配日期列（period_cols 里）\n"
    "4. confidence：0.0~1.0（精确列名且类型匹配 ≥0.9；语义相近 0.7-0.85；猜测 <0.6）\n"
    "5. reason 口语化 1 句，像同事闲聊（如「列名就叫回款总额，直接对上」），\n"
    "   禁连接词/营销动词/感叹号/排比\n"
    "6. statistic 变量（n/x̄/s/CV 等）：不用映射列，输出 stat_binding：\n"
    "   {var_name, stat: \"COUNT\"|\"MEAN\"|\"STD\"|\"MEDIAN\"|\"VAR\", based_on: 同模型观测值变量名}——\n"
    "   基于同一模型 input 变量（如 x_i）绑定统计函数\n"
    "7. output 变量：跳过（模型计算结果，无需映射）\n\n"
    "输出严格 JSON（不要 markdown 围栏，不要多余文字）：\n"
    '{"mappings": [{"model_id":"g1-descriptive-stats","var_name":"x_i","mapped_col":"回款总额",'
    '"confidence":0.95,"reason":"...","candidates":["回款总额","应发金额"]}],\n'
    ' "stat_bindings": [{"model_id":"g1-descriptive-stats","var_name":"x̄","stat":"MEAN","based_on":"x_i"}]}'
)


def _build_varmap_user_content(project_id: str, file_name: str, sheet_name: str,
                               model_ids: list[str],
                               file_names: list[str] | None = None) -> tuple[str, dict]:
    """组装 varmap-suggest 的 LLM 用户消息；返回 (content, base_result)。

    base_result = `_finmod_varmap` 确定性结果（LLM 降级兜底 + 统计量/输出标记）。
    R1：file_names 传入时列索引按多文件合并（含来源文件标注）。
    """
    store = ProjectDataStore(get_db())
    base = _finmod_varmap(store, project_id, file_name, sheet_name, model_ids,
                          file_names=file_names)
    lines: list[str] = []
    # 列名索引（含类型 + 前 3 样本值 + 来源文件）
    if file_names and len(file_names) > 0:
        from tools.finmod_merge import collect_all_columns
        col_idx = collect_all_columns(store, project_id, file_names, sheet_name)
        samples = {}
        for fn in file_names:
            try:
                samples.update(_col_samples(store, project_id, fn, sheet_name))
            except Exception:  # noqa: BLE001
                continue
        lines.append("数据文件列名索引（含类型/样本值/来源文件，只读不执行）：")
        for c in col_idx["cols_info"]:
            name = c["name"]
            sam = "、".join(str(x) for x in (samples.get(name) or [])[:3])
            src = "、".join(c.get("files") or [])
            lines.append(f"- {name}（类型:{c.get('type') or '未知'}，样本:{sam or '—'}，来源:{src or '—'}）")
        lines.append(f"期间列候选：{'、'.join(base['period_cols']) or '（无）'}")
    else:
        cols_info = _sheet_columns(store, project_id, file_name, sheet_name)
        samples = _col_samples(store, project_id, file_name, sheet_name)
        lines.append("数据文件列名索引（含类型与样本值，只读不执行）：")
        for c in cols_info:
            name = c.get("name") or ""
            sam = "、".join(str(x) for x in (samples.get(name) or [])[:3])
            lines.append(f"- {name}（类型:{c.get('type') or '未知'}，样本:{sam or '—'}）")
        lines.append(f"期间列候选：{'、'.join(base['period_cols']) or '（无）'}")
    lines.append("")
    # 模型变量定义（只列出 input + statistic；output 跳过）
    lines.append("模型变量（direction 标注）：")
    for m in base["models"]:
        lines.append(f"## {m['code']} {m['name']}（{m['model_id']}）")
        for v in m["variables"]:
            tag = f"[{v['direction']}] {v['var_name']}（{v['var_meaning'] or '无含义'}，{v['var_type']}）"
            if v["direction"] == "input":
                tag += f"，当前预填: {v['mapped_col'] or '（未匹配）'}"
            lines.append(f"- {tag}")
    return "\n".join(lines), base


def _col_samples(store: ProjectDataStore, project_id: str, file_name: str,
                 sheet_name: str) -> dict[str, list]:
    """每列前 3 个非空样本值（LLM 类型判断用；只读主库，读前 5 行）。"""
    try:
        from tools.finmod_eval import load_dataframe
        df = load_dataframe(store, project_id, file_name, sheet_name)
        out: dict[str, list] = {}
        for c in df.columns[:20]:
            vals = [str(v) for v in df[c].dropna().head(3).tolist()]
            out[str(c)] = vals
        return out
    except Exception:  # noqa: BLE001 —— 样本读取失败不阻塞（列名索引仍可用）
        return {}


@finmod_bp.post("/varmap-suggest")
def finmod_varmap_suggest():
    """AI 变量匹配：模型变量 × 文件列名 → LLM 推荐（置信度 + 理由 + 统计量绑定）。

    body: {project_id, file_name?, file_names?: [], sheet_name?, model_ids: [], model_id: LLM 模型}
    R1：file_names 传入时多文件列索引合并（LLM 输入含来源文件标注）。
    Returns: {varmap: 确定性基座（含 direction/type），ai_suggestions, used_llm}
    """
    p = payload()
    project_id = (p.get("project_id") or "").strip()
    file_name = (p.get("file_name") or "").strip()
    file_names = p.get("file_names") or []
    if isinstance(file_names, str):
        file_names = [file_names]
    file_names = [f for f in file_names if f]
    if not file_names and file_name:
        file_names = [file_name]
    sheet_name = (p.get("sheet_name") or "").strip()
    model_ids = p.get("model_ids") or []
    llm_model = (p.get("model_id") or "").strip()
    if not project_id or not file_names:
        return error("缺少 project_id/file_name")
    if not model_ids:
        return error("缺少 model_ids")
    try:
        content, base = _build_varmap_user_content(project_id, file_name, sheet_name,
                                                   list(model_ids), file_names=list(file_names))
        ai_suggestions: dict = {"mappings": [], "stat_bindings": []}
        used_llm = False
        client = _build_llm_client(llm_model)
        if client:
            try:
                raw = _chat_complete(
                    client,
                    [{"role": "system", "content": VAR_MAP_SYSTEM},
                     {"role": "user", "content": content}],
                    temperature=0.2,
                    max_tokens=4000,
                )
                obj = _parse_guide_json(raw) or {}
                ai_suggestions = {
                    "mappings": [m for m in (obj.get("mappings") or []) if isinstance(m, dict)],
                    "stat_bindings": [s for s in (obj.get("stat_bindings") or []) if isinstance(s, dict)],
                }
                # v3.6 容错：LLM（尤其是 deepseek 系）常输出自定义结构而非标准
                # {"mappings":[{model_id,var_name,mapped_col,...}]}。识别这类替代结构
                # （matched_columns/column_mapping/columns/建议/推荐列 等：值=列名或
                # {mapped_col/column/建议列}），归一化为标准 mappings，避免「AI 匹配不可用」。
                if not ai_suggestions["mappings"] and not ai_suggestions["stat_bindings"]:
                    ai_suggestions["mappings"] = _normalize_ai_mappings(obj, base["models"])
                    if ai_suggestions["mappings"]:
                        used_llm = True
                used_llm = bool(ai_suggestions["mappings"] or ai_suggestions["stat_bindings"])
                # v3.1：LLM 常把 var_meaning 拼进 var_name（如「本期/去年同期（对比期数值）」）
                # 而基座 var_name 是规范名（如「本期/去年同期」）——归一化回基座名，
                # 否则前端 over[v.var_name] 匹配不上，AI 高置信映射无法自动应用。
                if used_llm:
                    canonical = {
                        (m["model_id"], v["var_name"])
                        for m in base["models"] for v in m["variables"]
                    }
                    def _canon_var(mid: str, ai_vn: str) -> str:
                        # 基座里存在完全一致名→直接用；否则用基座变量名是 ai_vn 前缀/子串的
                        if (mid, ai_vn) in canonical:
                            return ai_vn
                        for (cmid, cvn) in canonical:
                            if cmid != mid:
                                continue
                            # ai_vn = 规范名 + （含义）后缀 → 取以 cvn 开头的那个
                            if cvn and ai_vn and ai_vn.startswith(cvn):
                                return cvn
                        return ai_vn
                    for m in ai_suggestions["mappings"]:
                        m["var_name"] = _canon_var(
                            str(m.get("model_id") or ""), str(m.get("var_name") or ""))
            except Exception as e:  # noqa: BLE001
                logger.warning("finmod/varmap-suggest LLM 失败，降级确定性: %s", e)
        # 与 /varmap 一致的统计字段（input/statistic 计数 + message）
        input_vars = [v for m in base["models"] for v in m["variables"]
                      if v["direction"] == "input"]
        missing = sum(1 for v in input_vars if v["status"] == "missing")
        statistic_n = sum(1 for m in base["models"] for v in m["variables"]
                          if v["direction"] == "statistic")
        base["missing_count"] = missing
        base["input_count"] = len(input_vars)
        base["statistic_count"] = statistic_n
        base["message"] = (
            f"共 {len(input_vars)} 个输入变量，{missing} 个未匹配"
            f"（AI 已推荐或可手动选列）" + (f"；{statistic_n} 个统计量将自动计算" if statistic_n else "")
        )
        # v3.4：为 derivable（可派生）变量生成候选派生公式（内置公式库 + 数值列）
        derived_formulas: list[dict] = []
        try:
            # 宽松数值列候选（int/float/num 类型 + 财务词列兜底）；多文件时用合并列索引
            _store = ProjectDataStore(get_db())
            if file_names and len(file_names) > 1:
                from tools.finmod_merge import collect_all_columns
                _cols = collect_all_columns(_store, project_id, file_names, sheet_name)["cols_info"]
            else:
                _cols = _sheet_columns(_store, project_id, file_names[0])
            num_col_names = _numeric_candidate_cols(_cols)
            for m in base["models"]:
                for v in m["variables"]:
                    if v["direction"] != "input" or v["status"] != "missing":
                        continue
                    if not _is_derivable_var(v, base.get("all_cols") or [], num_col_names):
                        continue
                    d = _derive_formula(v, num_col_names)
                    if d:
                        derived_formulas.append({
                            "model_id": m["model_id"],
                            "var_name": v["var_name"],
                            "formula": d["formula"],
                            "based_on": d["based_on"],
                            "note": d["note"],
                        })
        except Exception as _dfe:  # noqa: BLE001
            logger.warning("finmod/varmap-suggest 派生公式生成失败: %s", _dfe)
            derived_formulas = []
        return success({
            "varmap": base,
            "ai_suggestions": ai_suggestions,
            "derived_formulas": derived_formulas,
            "used_llm": used_llm,
        })
    except Exception as e:  # noqa: BLE001
        logger.exception("finmod/varmap-suggest 失败")
        return error(f"变量匹配失败: {e}")


# ======================================================================
# 应用二 finmod — V3 数据预处理（2026-08-21）
# ======================================================================
# Stata/SPSS 式「分析就绪」：清洗 / 类型修正 / 多 sheet 合并 / 透视面板化。
# 确定性 pandas（0 LLM），供步骤 3「数据准备」区实时预览与 run 前物化。

@finmod_bp.post("/prep-data")
def finmod_prep_data():
    """数据预处理：steps 步骤链 → 变换后列信息 + 预览 + 日志。

    body: {project_id, file_name?, file_names?: [], sheet_name?, steps: [{op, ...}]}
    R1：file_names 传入（多文件）时先自动合并成一个 DataFrame，再执行步骤链。
    Returns: {success, columns: [{name, type}], rows, preview: [前5行], logs, errors}
    """
    p = payload()
    project_id = (p.get("project_id") or "").strip()
    file_name = (p.get("file_name") or "").strip()
    file_names = p.get("file_names") or []
    if isinstance(file_names, str):
        file_names = [file_names]
    file_names = [f for f in file_names if f]
    if not file_names and file_name:
        file_names = [file_name]
    steps = p.get("steps") or []
    if not project_id or not file_names:
        return error("缺少 project_id/file_name")
    if not steps:
        return error("缺少 steps")
    try:
        from tools.finmod_prep import run_prep_steps
        from tools.finmod_merge import merge_files_for_model
        store = ProjectDataStore(get_db())
        # R1：多文件先自动合并再预处理（单文件走原逻辑）
        base_df = None
        if len(file_names) > 1:
            merged = merge_files_for_model(store, project_id, file_names, (p.get("sheet_name") or ""))
            base_df = merged["df"]
        result = run_prep_steps(store, project_id, file_names[0],
                                (p.get("sheet_name") or ""), list(steps), base_df=base_df)
        # 不返回内存 df（仅预览/日志；run 时再执行同一 steps）
        result.pop("df", None)
        return success(result)
    except Exception as e:  # noqa: BLE001
        logger.exception("finmod/prep-data 失败")
        return error(f"数据预处理失败: {e}")


@finmod_bp.post("/derived-eval")
def finmod_derived_eval():
    """派生变量表达式求值（_finmod_eval，确定性，无 LLM）。

    body: {project_id, file_name?, file_names?: [], sheet_name?, formulas: ["利润=收入-成本"],
           mappings?: {模型变量名: 实际列名}}
    R1：file_names 传入时多文件合并成一个 DataFrame 求值。
    Returns:
        {results: [{name, type, sample[], rows, dtype}], errors: [{line, name, kind, message}],
         all_cols, row_count}
    """
    p = payload()
    project_id = (p.get("project_id") or "").strip()
    file_name = (p.get("file_name") or "").strip()
    file_names = p.get("file_names") or []
    if isinstance(file_names, str):
        file_names = [file_names]
    file_names = [f for f in file_names if f]
    if not file_names and file_name:
        file_names = [file_name]
    formulas = p.get("formulas") or []
    mappings = p.get("mappings") or {}
    if not project_id or not file_names:
        return error("缺少 project_id/file_name")
    if not formulas:
        return success({"results": {}, "errors": [], "all_cols": [], "row_count": 0})
    try:
        from tools.finmod_eval import eval_named_formulas
        from tools.finmod_merge import merge_files_for_model
        store = ProjectDataStore(get_db())
        if len(file_names) > 1:
            merged = merge_files_for_model(store, project_id, file_names, (p.get("sheet_name") or ""))
            df = merged["df"]
        else:
            from tools.finmod_eval import load_dataframe
            df = load_dataframe(store, project_id, file_names[0], (p.get("sheet_name") or ""))
        results, errors = eval_named_formulas(
            [str(f) for f in formulas], df, aliases=mappings, limit=5,
        )
        return success({
            "results": results,
            "errors": errors,
            "all_cols": [str(c) for c in df.columns],
            "row_count": int(df.shape[0]),
        })
    except Exception as e:  # noqa: BLE001
        logger.exception("finmod/derived-eval 失败")
        return error(f"派生变量求值失败: {e}")


# ======================================================================
# 应用二 finmod — P4 图表配置（2026-08-21）
# ======================================================================
# 需求文档 §四 步骤 5：AI 推荐图表（模型→模板确定性映射）+ 档位白名单。
# 前端在此建议基础上做宏观描述（类别/复杂度/配色）+ 微观勾选 + 预览，
# 最终收敛为 chart_manifest[]（模板名 + 变体 + 数据口径 + color_scheme）。

# 模型 → 推荐图表模板（确定性，来自 SKILL.md 分支 5a-5d + 各模型注意事项）
_MODEL_CHART_PREFS: dict[str, list[str]] = {
    # A 报表预测
    "a1-three-statement": ["bar", "line"],
    "a2-income-forecast": ["line", "waterfall"],
    "a3-cashflow-forecast": ["line", "bar"],
    "a4-consolidation": ["bar", "pie"],
    # B 预算预测
    "b1-budget": ["dual-axis", "gauge"],
    "b2-rolling-forecast": ["line", "dual-axis"],
    "b3-sales-forecast": ["line", "error-bar"],
    "b4-cost-budget": ["bar", "waterfall"],
    # C 成本盈利
    "c1-cvp-breakeven": ["line", "waterfall"],
    "c2-contribution-margin": ["bar", "waterfall"],
    "c3-cost-variance": ["tornado", "waterfall"],
    "c4-product-profitability": ["bar", "treemap"],
    # D 绩效比率
    "d1-dupont": ["radar", "bar"],
    "d2-financial-ratios": ["radar"],
    "d3-budget-variance": ["waterfall", "bar"],
    "d4-yoy-mom": ["bar", "line"],
    "d5-leverage": ["bar"],
    # E 资本决策
    "e1-npv-irr": ["bar", "error-bar"],
    "e2-wacc": ["gauge"],
    "e3-sensitivity": ["tornado", "heatmap"],
    "e4-scenario": ["bar", "radar"],
    "e5-project-breakeven": ["line", "bar"],
    "e6-equipment-replacement": ["bar", "waterfall"],
    # F 营运资金
    "f1-cash-cycle": ["line", "bar"],
    "f2-aging-analysis": ["bar", "pie"],
    "f3-inventory-turnover": ["line", "bar"],
    "f4-wcr": ["line", "bar"],
    # G 统计量化
    "g1-descriptive-stats": ["boxplot", "histogram"],
    "g2-correlation": ["heatmap", "scatter"],
    "g3-regression": ["scatter", "line"],
    "g4-time-series-decompose": ["line", "bar"],
    "g5-forecasting": ["line", "error-bar"],
}

# 档位白名单：L1 任务不出现 L3 模板（需求文档 §四 步骤 5 约束）
LEVEL_ALLOWED = {"L1": ["L1"], "L2": ["L1", "L2"], "L3": ["L1", "L2", "L3"]}

# R4 图表类别（确定性映射，供 style_prefs.categories 偏好过滤；源自 SKILL.md 选型口诀）
# 趋势=看时间变化 / 对比=横向比较 / 占比=看结构 / 敏感性=参数变化影响 /
# 分布=数据分布 / 关系=变量间关系
CHART_CATEGORIES: dict[str, str] = {
    "line": "trend", "dual-axis": "trend", "error-bar": "trend", "calendar": "trend",
    "bar": "compare", "tornado": "compare", "boxplot": "distribution",
    "pie": "share", "funnel": "share", "sunburst": "share", "treemap": "share", "sankey": "share",
    "radar": "compare", "heatmap": "relation", "scatter": "relation", "graph": "relation",
    "waterfall": "compare", "gauge": "compare", "parallel": "compare",
    "histogram": "distribution",
    "scatter3d": "relation", "bar3d": "compare", "waterfall3d": "compare", "histogram-4grid": "distribution",
}
# 类别中文名（前端展示用）
CHART_CATEGORY_LABELS = {
    "trend": "趋势", "compare": "对比", "share": "占比",
    "sensitivity": "敏感性", "distribution": "分布", "relation": "关系",
}


def _finmod_chart_suggest(model_ids: list[str], guide_charts: list[str] | None = None,
                          level: str = "L2",
                          style_prefs: dict | None = None) -> dict:
    """图表推荐（确定性）：guide 推荐优先 + 模型→模板映射补齐 → 档位白名单过滤。

    R4（2026-08-23）：支持 style_prefs 偏好 + 重要性标注。
      - style_prefs: {level?: "L1"|"L2"|"L3", colors?: str, categories?: [str]}
        categories 取 CHART_CATEGORY_LABELS 键（trend/compare/share/sensitivity/
        distribution/relation）——命中偏好的图表 importance 升一级。
      - importance: primary（guide 推荐 / 模型首选）/ secondary（模型映射补齐）/
        optional（兜底 或 与偏好类别不符）。

    Returns:
        {level, level_label, categories, suggestions: [{template, name, level,
          level_label, default_variant, reason, importance, category, category_label}], note}
    """
    prefs = style_prefs or {}
    level = (str(prefs.get("level") or level or "L2")).upper()
    if level not in LEVEL_ALLOWED:
        level = "L2"
    allowed = set(LEVEL_ALLOWED[level])
    pref_cats = [str(c) for c in (prefs.get("categories") or []) if c]

    charts_meta = {c["id"]: c for c in finmod_refs.scan_charts()}
    ordered: list[tuple[str, str, str]] = []  # (template, reason, source)
    seen: set[str] = set()

    # 1) guide 推荐优先（LLM 已按诉求定制）→ primary
    for t in guide_charts or []:
        t = (t or "").strip()
        base = t.split("-")[0] if "-" in t else t  # 变体取类型过滤
        if base in charts_meta and charts_meta[base]["level"] in allowed and t not in seen:
            ordered.append((t, "AI 根据你的诉求推荐", "primary"))
            seen.add(t)

    # 2) 模型 → 模板映射补齐（首选 primary，其余 secondary）
    for mid in model_ids:
        prefs_list = _MODEL_CHART_PREFS.get(mid) or []
        for idx, t in enumerate(prefs_list):
            if t in charts_meta and charts_meta[t]["level"] in allowed and t not in seen:
                imp = "primary" if idx == 0 else "secondary"
                ordered.append((t, "与所选模型分析类型匹配", imp))
                seen.add(t)

    # 3) 兜底：档位内默认模板（至少 1 张）→ optional
    if not ordered:
        for t, meta in charts_meta.items():
            if meta["level"] in allowed:
                ordered.append((t, "默认推荐", "optional"))
                break

    suggestions = []
    for t, reason, source_imp in ordered:
        meta = charts_meta.get(t.split("-")[0])
        if not meta:
            continue
        # R4：图表类别（用于偏好过滤）
        category = CHART_CATEGORIES.get(t.split("-")[0], "compare")
        # 偏好类别命中 → importance 升一级（optional→secondary→primary）；
        # 未命中 → secondary 降为 optional（primary 模型首选保留）。
        importance = source_imp
        if pref_cats:
            if category in pref_cats:
                if importance == "optional":
                    importance = "secondary"
                elif importance == "secondary":
                    importance = "primary"
            else:
                if importance == "secondary":
                    importance = "optional"
        # 阶段 3：官方级变体偏好（v6.6）——推荐该类型最接近官方代表图的变体：
        # 如 bar → rounded（官方 bar-gradient 圆角渐变观感）、line → area（官方
        # 渐变面积）、scatter → effect（官方涟漪）；默认变体保持纯类型名。
        var_pref = {
            "bar": "", "line": "", "pie": "donut",
            "scatter": "effect", "radar": "multi", "heatmap": "discrete",
            "waterfall": "bar", "boxplot": "multi", "sankey": "", "gauge": "progress",
            "treemap": "drilldown", "graph": "force", "funnel": "compare",
            "calendar": "year", "dual-axis": "", "sunburst": "", "tornado": "",
            "parallel": "", "histogram": "", "error-bar": "range", "histogram-4grid": "",
            "waterfall3d": "", "scatter3d": "", "bar3d": "",
        }[t.split("-")[0]]
        suggested = f"{t.split('-')[0]}-{var_pref}" if var_pref else t.split("-")[0]
        suggestions.append({
            "template": t,  # 保持原始（含 guide 变体如 line-forecast）
            "name": meta["name"],
            "level": meta["level"],
            "level_label": meta["level_label"],
            "default_variant": suggested,
            "reason": reason,
            "importance": importance,  # R4：primary/secondary/optional
            "category": category,  # R4：trend/compare/share/... 
            "category_label": CHART_CATEGORY_LABELS.get(category, category),  # R4：中文
        })
    return {
        "level": level,
        "level_label": finmod_refs.CHART_LEVELS.get(level, ""),
        "categories": list(CHART_CATEGORY_LABELS.values()),  # R4：可用类别
        "suggestions": suggestions,
        "note": (f"档位白名单生效：{level} 任务仅显示 {', '.join(sorted(allowed))} 档模板；"
                 f"推荐默认采用官方级变体（大数据量 + 渐变/动画，对齐 ECharts 官方示例）"
                 + (f"；已按偏好类别过滤：{', '.join(CHART_CATEGORY_LABELS.get(c, c) for c in pref_cats)}" if pref_cats else "")),
    }


@finmod_bp.post("/charts-suggest")
def finmod_charts_suggest():
    """图表推荐：模型 + guide 推荐 + 风格偏好 → 模板清单（确定性，无 LLM）。

    body: {model_ids: [], guide_charts?: [template], level?: "L1"|"L2"|"L3",
           style_prefs?: {level?, colors?, categories?: [str]}}
    """
    p = payload()
    model_ids = p.get("model_ids") or []
    guide_charts = p.get("guide_charts") or []
    level = p.get("level") or "L2"
    style_prefs = p.get("style_prefs") or {}
    if not model_ids:
        return error("缺少 model_ids")
    try:
        return success(_finmod_chart_suggest(
            list(model_ids), list(guide_charts), level, style_prefs))
    except Exception as e:  # noqa: BLE001
        logger.exception("finmod/charts-suggest 失败")
        return error(f"图表推荐失败: {e}")


# ======================================================================
# 应用二 finmod — P5 执行引擎（2026-08-21）
# ======================================================================
# 需求文档 §四 步骤 6：确定性执行（0 LLM 调用）——
#   - 快照：TmpRun 创建独立 SQLite，复制项目数据（主库零污染）
#   - 分派：模型计算注册表（_finmod_models.py）32 模型全覆盖
#   - 并行：多模型线程池 + 单模型 try/except 不阻塞整体
#   - 输出：{models: [{model_id, 结果摘要(JSON)}], charts: [{template, option, data_table}]}
#   - 数据分析器：POST /analyze（复用 _finmod_eval 求值器）


def _run_models_parallel(specs: list[dict], df: pd.DataFrame,
                         params_map: dict[str, dict]) -> list[dict]:
    """多模型并行计算（线程池）；单模型失败不阻塞整体。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from tools._finmod_models import run_model

    def _one(spec: dict) -> dict:
        model_id = spec["model_id"]
        return run_model(model_id, df, params_map.get(model_id, {}))

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=min(8, len(specs))) as pool:
        futs = {pool.submit(_one, s): s for s in specs}
        for fut in as_completed(futs):
            try:
                results.append(fut.result())
            except Exception as e:  # noqa: BLE001
                s = futs[fut]
                results.append({"model_id": s["model_id"], "code": s.get("code", "?"),
                                "name": s.get("name", ""), "ok": False, "summary": {"错误": str(e)}})
    # 按 model_ids 顺序稳定返回 + NaN→None（JSON 序列化安全）
    order = {s["model_id"]: i for i, s in enumerate(specs)}
    results.sort(key=lambda r: order.get(r["model_id"], 999))
    for r in results:
        r["summary"] = _clean_nan(r.get("summary", {}))
    return results


def _clean_nan(obj: Any) -> Any:
    """递归 NaN/inf → None（JSON 严格解析安全）。"""
    import math
    import numpy as np
    if isinstance(obj, dict):
        return {k: _clean_nan(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean_nan(v) for v in obj]
    if isinstance(obj, (float, np.floating)):
        f = float(obj)
        return None if (math.isnan(f) or math.isinf(f)) else f
    return obj


@finmod_bp.post("/run")
def finmod_run():
    """确定性执行：配置清单 → TmpRun 快照 → 模型并行计算 → 结果 + 图表数据（0 LLM）。

    body: {project_id, file_name?, file_names?: [], model_ids,
           mappings: {model_id: {var: col}},
           params?: {model_id: {...}}, chart_manifest?: [...]}
    R1：file_names 传入（多文件）时自动跨文件合并成统一 DataFrame 再喂模型。
    Returns:
        {run_id, models: [{model_id, code, name, ok, summary}],
         charts: [{chart_id, template, variant, name, level, color_scheme, data_table}],
         merge_strategy, merge_logs}
    """
    p = payload()
    project_id = (p.get("project_id") or "").strip()
    file_name = (p.get("file_name") or "").strip()
    file_names = p.get("file_names") or []
    if isinstance(file_names, str):
        file_names = [file_names]
    file_names = [f for f in file_names if f]
    if not file_names and file_name:
        file_names = [file_name]
    model_ids = list(p.get("model_ids") or [])
    mappings = p.get("mappings") or {}
    params = p.get("params") or {}
    manifest = p.get("chart_manifest") or []
    derived_formulas = p.get("derived_formulas") or []  # V1：派生/统计量公式（含统计量广播）
    prep_steps = p.get("prep_steps") or []  # V3：数据预处理步骤（清洗/合并/透视）
    if not project_id or not file_names:
        return error("缺少 project_id/file_name")
    if not model_ids:
        return error("缺少 model_ids")

    run = TmpRun.create()
    register_run(run.run_id, run)
    try:
        _copy_project_data_to_tmp(get_db(), run.db, project_id)
        tmp_store = ProjectDataStore(run.db)

        # R1：多文件 → 自动合并成统一 DataFrame（单文件走原逻辑）
        from tools.finmod_merge import merge_files_for_model
        merge_strategy = "single"
        merge_logs: list[str] = []
        merged_res = None
        if len(file_names) > 1:
            merged_res = merge_files_for_model(tmp_store, project_id, file_names,
                                               (p.get("sheet_name") or ""))
            merge_strategy = merged_res["strategy"]
            merge_logs = merged_res["logs"]
            base_df = merged_res["df"]
        else:
            base_df = None

        # V3：数据预处理（可选）——先变换再加载（pivot/merge 后列结构变化）
        from tools.finmod_eval import load_dataframe, materialize_derived
        prep_logs: list[str] = []
        if prep_steps:
            from tools.finmod_prep import run_prep_steps
            prep_res = run_prep_steps(tmp_store, project_id, file_names[0],
                                      (p.get("sheet_name") or ""), list(prep_steps),
                                      base_df=base_df)
            prep_logs = prep_res.get("logs") or []
            raw_df = prep_res.get("df")
        else:
            if base_df is not None:
                raw_df = base_df
            else:
                raw_df = load_dataframe(tmp_store, project_id, file_names[0],
                                        (p.get("sheet_name") or ""))
        # 所有模型所需变量并集
        all_vars: set[str] = set()
        for mid in model_ids:
            spec = _get_model_registry_spec(mid)
            if spec:
                all_vars.update(spec.get("required_vars") or [])
        # 构造模型变量 → 列映射（mappings 为 {model_id: {var: col}}；未映射列保持原名）
        alias: dict[str, str] = {}
        for mid, mp in mappings.items():
            for var, col in (mp or {}).items():
                alias[str(var)] = str(col)
        df = raw_df.copy()
        for var in all_vars:
            col = alias.get(var, var)
            if col in df.columns:
                continue
            # 未映射 → 尝试同名列
            if var in df.columns:
                df[var] = raw_df[var]
        # 重命名：模型变量名列已存在则直接用；别名映射的列复制到变量名
        for var, col in alias.items():
            if var in df.columns and col in df.columns and var != col:
                df[var] = raw_df[col]
            elif col in df.columns and var not in df.columns:
                df[var] = raw_df[col]

        # V1：物化派生/统计量列（统计量广播整列；列加入 df 供模型取用）
        derived_errors: list[dict] = []
        if derived_formulas:
            formulas = [str(f) for f in derived_formulas if str(f).strip()]
            if formulas:
                df, _dres, derived_errors = materialize_derived(df, formulas, alias)

        specs = [{"model_id": mid} for mid in model_ids]
        results = _run_models_parallel(specs, df, {mid: dict(params.get(mid) or {}) for mid in model_ids})

        # v3.6：收集每个模型的真正缺失变量（引擎 required_vars 中既不在 df、
        # 也无 alias 映射、也无派生公式覆盖的列）→ 附加到 result.missing_vars，
        # 供前端传「允许缺失分析」标记 & 报告「数据补充说明」节。
        for r in results:
            mid = r.get("model_id") or ""
            spec = _get_model_registry_spec(mid)
            req = list(spec.get("required_vars") or []) if spec else []
            mv = []
            for var in req:
                if var in df.columns:
                    continue
                if var in alias:
                    continue
                # 有派生公式覆盖（如 收入占比_i=...）则不算缺失
                if any(var in str(f) for f in derived_formulas):
                    continue
                mv.append(var)
            r["missing_vars"] = mv

        # 图表数据：从 df 提取（分类=首文本列或期间列；系列=模型结果摘要）
        charts_out: list[dict] = []
        for item in manifest:
            cid = item.get("id") or ""
            template = item.get("template") or ""
            variant = item.get("variant") or template
            name = item.get("name") or template
            level = item.get("level") or "L2"
            color_scheme = item.get("color_scheme") or "auto"
            # 数据口径：categories = 文本列/期间列，series = 数值列
            num_cols = [c for c in df.columns if pd_to_numeric(df[c]).notna().sum() > 0]
            cat_cols = [c for c in df.columns if c not in num_cols]
            categories = (df[cat_cols[0]].astype(str).tolist() if cat_cols else
                          [str(i + 1) for i in range(len(df))])[:20]
            base = template.split("-")[0]
            # 按模板类型适配数据结构（不同 build 函数期望不同格式）
            if base in ("pie", "funnel", "sunburst", "treemap", "gauge"):
                # {name, value} 对象（pie/sunburst/gauge 用 categories 作 name）
                first_val = num_cols[0] if num_cols else None
                data: dict = {
                    "categories": categories,
                    "series": [{
                        "name": first_val or "值",
                        "data": [
                            {"name": categories[i] if i < len(categories) else f"项{i + 1}",
                             "value": _round2(pd_to_numeric(df[first_val]).head(20).tolist()[i]) if first_val and i < len(df) else 0}
                            for i in range(min(len(df), 20))
                        ],
                    }],
                }
            elif base == "radar":
                # indicators = 数值列名；series[0].data[0].value = 各数值列首行值
                data = {
                    "indicators": [{"name": c, "max": float(pd_to_numeric(df[c]).max()) or 100}
                                   for c in num_cols[:6]],
                    "series": [{
                        "name": "指标",
                        "data": [{
                            "value": [_round2(pd_to_numeric(df[c]).head(20).tolist()[0]) if len(df) > 0 else 0
                                      for c in num_cols[:6]],
                        }],
                    }],
                }
            elif base in ("boxplot",):
                # 各数值列分布
                data = {
                    "categories": num_cols[:6],
                    "series": [{
                        "name": "分布",
                        "data": [[_round2(v) for v in pd_to_numeric(df[c]).dropna().tolist()[:20]]
                                 for c in num_cols[:6]],
                    }],
                }
            elif base in ("waterfall3d", "bar3d", "scatter3d"):
                # v6.9：3D 模板改用 Python(mplot3d) 生成 —— 需输出 Python `_norm_3d` 兼容数据结构：
                #   waterfall3d: xCategories(时间) + yCategories(指标) + series[0].data=[[xIdx,yIdx,zVal],...]
                #   bar3d/scatter3d: series[0].data=[[x,y,z],...]
                xc = categories[:12]                      # 时间/类别（x 轴）
                yc = num_cols[:10]                        # 指标（y 轴 waterfall3d）
                if base == "waterfall3d":
                    cells = []
                    for yi, col in enumerate(yc):
                        vals = pd_to_numeric(df[col]).head(len(xc)).tolist()
                        for xi, v in enumerate(vals):
                            cells.append([xi, yi, _round2(float(v)) if v is not None and pd.notna(v) else 0])
                    data = {
                        "xCategories": xc, "yCategories": yc,
                        "xAxisName": cat_cols[0] if cat_cols else "时间",
                        "yAxisName": "财务指标", "zAxisName": "数值",
                        "series": [{"name": "指标对比", "data": cells}],
                    }
                else:
                    # bar3d/scatter3d：数值坐标三元组 [[xIdx, yIdx, zVal], ...]
                    cells = []
                    for xi, _v in enumerate(xc):
                        for yi, col in enumerate(yc):
                            v = pd_to_numeric(df[col]).head(len(xc)).iloc[xi] if len(df) > xi else None
                            if v is not None and pd.notna(v):
                                cells.append([xi, yi, _round2(float(v))])
                    data = {
                        "xCategories": xc, "yCategories": yc,
                        "xAxisName": cat_cols[0] if cat_cols else "X",
                        "yAxisName": "指标", "zAxisName": "数值",
                        "series": [{"name": "三维", "data": cells}],
                    }
            else:
                # line/bar/bar-stacked/dual-axis/histogram/tornado/waterfall 等：数字数组
                series = []
                for c in num_cols[:6]:
                    series.append({"name": c, "data": [_round2(v) for v in pd_to_numeric(df[c]).head(20).tolist()]})
                data = {"categories": categories, "series": series}
            charts_out.append({
                "chart_id": cid,
                "template": template,
                "variant": variant,
                "name": name,
                "level": level,
                "color_scheme": color_scheme,
                "data": _clean_nan(data),
                "data_table": _clean_nan(df.head(20).to_dict("records")),
            })
        # R5：数据统计摘要（供报告「数据概览」节；AI 解读依据）
        data_stats: dict = {}
        try:
            num_cols_stat = [c for c in df.columns[:12] if pd_to_numeric(df[c]).notna().sum() > 0]
            data_stats = {
                "rows": int(df.shape[0]),
                "columns": int(df.shape[1]),
                "files": file_names,
                "period_col": (p.get("sheet_name") or ""),
            }
            for c in num_cols_stat[:6]:
                s = pd_to_numeric(df[c]).dropna()
                if len(s) == 0:
                    continue
                data_stats[str(c)] = {
                    "均值": _round2(s.mean()),
                    "中位": _round2(s.median()),
                    "最小": _round2(s.min()),
                    "最大": _round2(s.max()),
                    "样本量": int(s.count()),
                }
        except Exception as _dse:  # noqa: BLE001
            logger.warning("finmod/run data_stats 计算失败: %s", _dse)
            data_stats = {"rows": int(df.shape[0]), "columns": int(df.shape[1]), "files": file_names}
        return success({
            "run_id": run.run_id,
            "runId": run.run_id,
            "models": results,
            "charts": charts_out,
            "row_count": int(df.shape[0]),
            "derived_errors": derived_errors,  # V1：派生/统计量公式错误（不阻塞执行）
            "prep_logs": prep_logs,  # V3：数据预处理步骤日志（空=未用预处理）
            "merge_strategy": merge_strategy,  # R1：多文件合并策略（single/join/concat/union）
            "merge_logs": merge_logs,  # R1：合并日志
            "files_used": file_names,  # R1：参与执行的文件
            "data_stats": data_stats,  # R5：数据统计摘要（报告数据概览）
        })
    except Exception as e:  # noqa: BLE001
        unregister_run(run.run_id)
        run.cleanup()
        logger.exception("finmod/run 失败")
        return error(f"执行失败: {e}")


@finmod_bp.post("/analyze")
def finmod_analyze():
    """数据分析器：formulas[] + 数据集定位 → _finmod_eval 求值 → 结果表（0 LLM）。

    body: {project_id, file_name?, file_names?: [], sheet_name?, formulas: []}
    R1：file_names 传入（多文件）时先合并成一个 DataFrame 再求值。
    Returns: {results, errors, columns, rows}
    """
    p = payload()
    project_id = (p.get("project_id") or "").strip()
    file_name = (p.get("file_name") or "").strip()
    file_names = p.get("file_names") or []
    if isinstance(file_names, str):
        file_names = [file_names]
    file_names = [f for f in file_names if f]
    if not file_names and file_name:
        file_names = [file_name]
    formulas = list(p.get("formulas") or [])
    if not project_id or not file_names:
        return error("缺少 project_id/file_name")
    try:
        from tools.finmod_eval import eval_named_formulas, load_dataframe
        from tools.finmod_merge import merge_files_for_model
        store = ProjectDataStore(get_db())
        if len(file_names) > 1:
            merged = merge_files_for_model(store, project_id, file_names, (p.get("sheet_name") or ""))
            df = merged["df"]
        else:
            df = load_dataframe(store, project_id, file_names[0], (p.get("sheet_name") or ""))
        results, errors = eval_named_formulas([str(f) for f in formulas], df, limit=None)
        # 组装结果表：原列 + 派生列（series 类型），前 100 行
        out_rows: list[dict] = []
        derived_series = {k: v for k, v in results.items() if v["type"] == "series"}
        for i in range(min(len(df), 100)):
            row: dict = {}
            for c in df.columns[:10]:
                val = df.iloc[i][c]
                row[str(c)] = _round2(val) if _is_number(val) or _is_np_number(val) else str(val)
            for name, meta in derived_series.items():
                sample = meta["sample"]
                row[name] = sample[i] if i < len(sample) else None
            out_rows.append(row)
        scalars = {k: _round2(v["sample"]) for k, v in results.items() if v["type"] == "scalar"}
        return success({
            "results": results,
            "errors": errors,
            "columns": [str(c) for c in df.columns] + list(derived_series.keys()),
            "rows": out_rows,
            "scalars": scalars,
        })
    except Exception as e:  # noqa: BLE001
        logger.exception("finmod/analyze 失败")
        return error(f"数据分析失败: {e}")


# 小工具（apps.py 局部，避免与 tools 冲突）
def _get_model_registry_spec(model_id: str) -> dict | None:
    from tools._finmod_models import MODEL_REGISTRY
    return MODEL_REGISTRY.get(model_id)


def pd_to_numeric(s) -> Any:
    import pandas as pd
    return pd.to_numeric(s, errors="coerce")


def _round2(v: Any) -> Any:
    import numpy as np
    if v is None:
        return None
    try:
        f = float(v)
        if np.isnan(f) or np.isinf(f):
            return None
        return round(f, 2)
    except (TypeError, ValueError):
        return v


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_np_number(v: Any) -> bool:
    import numpy as np
    return isinstance(v, (np.integer, np.floating))


# ======================================================================
# 应用二 finmod — P6 报告交付（2026-08-21）
# ======================================================================
# 需求文档 §四 步骤 7 + §六：
#   时序强制：run → 前端渲染 → save-chart（返回落盘路径）→
#            export-md（LLM 报告 + 路径）→ md 落盘
#   预览图片走 finmod/files/<run_id>/assets/（静态代理）；md 落盘用相对路径。
#   2D 一律 SVG（矢量）；3D 降级 PNG 截图。

# 报告生成 System prompt（LLM 只写报告正文，不执行）
# R5.1（2026-08-23）：券商研报结构 + 降 AI 味硬性规范
REPORT_SYSTEM = (
    "你是「财务建模与分析」集成应用的**分析报告**撰写 AI。\n"
    "输入是确定性引擎输出的模型结果摘要 JSON + 图表清单（含已落盘路径）"
    "+ 数据统计摘要 + 用户诉求 + 图表风格偏好。\n"
    "请撰写**专业、克制、数据驱动的中文分析报告**（Markdown），面向无财务基础的业务人员。\n"
    "文风对标券商研究所研究报告：先结论后论证、客观陈述、用数值说话。\n\n"
    "硬性规则：\n"
    "1. 报告结构（结论先行）：\n"
    "   # 标题（一句话点题，无修饰）→ ## 一、核心观点（2-4 条判断+关键数值）\n"
    "   → ## 二、分析基础（数据来源/规模/统计表/口径/假设缺失）\n"
    "   → ## 三、分析过程（方法简述 1-2 句 → 发现 1/2/3，每发现=判断+数值依据+图 X）\n"
    "   → ## 四、结论与建议（可执行建议 + 风险提示）\n"
    "   → （可选）## 附录：术语速查（仅确有必要）\n"
    "2. 所有公式用 $$...$$ 包裹（禁止单 $，货币金额用普通文本；中文用 \\text{}）\n"
    "3. 图表引用：直接用图表清单给出的相对路径 ![图N](<图表清单里的路径>)（路径已含\n"
    "   报告目录前缀，直接使用，勿改动）；每张图正文必须有解读（图 X 显示……）；\n"
    "   图表数量与内容匹配，不堆砌\n"
    "4. 只输出报告本身，不要多余解释、不要客套、不要 markdown 围栏\n"
    "5. ★降 AI 味（最优先，违反即不合格）：\n"
    "   - 禁止比喻/象征（宛如、犹如、护城河、引擎、灯塔）、华丽形容词（卓越、显著、璀璨、稳健前行、赋能、助力）\n"
    "   - 禁止感叹号、排比句、对仗；禁止滥用引号「」和破折号「——」\n"
    "   - 禁止空泛结论（总体向好、值得关注、表现亮眼）——所有定性必须带数值\n"
    "   - 克制表达：用「较为/相对/存在/我们判断」代替「非常/明显/显然/大幅」（无对比时）\n"
    "   - 先判断后论证：每条观点先给结论一句话，再给数值/图依据\n"
    "   - 面向单点分析：不写宏观综述、不写行业全貌，只聚焦本次分析主题\n"
    "6. **解读而非复述**：每条发现=判断 + 数值 + 业务含义，禁止只贴数字\n"
    "7. 面向无基础读者：术语首次出现给 1 句白话解释；假设缺失时明确说明\n"
    "8. ★v3.6 若输入含「数据缺失清单」，在「二、分析基础」末尾追加「数据补充说明」：" 
    "列出每个模型的缺失变量、一句话说明对结果的影响、建议补充什么数据或如何用已有列派生"
)


def _build_report_user_content(goal: str, models: list[dict],
                               charts: list[dict],
                               data_stats: dict | None = None,
                               style_prefs: dict | None = None) -> str:
    """组装 LLM 用户消息：诉求 + 模型结果摘要 + 缺失变量 + 图表清单 + 数据统计 + 风格偏好。

    R5：新增 data_stats（核心数据统计供 AI 解读）与 style_prefs（图表风格偏好，
    作为「优先建议」供 AI 参考决定图表构成）。
    """
    lines = [f"用户诉求：{goal or '（未提供）'}", ""]
    # R5：数据统计摘要（供「二、数据概览」引用）
    if data_stats:
        lines.append("## 数据统计摘要（确定性引擎，供「数据概览」节引用）")
        lines.append(json.dumps(data_stats, ensure_ascii=False)[:4000])
        lines.append("")
    # R5：图表风格偏好（用户表达；AI 据此决定图表构成，可增减）
    if style_prefs:
        prefs_zh = {
            "level": {"L1": "简单", "L2": "中等", "L3": "复杂"}.get(str(style_prefs.get("level")), style_prefs.get("level")),
            "colors": style_prefs.get("colors"),
            "categories": style_prefs.get("categories"),
        }
        lines.append("## 图表风格偏好（用户表达，作为优先建议；AI 可据内容增减图表）")
        lines.append(json.dumps(prefs_zh, ensure_ascii=False))
        lines.append("")
    lines.append("## 模型结果摘要（确定性引擎输出，JSON）")
    lines.append(json.dumps([
        {"model_id": m.get("code"), "name": m.get("name"),
         "summary": m.get("summary", {}), "ok": m.get("ok", False),
         "missing_vars": m.get("missing_vars") or []}  # v3.6：缺失变量（报告补充说明）
        for m in models
    ], ensure_ascii=False)[:12000])
    # v3.6：缺失变量汇总（供报告「数据补充说明」节）
    all_missing = {}
    for m in models:
        if m.get("missing_vars"):
            all_missing.setdefault(f"{m.get('code')} {m.get('name')}", []).extend(m["missing_vars"])
    if all_missing:
        lines.append("")
        lines.append("## 数据缺失清单（v3.6）")
        for k, vars in all_missing.items():
            lines.append(f"- {k}：{ '、'.join(vars) }")
    lines.append("")
    lines.append("## 图表清单（已落盘，相对路径直接引用；带 importance 供 AI 参考优先级）")
    for ch in charts:
        rel = ch.get("rel_path") or ch.get("path") or ""
        imp = ch.get("importance") or "secondary"
        lines.append(f"- {ch.get('name') or ch.get('template')} (importance={imp}): ![图]({rel})")
    return "\n".join(lines)


def _fallback_md_report(goal: str, models: list[dict], charts: list[dict],
                        data_stats: dict | None = None,
                        style_prefs: dict | None = None) -> str:
    """模型不可用时的确定性降级报告（R5.1：核心观点/分析基础/分析过程/结论建议）。"""
    lines = [
        f"# {goal or '财务建模分析'}（确定性引擎）", "",
        "## 一、核心观点", "",
        f"本次分析围绕「{goal or '未提供诉求'}」，由确定性财务引擎执行"
        f"（0 AI 参与计算），所选模型 {len(models)} 个，产出图表 {len(charts)} 张。", "",
    ]
    # R5.1：分析基础（数据概览）
    lines.append("## 二、分析基础（数据与口径）")
    lines.append("")
    if data_stats:
        rows = data_stats.get("rows") or data_stats.get("row_count") or 0
        cols = data_stats.get("columns") or len(data_stats.get("cols") or [])
        files = data_stats.get("files") or []
        lines.append(f"- 数据量：{rows} 行 × {cols} 列" + (f"，来源文件：{'、'.join(files)}" if files else ""))
        for k, v in list(data_stats.items()):
            if k in ("rows", "row_count", "columns", "cols", "files"):
                continue
            lines.append(f"- {k}：{json.dumps(v, ensure_ascii=False)[:200]}")
        lines.append("")
    else:
        lines.append("- 数据量以执行引擎 row_count 为准；变量口径见各模型映射。", "")
    lines.append("## 三、分析过程（模型与方法）")
    lines.append("")
    lines.append("本次分析由确定性财务引擎执行（0 AI 参与计算），所选模型如下：")
    lines.append("")
    for m in models:
        lines.append(f"- **{m.get('code')} {m.get('name')}**"
                     f"{'（执行成功）' if m.get('ok') else '（执行失败）'}")
    lines.append("")
    lines.append("| 模型 | 结果摘要 |")
    lines.append("|---|---|")
    for m in models:
        summary = json.dumps(m.get("summary", {}), ensure_ascii=False)[:500]
        lines.append(f"| {m.get('code')} {m.get('name')} | {summary} |")
    lines.append("")
    if charts:
        lines.append("## 图表")
        lines.append("")
        for ch in charts:
            rel = ch.get("rel_path") or ch.get("path") or ""
            lines.append(f"![{ch.get('name') or ch.get('template')}]({rel})")
        lines.append("")
    # v3.6：数据缺失说明（确定性文本，AI 不可用降级时也给出）
    missing_models = [m for m in models if m.get("missing_vars")]
    if missing_models:
        lines.append("## 数据补充说明")
        lines.append("")
        lines.append("> 注：以下模型因数据缺失，结果仅供参考；建议补充数据后重新执行。")
        for m in missing_models:
            mv = m.get("missing_vars") or []
            lines.append(f"- **{m.get('code')} {m.get('name')}**：缺少 {'、'.join(mv)}")
        lines.append("")
    lines.append("## 四、结论与建议")
    lines.append("")
    lines.append("> 注：当前模型不可用，本报告由确定性引擎直接生成；如需 AI 归因与建议，请检查模型配置后重新执行。")
    return "\n".join(lines)


# ----------------------------------------------------------------------
# 报告目录管理器（阶段 1：报告/图片统一落到隐藏项目目录「财务分析报告」下）
# ----------------------------------------------------------------------
# 架构：每个隐藏项目 = 一个 work_dir。分析产物统一放 work_dir/财务分析报告/
#   /财务分析报告N/ 下（报告 md 与图片平级，不单独设 assets/ 子文件夹）。
# 同一次运行（run_id）的图片与报告必须落同一个「财务分析报告N/」目录，
# 因此用 run_id → 报告目录 的会话级映射（单用户离线场景足够）。
_report_dir_map: dict[str, str] = {}


def _finmod_work_dir(project_id: str) -> str:
    """获取隐藏项目 work_dir（找不到则回退默认 finmod 工作目录）。"""
    proj = _project(project_id)
    if proj and proj.get("work_dir"):
        return str(proj["work_dir"])
    from config.settings import DATA_DIR
    default = DATA_DIR / "app-workspaces" / "finmod"
    default.mkdir(parents=True, exist_ok=True)
    return str(default)


def _next_report_number(work_dir: str) -> int:
    """扫描 work_dir/财务分析报告/ 下已有子文件夹，返回下一个编号（从 1 开始）。"""
    root = Path(work_dir) / "财务分析报告"
    root.mkdir(parents=True, exist_ok=True)
    max_n = 0
    for child in root.iterdir():
        if child.is_dir():
            m = re.match(r"^财务分析报告(\d+)$", child.name)
            if m:
                max_n = max(max_n, int(m.group(1)))
    return max_n + 1


def _finmod_report_dir(run_id: str, project_id: str) -> str:
    """返回本次 run 的「财务分析报告N」目录绝对路径（不存在则创建）。

    同一 run_id 复用已分配目录（保证图片与报告同处一个目录）。首次调用时
    扫描分配下一个编号。
    """
    if run_id in _report_dir_map:
        return _report_dir_map[run_id]
    work_dir = _finmod_work_dir(project_id)
    n = _next_report_number(work_dir)
    report_dir = Path(work_dir) / "财务分析报告" / f"财务分析报告{n}"
    report_dir.mkdir(parents=True, exist_ok=True)
    _report_dir_map[run_id] = str(report_dir)
    logger.info("finmod 报告目录: run=%s → %s (编号 %s)", run_id, report_dir, n)
    return str(report_dir)


def _finmod_report_rel_base(run_id: str, project_id: str) -> str:
    """返回「财务分析报告N」相对项目根的路径（如 财务分析报告/财务分析报告1）。"""
    work_dir = Path(_finmod_work_dir(project_id)).resolve()
    report_dir = Path(_finmod_report_dir(run_id, project_id)).resolve()
    return report_dir.relative_to(work_dir).as_posix()


@finmod_bp.post("/py-chart")
def finmod_py_chart():
    """Python 3D 图（瀑布/柱状/散点）：data → matplotlib mplot3d → base64 PNG。

    背景（2026-08-23）：echarts-gl 无法还原「每行折线围成填充平面」的 3D 瀑布图，
    且 3D 无法矢量导出。用户决策：立体瀑布/散点/柱状改用 Python(mplot3d) 生成 PNG。

    body: {template: "waterfall3d"|"bar3d"|"scatter3d", data: chart-json}
    Returns: {b64, note, success}
    """
    p = payload()
    template = (p.get("template") or "").strip()
    data = p.get("data") or {}
    if not template:
        return error("缺少 template")
    from tools.finmod_py_charts import render_py_chart
    return success(render_py_chart(template, data))


@finmod_bp.post("/save-chart")
def finmod_save_chart():
    """图表落盘：SVG/PNG 字符串 → 隐藏项目「财务分析报告N/」（阶段 1）。

    body: {run_id, project_id, filename, content, format, mime?}
    Returns: {path, rel_path(相对项目根), filename}
    """
    p = payload()
    run_id = (p.get("run_id") or "").strip()
    project_id = (p.get("project_id") or "").strip()
    filename = (p.get("filename") or "").strip()
    content = p.get("content") or ""
    fmt = (p.get("format") or "svg").lower()
    if not run_id or not filename or not content:
        return error("缺少 run_id/filename/content")
    if not filename.endswith(f".{fmt}"):
        filename = f"{filename}.{fmt}"
    # 文件名安全（防路径穿越）
    safe_name = os.path.basename(filename)
    # 图片与报告同处「财务分析报告N」目录（与 md 平级）
    report_dir = _finmod_report_dir(run_id, project_id)
    full_path = os.path.join(report_dir, safe_name)
    try:
        mode = "wb" if fmt == "png" else "w"
        if fmt == "png":
            import base64
            raw = base64.b64decode(content)
            with open(full_path, "wb") as f:
                f.write(raw)
        else:
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
        rel_base = _finmod_report_rel_base(run_id, project_id)
        return success({
            "path": full_path,
            "rel_path": f"{rel_base}/{safe_name}",
            "filename": safe_name,
        })
    except Exception as e:  # noqa: BLE001
        logger.exception("finmod/save-chart 失败")
        return error(f"图表落盘失败: {e}")


@finmod_bp.get("/files/<run_id>/assets/<path:filepath>")
def finmod_files_assets(run_id: str, filepath: str):
    """工作区静态代理：只读托管 run 报告目录里的图片（兼容旧 tmp_runs/assets）。

    新架构：图片已写到隐藏项目「财务分析报告N」，前端主要走 /api/files/raw。
    此端点保留，用于旧 format 的 assets/ 相对路径兼容。
    """
    import mimetypes
    from flask import send_file
    if not run_id or not filepath:
        return error("缺少 run_id/filepath")
    safe = os.path.basename(filepath)
    # 优先新报告目录（run_id → 报告目录映射）；其次旧 tmp_runs/assets
    report_dir = _report_dir_map.get(run_id)
    if report_dir and os.path.isfile(os.path.join(report_dir, safe)):
        full = os.path.join(report_dir, safe)
    else:
        from config.settings import DATA_DIR
        full = str(DATA_DIR / "tmp_runs" / run_id / "assets" / safe)
    if not os.path.isfile(full):
        return error(f"资源不存在: {filepath}", 404)
    mime, _ = mimetypes.guess_type(full)
    return send_file(full, mimetype=mime or "application/octet-stream")


@finmod_bp.post("/export-md")
def finmod_export_md():
    """报告组装：LLM 报告正文 + 图表相对路径 → 单文件 md 落盘 run 目录。

    body: {project_id, run_id, goal, model_id, models[], charts[],
           data_stats?, style_prefs?}   # R5：数据统计 + 风格偏好
    Returns: {path, rel_path, filename, report, used_llm}
    """
    p = payload()
    project_id = (p.get("project_id") or "").strip()
    run_id = (p.get("run_id") or "").strip()
    goal = (p.get("goal") or "").strip()
    model_id = (p.get("model_id") or "").strip()
    models = list(p.get("models") or [])
    charts = list(p.get("charts") or [])
    data_stats = p.get("data_stats") or {}   # R5：数据统计摘要（run 返回）
    style_prefs = p.get("style_prefs") or {}  # R5：图表风格偏好
    if not run_id:
        return error("缺少 run_id")

    report = ""
    used_llm = False
    client = _build_llm_client(model_id)
    if client:
        try:
            report = _chat_complete(
                client,
                [
                    {"role": "system", "content": REPORT_SYSTEM},
                    {"role": "user", "content": _build_report_user_content(
                        goal, models, charts, data_stats, style_prefs)},
                ],
                temperature=0.3,
                max_tokens=6000,
            )
            if report.strip():
                used_llm = True
        except Exception as e:  # noqa: BLE001
            logger.warning("LLM 报告生成失败，降级为确定性报告: %s", e)
    if not report.strip():
        report = _fallback_md_report(goal, models, charts, data_stats, style_prefs)

    # 阶段 1：报告落盘到隐藏项目「财务分析报告N/财务分析报告N.md」
    report_dir = _finmod_report_dir(run_id, project_id)
    n = Path(report_dir).name  # 财务分析报告N
    filename = f"{n}.md"
    full_path = os.path.join(report_dir, filename)
    try:
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(report)
        rel_path = f"{_finmod_report_rel_base(run_id, project_id)}/{filename}"
        return success({
            "path": full_path,
            "rel_path": rel_path,
            "filename": filename,
            "report": report,
            "used_llm": used_llm,
        })
    except Exception as e:  # noqa: BLE001
        logger.exception("finmod/export-md 失败")
        return error(f"报告落盘失败: {e}")


@finmod_bp.post("/export-docx")
def finmod_export_docx():
    """D5：应用二报告 Markdown → Word (docx)。

    报告 md 落盘在 DATA_DIR/tmp_runs/<run_id>/（项目 work_dir 之外），
    故不走 /api/files/export-docx（依赖 work_dir 校验）。
    body: {run_id, content?}——content 优先（当前编辑器未保存内容）；
          否则读 run 目录落盘的 md。
    转换：pandoc -f markdown+tex_math_dollars -t docx。
    """
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    from config.settings import DATA_DIR

    p = payload()
    run_id = (p.get("run_id") or "").strip()
    content = p.get("content")
    if not run_id:
        return error("缺少 run_id")

    if content is None:
        run_dir = str(DATA_DIR / "tmp_runs" / run_id)
        filename = f"财务建模分析报告_{run_id[:8]}.md"
        full_path = os.path.join(run_dir, filename)
        if not os.path.exists(full_path):
            return error("报告文件不存在", 404)
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError as exc:
            return error(f"读取报告失败：{exc}", 500)

    # Pandoc 探测：PATH 优先，次离线介质（与 files.py 一致）
    _base = Path(__file__).resolve().parent.parent
    pandoc = shutil.which("pandoc")
    if not pandoc:
        for cand in (
            _base / "offline_packages" / "pandoc" / "pandoc.exe",
            _base / "offline_packages" / "pandoc" / "pandoc-3.10.2" / "pandoc.exe",
        ):
            if cand.is_file():
                pandoc = str(cand)
                break
    if not pandoc:
        return error(
            "Pandoc 未安装：请从离线介质 offline_packages/pandoc/ 安装 "
            "pandoc.exe（或加入系统 PATH）后重试",
            501,
        )

    stem = f"财务建模分析报告_{run_id[:8]}"
    # 论文/报告排版模板：Pandoc --reference-doc（离线 offline_packages/pandoc/）
    _ref_doc = _base / "offline_packages" / "pandoc" / "reference-template.docx"
    try:
        fd, out_path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        _cmd = [pandoc, "-f", "markdown+tex_math_dollars", "-t", "docx", "-o", out_path, "-"]
        if _ref_doc.is_file():
            _cmd.insert(1, f"--reference-doc={_ref_doc}")
        proc = subprocess.run(
            _cmd,
            input=content.encode("utf-8"),
            capture_output=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return error("Word 导出超时（60s）", 500)
    except OSError as exc:
        return error(f"Pandoc 执行失败：{exc}", 500)

    if proc.returncode != 0:
        err_msg = proc.stderr.decode("utf-8", errors="replace")[:300]
        return error(f"Word 导出失败：{err_msg}", 500)

    from flask import send_file
    try:
        return send_file(
            out_path,
            as_attachment=True,
            download_name=f"{stem}.docx",
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    except OSError as exc:
        return error(f"导出文件读取失败：{exc}", 500)
    finally:
        try:
            os.remove(out_path)
        except OSError:
            pass
