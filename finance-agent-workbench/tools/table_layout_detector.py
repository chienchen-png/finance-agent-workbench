"""Table layout detector — Phase 14E.

Deterministically locate the header row in a messy financial Excel sheet
without any LLM call.  Financial workbooks frequently prefix title /
date / note rows above the real variable-name row and append 合计 / 备注
trailing rows.  This module scores every early row and picks the one that
"looks like" a header: high non-empty cell count, field-name keywords,
and a type distribution that differs sharply from the data rows below.

Design (per PRD §3.12.4 discussion):
  - Pure stdlib, offline, deterministic → used by BOTH the manual import
    dialog and the AI (ask_user) path as the low-confidence trigger.
  - Returns a Layout object the importer can consume directly, or a
    low-confidence signal that routes to the user-confirmation step.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Scan window: headers almost never live beyond row 20 in practice.
MAX_SCAN_ROWS = 20
# A row is a plausible header if >= this fraction of its cells are non-empty.
HEADER_MIN_FILL = 0.5
# Below this confidence we ask the user to confirm the header row.
CONFIDENCE_OK = 0.7

# Field-name keywords seen in financial headers (both sides of the colon).
_FIELD_KEYWORDS = (
    "序号", "编号", "合同", "客户", "名称", "型号", "日期", "时间", "金额", "数量",
    "单价", "比例", "比率", "提成", "回款", "应收", "应付", "收入", "销售", "成本",
    "费用", "税额", "税率", "备注", "说明", "摘要", "科目", "部门", "项目", "规格",
    "单位", "方式", "期限", "年份", "季度", "月份", "状态", "人员", "姓名", "岗位",
    "id", "no", "name", "date", "amount", "count", "price", "type", "status",
    "remark", "note", "memo", "sum", "total",
)

# Trailing rows that are NOT data (matched by first non-empty cell).
_TAIL_PATTERNS = (
    re.compile(r"^\s*(合\s*计|总\s*计|小\s*计|备\s*注|注[:：]|说明[:：]|附\s*注|"
               r"※|\*\s*\*|制\s*表|复\s*核|审\s*核|领导|负责人)"),
)


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _non_empty(row: list) -> int:
    return sum(1 for c in row if _cell_text(c))


def _is_mostly_text(row: list) -> bool:
    """A header row is mostly short text cells, not numbers/dates."""
    texts = [_cell_text(c) for c in row if _cell_text(c)]
    if not texts:
        return False
    numeric = sum(1 for t in texts if re.fullmatch(r"[\d.,%\-—/]{2,}", t))
    return numeric / len(texts) < 0.4


def _keyword_hits(row: list) -> int:
    text = " ".join(_cell_text(c) for c in row).lower()
    return sum(1 for kw in _FIELD_KEYWORDS if kw.lower() in text)


def _type_distribution(rows: list[list]) -> dict[str, float]:
    """Fraction of cells per broad type across rows (for below-row compare)."""
    from datetime import datetime, date
    types = {"text": 0, "number": 0, "date": 0}
    total = 0
    for row in rows:
        for c in row:
            if c is None or _cell_text(c) == "":
                continue
            total += 1
            if isinstance(c, (int, float)) and not isinstance(c, bool):
                types["number"] += 1
            elif isinstance(c, (datetime, date)):
                types["date"] += 1
            else:
                types["text"] += 1
    if not total:
        return {"text": 1.0, "number": 0.0, "date": 0.0}
    return {k: v / total for k, v in types.items()}


def _type_similarity(a: dict, b: dict) -> float:
    return 1.0 - sum(abs(a[k] - b[k]) for k in ("text", "number", "date")) / 2


@dataclass
class Layout:
    """Detected layout of one sheet."""

    header_row: int = 0          # 0-based row index of the variable-name row
    data_start_row: int = 1      # first data row (0-based)
    data_end_row: int = -1       # last data row (0-based, inclusive); -1=to end
    columns: list[str] = field(default_factory=list)
    confidence: float = 0.0
    matched_keywords: int = 0
    fill_rate: float = 0.0

    @property
    def is_confident(self) -> bool:
        return self.confidence >= CONFIDENCE_OK


def detect_layout(rows: list[list]) -> Layout:
    """Pick the header row and data range from raw sheet rows.

    Strategy:
      1. Scan rows[0:MAX_SCAN_ROWS].
      2. Score each row: fill rate + keyword hits + "mostly text" bonus.
      3. Prefer the row ABOVE the first data row (type-distribution shift).
      4. Trim trailing 合计/备注 rows from the data range.
    """
    scan = rows[:MAX_SCAN_ROWS]
    if not scan:
        return Layout()

    candidates: list[tuple[float, int, dict]] = []
    for i, row in enumerate(scan):
        non_empty = _non_empty(row)
        if non_empty == 0:
            continue
        fill = non_empty / max(len(row), 1)
        if fill < HEADER_MIN_FILL:
            continue
        kws = _keyword_hits(row)
        score = fill * 2.0 + kws * 1.2
        if _is_mostly_text(row):
            score += 0.6
        # Bonus: rows that contain "序号" or "编号" as first cell are almost
        # always headers.
        first = _cell_text(row[0]) if row else ""
        if first in ("序号", "编号", "No", "NO", "no"):
            score += 1.5
        candidates.append((score, i, {"fill": fill, "kws": kws}))

    if not candidates:
        return Layout()

    # Order by score desc, then row index asc (prefer earliest strong hit).
    candidates.sort(key=lambda t: (-t[0], t[1]))
    best_score, best_row, best_meta = candidates[0]

    # Data rows below the header (up to ~10 rows) for type-shift check.
    below = rows[best_row + 1: best_row + 1 + 10]
    if below:
        below_dist = _type_distribution(below)
        above_dist = _type_distribution(rows[max(0, best_row - 3):best_row + 1])
        shift = 1.0 - _type_similarity(above_dist, below_dist)
        # If the row below the candidate looks like data (mostly numbers),
        # strongly confirm this is the header.
        if below_dist["number"] + below_dist["date"] > 0.5:
            best_score += 1.0
        # Add a small signal for the type-shift between header text and data.
        best_score += shift * 0.5

    # Recompute confidence 0..1 (heuristic calibration).
    fill = best_meta["fill"]
    kws = best_meta["kws"]
    confidence = min(1.0, 0.35 + fill * 0.35 + kws * 0.06)
    if best_row == 0:
        # Row 0 is the default assumption; only trust it if clearly header-y.
        confidence *= 0.85 if kws >= 2 else 0.6

    # Two-level header merge (Phase 14E enhancement).
    # Financial sheets sometimes split a header across two rows, e.g.
    #
    #   行1: 姓名 | ... | 收入时间 | (空) | 项目奖金包 | (空) | (空) | (空) | ...
    #   行2: (空) | ... | 年      | 月   | (空)        | 回款系数 | 回款属性 | 回款金额（元）
    #
    # The second row fills the blank cells of the header row and must NOT
    # be treated as a data row.  When detected, we lift those values up as
    # column names and advance the data start past the sub-header.
    data_start = best_row + 1
    sub_row = scan[best_row + 1] if best_row + 1 < len(scan) else None
    if sub_row is not None:
        header_non_empty = _non_empty(scan[best_row])
        blanks = [i for i, c in enumerate(scan[best_row]) if not _cell_text(c)]
        sub_vals = {
            i: _cell_text(sub_row[i])
            for i in blanks
            if i < len(sub_row) and _cell_text(sub_row[i])
        }
        if sub_vals:
            # A sub-header is mostly TEXT (data rows are mostly numbers)…
            num = sum(1 for v in sub_vals.values()
                      if re.fullmatch(r"[\d.,%\-—/]{2,}", v))
            text_ratio = 1.0 - num / len(sub_vals)
            # …covers at least half of the header blanks…
            cover = len(sub_vals) * 2 >= len(blanks)
            # …is noticeably sparser than the header row (excludes data rows,
            # which are dense; also excludes the xlsx 说明 sheet)…
            sparse = _non_empty(sub_row) < header_non_empty * 0.6
            # …and has almost no values OUTSIDE the header blanks (a real
            # data row fills every column, not just the header gaps).
            off_blank = [
                i for i, c in enumerate(sub_row)
                if _cell_text(c) and i not in blanks
            ]
            outside = len(off_blank) <= max(1, len(sub_vals) // 2)
            if text_ratio >= 0.6 and cover and sparse and outside:
                for i, v in sub_vals.items():
                    scan[best_row][i] = v
                data_start = best_row + 2  # skip the sub-header row

    columns = [_sanitize_header(_cell_text(c)) for c in scan[best_row]]

    # Trim trailing non-data rows (合计/备注/empty-tail/single-value notes).
    # A "single-value row" (only one non-empty cell) is treated as a bottom
    # annotation (e.g. "2025年支付2024年" appended after the 合计 row).
    data_end = len(rows) - 1
    for r in range(len(rows) - 1, data_start - 1, -1):
        row = rows[r]
        n = _non_empty(row)
        if n == 0:
            data_end = r - 1
            continue
        text = _cell_text(row[0]) if row else ""
        if any(p.match(text) for p in _TAIL_PATTERNS):
            data_end = r - 1
            continue
        if n == 1:
            data_end = r - 1
            continue
        break

    return Layout(
        header_row=best_row,
        data_start_row=data_start,
        data_end_row=data_end,
        columns=columns,
        confidence=round(confidence, 2),
        matched_keywords=kws,
        fill_rate=round(fill, 2),
    )


def _sanitize_header(name: str) -> str:
    """Clean a raw header cell to a usable column name (blank → ColN)."""
    cleaned = re.sub(r"\s+", "", name)
    if not cleaned:
        return "Col"
    return cleaned


# ══════════════════════════════════════════════════════════════════════
# Col audit & self-correction (Phase 14E enhancement #2)
#
# A "Col" column means a header cell was blank and the detector could not
# find a name for it.  In many real financial workbooks this happens when
# a group header spans several sub-columns (e.g. "项目奖金包" spans three
# numeric sub-columns whose names live in a sub-header row we already
# merged, or the source simply left the header cell blank).
#
# We correct Cols in three tiers, in order:
#   1. Cross-sheet isomorphic fill  — another sheet in the SAME workbook
#      has the same column count and aligned non-Col header positions, but
#      no Col at that index → copy its column name.
#   2. Neighbor-derived fill         — the Col sits inside a group whose
#      neighbor header is known (e.g. right after "项目奖金包") and its data
#      is numeric → derive "<group>_金额"/"<group>_数量"/"<group>_N".
#   3. Left as Col                  — unrecoverable; reported in audit so
#      the caller can surface it to the user.
# ══════════════════════════════════════════════════════════════════════


def col_indices(columns: list[str]) -> list[int]:
    """Indices of columns whose sanitized name starts with Col (blank)."""
    return [i for i, c in enumerate(columns) if (c or "").startswith("Col")]


def audit_and_correct(
    sheets_rows: dict[str, list[list]],
    layouts: dict[str, Layout],
) -> dict[str, list[int]]:
    """Self-correct Col columns across all sheets of one workbook.

    Mutates each Layout's columns in place (fills blank headers).  Returns
    {sheet_name: [col_index, ...]} for the Cols that could NOT be
    corrected (still unnamed) so callers can warn the user.
    """
    # Tier 1: cross-sheet isomorphic fill.
    # A "reference" sheet has zero Cols.  A "target" sheet has the same
    # column count and its non-Col header cells align with the reference
    # at every non-blank position → the reference names the target's Cols.
    references = {
        name: lay.columns
        for name, lay in layouts.items()
        if not col_indices(lay.columns)
    }
    remaining: dict[str, list[int]] = {}
    for tname, tlay in layouts.items():
        tcols = tlay.columns
        t_col_idx = col_indices(tcols)
        if not t_col_idx:
            continue
        ncol = len(tcols)
        best_ref: list[str] | None = None
        best_align = -1
        for rname, rcols in references.items():
            if len(rcols) != ncol:
                continue
            # Count aligned non-blank positions where the target is NOT a
            # Col (both must have a name and agree) — shared structure.
            aligned = sum(
                1 for i in range(ncol)
                if i not in t_col_idx and _cell_text(rcols[i])
                and tcols[i] == rcols[i]
            )
            if aligned > best_align:
                best_align = aligned
                best_ref = rcols
        if best_ref is not None and best_align >= max(3, ncol // 2):
            for i in t_col_idx:
                if i < len(best_ref) and _cell_text(best_ref[i]):
                    # De-duplicate against names already in the target.
                    tcols[i] = _dedupe_name(best_ref[i], set(tcols))
            t_col_idx = [i for i in t_col_idx
                         if not _cell_text(tcols[i]) or tcols[i].startswith("Col")]
        if t_col_idx:
            remaining[tname] = t_col_idx

    # Tier 2: neighbor-derived fill (group header + numeric data).
    for tname, tlay in layouts.items():
        tcols = tlay.columns
        t_col_idx = col_indices(tcols)
        if not t_col_idx:
            continue
        rows = sheets_rows.get(tname)
        if not rows:
            continue
        data_start = tlay.data_start_row
        for i in t_col_idx:
            # Find nearest named neighbor to the left with a group-ish name.
            group = ""
            for j in range(i - 1, -1, -1):
                if _cell_text(tcols[j]) and not tcols[j].startswith("Col"):
                    group = tcols[j]
                    break
            if not group:
                continue
            # Check the data under this column: numeric → amount/count.
            vals = [
                rows[r][i] for r in range(data_start, len(rows))
                if r < len(rows) and i < len(rows[r])
                and rows[r][i] not in (None, "")
            ]
            if not vals:
                continue
            numeric = sum(1 for v in vals
                          if isinstance(v, (int, float)) and not isinstance(v, bool))
            if numeric / len(vals) < 0.8:
                continue  # not numeric → don't guess a numeric-style name
            suffix = "金额" if any(k in group for k in ("金额", "款", "元", "回款", "提成")) else "数量"
            cand = f"{group}_{suffix}"
            # Avoid collision with an existing "<group>_金额" in the same row.
            used = set(tcols)
            tcols[i] = _dedupe_name(cand, used)
            t_col_idx.remove(i)

        if t_col_idx:
            remaining[tname] = t_col_idx

    return remaining


def _dedupe_name(base: str, used: set[str]) -> str:
    """Return base (or base_N) not present in used."""
    if base not in used:
        return base
    i = 2
    while f"{base}_{i}" in used:
        i += 1
    return f"{base}_{i}"
