#!/usr/bin/env python3
"""Markdown → HWPX 변환기.

마크다운의 구조 요소를 템플릿 스타일(charPr/paraPr)에 매핑해 section0.xml을
생성하고, build_hwpx.py 파이프라인으로 .hwpx를 조립한다.

지원(핵심 요소):
  - 제목  # ## ### ####
  - 문단, **굵게**/__굵게__, `코드`(텍스트만), [링크](url)→"링크"
  - 순서 없는 목록 - * +  (들여쓰기 중첩), 순서 목록 1.
  - 인용 >  (각주/작은 글씨)
  - 코드펜스 ``` (고딕 프리포맷)
  - 표 | ... |  (GFM)
  - 수평선 ---

사용법:
  python3 md_to_hwpx.py input.md --output out.hwpx            # 기본 report
  python3 md_to_hwpx.py input.md --template govplan -o out.hwpx
  python3 md_to_hwpx.py input.md --title "제목" --creator "작성자" -o out.hwpx
"""

import argparse
import re
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import build_hwpx  # noqa: E402  (build() 재사용)

# --- 본문폭(HWPUNIT) ---
BODY_WIDTH = 42520

# --- secPr 포함 첫 문단 (base/section0.xml 표준) ---
SEC_OPEN = (
    "<?xml version='1.0' encoding='UTF-8'?>\n"
    '<hs:sec xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
    'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section">\n'
    '  <hp:p id="1000000001" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">\n'
    '    <hp:run charPrIDRef="0">\n'
    '      <hp:secPr id="" textDirection="HORIZONTAL" spaceColumns="1134" tabStop="8000" tabStopVal="4000" tabStopUnit="HWPUNIT" outlineShapeIDRef="1" memoShapeIDRef="0" textVerticalWidthHead="0" masterPageCnt="0">\n'
    '        <hp:grid lineGrid="0" charGrid="0" wonggojiFormat="0"/>\n'
    '        <hp:startNum pageStartsOn="BOTH" page="0" pic="0" tbl="0" equation="0"/>\n'
    '        <hp:visibility hideFirstHeader="0" hideFirstFooter="0" hideFirstMasterPage="0" border="SHOW_ALL" fill="SHOW_ALL" hideFirstPageNum="0" hideFirstEmptyLine="0" showLineNumber="0"/>\n'
    '        <hp:lineNumberShape restartType="0" countBy="0" distance="0" startNumber="0"/>\n'
    '        <hp:pagePr landscape="WIDELY" width="59528" height="84186" gutterType="LEFT_ONLY">\n'
    '          <hp:margin header="4252" footer="4252" gutter="0" left="8504" right="8504" top="5668" bottom="4252"/>\n'
    '        </hp:pagePr>\n'
    '        <hp:footNotePr>\n'
    '          <hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")" supscript="0"/>\n'
    '          <hp:noteLine length="-1" type="SOLID" width="0.12 mm" color="#000000"/>\n'
    '          <hp:noteSpacing betweenNotes="283" belowLine="567" aboveLine="850"/>\n'
    '          <hp:numbering type="CONTINUOUS" newNum="1"/>\n'
    '          <hp:placement place="EACH_COLUMN" beneathText="0"/>\n'
    '        </hp:footNotePr>\n'
    '        <hp:endNotePr>\n'
    '          <hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")" supscript="0"/>\n'
    '          <hp:noteLine length="14692344" type="SOLID" width="0.12 mm" color="#000000"/>\n'
    '          <hp:noteSpacing betweenNotes="0" belowLine="567" aboveLine="850"/>\n'
    '          <hp:numbering type="CONTINUOUS" newNum="1"/>\n'
    '          <hp:placement place="END_OF_DOCUMENT" beneathText="0"/>\n'
    '        </hp:endNotePr>\n'
    '        <hp:pageBorderFill type="BOTH" borderFillIDRef="1" textBorder="PAPER" headerInside="0" footerInside="0" fillArea="PAPER">\n'
    '          <hp:offset left="1417" right="1417" top="1417" bottom="1417"/>\n'
    '        </hp:pageBorderFill>\n'
    '        <hp:pageBorderFill type="EVEN" borderFillIDRef="1" textBorder="PAPER" headerInside="0" footerInside="0" fillArea="PAPER">\n'
    '          <hp:offset left="1417" right="1417" top="1417" bottom="1417"/>\n'
    '        </hp:pageBorderFill>\n'
    '        <hp:pageBorderFill type="ODD" borderFillIDRef="1" textBorder="PAPER" headerInside="0" footerInside="0" fillArea="PAPER">\n'
    '          <hp:offset left="1417" right="1417" top="1417" bottom="1417"/>\n'
    '        </hp:pageBorderFill>\n'
    '      </hp:secPr>\n'
    '      <hp:ctrl>\n'
    '        <hp:colPr id="" type="NEWSPAPER" layout="LEFT" colCount="1" sameSz="1" sameGap="0"/>\n'
    '      </hp:ctrl>\n'
    '    </hp:run>\n'
    '    <hp:run charPrIDRef="0"><hp:t/></hp:run>\n'
    '  </hp:p>\n'
)
SEC_CLOSE = "</hs:sec>\n"

# --- 템플릿별 스타일 프로파일 ---
# 각 값은 (charPrIDRef, paraPrIDRef). 표는 별도 키.
PROFILES = {
    "report": {
        "title": (7, 20), "h": {2: (13, 27), 3: (8, 0), 4: (9, 0)},
        "body": (0, 0), "bold": 9,
        "ul": {0: (24, "ㅇ"), 1: (25, "-"), 2: (26, "·")},
        "ol": {0: 24, 1: 25, 2: 26},
        "quote": (11, 24), "code": (1, 0),
        "tbl": {"hdr_c": 9, "hdr_bf": 4, "cell_c": 0, "cell_bf": 3, "hdr_p": 21, "cell_p": 22},
    },
    "govplan": {
        "title": (16, 20), "h": {2: (12, 27), 3: (22, 31), 4: (13, 0)},
        "body": (0, 0), "bold": 9,
        "ul": {0: (32, "ㅇ"), 1: (33, "-"), 2: (34, "·")},
        "ol": {0: 35, 1: 35, 2: 35},
        "quote": (11, 34), "code": (1, 0),
        "tbl": {"hdr_c": 9, "hdr_bf": 4, "cell_c": 0, "cell_bf": 3, "hdr_p": 21, "cell_p": 22},
    },
    "gonmun": {
        "title": (7, 20), "h": {2: (8, 0), 3: (10, 0), 4: (10, 0)},
        "body": (0, 0), "bold": 10,
        "ul": {0: (0, "ㅇ"), 1: (0, "-"), 2: (0, "·")},
        "ol": {0: 0, 1: 0, 2: 0},
        "quote": (9, 0), "code": (1, 0),
        "tbl": {"hdr_c": 10, "hdr_bf": 4, "cell_c": 0, "cell_bf": 3, "hdr_p": 21, "cell_p": 22},
    },
}
PROFILES["minutes"] = PROFILES["report"]
PROFILES["proposal"] = PROFILES["report"]


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_CODE = re.compile(r"`([^`]+)`")
_IMG = re.compile(r"!\[([^\]]*)\]\([^)]*\)")


def parse_inline(text: str):
    """인라인 마크다운 → [(text, is_bold), ...] 런 목록."""
    text = _IMG.sub(lambda m: m.group(1) or "[이미지]", text)
    text = _LINK.sub(lambda m: m.group(1), text)   # 링크는 표시 텍스트만
    text = _CODE.sub(lambda m: m.group(1), text)   # 인라인 코드는 텍스트만
    runs = []
    pos = 0
    for m in _BOLD.finditer(text):
        if m.start() > pos:
            runs.append((text[pos:m.start()], False))
        runs.append((m.group(1) or m.group(2), True))
        pos = m.end()
    if pos < len(text):
        runs.append((text[pos:], False))
    return [(t, b) for t, b in runs if t]


class Builder:
    def __init__(self, profile):
        self.p = profile
        self.parts = []
        self.pid = 1000000001
        self.tid = 1000000500

    def _nid(self):
        self.pid += 1
        return self.pid

    def _ntid(self):
        self.tid += 1
        return self.tid

    def para(self, runs, para_id, prefix=None, prefix_char=None):
        """runs: [(text,bold)]; prefix: 앞에 붙일 기호 텍스트."""
        pid = self._nid()
        body_c = self.p["body"][0]
        buf = [f'  <hp:p id="{pid}" paraPrIDRef="{para_id}" styleIDRef="0" '
               f'pageBreak="0" columnBreak="0" merged="0">']
        if prefix:
            pc = prefix_char if prefix_char is not None else body_c
            buf.append(f'    <hp:run charPrIDRef="{pc}"><hp:t>{esc(prefix)}</hp:t></hp:run>')
        if not runs:
            buf.append(f'    <hp:run charPrIDRef="{body_c}"><hp:t/></hp:run>')
        for t, bold in runs:
            c = self.p["bold"] if bold else body_c
            buf.append(f'    <hp:run charPrIDRef="{c}"><hp:t>{esc(t)}</hp:t></hp:run>')
        buf.append('  </hp:p>')
        self.parts.append("\n".join(buf))

    def blank(self):
        self.para([], 0)

    def heading(self, level, text):
        if level == 1:
            c, para = self.p["title"]
        else:
            c, para = self.p["h"].get(min(level, 4), self.p["h"][4])
        pid = self._nid()
        self.parts.append(
            f'  <hp:p id="{pid}" paraPrIDRef="{para}" styleIDRef="0" pageBreak="0" '
            f'columnBreak="0" merged="0">\n'
            f'    <hp:run charPrIDRef="{c}"><hp:t>{esc(text)}</hp:t></hp:run>\n'
            f'  </hp:p>'
        )

    def list_item(self, ordered, depth, number, text):
        depth = min(depth, 2)
        runs = parse_inline(text)
        if ordered:
            para = self.p["ol"].get(depth, self.p["ol"][max(self.p["ol"])])
            self.para(runs, para, prefix=f"{number}. ")
        else:
            para, bullet = self.p["ul"].get(depth, self.p["ul"][max(self.p["ul"])])
            self.para(runs, para, prefix=f"{bullet} ")

    def quote(self, text):
        c, para = self.p["quote"]
        runs = parse_inline(text)
        pid = self._nid()
        buf = [f'  <hp:p id="{pid}" paraPrIDRef="{para}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">']
        for t, _ in (runs or [("", False)]):
            buf.append(f'    <hp:run charPrIDRef="{c}"><hp:t>{esc(t)}</hp:t></hp:run>')
        buf.append('  </hp:p>')
        self.parts.append("\n".join(buf))

    def code_block(self, lines):
        c, para = self.p["code"]
        for ln in lines:
            pid = self._nid()
            self.parts.append(
                f'  <hp:p id="{pid}" paraPrIDRef="{para}" styleIDRef="0" pageBreak="0" '
                f'columnBreak="0" merged="0">\n'
                f'    <hp:run charPrIDRef="{c}"><hp:t>{esc(ln) or ""}</hp:t></hp:run>\n'
                f'  </hp:p>'
            )

    def table(self, header, rows):
        t = self.p["tbl"]
        ncol = len(header)
        widths = [BODY_WIDTH // ncol] * ncol
        widths[-1] = BODY_WIDTH - sum(widths[:-1])
        nrow = 1 + len(rows)
        rowh = 2800
        tbl_id = self._ntid()
        pid = self._nid()
        out = [f'  <hp:p id="{pid}" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">',
               '    <hp:run charPrIDRef="0">',
               f'      <hp:tbl id="{tbl_id}" zOrder="0" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" '
               f'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" pageBreak="CELL" repeatHeader="1" '
               f'rowCnt="{nrow}" colCnt="{ncol}" cellSpacing="0" borderFillIDRef="{t["cell_bf"]}" noAdjust="0">',
               f'        <hp:sz width="{BODY_WIDTH}" widthRelTo="ABSOLUTE" height="{rowh*nrow}" heightRelTo="ABSOLUTE" protect="0"/>',
               '        <hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>',
               '        <hp:outMargin left="0" right="0" top="0" bottom="0"/>',
               '        <hp:inMargin left="0" right="0" top="0" bottom="0"/>']

        def cell(text, r, cidx, header_cell):
            cc = t["hdr_c"] if header_cell else t["cell_c"]
            cbf = t["hdr_bf"] if header_cell else t["cell_bf"]
            cp = t["hdr_p"] if header_cell else t["cell_p"]
            cpid = self._nid()
            runs = parse_inline(text)
            rbuf = "".join(
                f'<hp:run charPrIDRef="{(self.p["bold"] if b else cc)}"><hp:t>{esc(tx)}</hp:t></hp:run>'
                for tx, b in (runs or [("", False)])
            )
            return (
                f'          <hp:tc name="" header="{1 if header_cell else 0}" hasMargin="1" protect="0" editable="0" dirty="0" borderFillIDRef="{cbf}">\n'
                f'            <hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">\n'
                f'              <hp:p paraPrIDRef="{cp}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0" id="{cpid}">{rbuf}</hp:p>\n'
                f'            </hp:subList>\n'
                f'            <hp:cellAddr colAddr="{cidx}" rowAddr="{r}"/>\n'
                f'            <hp:cellSpan colSpan="1" rowSpan="1"/>\n'
                f'            <hp:cellSz width="{widths[cidx]}" height="{rowh}"/>\n'
                f'            <hp:cellMargin left="283" right="283" top="141" bottom="141"/>\n'
                f'          </hp:tc>'
            )

        out.append('        <hp:tr>')
        for ci, h in enumerate(header):
            out.append(cell(h, 0, ci, True))
        out.append('        </hp:tr>')
        for ri, row in enumerate(rows, start=1):
            out.append('        <hp:tr>')
            for ci in range(ncol):
                out.append(cell(row[ci] if ci < len(row) else "", ri, ci, False))
            out.append('        </hp:tr>')
        out += ['      </hp:tbl>', '    </hp:run>', '  </hp:p>']
        self.parts.append("\n".join(out))

    def xml(self):
        return SEC_OPEN + "\n".join(self.parts) + "\n" + SEC_CLOSE


def split_table_row(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def convert(md_text: str, profile) -> str:
    b = Builder(profile)
    lines = md_text.replace("\r\n", "\n").split("\n")
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()

        # 코드펜스
        if stripped.startswith("```"):
            j = i + 1
            code = []
            while j < n and not lines[j].strip().startswith("```"):
                code.append(lines[j]); j += 1
            b.code_block(code)
            i = j + 1
            continue

        # 빈 줄 / 수평선
        if not stripped or re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", stripped):
            b.blank(); i += 1; continue

        # 제목
        m = re.match(r"(#{1,6})\s+(.*)$", stripped)
        if m:
            b.heading(len(m.group(1)), m.group(2).strip()); i += 1; continue

        # 표 (현재 줄이 |, 다음 줄이 구분자)
        if stripped.startswith("|") and i + 1 < n and re.search(r"\|?\s*:?-{2,}", lines[i + 1]):
            header = split_table_row(lines[i])
            rows = []
            j = i + 2
            while j < n and lines[j].strip().startswith("|"):
                rows.append(split_table_row(lines[j])); j += 1
            b.table(header, rows)
            i = j; continue

        # 인용
        if stripped.startswith(">"):
            b.quote(re.sub(r"^>\s?", "", stripped)); i += 1; continue

        # 목록 (들여쓰기 depth = leading spaces // 2)
        lm = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)$", line)
        if lm:
            depth = len(lm.group(1)) // 2
            marker = lm.group(2)
            ordered = bool(re.match(r"\d+\.", marker))
            num = marker[:-1] if ordered else None
            b.list_item(ordered, depth, num, lm.group(3).strip())
            i += 1; continue

        # 일반 문단
        b.para(parse_inline(stripped), 0)
        i += 1

    return b.xml()


def main():
    ap = argparse.ArgumentParser(description="Markdown → HWPX 변환")
    ap.add_argument("input", type=Path, help="입력 .md 파일")
    ap.add_argument("--template", "-t", default="report",
                    help="템플릿 스타일 (report/govplan/gonmun/minutes/proposal, 기본 report)")
    ap.add_argument("--title", help="문서 제목(메타)")
    ap.add_argument("--creator", help="작성자(메타)")
    ap.add_argument("--output", "-o", type=Path, required=True, help="출력 .hwpx")
    args = ap.parse_args()

    if not args.input.is_file():
        raise SystemExit(f"입력 파일 없음: {args.input}")
    profile = PROFILES.get(args.template)
    if profile is None:
        print(f"경고: '{args.template}' 프로파일 없음 → report 사용", file=sys.stderr)
        profile = PROFILES["report"]

    md = args.input.read_text(encoding="utf-8")
    section_xml = convert(md, profile)

    # 첫 # 제목을 메타 제목 기본값으로
    title = args.title
    if not title:
        m = re.search(r"^#\s+(.*)$", md, re.M)
        if m:
            title = m.group(1).strip()

    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-8") as tf:
        tf.write(section_xml)
        sec_path = Path(tf.name)
    try:
        build_hwpx.build(
            template=args.template if args.template in build_hwpx.AVAILABLE_TEMPLATES else "report",
            header_override=None,
            section_override=sec_path,
            title=title,
            creator=args.creator,
            output=args.output,
        )
    finally:
        sec_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
