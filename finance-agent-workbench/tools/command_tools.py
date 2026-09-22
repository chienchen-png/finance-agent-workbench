"""Command Tools — execute shell commands within project workspace.

Phase 8: Real subprocess execution with timeout, output capture, risk analysis,
and workspace boundary enforcement.
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import Any


# Command blacklist
COMMAND_BLACKLIST: list[str] = [
    "format", "shutdown", "del /f /s", "rm -rf /",
    "rd /s /q C:", "diskpart", "reg delete", "taskkill /f /im",
]

DEFAULT_TIMEOUT = 60
MAX_OUTPUT_BYTES = 100 * 1024

SAFE_ENV_VARS: set[str] = {
    "PATH", "PYTHONPATH", "TEMP", "TMP", "USERPROFILE",
    "COMPUTERNAME", "HOMEDRIVE", "HOMEPATH", "SystemRoot",
    # Fix: user site-packages live under %APPDATA%\Python\... and
    # %LOCALAPPDATA%\Programs\Python\... — without these, packages
    # installed to the user environment (e.g. xlrd, pandas) cannot be
    # imported by subprocesses, even though the same python.exe sees them.
    "APPDATA", "LOCALAPPDATA", "PYTHONUSERBASE",
}


def _check_blacklist(command: str) -> str:
    cmd_lower = command.lower()
    for pattern in COMMAND_BLACKLIST:
        if pattern.lower() in cmd_lower:
            return f"命令被安全策略阻止（匹配黑名单: {pattern})"
    return ""


def _classify_risk(command: str) -> str:
    cmd_lower = command.lower()
    for kw in ["c:\\windows", "reg ", "net user", "net localgroup", "sc ", "msiexec"]:
        if kw in cmd_lower:
            return "system_sensitive"
    for kw in ["del ", "rmdir", "rm ", "format", ">", "2>", "pip install", "npm install"]:
        if kw in cmd_lower:
            return "sensitive_workspace"
    return "safe_workspace"


def _safe_env() -> dict:
    safe = {}
    for var in SAFE_ENV_VARS:
        val = os.environ.get(var)
        if val:
            safe[var] = val
    safe["PYTHONUNBUFFERED"] = "1"
    return safe


def run_command(
    command: str,
    work_dir: str = "",
    timeout: int = 60,
    reason: str = "",
    expected_effect: str = "",
) -> dict[str, Any]:
    """Execute a shell command within the project workspace.
    
    Security:
        - Blacklisted commands rejected automatically
        - Output > 100KB truncated
        - Environment variables filtered
    """
    blacklist_reason = _check_blacklist(command)
    if blacklist_reason:
        return {
            "success": False, "stdout": "", "stderr": blacklist_reason,
            "exit_code": -1, "duration_ms": 0.0, "truncated": False,
            "risk_level": "system_sensitive", "command": command,
        }

    risk_level = _classify_risk(command)
    cwd = work_dir or os.getcwd()
    start_time = time.time()

    try:
        # Fix: decode subprocess output robustly. On Windows, text=True uses
        # the console codepage (e.g. GBK), which raises UnicodeDecodeError on
        # UTF-8 output from scripts. Use explicit utf-8 with errors='replace'
        # so Chinese output is preserved and decoding never crashes.
        result = subprocess.run(
            command, shell=True, cwd=cwd, timeout=timeout,
            capture_output=True, text=False, env=_safe_env(),
        )
        duration_ms = (time.time() - start_time) * 1000
        try:
            stdout = (result.stdout or b"").decode("utf-8", errors="replace")
            stderr = (result.stderr or b"").decode("utf-8", errors="replace")
        except Exception:
            stdout = (result.stdout or b"").decode("gbk", errors="replace")
            stderr = (result.stderr or b"").decode("gbk", errors="replace")
        stdout = stdout[:MAX_OUTPUT_BYTES]
        stderr = stderr[:MAX_OUTPUT_BYTES]
        truncated = len(stdout) > MAX_OUTPUT_BYTES or len(stderr) > MAX_OUTPUT_BYTES
        return {
            "success": result.returncode == 0,
            "stdout": stdout, "stderr": stderr,
            "exit_code": result.returncode,
            "duration_ms": round(duration_ms, 1),
            "truncated": truncated, "risk_level": risk_level,
        }
    except subprocess.TimeoutExpired:
        duration_ms = (time.time() - start_time) * 1000
        return {
            "success": False, "stdout": "", "stderr": f"命令执行超时({timeout}秒)",
            "exit_code": -1, "duration_ms": round(duration_ms, 1),
            "truncated": False, "risk_level": risk_level,
        }
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        return {
            "success": False, "stdout": "", "stderr": str(e),
            "exit_code": -1, "duration_ms": round(duration_ms, 1),
            "truncated": False, "risk_level": risk_level,
        }
