#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
软著申请 —— 文档鉴别材料（软件说明书 Word 文档）生成器
=====================================================
整合操作说明书 + 软件介绍 + 架构 + 功能说明，生成 60 页的完整软件说明书。
用 _md_to_docx.md_to_docx() 把 Markdown 转成 docx。
"""

import os
import sys

# 保证可导入同目录脚本
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _md_to_docx import md_to_docx
from _softcopyright_doc_content import get_full_content

SOFT_NAME = "财务标准化作业系统"
SOFT_FULL_NAME = "基于自然语言操控的财务标准化作业执行系统"
SOFT_VERSION = "V1.0.0"

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(os.path.dirname(BASE), "软著材料")
os.makedirs(OUT_DIR, exist_ok=True)
OUT_PATH = os.path.join(OUT_DIR, "文档鉴别材料-软件说明书.docx")


def main():
    print("=" * 60)
    print("文档鉴别材料（软件说明书）生成器")
    print("=" * 60)
    print(f"软件名称：{SOFT_NAME} {SOFT_VERSION}")
    print(f"目标：生成 60 页完整软件说明书")
    print("-" * 60)

    content = get_full_content()
    print(f"内容总字符数：{len(content)}")

    md_to_docx(
        md_text=content,
        out_path=OUT_PATH,
        soft_name=SOFT_NAME,
        soft_version=SOFT_VERSION,
        doc_type="软件说明书",
    )
    print(f"\n输出文件：{OUT_PATH}")
    print(f"请打开 Word 审核，确认无误后另存为 PDF。")


if __name__ == "__main__":
    main()
