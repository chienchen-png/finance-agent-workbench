"""smol_tools — 28 个现有工具转 smolagents Tool 子类。

阶段 1（引擎层替换）：把现有 tools/*.py 的实现函数包装为 smolagents Tool，
供 SmolAgentEngine（ToolCallingAgent）调用。

设计约束（smolagents 静态验证要求）：
1. 每个 Tool 子类必须【手写】——validate_tool_attributes 解析类源码，
   动态工厂生成（exec/type）没有源码会被拒。
2. forward 方法内【局部 import】实现函数——模块级引用 WORK_DIR 等变量会报
   "Name undefined"。
3. 实例属性（work_dir/project_id）在 __init__ 注入——类属性必须纯字符串/dict。
4. forward 必须用【命名参数】签名（smolagents 按 JSON schema 传参）。

命名规范（函数与变量总文档 0.1）：
- 工具名与现有 ToolRegistry 一致（read_file 等）
- 类名 = 工具名 PascalCase + "Tool"（ReadFileTool）
"""

from __future__ import annotations

from smolagents import Tool


class _WorkdirTool(Tool):
    """共享基类：注入 work_dir/project_id。

    注意：smolagents 验证会解析【每个子类】的 forward 源码，
    基类属性（name/description/inputs）被子类覆盖，这里只放实例注入逻辑。
    """

    def __init__(self, work_dir: str = "", project_id: str = "",
                 allow_outside: bool = False):
        super().__init__()
        self._work_dir = work_dir
        self._project_id = project_id
        # 阶段 G：全自动模式解除文件沙箱（allow_outside=True → 可访问项目外）
        self._allow_outside = allow_outside


# =====================================================================
# 1. 文件系统工具（filesystem_tools.py，8 个）
# =====================================================================


class ReadFileTool(_WorkdirTool):
    name = "read_file"
    description = "读取文本文件内容（支持指定行范围与编码）。"
    inputs = {
        "path": {"type": "string", "description": "文件路径（相对工作目录）"},
        "encoding": {"type": "string", "description": "文件编码，默认 utf-8", "nullable": True},
        "start_line": {"type": "integer", "description": "起始行（1-based，0=全文）", "nullable": True},
        "end_line": {"type": "integer", "description": "结束行（0=到末尾）", "nullable": True},
    }
    output_type = "string"

    def forward(self, path: str, encoding: str = "utf-8", start_line: int = 0, end_line: int = 0) -> str:
        import json as _json
        from tools.filesystem_tools import read_file as _fn
        res = _fn(path, work_dir=self._work_dir, encoding=encoding,
                  start_line=start_line, end_line=end_line,
                  allow_outside=self._allow_outside)
        return _json.dumps(res, ensure_ascii=False, default=str)[:10000]


class ListDirectoryTool(_WorkdirTool):
    name = "list_directory"
    description = "列出目录内容（支持递归，返回文件/子目录清单）。"
    inputs = {
        "path": {"type": "string", "description": "目录路径，默认 .", "nullable": True},
        "recursive": {"type": "boolean", "description": "是否递归列出，默认 false", "nullable": True},
    }
    output_type = "string"

    def forward(self, path: str = ".", recursive: bool = False) -> str:
        import json as _json
        from tools.filesystem_tools import list_directory as _fn
        res = _fn(path, work_dir=self._work_dir, recursive=recursive,
                  allow_outside=self._allow_outside)
        return _json.dumps(res, ensure_ascii=False, default=str)[:10000]


class SearchFilesTool(_WorkdirTool):
    name = "search_files"
    description = "按模式搜索文件（支持内容搜索）。"
    inputs = {
        "pattern": {"type": "string", "description": "搜索模式（glob）"},
        "path": {"type": "string", "description": "起始目录，默认 .", "nullable": True},
        "search_content": {"type": "string", "description": "搜索文件内容关键词", "nullable": True},
        "case_sensitive": {"type": "boolean", "description": "是否区分大小写", "nullable": True},
    }
    output_type = "string"

    def forward(self, pattern: str, path: str = ".", search_content: str = "",
                case_sensitive: bool = False) -> str:
        import json as _json
        from tools.filesystem_tools import search_files as _fn
        res = _fn(pattern, path, work_dir=self._work_dir,
                  search_content=search_content, case_sensitive=case_sensitive,
                  allow_outside=self._allow_outside)
        return _json.dumps(res, ensure_ascii=False, default=str)[:10000]


class WriteFileTool(_WorkdirTool):
    name = "write_file"
    description = "写入文本文件（支持备份）。"
    inputs = {
        "path": {"type": "string", "description": "文件路径（相对工作目录）"},
        "content": {"type": "string", "description": "文件内容"},
        "encoding": {"type": "string", "description": "编码，默认 utf-8", "nullable": True},
    }
    output_type = "string"

    def forward(self, path: str, content: str, encoding: str = "utf-8") -> str:
        import json as _json
        from tools.filesystem_tools import write_file as _fn
        res = _fn(path, content, work_dir=self._work_dir, encoding=encoding,
                  allow_outside=self._allow_outside)
        return _json.dumps(res, ensure_ascii=False, default=str)[:5000]


class CreateDirectoryTool(_WorkdirTool):
    name = "create_directory"
    description = "创建目录（可递归，exist_ok）。"
    inputs = {
        "path": {"type": "string", "description": "目录路径"},
        "exist_ok": {"type": "boolean", "description": "已存在时不报错", "nullable": True},
    }
    output_type = "string"

    def forward(self, path: str, exist_ok: bool = True) -> str:
        import json as _json
        from tools.filesystem_tools import create_directory as _fn
        res = _fn(path, work_dir=self._work_dir, exist_ok=exist_ok,
                  allow_outside=self._allow_outside)
        return _json.dumps(res, ensure_ascii=False, default=str)[:3000]


class DeletePathTool(_WorkdirTool):
    name = "delete_path"
    description = "删除文件或目录。"
    inputs = {
        "path": {"type": "string", "description": "要删除的路径"},
    }
    output_type = "string"

    def forward(self, path: str) -> str:
        import json as _json
        from tools.filesystem_tools import delete_path as _fn
        res = _fn(path, work_dir=self._work_dir, allow_outside=self._allow_outside)
        return _json.dumps(res, ensure_ascii=False, default=str)[:3000]


class MovePathTool(_WorkdirTool):
    name = "move_path"
    description = "移动/重命名文件或目录。"
    inputs = {
        "source": {"type": "string", "description": "源路径"},
        "destination": {"type": "string", "description": "目标路径"},
    }
    output_type = "string"

    def forward(self, source: str, destination: str) -> str:
        import json as _json
        from tools.filesystem_tools import move_path as _fn
        res = _fn(source, destination, work_dir=self._work_dir,
                  allow_outside=self._allow_outside)
        return _json.dumps(res, ensure_ascii=False, default=str)[:3000]


class CopyPathTool(_WorkdirTool):
    name = "copy_path"
    description = "复制文件或目录。"
    inputs = {
        "source": {"type": "string", "description": "源路径"},
        "destination": {"type": "string", "description": "目标路径"},
    }
    output_type = "string"

    def forward(self, source: str, destination: str) -> str:
        import json as _json
        from tools.filesystem_tools import copy_path as _fn
        res = _fn(source, destination, work_dir=self._work_dir,
                  allow_outside=self._allow_outside)
        return _json.dumps(res, ensure_ascii=False, default=str)[:3000]


# =====================================================================
# 2. 命令工具（command_tools.py，1 个）
# =====================================================================


class RunCommandTool(_WorkdirTool):
    name = "run_command"
    description = ("在工作目录执行 shell 命令（带黑名单与超时）。"
                   "文件系统操作（列目录/查文件/批量复制/项目外访问）优先用此工具一次完成；"
                   "禁止用其读取 Excel 数据（须先 import_excel_to_db 用数据库工具查询）。"
                   "人工审批模式每次执行会请求确认。")
    inputs = {
        "command": {"type": "string", "description": "要执行的命令"},
        "timeout": {"type": "integer", "description": "超时秒数，默认 60", "nullable": True},
        "reason": {"type": "string", "description": "执行原因", "nullable": True},
        "expected_effect": {"type": "string", "description": "预期效果", "nullable": True},
    }
    output_type = "string"

    def forward(self, command: str, timeout: int = 60, reason: str = "",
                expected_effect: str = "") -> str:
        import json as _json
        from tools.command_tools import run_command as _fn
        res = _fn(command, work_dir=self._work_dir, timeout=timeout,
                  reason=reason, expected_effect=expected_effect)
        return _json.dumps(res, ensure_ascii=False, default=str)[:10000]


# =====================================================================
# 3. Python 工具（python_tools.py，4 个）
# =====================================================================


class GetPythonVersionTool(_WorkdirTool):
    name = "get_python_version"
    description = "获取当前 Python 解释器版本。"
    inputs = {}
    output_type = "string"

    def forward(self) -> str:
        import json as _json
        from tools.python_tools import get_version as _fn
        res = _fn()
        return _json.dumps(res, ensure_ascii=False, default=str)[:3000]


class GetPythonExecutableTool(_WorkdirTool):
    name = "get_python_executable"
    description = "获取当前 Python 可执行文件路径。"
    inputs = {}
    output_type = "string"

    def forward(self) -> str:
        import json as _json
        from tools.python_tools import get_executable as _fn
        res = _fn()
        return _json.dumps(res, ensure_ascii=False, default=str)[:3000]


class GetInstalledPackagesTool(_WorkdirTool):
    name = "get_installed_packages"
    description = "列出当前环境已安装的 Python 包。"
    inputs = {}
    output_type = "string"

    def forward(self) -> str:
        import json as _json
        from tools.python_tools import get_installed_packages as _fn
        res = _fn()
        return _json.dumps(res, ensure_ascii=False, default=str)[:10000]


class ConfigurePythonEnvironmentTool(_WorkdirTool):
    name = "configure_python_environment"
    description = "配置 Python 环境（切换解释器/安装包）。"
    inputs = {
        "python_path": {"type": "string", "description": "Python 解释器路径", "nullable": True},
        "install_packages": {"type": "array", "items": {"type": "string"}, "description": "要安装的包列表", "nullable": True},
    }
    output_type = "string"

    def forward(self, python_path: str = "", install_packages: list | None = None) -> str:
        import json as _json
        from tools.python_tools import configure_environment as _fn
        res = _fn(work_dir=self._work_dir, python_path=python_path,
                  install_packages=install_packages)
        return _json.dumps(res, ensure_ascii=False, default=str)[:10000]


# =====================================================================
# 4. Excel 工具（excel_tools.py，5 个）
# =====================================================================


class ReadExcelTool(_WorkdirTool):
    name = "read_excel"
    description = "读取 Excel 文件内容（支持指定工作表/行范围/最大行数）。"
    inputs = {
        "path": {"type": "string", "description": "Excel 文件路径（相对工作目录）"},
        "sheet": {"type": "string", "description": "工作表名，默认第一个", "nullable": True},
        "range_spec": {"type": "string", "description": "范围描述，如 A1:D10", "nullable": True},
        "max_rows": {"type": "integer", "description": "最多返回行数，默认 2000", "nullable": True},
    }
    output_type = "string"

    def forward(self, path: str, sheet: str = "", range_spec: str = "", max_rows: int = 2000) -> str:
        import json as _json
        from tools.excel_tools import read_excel as _fn
        res = _fn(path, sheet=sheet, work_dir=self._work_dir,
                  range_spec=range_spec, max_rows=max_rows,
                  allow_outside=self._allow_outside)
        return _json.dumps(res, ensure_ascii=False, default=str)[:10000]


class GetSheetInfoTool(_WorkdirTool):
    name = "get_sheet_info"
    description = "获取 Excel 工作表信息（表名/行列数/字段）。"
    inputs = {
        "path": {"type": "string", "description": "Excel 文件路径"},
    }
    output_type = "string"

    def forward(self, path: str) -> str:
        import json as _json
        from tools.excel_tools import get_sheet_info as _fn
        res = _fn(path, work_dir=self._work_dir, allow_outside=self._allow_outside)
        return _json.dumps(res, ensure_ascii=False, default=str)[:10000]


class WriteExcelTool(_WorkdirTool):
    name = "write_excel"
    description = "写入 Excel 文件（支持备份）。"
    inputs = {
        "path": {"type": "string", "description": "Excel 文件路径"},
        "data": {"type": "string", "description": "JSON 格式数据（含 headers + rows）"},
        "sheet": {"type": "string", "description": "工作表名，默认 Sheet1", "nullable": True},
    }
    output_type = "string"

    def forward(self, path: str, data: str, sheet: str = "Sheet1") -> str:
        import json as _json
        from tools.excel_tools import write_excel as _fn
        parsed = _json.loads(data) if data else {}
        res = _fn(path, parsed, sheet=sheet, work_dir=self._work_dir,
                  allow_outside=self._allow_outside)
        return _json.dumps(res, ensure_ascii=False, default=str)[:5000]


class AnalyzeExcelTool(_WorkdirTool):
    name = "analyze_excel"
    description = "分析 Excel 文件（结构/字段/统计概览）。"
    inputs = {
        "path": {"type": "string", "description": "Excel 文件路径"},
    }
    output_type = "string"

    def forward(self, path: str) -> str:
        import json as _json
        from tools.excel_tools import analyze_excel as _fn
        res = _fn(path, work_dir=self._work_dir, allow_outside=self._allow_outside)
        return _json.dumps(res, ensure_ascii=False, default=str)[:10000]


class CompareExcelSheetsTool(_WorkdirTool):
    name = "compare_excel_sheets"
    description = "比较两个 Excel 工作表（按键列对齐，返回差异）。"
    inputs = {
        "file1": {"type": "string", "description": "第一个文件"},
        "sheet1": {"type": "string", "description": "第一个工作表"},
        "file2": {"type": "string", "description": "第二个文件"},
        "sheet2": {"type": "string", "description": "第二个工作表"},
        "key_columns": {"type": "array", "items": {"type": "string"}, "description": "键列", "nullable": True},
    }
    output_type = "string"

    def forward(self, file1: str, sheet1: str, file2: str, sheet2: str,
                key_columns: list | None = None) -> str:
        import json as _json
        from tools.excel_tools import compare_excel_sheets as _fn
        res = _fn(file1, sheet1, file2, sheet2, key_columns=key_columns,
                  work_dir=self._work_dir, allow_outside=self._allow_outside)
        return _json.dumps(res, ensure_ascii=False, default=str)[:10000]


# =====================================================================
# 5. 项目数据平面（project_data_tools.py，7 个）
# =====================================================================


class ImportExcelToDbTool(_WorkdirTool):
    name = "import_excel_to_db"
    description = "把 Excel 文件导入项目数据库。"
    inputs = {
        "path": {"type": "string", "description": "Excel 文件路径"},
        "header_row": {"type": "integer", "description": "表头行（1-based），默认自动检测", "nullable": True},
    }
    output_type = "string"

    def forward(self, path: str, header_row: int | None = None) -> str:
        import json as _json
        from tools.project_data_tools import import_excel_to_db as _fn
        res = _fn(path, header_row=header_row, project_id=self._project_id,
                  work_dir=self._work_dir)
        return _json.dumps(res, ensure_ascii=False, default=str)[:10000]


class QueryTableTool(_WorkdirTool):
    name = "query_table"
    description = "查询数据库表数据（支持列筛选/过滤/排序/聚合）。"
    inputs = {
        "file": {"type": "string", "description": "数据文件标识"},
        "sheet": {"type": "string", "description": "工作表名", "nullable": True},
        "columns": {"type": "array", "items": {"type": "string"}, "description": "选择列", "nullable": True},
        "filters": {"type": "object", "description": "过滤条件 {列: 值}", "nullable": True},
        "order_by": {"type": "string", "description": "排序列", "nullable": True},
        "limit": {"type": "integer", "description": "限制行数，默认 100", "nullable": True},
        "aggregate": {"type": "object", "description": "聚合配置", "nullable": True},
    }
    output_type = "string"

    def forward(self, file: str, sheet: str = "", columns: list | None = None,
                filters: dict | None = None, order_by: str = "", limit: int = 100,
                aggregate: dict | None = None) -> str:
        import json as _json
        from tools.project_data_tools import query_table as _fn
        res = _fn(file, sheet=sheet, columns=columns, filters=filters,
                  order_by=order_by, limit=limit, project_id=self._project_id,
                  aggregate=aggregate, work_dir=self._work_dir)
        return _json.dumps(res, ensure_ascii=False, default=str)[:10000]


class TableStatsTool(_WorkdirTool):
    name = "table_stats"
    description = "统计数据表（分组/聚合统计）。"
    inputs = {
        "file": {"type": "string", "description": "数据文件标识"},
        "sheet": {"type": "string", "description": "工作表名", "nullable": True},
        "group_by": {"type": "string", "description": "分组列", "nullable": True},
        "agg": {"type": "string", "description": "聚合函数 sum/avg/count/min/max，默认 sum", "nullable": True},
        "agg_column": {"type": "string", "description": "聚合列", "nullable": True},
    }
    output_type = "string"

    def forward(self, file: str, sheet: str = "", group_by: str = "",
                agg: str = "sum", agg_column: str = "") -> str:
        import json as _json
        from tools.project_data_tools import table_stats as _fn
        res = _fn(file, sheet=sheet, group_by=group_by, agg=agg,
                  agg_column=agg_column, project_id=self._project_id,
                  work_dir=self._work_dir)
        return _json.dumps(res, ensure_ascii=False, default=str)[:10000]


class JoinTablesTool(_WorkdirTool):
    name = "join_tables"
    description = "跨表连接（inner/left join）。"
    inputs = {
        "left_file": {"type": "string", "description": "左表文件"},
        "right_file": {"type": "string", "description": "右表文件"},
        "left_key": {"type": "string", "description": "左表键列"},
        "right_key": {"type": "string", "description": "右表键列"},
        "left_sheet": {"type": "string", "description": "左表工作表", "nullable": True},
        "right_sheet": {"type": "string", "description": "右表工作表", "nullable": True},
        "columns": {"type": "array", "items": {"type": "string"}, "description": "选择列", "nullable": True},
        "how": {"type": "string", "description": "inner/left，默认 inner", "nullable": True},
        "limit": {"type": "integer", "description": "限制行数", "nullable": True},
    }
    output_type = "string"

    def forward(self, left_file: str, right_file: str, left_key: str, right_key: str,
                left_sheet: str = "", right_sheet: str = "", columns: list | None = None,
                how: str = "inner", limit: int = 100) -> str:
        import json as _json
        from tools.project_data_tools import join_tables as _fn
        res = _fn(left_file, right_file, left_key, right_key,
                  left_sheet=left_sheet, right_sheet=right_sheet, columns=columns,
                  how=how, limit=limit, project_id=self._project_id,
                  work_dir=self._work_dir)
        return _json.dumps(res, ensure_ascii=False, default=str)[:10000]


class UpdateRowsTool(_WorkdirTool):
    name = "update_rows"
    description = "按过滤条件更新数据表行。"
    inputs = {
        "file": {"type": "string", "description": "数据文件标识"},
        "sheet": {"type": "string", "description": "工作表名", "nullable": True},
        "filters": {"type": "object", "description": "定位条件", "nullable": True},
        "updates": {"type": "object", "description": "要更新的 {列: 新值}", "nullable": True},
    }
    output_type = "string"

    def forward(self, file: str, sheet: str = "", filters: dict | None = None,
                updates: dict | None = None) -> str:
        import json as _json
        from tools.project_data_tools import update_rows as _fn
        res = _fn(file, sheet=sheet, filters=filters, updates=updates,
                  project_id=self._project_id, work_dir=self._work_dir)
        return _json.dumps(res, ensure_ascii=False, default=str)[:10000]


class InsertRowsTool(_WorkdirTool):
    name = "insert_rows"
    description = "向数据表插入新行。"
    inputs = {
        "file": {"type": "string", "description": "数据文件标识"},
        "sheet": {"type": "string", "description": "工作表名", "nullable": True},
        "rows": {"type": "array", "description": "要插入的行列表", "nullable": True},
    }
    output_type = "string"

    def forward(self, file: str, sheet: str = "", rows: list | None = None) -> str:
        import json as _json
        from tools.project_data_tools import insert_rows as _fn
        res = _fn(file, sheet=sheet, rows=rows, project_id=self._project_id,
                  work_dir=self._work_dir)
        return _json.dumps(res, ensure_ascii=False, default=str)[:10000]


class DeleteRowsTool(_WorkdirTool):
    name = "delete_rows"
    description = "按过滤条件删除数据表行。"
    inputs = {
        "file": {"type": "string", "description": "数据文件标识"},
        "sheet": {"type": "string", "description": "工作表名", "nullable": True},
        "filters": {"type": "object", "description": "定位条件", "nullable": True},
    }
    output_type = "string"

    def forward(self, file: str, sheet: str = "", filters: dict | None = None) -> str:
        import json as _json
        from tools.project_data_tools import delete_rows as _fn
        res = _fn(file, sheet=sheet, filters=filters, project_id=self._project_id,
                  work_dir=self._work_dir)
        return _json.dumps(res, ensure_ascii=False, default=str)[:10000]


class ExportProjectDataTool(_WorkdirTool):
    name = "export_project_data"
    description = "把数据库数据导出回 Excel 文件（模板重建/精确回写）。"
    inputs = {
        "file": {"type": "string", "description": "数据文件标识"},
        "mode": {"type": "string", "description": "template/precise，默认 template", "nullable": True},
        "sheet": {"type": "string", "description": "工作表名", "nullable": True},
    }
    output_type = "string"

    def forward(self, file: str, mode: str = "template", sheet: str = "") -> str:
        import json as _json
        from tools.project_data_tools import export_project_data as _fn
        res = _fn(file, mode=mode, sheet=sheet, project_id=self._project_id,
                  work_dir=self._work_dir)
        return _json.dumps(res, ensure_ascii=False, default=str)[:10000]


# 智能体优化 3.0（阶段 C）：数据索引按需化工具——
# list_data_files 返回文件清单（~50 token），get_table_index 返回单表
# 字段索引（~100 token），取代全量字段注入（N 表 × 300 token 常驻）。


class ListDataFilesTool(_WorkdirTool):
    name = "list_data_files"
    description = "列出项目数据库已导入的数据文件清单（文件名+分表+行数）。"
    inputs = {}
    output_type = "string"

    def forward(self) -> str:
        import json as _json
        from tools.project_data_tools import list_data_files as _fn
        res = _fn(project_id=self._project_id, work_dir=self._work_dir)
        return _json.dumps(res, ensure_ascii=False, default=str)[:10000]


class GetTableIndexTool(_WorkdirTool):
    name = "get_table_index"
    description = "查看单表字段索引（字段名/类型/行数），用于定位匹配键与金额列。"
    inputs = {
        "file": {"type": "string", "description": "数据文件标识"},
        "sheet": {"type": "string", "description": "工作表名，默认第一个", "nullable": True},
    }
    output_type = "string"

    def forward(self, file: str, sheet: str = "") -> str:
        import json as _json
        from tools.project_data_tools import get_table_index as _fn
        res = _fn(file, sheet=sheet, project_id=self._project_id,
                  work_dir=self._work_dir)
        return _json.dumps(res, ensure_ascii=False, default=str)[:10000]


# 智能体优化 3.0（阶段 D）：reconcile_variables 核对工具——
# 库内完成多级匹配 + 五级分级，AI 只读摘要 JSON 做判断（省算力）。


class ReconcileVariablesTool(_WorkdirTool):
    name = "reconcile_variables"
    description = "核对两表金额变量（多级匹配+五级分级）。match_keys 传匹配键层级；金额列名不同用 '源->目标'。"
    inputs = {
        "file1": {"type": "string", "description": "依据表（源）"},
        "file2": {"type": "string", "description": "目标表（对照）"},
        "sheet1": {"type": "string", "description": "依据表工作表，默认第一个", "nullable": True},
        "sheet2": {"type": "string", "description": "目标表工作表，默认第一个", "nullable": True},
        "match_keys": {"type": "array", "items": {"type": "string"}, "description": "匹配键层级列表，如 ['合同编号','销售人员','销售客户']", "nullable": True},
        "amount_col": {"type": "string", "description": "目标金额列；列名不同用 '源列->目标列'", "nullable": True},
        "tolerance": {"type": "number", "description": "自动修正阈值（元），默认 1.0", "nullable": True},
        "unmatched_action": {"type": "string", "description": "匹配不上的处理：list（默认，人工复核）/ fallback_person_customer（按人员+客户降级）", "nullable": True},
    }
    output_type = "string"

    def forward(self, file1: str, file2: str, sheet1: str = "", sheet2: str = "",
                match_keys: list | None = None, amount_col: str = "",
                tolerance: float = 1.0, unmatched_action: str = "list") -> str:
        import json as _json
        from tools.reconcile_tool import reconcile_variables as _fn
        res = _fn(file1, file2, sheet1=sheet1, sheet2=sheet2,
                  match_keys=match_keys, amount_col=amount_col,
                  tolerance=tolerance, unmatched_action=unmatched_action,
                  project_id=self._project_id, work_dir=self._work_dir)
        return _json.dumps(res, ensure_ascii=False, default=str)[:15000]


# 智能体优化 3.0（阶段 B）：ReadSkillTool——按名读取 SKILL.md 正文（L1 按需）。
# AI 自主判断任务命中触发词 → 调本工具读 skill 方法论进上下文。


class ReadSkillTool(Tool):
    name = "read_skill"
    description = "读取 Skill 方法论文档。任务命中 skill 触发词时调用，按其流程执行。"
    inputs = {
        "name": {"type": "string", "description": "技能名称，如 data-reconcile / financial-modeling"},
    }
    output_type = "string"

    def forward(self, name: str) -> str:
        from agent.skill_loader import read_skill as _fn
        return _fn(name)


class ReadSkillResourceTool(Tool):
    name = "read_skill_resource"
    description = ("读取 Skill 的 references/ 资源文件（L2 按需加载）。"
                   "如 financial-modeling 的 models/d1-dupont.md / charts/line.md。")
    inputs = {
        "skill": {"type": "string", "description": "技能名称，如 financial-modeling"},
        "path": {"type": "string", "description": "references/ 下相对路径，如 models/d1-dupont.md 或 charts/line.md", "nullable": True},
    }
    output_type = "string"

    def forward(self, skill: str, path: str = "") -> str:
        from agent.skill_loader import read_skill_resource as _fn
        return _fn(skill, path)


# =====================================================================
# 6. 财务分析工具（financial_analysis_tools.py，7 个）
# financial-modeling skill 计算层（P2）：6 个 L1 预写 + 1 个 L2 沙箱执行
# =====================================================================


class FinancialMetricsTool(_WorkdirTool):
    name = "financial_metrics"
    description = ("财务指标计算：五维比率/杜邦/资本预算（NPV/IRR/回收期）/现金周期。"
                   "输入文件 + 科目列映射（net_profit_col 等），数据从项目数据库读取。")
    inputs = {
        "file": {"type": "string", "description": "数据文件标识（项目数据库）"},
        "sheet": {"type": "string", "description": "工作表名，默认第一个", "nullable": True},
        "metrics": {"type": "array", "items": {"type": "string"}, "description": "要计算的指标组：ratios/dupont/capital/ccc，空=全量", "nullable": True},
        "net_profit_col": {"type": "string", "description": "净利润列名", "nullable": True},
        "revenue_col": {"type": "string", "description": "营业收入列名", "nullable": True},
        "total_assets_col": {"type": "string", "description": "总资产列名", "nullable": True},
        "equity_col": {"type": "string", "description": "所有者权益列名", "nullable": True},
        "current_assets_col": {"type": "string", "description": "流动资产列名", "nullable": True},
        "current_liab_col": {"type": "string", "description": "流动负债列名", "nullable": True},
        "inventory_col": {"type": "string", "description": "存货列名", "nullable": True},
        "receivables_col": {"type": "string", "description": "应收账款列名", "nullable": True},
        "cost_col": {"type": "string", "description": "营业成本列名", "nullable": True},
        "interest_col": {"type": "string", "description": "利息费用列名", "nullable": True},
        "cashflow_col": {"type": "string", "description": "现金流列名（含期初，用于 NPV/IRR）", "nullable": True},
        "discount_rate": {"type": "number", "description": "折现率，默认 0.10", "nullable": True},
    }
    output_type = "string"

    def forward(self, file: str, sheet: str = "", metrics=None,
                net_profit_col: str = "", revenue_col: str = "",
                total_assets_col: str = "", equity_col: str = "",
                current_assets_col: str = "", current_liab_col: str = "",
                inventory_col: str = "", receivables_col: str = "",
                cost_col: str = "", interest_col: str = "",
                cashflow_col: str = "", discount_rate: float = 0.10) -> str:
        import json as _json
        from tools.financial_analysis_tools import financial_metrics as _fn
        res = _fn(file, sheet=sheet, metrics=metrics,
                  net_profit_col=net_profit_col, revenue_col=revenue_col,
                  total_assets_col=total_assets_col, equity_col=equity_col,
                  current_assets_col=current_assets_col, current_liab_col=current_liab_col,
                  inventory_col=inventory_col, receivables_col=receivables_col,
                  cost_col=cost_col, interest_col=interest_col,
                  cashflow_col=cashflow_col, discount_rate=discount_rate,
                  project_id=self._project_id, work_dir=self._work_dir)
        return _json.dumps(res, ensure_ascii=False, default=str)[:10000]


class RegressionAnalysisTool(_WorkdirTool):
    name = "regression_analysis"
    description = ("线性回归：一元/多元，输出系数/R²/p 值/残差摘要。"
                   "用于成本动因、销售驱动分析。")
    inputs = {
        "file": {"type": "string", "description": "数据文件标识（项目数据库）"},
        "sheet": {"type": "string", "description": "工作表名，默认第一个", "nullable": True},
        "x_columns": {"type": "array", "items": {"type": "string"}, "description": "自变量列名列表（1=一元，≥2=多元）", "nullable": True},
        "y_column": {"type": "string", "description": "因变量列名", "nullable": True},
        "add_constant": {"type": "boolean", "description": "是否含截距，默认 true", "nullable": True},
    }
    output_type = "string"

    def forward(self, file: str, sheet: str = "", x_columns=None,
                y_column: str = "", add_constant: bool = True) -> str:
        import json as _json
        from tools.financial_analysis_tools import regression_analysis as _fn
        res = _fn(file, sheet=sheet, x_columns=x_columns, y_column=y_column,
                  add_constant=add_constant,
                  project_id=self._project_id, work_dir=self._work_dir)
        return _json.dumps(res, ensure_ascii=False, default=str)[:10000]


class CorrelationMatrixTool(_WorkdirTool):
    name = "correlation_matrix"
    description = ("相关性分析：Pearson/Spearman 相关矩阵 + Top 强相关对。"
                   "用于变量关系探索、建模前变量筛选。")
    inputs = {
        "file": {"type": "string", "description": "数据文件标识（项目数据库）"},
        "sheet": {"type": "string", "description": "工作表名，默认第一个", "nullable": True},
        "columns": {"type": "array", "items": {"type": "string"}, "description": "参与相关分析的列，空=全部数值列", "nullable": True},
        "method": {"type": "string", "description": "pearson/spearman，默认 pearson", "nullable": True},
        "threshold": {"type": "number", "description": "强相关阈值，默认 0.6", "nullable": True},
    }
    output_type = "string"

    def forward(self, file: str, sheet: str = "", columns=None,
                method: str = "pearson", threshold: float = 0.6) -> str:
        import json as _json
        from tools.financial_analysis_tools import correlation_matrix as _fn
        res = _fn(file, sheet=sheet, columns=columns, method=method, threshold=threshold,
                  project_id=self._project_id, work_dir=self._work_dir)
        return _json.dumps(res, ensure_ascii=False, default=str)[:10000]


class TimeSeriesAnalysisTool(_WorkdirTool):
    name = "time_series_analysis"
    description = ("时间序列：趋势 + 季节分解 + 预测（线性外推/指数平滑/移动平均）。"
                   "用于销售/收入趋势预测。")
    inputs = {
        "file": {"type": "string", "description": "数据文件标识（项目数据库）"},
        "sheet": {"type": "string", "description": "工作表名，默认第一个", "nullable": True},
        "date_column": {"type": "string", "description": "日期/期间列名", "nullable": True},
        "value_column": {"type": "string", "description": "数值列名", "nullable": True},
        "freq": {"type": "string", "description": "频率：M=月 Q=季 Y=年，默认 M", "nullable": True},
        "decompose": {"type": "boolean", "description": "是否季节分解，默认 true", "nullable": True},
        "forecast_horizon": {"type": "integer", "description": "预测期数，默认 3", "nullable": True},
        "method": {"type": "string", "description": "auto/linear/exp_smooth/moving_avg，默认 auto", "nullable": True},
    }
    output_type = "string"

    def forward(self, file: str, sheet: str = "", date_column: str = "",
                value_column: str = "", freq: str = "M", decompose: bool = True,
                forecast_horizon: int = 3, method: str = "auto") -> str:
        import json as _json
        from tools.financial_analysis_tools import time_series_analysis as _fn
        res = _fn(file, sheet=sheet, date_column=date_column, value_column=value_column,
                  freq=freq, decompose=decompose, forecast_horizon=forecast_horizon,
                  method=method, project_id=self._project_id, work_dir=self._work_dir)
        return _json.dumps(res, ensure_ascii=False, default=str)[:10000]


class SensitivityAnalysisTool(_WorkdirTool):
    name = "sensitivity_analysis"
    description = ("敏感性/情景分析：单/双变量、CVP 盈亏平衡、三情景对比。"
                   "model_type: cvp/npv/custom_formula。用于风险识别、保本测算。")
    inputs = {
        "base_inputs": {"type": "object", "description": "基准输入 {变量: 值}，如 cvp 需 price/vc/qty/fc", "nullable": True},
        "model_type": {"type": "string", "description": "cvp/npv/custom_formula，默认 cvp", "nullable": True},
        "formula": {"type": "string", "description": "custom_formula 时的表达式（仅四则/括号/白名单变量）", "nullable": True},
        "variable_ranges": {"type": "object", "description": "变量步长 {变量: {steps: [...]}}，默认 ±15%", "nullable": True},
        "two_way_vars": {"type": "array", "items": {"type": "string"}, "description": "双变量分析变量对（最多 2 个）", "nullable": True},
        "discount_rate": {"type": "number", "description": "npv 模型折现率，默认 0.10", "nullable": True},
        "scenarios": {"type": "object", "description": "情景 {乐观: {...}, 悲观: {...}}", "nullable": True},
    }
    output_type = "string"

    def forward(self, base_inputs=None, model_type: str = "cvp", formula: str = "",
                variable_ranges=None, two_way_vars=None, discount_rate: float = 0.10,
                scenarios=None) -> str:
        import json as _json
        from tools.financial_analysis_tools import sensitivity_analysis as _fn
        res = _fn(base_inputs=base_inputs, model_type=model_type, formula=formula,
                  variable_ranges=variable_ranges, two_way_vars=two_way_vars,
                  discount_rate=discount_rate, scenarios=scenarios,
                  project_id=self._project_id, work_dir=self._work_dir)
        return _json.dumps(res, ensure_ascii=False, default=str)[:10000]


class GenerateChartTool(Tool):
    name = "generate_chart"
    description = ("ECharts 图表：选模板（25 类含 3D）+ 数据 + data_table（必填，先表后图）。"
                   "返回 chart-json 嵌入回答，前端渲染。"
                   "3D 模板（scatter3d/bar3d/waterfall3d）由 Python(mplot3d) 生成 PNG，"
                   "AI 正常提交数据即可，无需介入绘图。")
    inputs = {
        "template": {"type": "string", "description": "图表模板名（25 类之一；3D 用 scatter3d/bar3d/waterfall3d）", "nullable": True},
        "title": {"type": "string", "description": "图表标题（图内不显示表名大标题，容器标题栏已展示）", "nullable": True},
        "data": {"type": "object", "description": "数据：{categories, series:[{name, data}], xCategories, yCategories, indicators}；3D 模板用 xCategories/yCategories + data=[[xIdx,yIdx,zVal],…]", "nullable": True},
        "option_overrides": {"type": "object", "description": "局部覆盖（轴名/颜色/单位等）", "nullable": True},
        "data_table": {"type": "array", "items": {"type": "object"}, "description": "对应数据表行（必填，[{col: val}]）", "nullable": True},
    }
    output_type = "string"

    def forward(self, template: str = "", title: str = "", data=None,
                option_overrides=None, data_table=None) -> str:
        import json as _json
        from tools.financial_analysis_tools import generate_chart as _fn
        res = _fn(template=template, title=title, data=data,
                  option_overrides=option_overrides, data_table=data_table)
        return _json.dumps(res, ensure_ascii=False, default=str)[:20000]


class RunPythonCodeTool(_WorkdirTool):
    name = "run_python_code"
    description = ("L2 沙箱执行 pandas/numpy 代码（长尾分析兜底）。"
                   "内置 load_data(file, sheet) 读库内数据。禁文件系统/网络。")
    inputs = {
        "code": {"type": "string", "description": "Python 代码；可用 load_data(file, sheet) 读库内 DataFrame；print/表达式输出结果", "nullable": True},
    }
    output_type = "string"

    def forward(self, code: str = "") -> str:
        import json as _json
        from smolagents.default_tools import PythonInterpreterTool
        # ⚠ authorized_imports 注入 pandas/numpy/json（默认沙箱不含）
        # ⚠ timeout_seconds=90：显式超时，防长尾分析脚本卡死对话（默认 30s 偏紧，
        #   但必须有上限——卡死会阻塞整个 run 直到用户手动终止）
        tool = PythonInterpreterTool(
            authorized_imports=["pandas", "numpy", "json", "statistics", "math",
                                "datetime", "re", "collections", "itertools",
                                "sqlite3", "os"],
            timeout_seconds=90,
        )
        # 注入 load_data 辅助函数：用 sqlite3 + pandas 内联读取项目数据库
        # （沙箱禁 import 项目模块，故复制最小读取逻辑；正式安全校验走 L1 工具）
        db_path = ""
        try:
            # 用 storage.db 模块级 DB_PATH（测试环境已被覆盖为临时库）
            import storage.db as _sdb
            db_path = str(_sdb.DB_PATH)
        except Exception:  # noqa: BLE001
            try:
                from config.settings import DB_PATH as _DB
                db_path = str(_DB)
            except Exception:  # noqa: BLE001
                pass
        helper = (
            "import pandas as pd\n"
            "import sqlite3\n"
            "def load_data(file, sheet=''):\n"
            "    _db = sqlite3.connect(%(db)r)\n"
            "    try:\n"
            "        _cur = _db.execute(\"SELECT id, file_name FROM project_data_files WHERE project_id=? AND file_name=?\", (%(pid)r, file))\n"
            "        _fid = None\n"
            "        for _r in _cur:\n"
            "            _fid = _r[0]\n"
            "        if not _fid:\n"
            "            raise ValueError('未找到数据文件: ' + str(file))\n"
            "        _srow = None\n"
            "        if sheet:\n"
            "            _cur = _db.execute(\"SELECT table_name, headers_json FROM project_data_sheets WHERE file_id=? AND sheet_name=?\", (_fid, sheet))\n"
            "        else:\n"
            "            _cur = _db.execute(\"SELECT table_name, headers_json FROM project_data_sheets WHERE file_id=? ORDER BY id LIMIT 1\", (_fid,))\n"
            "        for _r in _cur:\n"
            "            _srow = _r\n"
            "        if not _srow:\n"
            "            raise ValueError('未找到工作表')\n"
            "        _tbl, _hdrs = _srow[0], _srow[1]\n"
            "        import json as _j\n"
            "        _cols = [_h['name'] for _h in _j.loads(_hdrs)] if _hdrs else []\n"
            "        _sel = ', '.join('\"' + c.replace('\"','\"\"') + '\"' for c in _cols)\n"
            "        _df = pd.read_sql_query('SELECT ' + _sel + ' FROM \"' + _tbl + '\"', _db)\n"
            "        # 自动清洗（P6-⑦）：占位符转 NaN + 数值列自动 to_numeric ——\n"
            "        # 导入时文本占位符（empty/None/''）与文本型数值列会导致分析工具反复清洗失败\n"
            "        # 注：pandas 3.0 字符串列 dtype 为 'str'（旧版 'object'），需同时兼容\n"
            "        for _c in _df.columns:\n"
            "            if str(_df[_c].dtype) in ('object', 'str', 'string'):\n"
            "                _df[_c] = _df[_c].replace(['empty', 'None', 'null', ''], None)\n"
            "                _conv = pd.to_numeric(_df[_c], errors='coerce')\n"
            "                if _conv.notna().sum() > 0:\n"
            "                    _df[_c] = _conv\n"
            "        return _df\n"
            "    finally:\n"
            "        _db.close()\n"
        ) % {"db": db_path, "pid": self._project_id}
        full = helper + "\n" + (code or "")
        try:
            out = tool.forward(full)
        except Exception as e:  # noqa: BLE001
            return _json.dumps({"success": False, "error": f"代码执行失败: {e}"}, ensure_ascii=False)[:10000]
        return _json.dumps({"success": True, "result": str(out)[:8000]}, ensure_ascii=False)


# =====================================================================
# 注册表：全部工具的工厂函数
# =====================================================================

TOOL_CLASSES: list[type[Tool]] = [
    # 文件系统（8）
    ReadFileTool, ListDirectoryTool, SearchFilesTool, WriteFileTool,
    CreateDirectoryTool, DeletePathTool, MovePathTool, CopyPathTool,
    # 命令（1）
    RunCommandTool,
    # Python（4）
    GetPythonVersionTool, GetPythonExecutableTool, GetInstalledPackagesTool,
    ConfigurePythonEnvironmentTool,
    # Excel（5）
    ReadExcelTool, GetSheetInfoTool, WriteExcelTool, AnalyzeExcelTool,
    CompareExcelSheetsTool,
    # 项目数据平面（10）
    ImportExcelToDbTool, QueryTableTool, TableStatsTool, JoinTablesTool,
    UpdateRowsTool, InsertRowsTool, DeleteRowsTool, ExportProjectDataTool,
    ListDataFilesTool, GetTableIndexTool,
    # 核对（1）
    ReconcileVariablesTool,
    # Skill（2）
    ReadSkillTool, ReadSkillResourceTool,
    # 财务分析（7）
    FinancialMetricsTool, RegressionAnalysisTool, CorrelationMatrixTool,
    TimeSeriesAnalysisTool, SensitivityAnalysisTool, GenerateChartTool,
    RunPythonCodeTool,
]


def build_smol_tools(work_dir: str = "", project_id: str = "",
                     allow_outside: bool = False) -> list[Tool]:
    """实例化全部 smolagents Tool（注入 work_dir/project_id/allow_outside）。

    阶段 G：allow_outside=True（全自动模式）→ 文件工具解除沙箱，
    可读写项目外路径（read_excel 等同样放行）。
    """
    return [cls(work_dir=work_dir, project_id=project_id,
                allow_outside=allow_outside) for cls in TOOL_CLASSES]


# =====================================================================
# 工具清单（阶段 7.8：智能体配置页静态展示用）
# =====================================================================

# 类别分组（与模块内分区注释一致）
TOOL_CATEGORIES: list[tuple[str, list[str]]] = [
    ("文件系统", [
        "read_file", "list_directory", "search_files", "write_file",
        "create_directory", "delete_path", "move_path", "copy_path",
    ]),
    ("命令", ["run_command"]),
    ("Python", [
        "get_python_version", "get_python_executable",
        "get_installed_packages", "configure_python_environment",
    ]),
    ("Excel", [
        "read_excel", "get_sheet_info", "write_excel",
        "analyze_excel", "compare_excel_sheets",
    ]),
    ("项目数据平面", [
        "import_excel_to_db", "query_table", "table_stats", "join_tables",
        "update_rows", "insert_rows", "delete_rows", "export_project_data",
        "list_data_files", "get_table_index",
    ]),
    ("核对", ["reconcile_variables"]),
    ("Skill", ["read_skill", "read_skill_resource"]),
    ("财务分析", [
        "financial_metrics", "regression_analysis", "correlation_matrix",
        "time_series_analysis", "sensitivity_analysis", "generate_chart",
        "run_python_code",
    ]),
]


def get_tool_catalog() -> list[dict]:
    """返回按类别分组的工具清单（name + description），供前端静态展示。

    遍历 TOOL_CLASSES 提取每个类的 name/description 类属性，
    按 TOOL_CATEGORIES 分组排序（类名 → 工具名映射）。
    """
    by_name: dict[str, dict] = {}
    for cls in TOOL_CLASSES:
        tname = getattr(cls, "name", "") or ""
        if not tname:
            continue
        by_name[tname] = {
            "name": tname,
            "description": (getattr(cls, "description", "") or "").strip(),
        }
    result: list[dict] = []
    for category, names in TOOL_CATEGORIES:
        tools = [by_name[n] for n in names if n in by_name]
        if tools:
            result.append({"category": category, "tools": tools})
    return result
