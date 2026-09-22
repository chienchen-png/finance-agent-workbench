"""reconcile_tool — reconcile_variables：库内多级匹配 + 五级分级核对工具。

智能体优化 3.0（阶段 D）：对齐原项目 reconciliation_engine 的核对逻辑。
AI 只调用本工具一次，库内完成「匹配 → 分级 → 摘要」，AI 读结果做判断
（省算力：确定性计算交给工具，AI 不逐行猜）。

五级分级（对齐原项目）：
- OK  ：匹配键命中 + 身份一致 + |金额差| ≤ tolerance → 忽略
- A1  ：目标表金额为空（0/None），依据表有值 → 自动填充
- A2  ：金额差 ≤ tolerance 且身份一致 → 自动修正
- B   ：身份不一致 或 金额差 > tolerance 或 多级匹配仍无法唯一确定 → 用户逐条确认
- C   ：依据表独有（目标表无此匹配键）→ 人工复核

多级匹配（对齐「填空式匹配原则」）：
  对依据表每行：
    ① 按 match_keys[0]（如合同编号）在目标表查找
       → 唯一命中 → 金额比对
       → 多条命中 → ② 按 match_keys[1]（如销售人员）细分
          → 唯一 → 金额比对
          → 多条 → ③ 按 match_keys[2]（如销售客户）细分
             → 唯一 → 金额比对
             → 仍多条/无法唯一确定 → B 类
       → 无命中 → 按 unmatched_action 处理：
          "list" → C 类（人工复核）
          "fallback_person_customer" → 用(人员+客户)降级查找 → 命中则继续，否则 C
"""

from __future__ import annotations

from typing import Any

from storage.db import get_db
from storage.project_data_store import ProjectDataStore


def _store(db_override: Any | None = None) -> tuple[ProjectDataStore, Any]:
    """返回 (store, db)。db_override 提供临时库连接时（应用执行场景），
    优先使用临时库；否则用全局主库（通用项目聊天场景）。"""
    db = db_override or get_db()
    return ProjectDataStore(db), db


def _num(value: Any) -> float | None:
    """Convert a DB cell to float; None/''/'-' → None (missing amount)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "")
    if s in ("", "-", "None", "null", "NaN", "nan"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _key(row: dict, key: str) -> str:
    """Normalize a match key value for comparison (strip whitespace)."""
    v = row.get(key)
    if v is None:
        return ""
    return str(v).strip()


def _same_identity(rows: list[dict], keys: list[str]) -> bool:
    """Check whether all candidate rows share the same match-key identity.

    汇总表 vs 明细表场景：同一销售人员（或合同）有多条明细行，键值全相同
    即视为同一身份，可聚合金额后对比。
    """
    if not rows or not keys:
        return True
    first = [_key(rows[0], k) for k in keys if k]
    if not first:
        return True
    for r in rows[1:]:
        vals = [_key(r, k) for k in keys if k]
        if vals != first:
            return False
    return True


def _resolve(store: ProjectDataStore, project_id: str,
             file: str, sheet: str = "") -> dict | None:
    """Resolve file + sheet → sheet record (or None)."""
    try:
        file_rec = store.find_file_by_name(project_id, file)
        if not file_rec:
            return None
        sheets = store.list_sheets(file_rec["id"])
        if not sheets:
            return None
        if not sheet:
            return sheets[0]
        for s in sheets:
            if s["sheet_name"] == sheet:
                return s
        return None
    except Exception:  # noqa: BLE001
        return None


def _fetch_rows(store: ProjectDataStore, project_id: str,
                file: str, sheet: str = "") -> tuple[list[dict] | None, dict | None]:
    """Fetch all rows of a sheet from DB.

    Returns (rows, sheet_rec); rows=None on error.
    """
    sheet_rec = _resolve(store, project_id, file, sheet)
    if not sheet_rec:
        return None, None
    db = store.db
    table_name = sheet_rec["table_name"]
    try:
        rows = db.execute(f'SELECT * FROM "{table_name}"').fetchall()
        return [dict(r) for r in rows], sheet_rec
    except Exception:  # noqa: BLE001
        return None, None


def _fetch_all_sheets_rows(store: ProjectDataStore, project_id: str,
                           file: str) -> tuple[list[dict] | None, list[dict] | None]:
    """Fetch rows of ALL sheets of a file, merged into one row list.

    分表多 sheet 场景（如 2025年1季度回款提成汇总表：按销售人员分 sheet，
    每个 sheet 列结构相同）：合并全部 sheet 的行，统一参与核对。

    Returns (merged_rows, [sheet_rec, ...]); None on error.
    """
    try:
        file_rec = store.find_file_by_name(project_id, file)
        if not file_rec:
            return None, None
        sheets = store.list_sheets(file_rec["id"])
        if not sheets:
            return None, None
        db = store.db
        merged: list[dict] = []
        recs: list[dict] = []
        for s in sheets:
            table_name = s.get("table_name")
            if not table_name:
                continue
            try:
                rows = db.execute(f'SELECT * FROM "{table_name}"').fetchall()
                merged.extend(dict(r) for r in rows)
                recs.append(s)
            except Exception:  # noqa: BLE001
                continue
        return (merged if merged else None), (recs if recs else None)
    except Exception:  # noqa: BLE001
        return None, None


def _valid_columns(sheet: dict) -> list[str]:
    """Column names from headers whitelist."""
    return [h["name"] for h in (sheet.get("headers") or [])]


def reconcile_variables(
    file1: str, file2: str,
    sheet1: str = "", sheet2: str = "",
    match_keys: list | None = None,
    amount_col: str = "",
    tolerance: float = 1.0,
    unmatched_action: str = "list",
    project_id: str = "",
    work_dir: str = "",
    merge_sheets2: bool = False,
    db_override: Any | None = None,
    audit_mode: bool = False,
    skip_keys: list[str] | None = None,
) -> dict[str, Any]:
    """库内完成多级匹配 + 五级分级，返回摘要 JSON（AI 只读此结果做判断）。

    Args:
        file1: 依据表（源，以此表为基准逐行匹配）
        file2: 目标表（对照）
        sheet1/sheet2: 工作表名（默认第一个）
        match_keys: 匹配键层级列表（填空式①②③），如
            ["合同编号", "销售人员", "销售客户"]；
            逐级精确匹配：先合同→多条则+人员→仍多条则+客户
        amount_col: 目标金额列（依据表与目标表都用此列名；若两表列名不同，
            传入 "依据列->目标列" 或只用同一列名时按同名匹配）
        tolerance: 自动修正阈值（元），默认 1.0
        unmatched_action: 匹配不上的处理：list（列清单人工复核，默认）/
            fallback_person_customer（按人员+客户降级）
        merge_sheets2: True 时合并 file2 的全部 sheet 行（分表按人员拆分场景），
            列结构以首个 sheet 为准
        db_override: 临时库连接（应用执行场景）。提供时所有数据访问走临时库；
            None 用全局主库（通用项目聊天场景）
        audit_mode: 轮次感知模式（2026-08-20 应用重构第一步）。True 时把
            未匹配记录升级为「待审计项」——细分总表独有/分表独有/一对多模糊，
            每条带 decision 槽位供前端逐条决策，支持多轮核对闭环。
        skip_keys: 审计决策后已处理的审计项 key 列表（格式 "side:key"，
            如 "base:合同A001" / "detail:合同B002" / "ambiguous:合同A001"）。
            下一轮核对时跳过这些项（不再计入未匹配/审计），实现决策生效。

    Returns:
        {
          "summary": {"total", "matched", "a1", "a2", "b", "c", "ok",
                      "unmatched", "audit"},
          "differences": [{level, key1, key2, source_amount, target_amount,
                           reason, matched_keys}, ...],
          "unmatched": [{key, reason}, ...],
          "audit_items": [audit_mode 时: {key, side, reason, decision, candidates}, ...],
          "fallback_stats": {"attempted", "found"},
          "columns": {file1: [...], file2: [...]},  # 实际可用字段（供 AI 参考）
        }
    """
    try:
        if not project_id:
            return {"success": False, "error": "缺少 project_id"}
        store, _ = _store(db_override)

        # ── 解析列名（支持 "依据列->目标列" 映射）──
        src_col = amount_col
        tgt_col = amount_col
        if "->" in str(amount_col):
            src_col, tgt_col = [x.strip() for x in str(amount_col).split("->", 1)]

        rows1, sh1 = _fetch_rows(store, project_id, file1, sheet1)
        # 分表多 sheet 合并（按人员拆分场景）：合并全部 sheet 行
        if merge_sheets2:
            rows2, sheets2 = _fetch_all_sheets_rows(store, project_id, file2)
            sh2 = (sheets2[0] if sheets2 else None)
        else:
            rows2, sh2 = _fetch_rows(store, project_id, file2, sheet2)
        if rows1 is None or rows2 is None:
            missing = []
            if rows1 is None:
                missing.append(file1)
            if rows2 is None:
                missing.append(file2)
            return {"success": False,
                    "error": f"无法读取数据表：{', '.join(missing)}（请先导入或检查文件名）"}

        cols1 = _valid_columns(sh1)
        if merge_sheets2:
            # 合并 sheet 时：列取所有 sheet headers 的并集（首个 sheet 可能只有汇总列）
            all_cols: set[str] = set()
            for s in (sheets2 or []):
                all_cols.update(_valid_columns(s))
            cols2 = sorted(all_cols)
        else:
            cols2 = _valid_columns(sh2)

        # 匹配键校验（对两表都存在的键才可用）
        keys = [k for k in (match_keys or []) if k]
        if not keys:
            return {"success": False,
                    "error": "缺少 match_keys（匹配键层级，如 ['合同编号','销售人员']）"}

        # 金额列校验
        if src_col not in cols1:
            return {"success": False,
                    "error": f"依据表无字段「{src_col}」；可用: {', '.join(cols1[:20])}"}
        if tgt_col not in cols2:
            return {"success": False,
                    "error": f"目标表无字段「{tgt_col}」；可用: {', '.join(cols2[:20])}"}

        # ── 构建目标表索引（按 match_keys 逐级）──
        # index[k0] = [(row, k1, k2...), ...] 用于多级细分
        try:
            tol = float(tolerance)
        except (TypeError, ValueError):
            tol = 1.0

        # 预分组：key0 → 候选行列表
        from collections import defaultdict
        index0: dict[str, list[dict]] = defaultdict(list)
        for r in rows2:
            index0[_key(r, keys[0])].append(r)

        summary = {"total": 0, "matched": 0, "ok": 0, "a1": 0, "a2": 0,
                   "b": 0, "c": 0, "unmatched": 0, "audit": 0}
        differences: list[dict] = []
        unmatched: list[dict] = []
        audit_items: list[dict] = []
        fallback_stats = {"attempted": 0, "found": 0}
        skip_set = set(skip_keys or [])  # 已决策项（"side:key"），下一轮跳过
        # 已消费的分表行（id → True）：detail 侧审计时排除（分表独有 = 未被任何
        # 总表行消费的分表行）。聚合/一对多分支消费全部候选行。
        consumed2: set[int] = set()

        def _skipped(side: str, key: str) -> bool:
            return f"{side}:{key}" in skip_set

        def _record_unmatched(key: str, reason: str, side: str = "base",
                              candidates: int = 0) -> None:
            """记录一条未匹配记录。audit_mode 时细分到 audit_items（带决策槽位），
            否则进 unmatched 清单（C 类）。已决策项（skip_keys）直接跳过。"""
            if _skipped(side, key):
                return
            summary["c"] += 1
            summary["unmatched"] += 1
            if audit_mode:
                summary["audit"] += 1
                audit_items.append({
                    "key": key,
                    "side": side,          # base=总表独有 / detail=分表独有 / ambiguous=一对多模糊
                    "reason": reason,
                    "decision": None,       # 前端逐条决策后回填
                    "candidates": candidates,
                })
            else:
                unmatched.append({"key": key, "reason": reason})

        for row1 in rows1:
            summary["total"] += 1
            k0 = _key(row1, keys[0])
            cands = index0.get(k0, [])

            # 逐级细分：keys[1..] 用于收窄
            matched = None
            level_used = 1  # 已用匹配键级数
            if len(cands) == 1:
                matched = cands[0]
                consumed2.add(id(matched))
            elif len(cands) > 1:
                # 多候选 → 依次按 keys[1], keys[2]... 细分
                for ki in range(1, min(len(keys), 3)):
                    sub: list[dict] = []
                    kk = _key(row1, keys[ki])
                    for c in cands:
                        if _key(c, keys[ki]) == kk:
                            sub.append(c)
                    if len(sub) == 1:
                        matched = sub[0]
                        level_used = ki + 1
                        consumed2.add(id(matched))
                        break
                    elif len(sub) > 1:
                        cands = sub  # 继续下一级
                    else:
                        cands = []  # 该级无匹配 → 停止
                        break
                # 细分后仍多条 → 若全部候选是「同一身份」（已用键值全相同）
                # 且金额可数值化 → 聚合求和对比（汇总表 vs 明细表场景）；
                # 否则 B 类（无法唯一确定）
                if matched is None and len(cands) > 1:
                    if _same_identity(cands, keys):
                        # 空金额（None/0）视为不贡献；只要存在任意非空金额即可聚合
                        tgt_vals = [_num(c.get(tgt_col)) for c in cands]
                        if any(v is not None for v in tgt_vals):
                            matched_agg = dict(cands[0])
                            matched_agg["_agg_sum"] = True
                            matched_agg[tgt_col] = sum(
                                v for v in tgt_vals if v is not None
                            )
                            matched = matched_agg
                            level_used = min(len(keys), 3)
                            for c in cands:
                                consumed2.add(id(c))
                        else:
                            summary["a1"] += 1
                            differences.append({
                                "level": "A1",
                                "key1": k0,
                                "key2": "",
                                "source_amount": _num(row1.get(src_col)),
                                "target_amount": None,
                                "reason": "目标表金额全部为空，应填充",
                                "matched_keys": keys[:level_used],
                                "candidates": len(cands),
                            })
                            for c in cands:
                                consumed2.add(id(c))
                            continue
                    else:
                        # 多条候选且身份不一致 → 一对多模糊。
                        # audit_mode 时升级为审计项（用户逐条确认对应关系），
                        # 否则保持 B 类（用户逐条确认）。
                        if audit_mode:
                            if _skipped("ambiguous", k0):
                                for c in cands:
                                    consumed2.add(id(c))
                                continue
                            summary["audit"] += 1
                            audit_items.append({
                                "key": k0,
                                "side": "ambiguous",
                                "reason": f"总表 1 条对应分表 {len(cands)} 条（多级匹配仍无法唯一确定）",
                                "decision": None,
                                "candidates": len(cands),
                            })
                            continue
                        summary["b"] += 1
                        differences.append({
                            "level": "B",
                            "key1": k0,
                            "key2": "",
                            "source_amount": _num(row1.get(src_col)),
                            "target_amount": None,
                            "reason": "多级匹配仍无法唯一确定（多条候选）",
                            "matched_keys": keys[:level_used],
                            "candidates": len(cands),
                        })
                        continue
            elif not cands:
                # 无命中 → 降级或 C 类
                if unmatched_action == "fallback_person_customer" and len(keys) >= 2:
                    fallback_stats["attempted"] += 1
                    # 用 (keys[1], keys[2]) 或 (keys[1]) 降级查找
                    fb_rows = [r for r in rows2
                               if _key(r, keys[1]) == _key(row1, keys[1]) and
                               (len(keys) < 3 or _key(r, keys[2]) == _key(row1, keys[2]))]
                    if len(fb_rows) == 1:
                        matched = fb_rows[0]
                        consumed2.add(id(matched))
                        fallback_stats["found"] += 1
                    else:
                        _record_unmatched(
                            k0,
                            f"目标表无此匹配键；{unmatched_action} 降级未唯一命中",
                            side="base",
                            candidates=len(fb_rows),
                        )
                        continue
                else:
                    _record_unmatched(
                        k0,
                        f"目标表无匹配键「{keys[0]}」的对应记录",
                        side="base",
                    )
                    continue

            # ── 已匹配 → 金额比对分级 ──
            if matched is not None:
                summary["matched"] += 1
                src_v = _num(row1.get(src_col))
                tgt_v = _num(matched.get(tgt_col))

                if tgt_v is None or tgt_v == 0:
                    # A1：目标为空 → 自动填充
                    summary["a1"] += 1
                    differences.append({
                        "level": "A1",
                        "key1": k0,
                        "key2": _key(matched, keys[0]),
                        "source_amount": src_v,
                        "target_amount": tgt_v,
                        "reason": "目标表金额为空，应填充",
                        "matched_keys": keys[:level_used],
                    })
                elif src_v is None:
                    # 依据表无金额（异常）→ B 类
                    summary["b"] += 1
                    differences.append({
                        "level": "B",
                        "key1": k0,
                        "key2": _key(matched, keys[0]),
                        "source_amount": None,
                        "target_amount": tgt_v,
                        "reason": "依据表金额缺失",
                        "matched_keys": keys[:level_used],
                    })
                elif abs(src_v - tgt_v) <= tol:
                    # OK：一致
                    summary["ok"] += 1
                elif abs(src_v - tgt_v) <= max(tol, tol * 2) and False:
                    pass  # 保留分支（A2 阈值逻辑见下）
                elif abs(src_v - tgt_v) <= tol * 2 and tol > 0:
                    # A2：小额误差（≤2×tolerance）→ 自动修正
                    summary["a2"] += 1
                    differences.append({
                        "level": "A2",
                        "key1": k0,
                        "key2": _key(matched, keys[0]),
                        "source_amount": src_v,
                        "target_amount": tgt_v,
                        "reason": f"金额误差 {abs(src_v - tgt_v):.2f} 元 ≤ 容差×2，可自动修正",
                        "matched_keys": keys[:level_used],
                        "diff": round(src_v - tgt_v, 2),
                    })
                else:
                    # B：金额差异大 或 身份不一致
                    summary["b"] += 1
                    differences.append({
                        "level": "B",
                        "key1": k0,
                        "key2": _key(matched, keys[0]),
                        "source_amount": src_v,
                        "target_amount": tgt_v,
                        "reason": f"金额差异 {abs(src_v - tgt_v):.2f} 元超过容差，需确认",
                        "matched_keys": keys[:level_used],
                        "diff": round(src_v - tgt_v, 2),
                    })

        # ── detail 侧审计（分表独有行）：分表存在、总表无对应记录 ──
        if audit_mode:
            for r in rows2:
                if id(r) in consumed2:
                    continue
                k2 = _key(r, keys[0])
                if not k2 or _skipped("detail", k2):
                    continue
                summary["c"] += 1
                summary["unmatched"] += 1
                summary["audit"] += 1
                audit_items.append({
                    "key": k2,
                    "side": "detail",
                    "reason": "分表独有：总表无此匹配键的对应记录",
                    "decision": None,
                    "candidates": 0,
                })

        return {
            "success": True,
            "summary": summary,
            "differences": differences,
            "unmatched": unmatched,
            "audit_items": audit_items,
            "fallback_stats": fallback_stats,
            "columns": {"file1": cols1, "file2": cols2},
            "amount_col": {"source": src_col, "target": tgt_col},
            "match_keys": keys,
            "tolerance": tol,
            "unmatched_action": unmatched_action,
        }
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"核对失败: {e}"}
