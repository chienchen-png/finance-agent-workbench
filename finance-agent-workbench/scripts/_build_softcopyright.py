#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
软著申请 —— 程序鉴别材料（源代码 Word 文档）自动生成器
=====================================================
功能：从项目中抽取核心源码，剔除空行/纯注释，按「每页 50 行」分页，
      生成「前 30 页 + 后 30 页」的连续代码，并附带：
        - 页眉：软件全称 + 版本号
        - 页脚：页码
        - 字体：代码用 Consolas(等宽) / 宋体，正文字号 9pt（小五）
        - 页边距：上2.0 下2.0 左2.5 右2.0 cm
      输出为标准 .docx（用 zipfile 手写 OOXML，不依赖 python-docx）。

无需第三方依赖，纯 Python 标准库实现。
"""

import os
import zipfile
from xml.sax.saxutils import escape

# ------------------------- 配置区 -------------------------

# 软件信息（请与软著申请表保持一致）
SOFT_NAME = "财务标准化作业系统"
SOFT_FULL_NAME = "基于自然语言操控的财务标准化作业执行系统"
SOFT_VERSION = "V1.0.0"

# 输出目录
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(os.path.dirname(BASE), "软著材料")
os.makedirs(OUT_DIR, exist_ok=True)
OUT_PATH = os.path.join(OUT_DIR, "程序鉴别材料-源代码.docx")

# 每页行数（行业标准：50 行/页）
LINES_PER_PAGE = 50
# 提交页数：前30页 + 后30页
N_PAGES = 30

# 核心源码文件清单（按「体现核心功能」挑选，顺序即拼接顺序）
# 决定"前30页"的源头和"后30页"的结尾落在哪里
CORE_FILES = [
    "app.py",
    "routes/workspace.py",
    "routes/apps.py",
    "agent/core.py",
    "agent/smol_engine.py",
    "agent/smol_tools.py",
    "storage/db.py",
    "storage/project_store.py",
    "storage/run_store.py",
    "tools/project_data_tools.py",
    "tools/financial_analysis_tools.py",
    "tools/_finmod_models.py",
]

# 是否剔除纯注释行 & 空行（建议 True，让每页更"满"，更专业）
STRIP_COMMENTS = True
STRIP_BLANK = True

# ------------------------- 源码读取 -------------------------

def read_sources(base, files):
    """读取所有核心文件内容，返回 [(文件路径, 行列表)]"""
    chunks = []
    for rel in files:
        p = os.path.join(base, rel)
        if not os.path.exists(p):
            print(f"  [跳过] 不存在: {rel}")
            continue
        with open(p, encoding="utf-8", errors="ignore") as f:
            lines = f.read().splitlines()
        chunks.append((rel, lines))
    return chunks


def is_comment_or_blank(line):
    """判定是否为纯注释行或空行（用于剔除）"""
    s = line.strip()
    if not s:
        return True  # 空行
    if s.startswith("#"):
        return True  # Python 注释
    if s.startswith("//") or s.startswith("/*") or s.startswith("*") or s.startswith("*/"):
        return True  # C/JS 风格注释
    if s.startswith("<!--") or s.endswith("-->"):
        return True  # HTML 注释
    return False


def build_clean_lines(chunks, strip_comments=True, strip_blank=True):
    """把源码拼成一份连续的、剔除空行/注释后的行列表。
    为避免因剔除导致前后拼接断裂，这里按文件顺序平铺，
    并在每个文件开始处保留一个文件标记（不作为代码行计数）。
    """
    clean = []          # 有效代码行
    file_marks = []     # [(行内容, 文件相对路径)] 便于后续标注
    for rel, lines in chunks:
        kept = []
        for ln in lines:
            if strip_blank and not ln.strip():
                continue
            if strip_comments and is_comment_or_blank(ln):
                continue
            kept.append(ln)
        if kept:
            file_marks.append((rel, len(kept)))
            clean.extend(kept)
    return clean, file_marks


# ------------------------- OOXML 生成（标准库手写 docx） -------------------------

XML_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'

def xml_escape(t):
    return escape(t)


def build_document_xml(clean_lines, file_marks):
    """构造 docx 的 document.xml —— 严格控制每页 50 行。"""
    ns = (
        'xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas"'
        ' xmlns:cx="http://schemas.microsoft.com/office/drawing/2014/chartex"'
        ' xmlns:dt="urn:schemas-microsoft-com:office:smarttags"'
        ' xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"'
        ' xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
        ' xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
        ' xmlns:o="urn:schemas-microsoft-com:office:office"'
        ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
        ' xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"'
        ' xmlns:v="urn:schemas-microsoft-com:vml"'
        ' xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing"'
        ' xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"'
        ' xmlns:w10="urn:schemas-microsoft-com:office:word"'
        ' xmlns:wne="http://schemas.microsoft.com/office/word/2006/wordml"'
        ' mc:Ignorable="w14 wp14"'
    )
    parts = []
    parts.append(f'<w:document {ns}>')
    parts.append('<w:body>')

    # ----- 文档级设置（字体、边距）-----
    # sectPr 放在 body 末尾（OOXML 规范要求），headerReference/footerReference 关联页眉页脚
    sect_pr = (
        '<w:sectPr>'
        '<w:pgSz w:w="11906" w:h="16838"/>'          # A4 竖版
        '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1417" '
        'w:header="709" w:footer="709" w:gutter="0"/>'   # 上2.0 右2.0 下2.0 左2.5cm
        '<w:headerReference w:type="default" r:id="rId2"/>'
        '<w:footerReference w:type="default" r:id="rId3"/>'
        '<w:cols w:space="708"/>'
        '<w:docGrid w:type="lines" w:linePitch="312"/>'
        '</w:sectPr>'
    )

    # ----- 计算要使用的行 -----
    total_lines = len(clean_lines)
    pages_needed = (total_lines + LINES_PER_PAGE - 1) // LINES_PER_PAGE

    if pages_needed <= N_PAGES * 2:
        # 代码不足60页 -> 全量提交
        lines_to_use = clean_lines
    else:
        # 前30页 + 后30页 = 60页。
        # 标准做法：前30页取满，后30页取满。
        # 中间省略说明作为「过渡注释」插入到前30页与后30页之间，
        # 但它本身不应额外增加页数。做法：把它作为第30页的「末行」
        # （即替换第30页最后一行代码），这样总页数恰好 60。
        first_end = N_PAGES * LINES_PER_PAGE        # 前30页的行数
        last_start = total_lines - N_PAGES * LINES_PER_PAGE  # 后30页起始行
        omitted = pages_needed - N_PAGES * 2        # 被省略的页数
        omitted_note = (
            "/* ====== 此处省略中间 %d 页（共 %d 行），与提交内容连续一致 ====== */"
            % (omitted, last_start - first_end)
        )

        # 取前 30 页的代码（前 first_end-1 行为真实代码，最后 1 行留给省略说明）
        first_part = clean_lines[: first_end - 1]
        # 取后 30 页的代码
        last_part = clean_lines[last_start:]
        # 拼接：前30页(含末行省略说明) + 后30页
        lines_to_use = first_part + [omitted_note] + last_part

    # ----- 每行代码 = 独立段落，每 50 行 = 一页（用分页符隔开） -----
    line_idx = 0
    for idx, ln in enumerate(lines_to_use):
        # 每 50 行之后插入分页符（不在最前面）
        if idx > 0 and idx % LINES_PER_PAGE == 0:
            parts.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
        # 段落：每行代码一个独立段落（禁止段后距，保证每页恰好50行）
        code = xml_escape(ln if ln else " ")
        p = (
            '<w:p>'
            '<w:pPr><w:spacing w:line="240" w:lineRule="auto" w:after="0"/>'
            '<w:rPr><w:rFonts w:ascii="Consolas" w:eastAsia="宋体" w:hAnsi="Consolas"/>'
            '<w:sz w:val="18"/></w:rPr></w:pPr>'
            '<w:r><w:rPr><w:rFonts w:ascii="Consolas" w:eastAsia="宋体" w:hAnsi="Consolas"/>'
            '<w:sz w:val="18"/></w:rPr>'
            f'<w:t xml:space="preserve">{code}</w:t></w:r>'
            '</w:p>'
        )
        parts.append(p)
        line_idx += 1

    # 末尾添加 sectPr（必须在 body 的最后）
    parts.append(sect_pr)
    parts.append('</w:body>')
    parts.append('</w:document>')

    xml = ''.join(parts)
    return xml


def build_header_footer_xml(kind, soft_name, version):
    """页眉(header) / 页脚(footer) 部件 XML。kind='header' 或 'footer'"""
    ns = (
        'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
        ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    )
    if kind == "header":
        # 页眉：居中显示软件名 + 版本号
        text = f"{soft_name} {version}  —— 源程序鉴别材料"
        xml = (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<w:hdr {ns}>'
            f'<w:p>'
            f'<w:pPr><w:jc w:val="center"/><w:pBdr>'
            f'<w:bottom w:val="single" w:sz="4" w:space="1" w:color="000000"/>'
            f'</w:pBdr></w:pPr>'
            f'<w:r><w:rPr><w:rFonts w:ascii="SimSun" w:eastAsia="宋体" w:hAnsi="SimSun"/>'
            f'<w:sz w:val="18"/></w:rPr>'
            f'<w:t>Software Name: {xml_escape(text)}</w:t></w:r>'
            f'</w:p>'
            f'</w:hdr>'
        )
        return xml
    else:
        # 页脚：居中页码 "第 X 页"
        xml = (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<w:ftr {ns}>'
            f'<w:p>'
            f'<w:pPr><w:jc w:val="center"/></w:pPr>'
            f'<w:r><w:rPr><w:rFonts w:ascii="SimSun" w:eastAsia="宋体" w:hAnsi="SimSun"/>'
            f'<w:sz w:val="18"/></w:rPr>'
            f'<w:fldChar w:fldCharType="begin"/></w:r>'
            f'<w:r><w:rPr><w:rFonts w:ascii="SimSun" w:eastAsia="宋体" w:hAnsi="SimSun"/>'
            f'<w:sz w:val="18"/></w:rPr>'
            f'<w:instrText xml:space="preserve">PAGE</w:instrText></w:r>'
            f'<w:r><w:rPr><w:rFonts w:ascii="SimSun" w:eastAsia="宋体" w:hAnsi="SimSun"/>'
            f'<w:sz w:val="18"/></w:rPr>'
            f'<w:fldChar w:fldCharType="end"/></w:r>'
            f'</w:p>'
            f'</w:ftr>'
        )
        return xml


def build_styles_xml():
    """Styles 部件：定义默认样式（含字体）"""
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    return (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w:styles {ns}>'
        f'<w:docDefaults>'
        f'<w:rPrDefault><w:rPr>'
        f'<w:rFonts w:ascii="Consolas" w:eastAsia="宋体" w:hAnsi="Consolas" w:cs="Consolas"/>'
        f'<w:sz w:val="18"/>'   # 9pt = 18 half-points (小五)
        f'<w:szCs w:val="18"/>'
        f'</w:rPr></w:rPrDefault>'
        f'<w:pPrDefault><w:pPr><w:spacing w:line="240" w:lineRule="auto"/></w:pPr></w:pPrDefault>'
        f'</w:docDefaults>'
        f'</w:styles>'
    )


def build_docx(out_path, clean_lines, file_marks, soft_name, version):
    """用 zipfile 手写一个合法的 .docx。"""
    document_xml = build_document_xml(clean_lines, file_marks)
    styles_xml = build_styles_xml()
    header_xml = build_header_footer_xml("header", soft_name, version)
    footer_xml = build_header_footer_xml("footer", soft_name, version)

    # Content_Types
    content_types = (
        XML_HEAD +
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        '<Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>'
        '<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
        '</Types>'
    )

    # _rels/.rels
    rels = (
        XML_HEAD +
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '</Relationships>'
    )

    # word/_rels/document.xml.rels
    doc_rels = (
        XML_HEAD +
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>'
        '</Relationships>'
    )

    # 让 sectPr 关联页眉页脚 —— 需要把 document.xml 里的 sectPr 加上 headerReference/footerReference
    # 我们直接重新生成一次 document xml，加上引用。
    document_xml = document_xml.replace(
        '<w:cols w:space="708"/>',
        '<w:headerReference w:type="default" r:id="rId2"/>'
        '<w:footerReference w:type="default" r:id="rId3"/>'
        '<w:cols w:space="708"/>'
    )

    # 写入 zip
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", document_xml)
        z.writestr("word/styles.xml", styles_xml)
        z.writestr("word/header1.xml", header_xml)
        z.writestr("word/footer1.xml", footer_xml)
        z.writestr("word/_rels/document.xml.rels", doc_rels)

    print(f"✅ 已生成: {out_path}")


def main():
    base = BASE
    print("=" * 60)
    print("程序鉴别材料（源代码）生成器")
    print("=" * 60)
    print(f"软件名称：{SOFT_NAME} {SOFT_VERSION}")
    print(f"核心文件数：{len(CORE_FILES)}")
    print(f"每页行数：{LINES_PER_PAGE}，前后各 {N_PAGES} 页")
    print("-" * 60)

    chunks = read_sources(base, CORE_FILES)
    clean_lines, file_marks = build_clean_lines(
        chunks, strip_comments=STRIP_COMMENTS, strip_blank=STRIP_BLANK
    )
    print(f"剔空行/注释后有效行数：{len(clean_lines)}")
    total_lines_all = sum(len(c) for _, c in chunks)
    print(f"原始总行数（含空行/注释）：{total_lines_all}")

    # 计算页数
    pages = (len(clean_lines) + LINES_PER_PAGE - 1) // LINES_PER_PAGE
    print(f"按 {LINES_PER_PAGE} 行/页，共 {pages} 页")
    if pages <= N_PAGES * 2:
        print("  -> 代码不足 60 页，将全量提交")
    else:
        print("  -> 满足 60 页，取前 30 页 + 后 30 页")

    build_docx(OUT_PATH, clean_lines, file_marks, SOFT_NAME, SOFT_VERSION)
    print(f"\n输出文件：{OUT_PATH}")
    print(f"请打开 Word 审核，确认无误后另存为 PDF。")


if __name__ == "__main__":
    main()
