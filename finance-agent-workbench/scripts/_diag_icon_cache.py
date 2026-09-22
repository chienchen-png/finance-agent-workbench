# -*- coding: utf-8 -*-
"""诊断图标缓存问题：列出图标缓存文件 + 检查快捷方式。"""
import os, glob, ctypes, struct

# 1. 图标缓存文件
cache_dir = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Explorer")
print("=== 图标缓存文件在:", cache_dir)
for pat in ("iconcache_*", "thumbcache_*"):
    for f in glob.glob(os.path.join(cache_dir, pat)):
        try:
            sz = os.path.getsize(f)
            mtime = os.path.getmtime(f)
            print(f"  {os.path.basename(f)}  size={sz}  mtime={mtime}")
        except Exception as e:
            print(f"  {os.path.basename(f)}  ERR {e}")

# 2. 确认 exe 图标存在
exe = r"D:\Finance Recon Agent\finance-agent-workbench\Finance Agent.exe"
print("\n=== exe:", exe, "存在:", os.path.exists(exe))
if os.path.exists(exe):
    st = os.stat(exe)
    print(f"  size={st.st_size}  mtime={st.st_mtime}")

# 3. 快捷方式 IconLocation
lnk = r"C:\Users\陈宇华\OneDrive\桌面\Finance Agent.exe - 快捷方式.lnk"
print("\n=== 快捷方式:", lnk, "存在:", os.path.exists(lnk))
