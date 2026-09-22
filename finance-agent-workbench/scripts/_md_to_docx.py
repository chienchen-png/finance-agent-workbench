#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通用 Markdown → Word (.docx) 转换器（软著文档鉴别材料专用）
=====================================================
纯 Python 标准库实现（zipfile 手写 OOXML），无第三方依赖。
支持：标题层级(H1-H4)、段落、粗体、行内代码、代码块、引用块、
      表格(含表头行)、有序/无序列表、分隔线、页眉页脚、每页行数控制。

用法：
    from _md_to_docx import md_to_docx
    md_to_docx(
        md_text=md_string,
        out_path="xxx.docx",
        soft_name="财务标准化作业系统",
        soft_version="V1.0.0",
        doc_type="软件说明书",
        page_break_every=None,   # 每N段自动分页（可选）
    )
"""

import os
import re
import zipfile
from xml.sax.saxutils import escape


def xml_escape(t):
    return escape(t)


# ------------------------------------------------------------------
#                 OOXML 辅助
# ------------------------------------------------------------------

NS = (
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

# 标题字号(half-points)
HEADING_SIZES = {1: 44, 2: 34, 3: 28, 4: 24}   # H1=22pt H2=17pt H3=14pt H4=12pt


def _rpr(run_props=""):
    return f"<w:rPr>{run_props}</w:rPr>"


def _font(font="宋体", ascii_f="Times New Roman", size=21, bold=False, color=None):
    """构造字体 run props。size 单位 half-points (21=10.5pt 五号)。"""
    b = "<w:b/>" if bold else ""
    c = f'<w:color w:val="{color}"/>' if color else ""
    return (
        f'<w:rFonts w:ascii="{ascii_f}" w:eastAsia="{font}" w:hAnsi="{ascii_f}" w:cs="{ascii_f}"/>'
        f'{b}{c}<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>'
    )


def _run(text, font="宋体", ascii_f="Times New Roman", size=21, bold=False, italic=False, color=None, mono=False):
    """生成一个 <w:r> run。mono 用 Consolas。"""
    if mono:
        rpr = (
            f'<w:rFonts w:ascii="Consolas" w:eastAsia="宋体" w:hAnsi="Consolas" w:cs="Consolas"/>'
            f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>'
        )
    else:
        rpr = _font(font, ascii_f, size, bold, color)
    if italic:
        rpr += "<w:i/>"
    return f'<w:r>{_rpr(rpr)}<w:t xml:space="preserve">{xml_escape(text)}</w:t></w:r>'


def _para(children, style=None, jc=None, spacing=None, indent=None, keep_next=False):
    """生成一个 <w:p> 段落。children 为多个 <w:r>。"""
    ppr = ""
    if style:
        ppr += f'<w:pStyle w:val="{style}"/>'
    if jc:
        ppr += f'<w:jc w:val="{jc}"/>'
    if spacing:
        ppr += spacing
    if indent:
        ppr += indent
    if keep_next:
        ppr += '<w:keepNext/>'
    ppr_el = f"<w:pPr>{ppr}</w:pPr>" if ppr else ""
    return f"<w:p>{ppr_el}{''.join(children)}</w:p>"


def _spacing(after=60, line=300, rule="auto", before=0):
    return f'<w:spacing w:before="{before}" w:after="{after}" w:line="{line}" w:lineRule="{rule}"/>'


def _tab_cell(text, width=2000, font="宋体", size=18, bold=False, jc="left"):
    """生成一个表格单元格 <w:tc>。"""
    ppr = f'<w:pPr><w:jc w:val="{jc}"/><w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/></w:pPr>'
    run = _run(text, font=font, size=size, bold=bold)
    tcpr = f'<w:tcPr><w:tcW w:w="{width}" w:type="dxa"/></w:tcPr>'
    return f"<w:tc>{tcpr}<w:p>{ppr}{run}</w:p></w:tc>"


# ------------------------------------------------------------------
#                 Markdown 行级解析
# ------------------------------------------------------------------

def parse_inline(text):
    """把行内 markdown（粗体、行内代码、斜体）转成多个 run。"""
    runs = []
    # 粗体/斜体/行内代码 用正则切分
    # 简单处理：**bold**、`code`、*italic*
    pattern = re.compile(r"(\*\*.+?\*\*|`[^`]+`|\*[^*]+\*)")
    for part in pattern.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            runs.append(_run(part[2:-2], bold=True))
        elif part.startswith("`") and part.endswith("`"):
            runs.append(_run(part[1:-1], mono=True, size=18))
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            runs.append(_run(part[1:-1], italic=True))
        else:
            runs.append(_run(part))
    return runs


# ------------------------------------------------------------------
#                 Markdown 块级解析
# ------------------------------------------------------------------

def _parse_table_block(lines, start_idx, widths):
    """解析一个表格块。返回 (xml_str, 下一个索引)。"""
    xml = []
    # 收集所有行（直到空行或者非 | 行）
    rows = []
    i = start_idx
    while i < len(lines) and lines[i].strip().startswith("|"):
        row = [c.strip() for c in lines[i].strip().strip("|").split("|")]
        rows.append(row)
        i += 1
    # 去掉分隔行(|---|)
    if len(rows) >= 2 and all(re.fullmatch(r":?-{2,}:?", c.replace(" ", "")) for c in rows[1]):
        header = rows[0]
        body = rows[2:]
    else:
        header = rows[0] if rows else []
        body = rows[1:] if rows else []

    if not header:
        return "", i

    # 处理表头
    ncols = len(header)
    # 构造表格
    t = ["<w:tbl>"]
    # 表格边框（三线表风格）
    t.append("<w:tblPr>")
    t.append('<w:tblW w:w="0" w:type="auto"/>')
    t.append(
        '<w:tblBorders>'
        '<w:top w:val="single" w:sz="12" w:space="0" w:color="000000"/>'
        '<w:left w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
        '<w:bottom w:val="single" w:sz="12" w:space="0" w:color="000000"/>'
        '<w:right w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
        '<w:insideH w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
        '<w:insideV w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
        "</w:tblBorders>"
    )
    t.append("</w:tblPr>")
    t.append('<w:tblGrid>')
    for _ in range(ncols):
        t.append(f'<w:gridCol w:w="{widths.get(0, 2000)}"/>')
    t.append("</w:tblGrid>")

    # 表头行（加底线下划线：用 bottom border on each header cell）
    t.append('<w:tr>')
    for idx, hc in enumerate(header):
        tcppr = (
            f'<w:tcPr><w:tcW w:w="{widths.get(idx, 2000)}" w:type="dxa"/>'
            f'<w:tcBorders><w:bottom w:val="single" w:sz="6" w:space="0" w:color="000000"/></w:tcBorders>'
            f'<w:vAlign w:val="center"/></w:tcPr>'
        )
        ppr = f'<w:pPr><w:jc w:val="center"/><w:spacing w:before="40" w:after="40" w:line="240" w:lineRule="auto"/></w:pPr>'
        t.append(f'<w:tc>{tcppr}<w:p>{ppr}{_run(hc, bold=True, size=18)}</w:p></w:tc>')
    t.append('</w:tr>')

    # 数据行
    for row in body:
        t.append('<w:tr>')
        for idx in range(ncols):
            cell_text = row[idx] if idx < len(row) else ""
            t.append(_tab_cell(cell_text, width=widths.get(idx, 2000), size=18))
        t.append('</w:tr>')

    t.append("</w:tbl>")
    return "".join(t), i


def md_to_docx(md_text, out_path, soft_name, soft_version, doc_type="软件说明书",
               page_break_every=None, footer_text=None):
    """把 Markdown 文本转成 docx。"""
    lines = md_text.splitlines()
    body_parts = []

    # 统计已生成的段落数（用于可选分页）
    para_count = 0

    # 全局表格列宽（按比例，A4 内容宽约 9026 twips）
    widths = {0: 2600, 1: 3200, 2: 3200, 3: 1800}

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.rstrip()
        s = line.strip()

        # 空行跳过
        if not s:
            i += 1
            continue

        # 表格
        if s.startswith("|"):
            tbl_xml, next_i = _parse_table_block(lines, i, widths)
            if tbl_xml:
                body_parts.append(tbl_xml)
                i = next_i
                continue

        # 标题
        hm = re.match(r"^(#{1,4})\s+(.*)$", s)
        if hm:
            level = len(hm.group(1))
            text = hm.group(2)
            hsize = HEADING_SIZES[level]
            # 标题段落加粗，居中按级别
            jc = "center" if level == 1 else "left"
            run = _run(text, font="黑体", ascii_f="Times New Roman", size=hsize, bold=True)
            body_parts.append(
                _para([run], jc=jc, spacing=_spacing(after=120, before=120), keep_next=True)
            )
            i += 1
            continue

        # 分隔线
        if re.fullmatch(r"-{3,}|\*{3,}|_{3,}", s):
            body_parts.append(
                _para([_run("─" * 30, size=18)], spacing=_spacing(after=60, before=60))
            )
            i += 1
            continue

        # 引用块 (>) 或 代码块 (```)
        if s.startswith("```"):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # 跳过闭合 ```
            # 代码块整体作为多行等宽段落
            body_parts.append(
                _para([_run("\n".join(code_lines) if code_lines else "", mono=True, size=16)],
                      spacing=_spacing(after=40, before=40))
            )
            continue

        # 引用块 (>)
        if s.startswith(">"):
            quote_text = s[1:].strip()
            body_parts.append(
                _para(parse_inline(quote_text), jc=None,
                      spacing=_spacing(after=40, before=40),
                      indent='<w:ind w:left="568"/>')
            )
            i += 1
            continue

        # 有序列表 / 无序列表
        olm = re.match(r"^(\d+)[.、]\s+(.*)$", s)
        ulm = re.match(r"^[-*]\s+(.*)$", s)
        if olm or ulm:
            marker = olm.group(1) + ". " if olm else "• "
            content = olm.group(2) if olm else ulm.group(1)
            body_parts.append(
                _para(parse_inline(marker + content),
                      spacing=_spacing(after=40, before=20),
                      indent='<w:ind w:left="426"/>')
            )
            i += 1
            continue

        # 普通段落
        body_parts.append(
            _para(parse_inline(s), spacing=_spacing(after=60), jc="left")
        )
        i += 1

    # ---- 组装文档 ----
    header_xml = build_header(soft_name, soft_version, doc_type)
    footer_xml = build_footer(soft_name, soft_version)
    styles_xml = build_styles()

    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        '<Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>'
        '<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
        '</Types>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '</Relationships>'
    )
    doc_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>'
        '</Relationships>'
    )

    sect_pr = (
        '<w:sectPr>'
        '<w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1800" '
        'w:header="720" w:footer="720" w:gutter="0"/>'
        '<w:headerReference w:type="default" r:id="rId2"/>'
        '<w:footerReference w:type="default" r:id="rId3"/>'
        '<w:cols w:space="708"/>'
        '<w:docGrid w:type="lines" w:linePitch="312"/>'
        '</w:sectPr>'
    )

    document_xml = (
        f'<w:document {NS}>'
        '<w:body>'
        + "".join(body_parts)
        + sect_pr
        + '</w:body></w:document>'
    )

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", document_xml)
        z.writestr("word/styles.xml", styles_xml)
        z.writestr("word/header1.xml", header_xml)
        z.writestr("word/footer1.xml", footer_xml)
        z.writestr("word/_rels/document.xml.rels", doc_rels)
    print(f"✅ 已生成: {out_path}")


def build_header(soft_name, soft_version, doc_type):
    text = f"{soft_name} {soft_version}  ——  {doc_type}"
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w:hdr {ns}>'
        '<w:p><w:pPr><w:jc w:val="center"/><w:pBdr>'
        '<w:bottom w:val="single" w:sz="4" w:space="1" w:color="000000"/>'
        '</w:pBdr></w:pPr>'
        f'<w:r><w:rPr><w:rFonts w:ascii="SimSun" w:eastAsia="宋体" w:hAnsi="SimSun"/>'
        '<w:sz w:val="18"/></w:rPr>'
        f'<w:t xml:space="preserve">{xml_escape(text)}</w:t></w:r></w:p>'
        '</w:hdr>'
    )


def build_footer(soft_name, soft_version):
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w:ftr {ns}>'
        '<w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
        '<w:r><w:rPr><w:rFonts w:ascii="SimSun" w:eastAsia="宋体" w:hAnsi="SimSun"/>'
        '<w:sz w:val="18"/></w:rPr>'
        '<w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:rPr><w:rFonts w:ascii="SimSun" w:eastAsia="宋体" w:hAnsi="SimSun"/>'
        '<w:sz w:val="18"/></w:rPr>'
        '<w:instrText xml:space="preserve">PAGE</w:instrText></w:r>'
        '<w:r><w:rPr><w:rFonts w:ascii="SimSun" w:eastAsia="宋体" w:hAnsi="SimSun"/>'
        '<w:sz w:val="18"/></w:rPr>'
        '<w:fldChar w:fldCharType="end"/></w:r>'
        '</w:p></w:ftr>'
    )


def build_styles():
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w:styles {ns}>'
        '<w:docDefaults><w:rPrDefault><w:rPr>'
        '<w:rFonts w:ascii="Times New Roman" w:eastAsia="宋体" w:hAnsi="Times New Roman" w:cs="Times New Roman"/>'
        '<w:sz w:val="21"/><w:szCs w:val="21"/>'
        '</w:rPr></w:rPrDefault>'
        '<w:pPrDefault><w:pPr><w:spacing w:line="360" w:lineRule="auto" w:after="60"/></w:pPr></w:pPrDefault>'
        '</w:docDefaults>'
        '</w:styles>'
    )


if __name__ == "__main__":
    # 自测
    demo = """# 测试文档

这是一段**加粗**测试文字，包含`行内代码`和*斜体*。

## 一级标题内容

- 项目列表项一
- 项目列表项二

1. 有序列表一
2. 有序列表二

> 这是一个引用块示例。

| 列一 | 列二 | 列三 |
|------|------|------|
| a    | b    | c    |
| d    | e    | f    |

```
def hello():
    print("world")
```
"""
    md_to_docx(demo, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_demo_out.docx"),
               "财务标准化作业系统", "V1.0.0")
