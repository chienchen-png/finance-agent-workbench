from pathlib import Path

APP_NAME = "Finance Agent Workbench"
APP_VERSION = "1.0.0"
HOST = "127.0.0.1"
PORT = 8080
DEBUG = True

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "app.db"
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"
# 新前端构建产物目录（Vite build 输出，由 Flask 直接托管）
FRONTEND_DIST_DIR = BASE_DIR / "frontend" / "dist"

NAV_ITEMS = [
    {"id": "dashboard", "label": "总览", "route": "/"},
    {"id": "ai_config", "label": "AI配置", "route": "/ai-config"},
    {"id": "projects", "label": "我的项目", "route": "/projects"},
    {"id": "workspace", "label": "工作台", "route": "/workspace"},
]
