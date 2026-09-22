# -*- coding: utf-8 -*-
"""_build_reference_docx — 生成 Pandoc reference-template.docx（论文排版模板）。

依据 docs/项目架构文档.md 附录A（原 docs/格式.md，GB/T 7713 学位论文规范），离线无外部依赖：
  - 读取 pandoc --print-default-data-file reference.docx
  - zipfile 直接编辑 word/styles.xml（样式）+ word/theme/theme1.xml（字体映射）
  - 重新 zip 写出 offline_packages/pandoc/reference-template.docx

用法：python scripts/_build_reference_docx.py
输出：offline_packages/pandoc/reference-template.docx
"""
import re
import subprocess
import sys
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
PANDOC = BASE / "offline_packages" / "pandoc" / "pandoc.exe"
OUT = BASE / "offline_packages" / "pandoc" / "reference-template.docx"


def get_default_ref() -> bytes:
    r = subprocess.run([str(PANDOC), "--print-default-data-file", "reference.docx"],
                       capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"pandoc 导出默认 reference.docx 失败: {r.stderr.decode('utf-8')[:200]}")
    return r.stdout


# ----------------------------------------------------------------------
# 样式值替换（styles.xml）
# ----------------------------------------------------------------------
# Normal（正文基准）：宋体 + Times New Roman，小四 12pt，行距 20 磅固定值，两端对齐，首行缩进 2 字符
NORMAL_RPR = (
    '<w:rFonts w:ascii="Times New Roman" w:eastAsia="宋体" '
    'w:hAnsi="Times New Roman" w:cs="Times New Roman"/>\n'
    '<w:sz w:val="24"/>\n'
    '<w:szCs w:val="24"/>'
)
NORMAL_PPR = (
    '<w:spacing w:line="400" w:lineRule="exact" w:before="0" w:after="0"/>\n'
    '<w:ind w:firstLineChars="200" w:firstLine="480"/>\n'
    '<w:jc w:val="both"/>'
)

# 各标题样式（Heading1-6）：黑体/宋体加粗 + 分级字号
HEADINGS = {
    # styleId: (rFonts_eastAsia, sz, bold, jc, spacing)
    "Heading1": ("黑体", 32, True, "center", '<w:spacing w:line="240" w:lineRule="auto" w:before="360" w:after="360"/>'),
    "Heading2": ("宋体", 28, True, "left", '<w:spacing w:line="240" w:lineRule="auto" w:before="270" w:after="270"/>'),
    "Heading3": ("宋体", 24, True, "left", '<w:spacing w:line="240" w:lineRule="auto" w:before="180" w:after="180"/>'),
    "Heading4": ("宋体", 24, True, "left", '<w:spacing w:line="240" w:lineRule="auto" w:before="90" w:after="90"/>'),
    "Heading5": ("宋体", 24, True, "left", '<w:spacing w:line="240" w:lineRule="auto" w:before="90" w:after="90"/>'),
    "Heading6": ("宋体", 24, False, "left", '<w:spacing w:line="240" w:lineRule="auto" w:before="0" w:after="0"/>'),
}


def build_styles(styles: str) -> str:
    # Normal：直接整体重建（默认参考的 Normal 是空样式，含 qFormat 无 rPr/pPr）
    def repl_normal(m: re.Match) -> str:
        return (
            '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">\n'
            '<w:name w:val="Normal" />\n'
            '<w:qFormat />\n'
            '<w:pPr>\n' + NORMAL_PPR + '\n</w:pPr>\n'
            '<w:rPr>\n' + NORMAL_RPR + '\n</w:rPr>\n'
            '</w:style>'
        )
    styles = re.sub(
        r'<w:style w:type="paragraph" w:default="1" w:styleId="Normal">.*?</w:style>',
        repl_normal, styles, flags=re.S)
    # 各标题
    for sid, (ea, sz, bold, jc, spacing) in HEADINGS.items():
        styles = _replace_heading(styles, sid, ea, sz, bold, jc, spacing)
    return styles


def _replace_heading(styles: str, sid: str, ea: str, sz: int, bold: bool, jc: str, spacing: str) -> str:
    pat = rf'(<w:style [^>]*w:styleId="{sid}".*?</w:style>)'
    def repl(m: re.Match) -> str:
        block = m.group(1)
        # 去掉现有 rFonts/sz/color/jc，插入论文值
        block = re.sub(r'<w:rFonts[^/]*/>', '', block)
        block = re.sub(r'<w:sz[^/]*/>', '', block)
        block = re.sub(r'<w:szCs[^/]*/>', '', block)
        block = re.sub(r'<w:color[^/]*/>', '', block)
        block = re.sub(r'<w:jc[^/]*/>', '', block)
        block = re.sub(r'<w:spacing [^/]*/>', spacing, block)
        # 若 spacing 未匹配到则插在 pPr 内
        if spacing not in block:
            block = re.sub(r'<w:pPr>', '<w:pPr>\n' + spacing, block, count=1)
        # 插入 rPr
        rpr = (f'<w:rFonts w:ascii="Times New Roman" w:eastAsia="{ea}" '
               f'w:hAnsi="Times New Roman" w:cs="Times New Roman"/>\n'
               f'<w:b/>' if bold else f'<w:rFonts w:ascii="Times New Roman" w:eastAsia="{ea}" '
               f'w:hAnsi="Times New Roman" w:cs="Times New Roman"/>') + f'\n<w:sz w:val="{sz}"/>\n<w:szCs w:val="{sz}"/>'
        if '<w:rPr>' in block:
            block = re.sub(r'<w:rPr>', '<w:rPr>\n' + rpr, block, count=1)
        else:
            block = block.replace('</w:style>', '<w:rPr>\n' + rpr + '</w:rPr></w:style>')
        # 对齐
        block = re.sub(r'<w:pPr>', '<w:pPr>\n<w:jc w:val="' + jc + '"/>', block, count=1)
        return block
    return re.sub(pat, repl, styles, flags=re.S)


# ----------------------------------------------------------------------
# Table 样式（三线表 + 五号宋体 + 居中 + 占满）
# ----------------------------------------------------------------------
def build_table(styles: str) -> str:
    """把 Pandoc 默认 Table 样式替换为「三线表」样式。

    三线表 = 上下粗线（1.5pt）+ 表头下细线（0.5pt）+ 无竖线，表格居中占满。
    Word 导出时 Pandoc 生成表格应用此 Table 样式 → 满足论文排版规范。
    """
    custom = (
        '<w:style w:type="table" w:default="1" w:styleId="Table">\n'
        '    <w:name w:val="Table" />\n'
        '    <w:basedOn w:val="TableNormal" />\n'
        '    <w:qFormat />\n'
        '    <w:tblPr>\n'
        '      <w:tblInd w:w="0" w:type="dxa" />\n'
        '      <w:tblW w:w="5000" w:type="pct" />\n'      # 表格占满 100%
        '      <w:jc w:val="center" />\n'                  # 表格水平居中
        '      <w:tblBorders>\n'
        '        <w:top w:val="single" w:sz="12" w:color="000000" />\n'      # 上粗线 1.5pt
        '        <w:left w:val="none" />\n'
        '        <w:right w:val="none" />\n'
        '        <w:bottom w:val="single" w:sz="12" w:color="000000" />\n'   # 下粗线 1.5pt
        '      </w:tblBorders>\n'
        '      <w:tblCellMar>\n'
        '        <w:top w:w="40" w:type="dxa" />\n'
        '        <w:left w:w="108" w:type="dxa" />\n'
        '        <w:bottom w:w="40" w:type="dxa" />\n'
        '        <w:right w:w="108" w:type="dxa" />\n'
        '      </w:tblCellMar>\n'
        '    </w:tblPr>\n'
        '    <w:tblStylePr w:type="firstRow">\n'
        '      <w:pPr>\n'
        '        <w:jc w:val="center" />\n'
        '      </w:pPr>\n'
        '      <w:rPr>\n'
        '        <w:b />\n'
        '        <w:sz w:val="21" />\n'
        '        <w:szCs w:val="21" />\n'
        '        <w:rFonts w:ascii="Times New Roman" w:eastAsia="宋体" w:hAnsi="Times New Roman" />\n'
        '      </w:rPr>\n'
        '      <w:tcPr>\n'
        '        <w:tcBorders>\n'
        '          <w:bottom w:val="single" w:sz="4" w:color="000000" />\n'   # 表头下细线 0.5pt
        '        </w:tcBorders>\n'
        '        <w:vAlign w:val="center" />\n'
        '      </w:tcPr>\n'
        '    </w:tblStylePr>\n'
        '  </w:style>'
    )
    # 用自定义样式替换默认 Table 样式；若找不到则追加到 styles 末尾（<w:latentStyles> 之后）
    if re.search(r'<w:style w:type="table" w:default="1" w:styleId="Table">', styles):
        return re.sub(r'<w:style w:type="table" w:default="1" w:styleId="Table">.*?</w:style>',
                      custom, styles, flags=re.S)
    # 兜底：插入到 </w:styles> 前
    return styles.replace('</w:styles>', custom + '</w:styles>')


# ----------------------------------------------------------------------
# theme1.xml：minorFont（正文）majorFont（标题）映射
# ----------------------------------------------------------------------
def build_theme(theme: str) -> str:
    # 正文 minorFont latin→Times New Roman，ea→宋体
    theme = re.sub(
        r'(<a:minorFont>\s*<a:latin typeface=")[^"]*"',
        r'\1Times New Roman"', theme)
    theme = re.sub(
        r'(<a:minorFont>.*?<a:ea typeface=")[^"]*"',
        r'\1宋体"', theme, flags=re.S)
    # 标题 majorFont latin→Times New Roman，ea→黑体
    theme = re.sub(
        r'(<a:majorFont>\s*<a:latin typeface=")[^"]*"',
        r'\1Times New Roman"', theme)
    theme = re.sub(
        r'(<a:majorFont>.*?<a:ea typeface=")[^"]*"',
        r'\1黑体"', theme, flags=re.S)
    return theme


# ----------------------------------------------------------------------
# document.xml：sectPr 页边距（A4 + 上30/下25/左30/右25mm）—— 写入到 sectPr
# ----------------------------------------------------------------------
def _emu_twips(mm: float) -> int:
    # 1mm = 56.6929 twips
    return int(round(mm * 56.6929))


def build_sectpr(doc: str) -> str:
    pg_sz = f'<w:pgSz w:w="11906" w:h="16838"/>'
    margin = (f'<w:pgMar w:top="{_emu_twips(30)}" w:right="{_emu_twips(25)}" '
              f'w:bottom="{_emu_twips(25)}" w:left="{_emu_twips(30)}" '
              f'w:header="{_emu_twips(23)}" w:footer="{_emu_twips(18)}" '
              f'w:gutter="0"/>')
    def repl(m: re.Match) -> str:
        block = m.group(1)
        block = re.sub(r'<w:pgSz[^/]*/>', pg_sz, block)
        block = re.sub(r'<w:pgMar[^/]*/>', margin, block)
        if '<w:pgSz' not in block:
            block = block.replace('<w:sectPr>', '<w:sectPr>\n' + pg_sz, 1)
        if '<w:pgMar' not in block:
            block = block.replace('<w:sectPr>', '<w:sectPr>\n' + margin, 1)
        return block
    return re.sub(r'(<w:sectPr.*?</w:sectPr>)', repl, doc, flags=re.S)


def main() -> int:
    default = get_default_ref()
    base_zip = BASE / "offline_packages" / "pandoc" / "_tmp_ref.docx"
    base_zip.write_bytes(default)

    with zipfile.ZipFile(base_zip, "r") as zin:
        names = zin.namelist()
        data = {n: zin.read(n) for n in names}

    styles = data["word/styles.xml"].decode("utf-8")
    theme = data["word/theme/theme1.xml"].decode("utf-8")
    doc = data["word/document.xml"].decode("utf-8")

    styles = build_styles(styles)
    styles = build_table(styles)
    theme = build_theme(theme)
    doc = build_sectpr(doc)

    data["word/styles.xml"] = styles.encode("utf-8")
    data["word/theme/theme1.xml"] = theme.encode("utf-8")
    data["word/document.xml"] = doc.encode("utf-8")

    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zout:
        for n in names:
            zout.writestr(n, data[n])

    # 清理临时默认文件
    base_zip.unlink(missing_ok=True)

    print("reference-template.docx 生成:", OUT, "size:", OUT.stat().st_size if OUT.exists() else "?")
    # 校验正常打包
    with zipfile.ZipFile(OUT) as zc:
        bad = zc.testzip()
        print("压缩包校验:", "OK" if bad is None else f"BAD {bad}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
