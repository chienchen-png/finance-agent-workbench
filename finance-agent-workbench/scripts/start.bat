@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0.."

if exist "..\.venv\Scripts\python.exe" (
    set "PYTHON=..\.venv\Scripts\python.exe"
) else if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
) else (
    set "PYTHON=python"
)

echo Finance Agent Workbench
echo URL: http://localhost:8080
echo.

"%PYTHON%" app.py

endlocal
