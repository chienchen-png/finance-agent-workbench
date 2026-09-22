# -*- coding: utf-8 -*-
"""修复 Windows 图标缓存：清空后重启资源管理器。
安全策略：先备份 iconcache_*.db / thumbcache_*.db 到临时目录，再删除。
"""
import os, glob, shutil, subprocess, time

cache_dir = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Explorer")
backup_dir = os.path.expandvars(r"%TEMP%\iconcache_backup")
os.makedirs(backup_dir, exist_ok=True)

print("1. 结束 explorer.exe ...")
subprocess.run(["taskkill", "/f", "/im", "explorer.exe"], capture_output=True)
time.sleep(1.5)

backed = []
deleted = []
for pat in ("iconcache_*", "thumbcache_*"):
    for f in glob.glob(os.path.join(cache_dir, pat)):
        # 跳过非文件（有些是目录/占位）
        if not os.path.isfile(f):
            continue
        name = os.path.basename(f)
        try:
            dst = os.path.join(backup_dir, name)
            shutil.copy2(f, dst)  # 备份
            backed.append(name)
        except Exception as e:
            print(f"  备份失败 {name}: {e}")
        try:
            os.remove(f)
            deleted.append(name)
        except Exception as e:
            print(f"  删除失败 {name}: {e}")

print(f"2. 已备份 {len(backed)} 个到 {backup_dir}")
print(f"3. 已删除 {len(deleted)} 个图标缓存")
for n in deleted:
    print("   -", n)

print("4. 重启 explorer.exe ...")
subprocess.run(["explorer.exe"], capture_output=True)
time.sleep(1.5)

print("完成。桌面图标缓存已清空并重启资源管理器。")
