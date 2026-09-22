"""Tool Registry — unified tool dispatch and approval guard.

⚠️ DEPRECATED（智能体优化 3.0）：本模块为 legacy AgentCore 的工具注册表，
仅被 agent/core.py（后备轨）引用。smol 引擎的工具定义在 agent/smol_tools.py
（TOOL_CLASSES 权威清单，30 个工具），新工具一律注册到 smol_tools。

Phase 8: Registers all 18 tools with their approval policies.
AgentCore calls registry.dispatch(name, params) → result.
"""

from __future__ import annotations

from agent.approval import ApprovalManager

# Import all tool implementations
from tools.command_tools import run_command
from tools.filesystem_tools import (
    read_file, list_directory, search_files,
    write_file, create_directory, delete_path, move_path, copy_path,
)
from tools.python_tools import (
    get_version, get_executable, get_installed_packages, configure_environment,
)
from tools.excel_tools import (
    read_excel, get_sheet_info, write_excel, analyze_excel, compare_excel_sheets,
)
from tools.project_data_tools import (
    import_excel_to_db, query_table, table_stats, join_tables,
    update_rows, insert_rows, delete_rows, export_project_data,
)

# All tool schemas for LLM function calling
ALL_TOOL_SCHEMAS: list[dict] = [
    # ── ask_user (handled by AgentCore directly) ──
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "向用户提问以获取缺失信息。调用后等待用户回答。",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "向用户提出的问题"},
                    "input_type": {"type": "string", "enum": ["text", "confirm", "select"], "description": "text=自由文本, confirm=是/否, select=选项列表"},
                    "options": {"type": "array", "items": {"type": "string"}, "description": "当input_type=select时的选项"},
                    "allow_skip": {"type": "boolean", "description": "是否允许用户跳过"},
                    "multi_select": {"type": "boolean", "description": "是否允许多选"},
                },
                "required": ["question"],
            },
        },
    },
    # ── plan_task (handled by AgentCore directly) ──
    {
        "type": "function",
        "function": {
            "name": "plan_task",
            "description": "生成结构化任务计划。复杂任务（3步以上）应先调用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string", "description": "步骤标题"},
                                "description": {"type": "string", "description": "步骤描述"},
                                "tools_needed": {"type": "array", "items": {"type": "string"}, "description": "此步骤需要的工具名"},
                                "expected_output": {"type": "string", "description": "预期产出"},
                            },
                            "required": ["title"],
                        },
                    },
                },
                "required": ["steps"],
            },
        },
    },
    # ── Filesystem tools ──
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取工作区文件内容。支持行范围切片和编码自动检测。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件相对路径"},
                    "encoding": {"type": "string", "description": "文件编码，默认utf-8"},
                    "start_line": {"type": "integer", "description": "起始行（0=从头开始）"},
                    "end_line": {"type": "integer", "description": "结束行（0=到末尾）"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "列出工作区目录内容。支持递归列出。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "目录路径，默认'.'=项目根目录"},
                    "recursive": {"type": "boolean", "description": "是否递归列出子目录"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "按文件名模式或内容搜索工作区文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "文件名glob模式，如*.xlsx"},
                    "path": {"type": "string", "description": "搜索起始目录，默认'.'"},
                    "search_content": {"type": "string", "description": "在文件内容中搜索的文本"},
                    "case_sensitive": {"type": "boolean", "description": "是否区分大小写"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "写入文件内容（不创建备份）。需要用户确认。\n注意：若返回 error_type=file_locked，说明文件正被 Excel/Word 等程序打开占用，请立即告知用户关闭该文件后再执行，不要重试。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件相对路径"},
                    "content": {"type": "string", "description": "要写入的文本内容"},
                    "encoding": {"type": "string", "description": "编码，默认utf-8"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_directory",
            "description": "在工作区创建新目录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "目录相对路径"},
                    "exist_ok": {"type": "boolean", "description": "已存在时不报错，默认true"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_path",
            "description": "删除工作区中的文件或目录。需要用户逐项确认。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要删除的文件/目录路径"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_path",
            "description": "移动或重命名工作区中的文件/目录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "源路径"},
                    "destination": {"type": "string", "description": "目标路径"},
                },
                "required": ["source", "destination"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "copy_path",
            "description": "复制工作区中的文件或目录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "源路径"},
                    "destination": {"type": "string", "description": "目标路径"},
                },
                "required": ["source", "destination"],
            },
        },
    },
    # ── Command tool ──
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "在工作区执行命令行。高风险命令需用户确认。超时默认60秒。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的命令"},
                    "timeout": {"type": "integer", "description": "超时秒数，默认60"},
                    "reason": {"type": "string", "description": "执行原因（用于审批展示）"},
                    "expected_effect": {"type": "string", "description": "预期效果"},
                },
                "required": ["command"],
            },
        },
    },
    # ── Python tools ──
    {
        "type": "function",
        "function": {
            "name": "get_python_version",
            "description": "获取Python解释器版本信息。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_python_executable",
            "description": "获取Python解释器可执行文件路径和虚拟环境信息。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_installed_packages",
            "description": "列出当前Python环境已安装的包。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "configure_python_environment",
            "description": "配置Python环境（安装包等）。需要用户确认。",
            "parameters": {
                "type": "object",
                "properties": {
                    "python_path": {"type": "string", "description": "Python解释器路径"},
                    "install_packages": {"type": "array", "items": {"type": "string"}, "description": "要安装的包名列表"},
                },
            },
        },
    },
    # ── Excel tools ──
    {
        "type": "function",
        "function": {
            "name": "read_excel",
            "description": "读取Excel文件数据。支持指定工作表、范围、最大行数。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Excel文件相对路径"},
                    "sheet": {"type": "string", "description": "工作表名称，留空返回所有工作表名"},
                    "range_spec": {"type": "string", "description": "A1区域，如 A1:E500；大表按区域分块读取时使用"},
                    "max_rows": {"type": "integer", "description": "最大读取行数，默认1000"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_sheet_info",
            "description": "获取Excel工作簿中所有工作表的元数据（表名、行列数、表头）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Excel文件相对路径"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_excel",
            "description": "将数据写入Excel文件。自动备份已有文件。需要用户确认。\n注意：若返回 error_type=file_locked，说明文件正被 Excel 打开占用，请立即告知用户关闭该文件后再执行，不要重试。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Excel文件相对路径"},
                    "data": {"type": "array", "items": {"type": "object"}, "description": "数据行列表，每行是字典"},
                    "sheet": {"type": "string", "description": "工作表名，默认Sheet1"},
                },
                "required": ["path", "data"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_excel",
            "description": "分析Excel文件结构和数据类型，建议关键匹配字段。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Excel文件相对路径"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_excel_sheets",
            "description": "对比两个Excel工作表的数据差异（财务核对核心工具）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file1": {"type": "string", "description": "第一个Excel文件路径"},
                    "sheet1": {"type": "string", "description": "第一个工作表名"},
                    "file2": {"type": "string", "description": "第二个Excel文件路径"},
                    "sheet2": {"type": "string", "description": "第二个工作表名"},
                    "key_columns": {"type": "array", "items": {"type": "string"}, "description": "匹配键列名，留空自动检测"},
                },
                "required": ["file1", "sheet1", "file2", "sheet2"],
            },
        },
    },
    # ── Project data plane tools (Phase 14B) ──
    {
        "type": "function",
        "function": {
            "name": "import_excel_to_db",
            "description": "将工作区中的Excel文件导入项目数据库（数据平面）。对话中用户提及处理某个Excel且该文件未导入时应先调用此工具。若返回 needs_anchor 提示，说明无法自动识别表头行，应通过 ask_user 询问用户表头在第几行（从1开始），然后用 header_row 参数重试。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Excel文件相对路径（如 data/2026Q2.xlsx）"},
                    "header_row": {"type": "integer", "description": "（可选）变量名/表头所在行号（从1开始），用于表头无法自动识别时由用户指定后重试"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_table",
            "description": "查询项目数据库中的数据表（库内查询，不读取原始Excel）。按字段名筛选、排序、限量返回结果子集；支持 aggregate 分组聚合（如 sum(销售额)），处理上万行数据时优先用聚合而不是拉全量。处理已导入的数据文件优先使用本工具而非 read_excel。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file": {"type": "string", "description": "数据文件名（如 2026Q2_流水.xlsx）"},
                    "sheet": {"type": "string", "description": "工作表名，省略取第一个分表"},
                    "columns": {"type": "array", "items": {"type": "string"}, "description": "要返回的字段名数组，省略返回全部"},
                    "filters": {"type": "object", "description": "筛选条件 {「字段名」: 值}，精确匹配，多个条件为AND关系"},
                    "order_by": {"type": "string", "description": "排序字段，如 '金额' 或 '金额:desc'；聚合模式可填 _m0 按第一个指标排序"},
                    "limit": {"type": "integer", "description": "返回行数上限，默认100，最大5000"},
                    "aggregate": {"type": "object", "description": "分组聚合：{group_by: [字段...], metrics: ['sum(金额)','count(*)']}；上万行数据优先用此参数"},
                },
                "required": ["file"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "table_stats",
            "description": "对项目数据库中的数据表做聚合统计（sum/avg/count/min/max），支持按字段分组。核对汇总、趋势分析优先使用本工具；多指标分组聚合也可用 query_table 的 aggregate 参数。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file": {"type": "string", "description": "数据文件名（如 2026Q2_流水.xlsx）"},
                    "sheet": {"type": "string", "description": "工作表名，省略取第一个分表"},
                    "group_by": {"type": "string", "description": "分组字段名，省略则不分组"},
                    "agg": {"type": "string", "enum": ["sum", "avg", "count", "min", "max"], "description": "聚合函数，默认sum"},
                    "agg_column": {"type": "string", "description": "被聚合的数值字段名（count 可省略）"},
                },
                "required": ["file"],
            },
        },
    },
    # ── Project data plane join (Phase 14D, read-only) ──
    {
        "type": "function",
        "function": {
            "name": "join_tables",
            "description": "跨表连接核对（库内 JOIN）：将两个数据表按键字段关联，返回结果子集。跨文件/跨工作表数据核对优先使用本工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "left_file": {"type": "string", "description": "左表数据文件名"},
                    "left_sheet": {"type": "string", "description": "左表工作表名，省略取第一个分表"},
                    "left_key": {"type": "string", "description": "左表连接键字段名"},
                    "right_file": {"type": "string", "description": "右表数据文件名"},
                    "right_sheet": {"type": "string", "description": "右表工作表名，省略取第一个分表"},
                    "right_key": {"type": "string", "description": "右表连接键字段名"},
                    "columns": {"type": "array", "items": {"type": "string"}, "description": "输出字段：\"字段\"（左表优先）/\"left:字段\"/\"right:字段\"（右表列以 R_ 前缀返回）；省略返回左表全部 + 右表非键列"},
                    "how": {"type": "string", "enum": ["inner", "left"], "description": "inner=内连接（默认）/ left=左连接（保留左表未匹配行）"},
                    "limit": {"type": "integer", "description": "返回行数上限，默认100，最大500"},
                },
                "required": ["left_file", "left_key", "right_file", "right_key"],
            },
        },
    },
    # ── Project data change tools (Phase 14C, write → needs confirm) ──
    {
        "type": "function",
        "function": {
            "name": "update_rows",
            "description": "更新项目数据库数据表中符合条件的行（cell 级变更日志）。修改数据请用本工具而非 write_excel 整表重写。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file": {"type": "string", "description": "数据文件名"},
                    "sheet": {"type": "string", "description": "工作表名，省略取第一个分表"},
                    "filters": {"type": "object", "description": "定位条件 {「字段」: 值}，精确匹配，必填"},
                    "updates": {"type": "object", "description": "要修改的字段 {「字段」: 新值}"},
                },
                "required": ["file", "filters", "updates"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "insert_rows",
            "description": "向项目数据库数据表插入新行（cell 级变更日志）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file": {"type": "string", "description": "数据文件名"},
                    "sheet": {"type": "string", "description": "工作表名，省略取第一个分表"},
                    "rows": {"type": "array", "items": {"type": "object"}, "description": "新行数组，每项为 {字段: 值} 对象"},
                },
                "required": ["file", "rows"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_rows",
            "description": "从项目数据库数据表删除符合条件的行（cell 级变更日志）。必须指定定位条件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file": {"type": "string", "description": "数据文件名"},
                    "sheet": {"type": "string", "description": "工作表名，省略取第一个分表"},
                    "filters": {"type": "object", "description": "定位条件 {「字段」: 值}，精确匹配，必填"},
                },
                "required": ["file", "filters"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_project_data",
            "description": "将项目数据库数据物化回写原始 Excel 文件（自动备份 .bak）。模板重建保留格式全量写回；精确回写仅写变更单元格。修改数据完成后调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file": {"type": "string", "description": "数据文件名"},
                    "mode": {"type": "string", "enum": ["template", "precise"], "description": "template=模板重建（默认，保留格式全量写回）；precise=精确回写（仅写变更单元格）"},
                    "sheet": {"type": "string", "description": "仅导出指定工作表（可选，默认全部）"},
                },
                "required": ["file"],
            },
        },
    },
]


class ToolRegistry:
    """Registry for all available tools with approval gating."""

    def __init__(self, work_dir: str = "", project_id: str = "") -> None:
        self.work_dir = work_dir
        self.project_id = project_id
        self.approval = ApprovalManager()
        self._tools: dict[str, callable] = {}
        self._register_all()

    def _register_all(self) -> None:
        """Register all Phase 8 + Phase 14B tools."""
        # Filesystem tools
        self.register("read_file", self._wrap(read_file))
        self.register("list_directory", self._wrap(list_directory))
        self.register("search_files", self._wrap(search_files))
        self.register("write_file", self._wrap(write_file))
        self.register("create_directory", self._wrap(create_directory))
        self.register("delete_path", self._wrap(delete_path))
        self.register("move_path", self._wrap(move_path))
        self.register("copy_path", self._wrap(copy_path))
        # Command
        self.register("run_command", self._wrap(run_command))
        # Python
        self.register("get_python_version", self._wrap_pure(get_version))
        self.register("get_python_executable", self._wrap_pure(get_executable))
        self.register("get_installed_packages", self._wrap_pure(get_installed_packages))
        self.register("configure_python_environment", self._wrap(configure_environment))
        # Excel
        self.register("read_excel", self._wrap(read_excel))
        self.register("get_sheet_info", self._wrap(get_sheet_info))
        self.register("write_excel", self._wrap(write_excel))
        self.register("analyze_excel", self._wrap(analyze_excel))
        self.register("compare_excel_sheets", self._wrap(compare_excel_sheets))
        # Project data plane (Phase 14B)
        self.register("import_excel_to_db", self._wrap(import_excel_to_db))
        self.register("query_table", self._wrap(query_table))
        self.register("table_stats", self._wrap(table_stats))
        # Project data plane join (Phase 14D)
        self.register("join_tables", self._wrap(join_tables))
        # Project data plane changes (Phase 14C)
        self.register("update_rows", self._wrap(update_rows))
        self.register("insert_rows", self._wrap(insert_rows))
        self.register("delete_rows", self._wrap(delete_rows))
        self.register("export_project_data", self._wrap(export_project_data))

    def _wrap(self, fn):
        """Wrap a tool function that accepts work_dir / project_id to auto-inject."""
        import inspect
        sig = inspect.signature(fn)
        accepts_work_dir = "work_dir" in sig.parameters
        accepts_project_id = "project_id" in sig.parameters

        def wrapped(params: dict, work_dir: str = "") -> dict:
            kwargs = dict(params or {})
            if accepts_work_dir:
                kwargs["work_dir"] = work_dir or self.work_dir
            if accepts_project_id:
                kwargs["project_id"] = self.project_id
            return fn(**kwargs)
        return wrapped

    def _wrap_pure(self, fn):
        """Wrap a pure function that doesn't need work_dir."""
        def wrapped(params: dict, work_dir: str = "") -> dict:
            return fn(**(params or {}))
        return wrapped

    def register(self, name: str, fn: callable) -> None:
        self._tools[name] = fn

    def get(self, name: str) -> callable | None:
        return self._tools.get(name)

    def check_approval(self, name: str, params: dict | None = None) -> str:
        return self.approval.check(name, params, self.work_dir)

    def dispatch(self, name: str, params: dict | None = None) -> dict:
        """Execute a tool by name with approval gating."""
        fn = self._tools.get(name)
        if fn is None:
            return {"success": False, "error": f"未知工具: {name}"}

        approval = self.check_approval(name, params)
        if approval == "deny":
            return {"success": False, "error": f"工具 '{name}' 被安全策略拒绝执行"}

        if approval == "confirm":
            return {
                "success": False,
                "needs_approval": True,
                "tool": name,
                "params": params,
                "reason": f"工具 '{name}' 需要用户确认后才能执行",
            }

        try:
            return fn(params or {}, work_dir=self.work_dir)
        except Exception as e:
            return {"success": False, "error": str(e)}
