#!/usr/bin/env python3
"""hwpx-plan — 정부 업무추진계획(본문형) 한글문서 작성기 (self-contained).

기존 hwpx 스킬의 templates/ (base·gonmun·report·govplan 오버레이)에 **의존하지 않는다.**
HWPX 패키지 전체(mimetype, META-INF, version, settings, content.hpf, header.xml,
section0.xml, Preview)를 이 스크립트가 직접 생성한다.

스타일(계층/글씨크기/문단간격)은 정부 기구설치·업무추진계획 문서에서 도출:
  - 본문 14pt 휴먼명조, 줄간격 160%, 양쪽정렬+내어쓰기(줄바꿈 줄은 본문 위치 시작)
  - □ 대항목 HY헤드라인M 15pt, ㅇ/- 휴먼명조 14pt (내어쓰기)
  - 문단 간격: □→ㅇ 5pt, ㅇ→- 3pt (빈 줄이 아닌 문단 위 간격으로 구현)

입력: 아래 마커로 시작하는 아웃라인 텍스트(.txt/.md)
  # 제목            → 문서 제목
  □ …              → 대항목
  ㅇ … / ○ …       → 중항목  ( (목적)/(근거) 라벨 그대로 사용 가능 )
  - …              → 세부
  ①…⑳ / 1) / 가.  → 열거
  * … / ※ …        → 각주(작은 글씨)
  | a | b |         → 표 (GFM, 다음 줄 |---| 구분자)
  (빈 줄)           → 빈 문단
  **굵게**          → 인라인 볼드

사용법:
  python3 plan_writer.py outline.txt -o result.hwpx
  python3 plan_writer.py outline.txt --title "제목" --creator "작성자" -o result.hwpx
"""

import argparse
import re
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

# ======================================================================
# STYLE SPEC (참조 문서에서 도출)
# ======================================================================
BODY_WIDTH = 48190          # A4 본문폭 (59528 - 5669*2, 좌우 20mm)
LINE = 160                  # 기본 줄간격 %
COLOR_DAEHANG = "#000000"   # □ 대항목 색 (참조 스펙: 검정 HY헤드라인M, 조정 가능)
COLOR_LABEL = "#1F4E79"     # (라벨) 강조색 (선택)

# 문단 간격(pt→HWPUNIT, 1pt=100). 참조 스펙: □→ㅇ 5pt, ㅇ→- 3pt.
GAP_O = 500                 # ㅇ 중항목 위 간격 = 5pt (□ 다음)
GAP_DASH = 300              # - 세부 위 간격 = 3pt (ㅇ 다음)

# fontRef id: 0=함초롬돋움, 1=함초롬바탕, 2=휴먼명조, 3=HY헤드라인M
FONTS = ["함초롬돋움", "함초롬바탕", "휴먼명조", "HY헤드라인M"]

# charPr: id -> (pt*100, fontRef, bold, color)   ※ 참조 스펙 반영
CHARPR = {
    0: (1400, 2, False, "#000000"),   # 본문 휴먼명조 14pt
    1: (1600, 0, True,  "#000000"),   # 제목 16pt 볼드 함초롬돋움
    2: (1500, 3, False, COLOR_DAEHANG),  # □ 대항목 HY헤드라인M 15pt
    3: (1400, 2, False, "#000000"),   # ㅇ 중항목 휴먼명조 14pt
    4: (1400, 2, False, "#000000"),   # - 세부 휴먼명조 14pt
    5: (1200, 2, False, "#595959"),   # * 각주 휴먼명조 12pt 회색
    6: (1400, 2, False, "#000000"),   # ① 열거 휴먼명조 14pt
    7: (1400, 0, True,  "#000000"),   # 표 헤더 14pt 볼드 고딕
    8: (1400, 2, True,  "#000000"),   # 인라인 볼드 휴먼명조 14pt
    9: (500,  3, False, "#000000"),   # 빈 문단 간격용 5pt (□ 뒤)
    10:(300,  2, False, "#000000"),   # 빈 문단 간격용 3pt (ㅇ/- 뒤)
}
# 계층 항목 뒤에 넣는 작은 글씨 빈 문단(검토본 방식). 값=간격용 charPr id.
SPACER_AFTER = {2: 9, 3: 10, 4: 10, 6: 10}   # □→5pt, ㅇ/-/①→3pt

# paraPr: id -> dict(align, left, intent, prev, next)   [case/HwpUnitChar 값]
#   왼쪽정렬 + 내어쓰기(hanging): 첫 줄은 기호가 왼쪽으로 나오고, 줄바꿈된 줄은
#   본문 텍스트 위치(left)에 맞춰 정렬. left=줄바꿈줄 기준, intent(음수)=첫줄 내어쓰기.
#   검토본(reviedplan_v3) 실측값 반영. prev=문단 위 간격(1pt=100).
PARAPR = {
    0:  dict(align="JUSTIFY",   left=0,    intent=0,     prev=0,        nxt=0),  # 본문
    1:  dict(align="CENTER", left=0,    intent=0,     prev=0,        nxt=600),# 제목
    2:  dict(align="JUSTIFY",   left=0,    intent=0,     prev=300,      nxt=0),  # □ 대항목
    3:  dict(align="JUSTIFY",   left=800,  intent=-800,  prev=GAP_O,    nxt=0),  # ㅇ 중항목 (□→ㅇ 5pt) 내어쓰기=좌여백(정형)
    4:  dict(align="JUSTIFY",   left=1400, intent=-1400, prev=GAP_DASH, nxt=0),  # - 세부 (ㅇ→- 3pt)
    5:  dict(align="JUSTIFY",   left=2000, intent=-2000, prev=0,        nxt=0),  # * 각주
    6:  dict(align="JUSTIFY",   left=800,  intent=-800,  prev=GAP_O,    nxt=0),  # ① 열거
    7:  dict(align="CENTER", left=0,    intent=0,     prev=0,        nxt=0),  # 표 헤더셀
    8:  dict(align="JUSTIFY",   left=0,    intent=0,     prev=0,        nxt=0),  # 표 본문셀
}

# ======================================================================
# 패키지 보일러플레이트 (self-contained)
# ======================================================================
MIMETYPE = "application/hwp+zip"

MANIFEST = ("<?xml version='1.0' encoding='UTF-8'?>\n"
            '<odf:manifest xmlns:odf="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>\n')

CONTAINER_XML = (
    "<?xml version='1.0' encoding='UTF-8'?>\n"
    '<ocf:container xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container" '
    'xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf">\n'
    '  <ocf:rootfiles>\n'
    '    <ocf:rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/>\n'
    '    <ocf:rootfile full-path="Preview/PrvText.txt" media-type="text/plain"/>\n'
    '    <ocf:rootfile full-path="META-INF/container.rdf" media-type="application/rdf+xml"/>\n'
    '  </ocf:rootfiles>\n'
    '</ocf:container>\n'
)

CONTAINER_RDF = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?><rdf:RDF '
    'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description rdf:about="">'
    '<ns0:hasPart xmlns:ns0="http://www.hancom.co.kr/hwpml/2016/meta/pkg#" '
    'rdf:resource="Contents/header.xml"/></rdf:Description><rdf:Description '
    'rdf:about="Contents/header.xml"><rdf:type '
    'rdf:resource="http://www.hancom.co.kr/hwpml/2016/meta/pkg#HeaderFile"/></rdf:Description>'
    '<rdf:Description rdf:about=""><ns0:hasPart '
    'xmlns:ns0="http://www.hancom.co.kr/hwpml/2016/meta/pkg#" '
    'rdf:resource="Contents/section0.xml"/></rdf:Description><rdf:Description '
    'rdf:about="Contents/section0.xml"><rdf:type '
    'rdf:resource="http://www.hancom.co.kr/hwpml/2016/meta/pkg#SectionFile"/></rdf:Description>'
    '<rdf:Description rdf:about=""><rdf:type '
    'rdf:resource="http://www.hancom.co.kr/hwpml/2016/meta/pkg#Document"/></rdf:Description></rdf:RDF>'
)

VERSION_XML = (
    "<?xml version='1.0' encoding='UTF-8'?>\n"
    '<hv:HCFVersion xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version" '
    'tagetApplication="WORDPROCESSOR" major="5" minor="1" micro="1" buildNumber="0" '
    'os="1" xmlVersion="1.5" application="Hancom Office Hangul" '
    'appVersion="13, 0, 0, 1408 WIN32LEWindows_10"/>\n'
)

SETTINGS_XML = (
    "<?xml version='1.0' encoding='UTF-8'?>\n"
    '<ha:HWPApplicationSetting xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" '
    'xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0">\n'
    '  <ha:CaretPosition listIDRef="0" paraIDRef="0" pos="0"/>\n'
    '</ha:HWPApplicationSetting>\n'
)

def content_hpf(title: str, creator: str) -> str:
    return (
        "<?xml version='1.0' encoding='UTF-8'?>\n"
        '<opf:package xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" '
        'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
        'xmlns:hp10="http://www.hancom.co.kr/hwpml/2016/paragraph" '
        'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
        'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" '
        'xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" '
        'xmlns:hhs="http://www.hancom.co.kr/hwpml/2011/history" '
        'xmlns:hm="http://www.hancom.co.kr/hwpml/2011/master-page" '
        'xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:opf="http://www.idpf.org/2007/opf/" version="" unique-identifier="" id="">\n'
        '  <opf:metadata>\n'
        f'    <opf:title>{esc(title)}</opf:title>\n'
        '    <opf:language>ko</opf:language>\n'
        f'    <opf:meta name="creator" content="{esc(creator)}"/>\n'
        '  </opf:metadata>\n'
        '  <opf:manifest>\n'
        '    <opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>\n'
        '    <opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>\n'
        '    <opf:item id="settings" href="settings.xml" media-type="application/xml"/>\n'
        '  </opf:manifest>\n'
        '  <opf:spine>\n'
        '    <opf:itemref idref="header" linear="yes"/>\n'
        '    <opf:itemref idref="section0" linear="yes"/>\n'
        '  </opf:spine>\n'
        '</opf:package>\n'
    )

# ======================================================================
# header.xml 생성
# ======================================================================
def _fontfaces() -> str:
    langs = ["HANGUL", "LATIN", "HANJA", "JAPANESE", "OTHER", "SYMBOL", "USER"]
    ti = ('<hh:typeInfo familyType="FCAT_GOTHIC" weight="6" proportion="4" contrast="0" '
          'strokeVariation="1" armStyle="1" letterform="1" midline="1" xHeight="1"/>')
    out = [f'    <hh:fontfaces itemCnt="{len(langs)}">']
    for lang in langs:
        out.append(f'      <hh:fontface lang="{lang}" fontCnt="{len(FONTS)}">')
        for fid, face in enumerate(FONTS):
            out.append(f'        <hh:font id="{fid}" face="{face}" type="TTF" isEmbedded="0">')
            out.append(f'          {ti}')
            out.append('        </hh:font>')
        out.append('      </hh:fontface>')
    out.append('    </hh:fontfaces>')
    return "\n".join(out)


def _borderfills() -> str:
    def bf(i, borders, fill=None):
        s = [f'      <hh:borderFill id="{i}" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0">',
             '        <hh:slash type="NONE" Crooked="0" isCounter="0"/>',
             '        <hh:backSlash type="NONE" Crooked="0" isCounter="0"/>']
        for side in ("left", "right", "top", "bottom"):
            t = borders.get(side, ("NONE", "0.1 mm", "#000000"))
            s.append(f'        <hh:{side}Border type="{t[0]}" width="{t[1]}" color="{t[2]}"/>')
        s.append('        <hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/>')
        if fill:
            s += ['        <hc:fillBrush>',
                  f'          <hc:winBrush faceColor="{fill}" hatchColor="#999999" alpha="0"/>',
                  '        </hc:fillBrush>']
        s.append('      </hh:borderFill>')
        return "\n".join(s)
    solid = ("SOLID", "0.12 mm", "#000000")
    allside = {k: solid for k in ("left", "right", "top", "bottom")}
    return "\n".join([
        '    <hh:borderFills itemCnt="4">',
        bf(1, {}),
        bf(2, {}, fill=None),
        bf(3, allside),
        bf(4, allside, fill="#D6DCE4"),
        '    </hh:borderFills>',
    ])


def _charpr(i, pt, fref, bold, color) -> str:
    b = "\n        <hh:bold/>" if bold else ""
    return (
        f'      <hh:charPr id="{i}" height="{pt}" textColor="{color}" shadeColor="none" '
        f'useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="2">\n'
        f'        <hh:fontRef hangul="{fref}" latin="{fref}" hanja="{fref}" japanese="{fref}" other="{fref}" symbol="{fref}" user="{fref}"/>\n'
        f'        <hh:ratio hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>\n'
        f'        <hh:spacing hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>\n'
        f'        <hh:relSz hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>\n'
        f'        <hh:offset hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>{b}\n'
        f'        <hh:underline type="NONE" shape="SOLID" color="#000000"/>\n'
        f'        <hh:strikeout shape="NONE" color="#000000"/>\n'
        f'        <hh:outline type="NONE"/>\n'
        f'        <hh:shadow type="NONE" color="#C0C0C0" offsetX="10" offsetY="10"/>\n'
        f'      </hh:charPr>'
    )


def _parapr(i, d) -> str:
    def block(mult):
        return (
            '            <hh:margin>\n'
            f'              <hc:intent value="{d["intent"]*mult}" unit="HWPUNIT"/>\n'
            f'              <hc:left value="{d["left"]*mult}" unit="HWPUNIT"/>\n'
            '              <hc:right value="0" unit="HWPUNIT"/>\n'
            f'              <hc:prev value="{d["prev"]*mult}" unit="HWPUNIT"/>\n'
            f'              <hc:next value="{d["nxt"]*mult}" unit="HWPUNIT"/>\n'
            '            </hh:margin>\n'
            f'            <hh:lineSpacing type="PERCENT" value="{LINE}" unit="HWPUNIT"/>'
        )
    return (
        f'      <hh:paraPr id="{i}" tabPrIDRef="0" condense="0" fontLineHeight="0" '
        f'snapToGrid="1" suppressLineNumbers="0" checked="0" textDir="LTR">\n'
        f'        <hh:align horizontal="{d["align"]}" vertical="BASELINE"/>\n'
        f'        <hh:heading type="NONE" idRef="0" level="0"/>\n'
        f'        <hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="BREAK_WORD" '
        f'widowOrphan="0" keepWithNext="0" keepLines="0" pageBreakBefore="0" lineWrap="BREAK"/>\n'
        f'        <hh:autoSpacing eAsianEng="0" eAsianNum="0"/>\n'
        f'        <hp:switch>\n'
        f'          <hp:case hp:required-namespace="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar">\n'
        f'{block(1)}\n'
        f'          </hp:case>\n'
        f'          <hp:default>\n'
        f'{block(2)}\n'
        f'          </hp:default>\n'
        f'        </hp:switch>\n'
        f'        <hh:border borderFillIDRef="2" offsetLeft="0" offsetRight="0" offsetTop="0" offsetBottom="0" connect="0" ignoreMargin="0"/>\n'
        f'      </hh:paraPr>'
    )


NUMBERING = """    <hh:numberings itemCnt="1">
      <hh:numbering id="1" start="0">
        <hh:paraHead start="1" level="1" align="LEFT" useInstWidth="1" autoIndent="1" widthAdjust="0" textOffsetType="PERCENT" textOffset="50" numFormat="DIGIT" charPrIDRef="4294967295" checkable="0">^1.</hh:paraHead>
        <hh:paraHead start="1" level="2" align="LEFT" useInstWidth="1" autoIndent="1" widthAdjust="0" textOffsetType="PERCENT" textOffset="50" numFormat="HANGUL_SYLLABLE" charPrIDRef="4294967295" checkable="0">^2.</hh:paraHead>
        <hh:paraHead start="1" level="3" align="LEFT" useInstWidth="1" autoIndent="1" widthAdjust="0" textOffsetType="PERCENT" textOffset="50" numFormat="DIGIT" charPrIDRef="4294967295" checkable="0">^3)</hh:paraHead>
        <hh:paraHead start="1" level="4" align="LEFT" useInstWidth="1" autoIndent="1" widthAdjust="0" textOffsetType="PERCENT" textOffset="50" numFormat="HANGUL_SYLLABLE" charPrIDRef="4294967295" checkable="0">^4)</hh:paraHead>
        <hh:paraHead start="1" level="5" align="LEFT" useInstWidth="1" autoIndent="1" widthAdjust="0" textOffsetType="PERCENT" textOffset="50" numFormat="DIGIT" charPrIDRef="4294967295" checkable="0">(^5)</hh:paraHead>
        <hh:paraHead start="1" level="6" align="LEFT" useInstWidth="1" autoIndent="1" widthAdjust="0" textOffsetType="PERCENT" textOffset="50" numFormat="HANGUL_SYLLABLE" charPrIDRef="4294967295" checkable="0">(^6)</hh:paraHead>
        <hh:paraHead start="1" level="7" align="LEFT" useInstWidth="1" autoIndent="1" widthAdjust="0" textOffsetType="PERCENT" textOffset="50" numFormat="CIRCLED_DIGIT" charPrIDRef="4294967295" checkable="1">^7</hh:paraHead>
        <hh:paraHead start="1" level="8" align="LEFT" useInstWidth="1" autoIndent="1" widthAdjust="0" textOffsetType="PERCENT" textOffset="50" numFormat="CIRCLED_HANGUL_SYLLABLE" charPrIDRef="4294967295" checkable="1">^8</hh:paraHead>
        <hh:paraHead start="1" level="9" align="LEFT" useInstWidth="1" autoIndent="1" widthAdjust="0" textOffsetType="PERCENT" textOffset="50" numFormat="HANGUL_JAMO" charPrIDRef="4294967295" checkable="0"/>
        <hh:paraHead start="1" level="10" align="LEFT" useInstWidth="1" autoIndent="1" widthAdjust="0" textOffsetType="PERCENT" textOffset="50" numFormat="ROMAN_SMALL" charPrIDRef="4294967295" checkable="1"/>
      </hh:numbering>
    </hh:numberings>"""

STYLES = """    <hh:styles itemCnt="1">
      <hh:style id="0" type="PARA" name="바탕글" engName="Normal" paraPrIDRef="0" charPrIDRef="0" nextStyleIDRef="0" langID="1042" lockForm="0"/>
    </hh:styles>"""


def build_header() -> str:
    charprs = "\n".join(_charpr(i, *CHARPR[i]) for i in sorted(CHARPR))
    paraprs = "\n".join(_parapr(i, PARAPR[i]) for i in sorted(PARAPR))
    return (
        "<?xml version='1.0' encoding='UTF-8'?>\n"
        '<hh:head xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" '
        'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
        'xmlns:hp10="http://www.hancom.co.kr/hwpml/2016/paragraph" '
        'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
        'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" '
        'xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" '
        'xmlns:hhs="http://www.hancom.co.kr/hwpml/2011/history" '
        'xmlns:hm="http://www.hancom.co.kr/hwpml/2011/master-page" '
        'xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:opf="http://www.idpf.org/2007/opf/" '
        'xmlns:hwpunitchar="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar" '
        'version="1.5" secCnt="1">\n'
        '  <hh:beginNum page="1" footnote="1" endnote="1" pic="1" tbl="1" equation="1"/>\n'
        '  <hh:refList>\n'
        f'{_fontfaces()}\n'
        f'{_borderfills()}\n'
        f'    <hh:charProperties itemCnt="{len(CHARPR)}">\n{charprs}\n    </hh:charProperties>\n'
        '    <hh:tabProperties itemCnt="3">\n'
        '      <hh:tabPr id="0" autoTabLeft="0" autoTabRight="0"/>\n'
        '      <hh:tabPr id="1" autoTabLeft="1" autoTabRight="0"/>\n'
        '      <hh:tabPr id="2" autoTabLeft="0" autoTabRight="1"/>\n'
        '    </hh:tabProperties>\n'
        f'{NUMBERING}\n'
        f'    <hh:paraProperties itemCnt="{len(PARAPR)}">\n{paraprs}\n    </hh:paraProperties>\n'
        f'{STYLES}\n'
        '  </hh:refList>\n'
        '  <hh:compatibleDocument targetProgram="HWP201X">\n'
        '    <hh:layoutCompatibility/>\n'
        '  </hh:compatibleDocument>\n'
        '  <hh:docOption>\n'
        '    <hh:linkinfo path="" pageInherit="0" footnoteInherit="0"/>\n'
        '  </hh:docOption>\n'
        '  <hh:trackchageConfig flags="56"/>\n'
        '</hh:head>\n'
    )


# ======================================================================
# section0.xml 생성
# ======================================================================
SEC_PR = (
    '      <hp:secPr id="" textDirection="HORIZONTAL" spaceColumns="1134" tabStop="8000" '
    'tabStopVal="4000" tabStopUnit="HWPUNIT" outlineShapeIDRef="1" memoShapeIDRef="0" '
    'textVerticalWidthHead="0" masterPageCnt="0">\n'
    '        <hp:grid lineGrid="0" charGrid="0" wonggojiFormat="0"/>\n'
    '        <hp:startNum pageStartsOn="BOTH" page="0" pic="0" tbl="0" equation="0"/>\n'
    '        <hp:visibility hideFirstHeader="0" hideFirstFooter="0" hideFirstMasterPage="0" '
    'border="SHOW_ALL" fill="SHOW_ALL" hideFirstPageNum="0" hideFirstEmptyLine="0" showLineNumber="0"/>\n'
    '        <hp:lineNumberShape restartType="0" countBy="0" distance="0" startNumber="0"/>\n'
    '        <hp:pagePr landscape="WIDELY" width="59528" height="84186" gutterType="LEFT_ONLY">\n'
    '          <hp:margin header="2835" footer="2835" gutter="0" left="5669" right="5669" top="4252" bottom="2835"/>\n'
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
    '        <hp:pageBorderFill type="BOTH" borderFillIDRef="1" textBorder="PAPER" '
    'headerInside="0" footerInside="0" fillArea="PAPER">\n'
    '          <hp:offset left="1417" right="1417" top="1417" bottom="1417"/>\n'
    '        </hp:pageBorderFill>\n'
    '        <hp:pageBorderFill type="EVEN" borderFillIDRef="1" textBorder="PAPER" '
    'headerInside="0" footerInside="0" fillArea="PAPER">\n'
    '          <hp:offset left="1417" right="1417" top="1417" bottom="1417"/>\n'
    '        </hp:pageBorderFill>\n'
    '        <hp:pageBorderFill type="ODD" borderFillIDRef="1" textBorder="PAPER" '
    'headerInside="0" footerInside="0" fillArea="PAPER">\n'
    '          <hp:offset left="1417" right="1417" top="1417" bottom="1417"/>\n'
    '        </hp:pageBorderFill>\n'
    '      </hp:secPr>'
)

_BOLD = re.compile(r"\*\*(.+?)\*\*")


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def inline_runs(text, base_char):
    """**굵게** → charPr8 런 분리."""
    runs, pos = [], 0
    for m in _BOLD.finditer(text):
        if m.start() > pos:
            runs.append((text[pos:m.start()], base_char))
        runs.append((m.group(1), 8))
        pos = m.end()
    if pos < len(text):
        runs.append((text[pos:], base_char))
    return [(t, c) for t, c in runs if t] or [("", base_char)]


class Section:
    def __init__(self):
        self.parts = []
        self.pid = 1000000000
        self.tid = 1000000500

    def nid(self):
        self.pid += 1
        return self.pid

    def _para(self, para_id, char_id, text, first=False):
        pid = self.nid()
        head = SEC_PR + '\n      <hp:ctrl><hp:colPr id="" type="NEWSPAPER" layout="LEFT" colCount="1" sameSz="1" sameGap="0"/></hp:ctrl>\n' if first else ""
        runs = inline_runs(text, char_id) if text else [("", char_id)]
        rbuf = []
        if first:
            rbuf.append(f'    <hp:run charPrIDRef="{char_id}">\n{head}    </hp:run>')
        for t, c in runs:
            rbuf.append(f'    <hp:run charPrIDRef="{c}"><hp:t>{esc(t)}</hp:t></hp:run>')
        self.parts.append(
            f'  <hp:p id="{pid}" paraPrIDRef="{para_id}" styleIDRef="0" pageBreak="0" '
            f'columnBreak="0" merged="0">\n' + "\n".join(rbuf) + '\n  </hp:p>'
        )

    def para(self, para_id, char_id, text):
        self._para(para_id, char_id, text)

    def first_para(self, para_id, char_id, text):
        self._para(para_id, char_id, text, first=True)

    def table(self, header, rows):
        ncol = len(header)
        widths = [BODY_WIDTH // ncol] * ncol
        widths[-1] = BODY_WIDTH - sum(widths[:-1])
        rowh, nrow = 2600, 1 + len(rows)
        self.tid += 1
        pid = self.nid()
        out = [f'  <hp:p id="{pid}" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">',
               '    <hp:run charPrIDRef="0">',
               f'      <hp:tbl id="{self.tid}" zOrder="0" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" '
               f'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" pageBreak="CELL" repeatHeader="1" '
               f'rowCnt="{nrow}" colCnt="{ncol}" cellSpacing="0" borderFillIDRef="3" noAdjust="0">',
               f'        <hp:sz width="{BODY_WIDTH}" widthRelTo="ABSOLUTE" height="{rowh*nrow}" heightRelTo="ABSOLUTE" protect="0"/>',
               '        <hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>',
               '        <hp:outMargin left="0" right="0" top="0" bottom="0"/>',
               '        <hp:inMargin left="0" right="0" top="0" bottom="0"/>']

        def cell(text, r, c, hdr):
            cc, cbf, cp = (7, 4, 7) if hdr else (0, 3, 8)
            cpid = self.nid()
            rbuf = "".join(f'<hp:run charPrIDRef="{cx}"><hp:t>{esc(tx)}</hp:t></hp:run>'
                           for tx, cx in inline_runs(text, cc))
            return (
                f'          <hp:tc name="" header="{1 if hdr else 0}" hasMargin="1" protect="0" editable="0" dirty="0" borderFillIDRef="{cbf}">\n'
                f'            <hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">\n'
                f'              <hp:p paraPrIDRef="{cp}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0" id="{cpid}">{rbuf}</hp:p>\n'
                f'            </hp:subList>\n'
                f'            <hp:cellAddr colAddr="{c}" rowAddr="{r}"/>\n'
                f'            <hp:cellSpan colSpan="1" rowSpan="1"/>\n'
                f'            <hp:cellSz width="{widths[c]}" height="{rowh}"/>\n'
                f'            <hp:cellMargin left="283" right="283" top="141" bottom="141"/>\n'
                f'          </hp:tc>'
            )
        out.append('        <hp:tr>')
        for c, h in enumerate(header):
            out.append(cell(h, 0, c, True))
        out.append('        </hp:tr>')
        for r, row in enumerate(rows, 1):
            out.append('        <hp:tr>')
            for c in range(ncol):
                out.append(cell(row[c] if c < len(row) else "", r, c, False))
            out.append('        </hp:tr>')
        out += ['      </hp:tbl>', '    </hp:run>', '  </hp:p>']
        self.parts.append("\n".join(out))

    def xml(self):
        return (
            "<?xml version='1.0' encoding='UTF-8'?>\n"
            '<hs:sec xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
            'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section">\n'
            + "\n".join(self.parts) + "\n</hs:sec>\n"
        )


# 마커 → (paraPr, charPr)
_ENUM = re.compile(r"^([①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]|\(?\d+\)|\d+\.|[가나다라마바사아자차카타파하]\.)\s")


def split_row(line):
    line = line.strip().strip("|")
    return [c.strip() for c in line.split("|")]


def parse(md: str, sec: Section):
    lines = md.replace("\r\n", "\n").split("\n")
    i, n = 0, len(lines)
    first_done = False

    def emit(pp, cc, text):
        nonlocal first_done
        if not first_done:
            sec.first_para(pp, cc, text)
            first_done = True
        else:
            sec.para(pp, cc, text)
        # 계층 항목 뒤 작은 글씨 빈 문단(5pt/3pt 간격) — 검토본 방식
        if pp in SPACER_AFTER:
            sec.para(pp, SPACER_AFTER[pp], "")

    while i < n:
        raw = lines[i]
        s = raw.strip()
        # 표
        if s.startswith("|") and i + 1 < n and re.search(r"\|?\s*:?-{2,}", lines[i + 1]):
            header = split_row(lines[i]); rows = []
            j = i + 2
            while j < n and lines[j].strip().startswith("|"):
                rows.append(split_row(lines[j])); j += 1
            if not first_done:                 # 표가 최상단이면 빈 첫 문단 먼저
                sec.first_para(0, 0, ""); first_done = True
            sec.table(header, rows); i = j; continue
        if not s:
            emit(0, 0, ""); i += 1; continue
        m = re.match(r"#+\s+(.*)$", s)
        if m:
            emit(1, 1, m.group(1).strip()); i += 1; continue
        if s[0] == "□":
            emit(2, 2, s); i += 1; continue
        if s[0] in "ㅇ○":
            emit(3, 3, s); i += 1; continue
        if s[0] == "-":
            emit(4, 4, s); i += 1; continue
        if s[0] in "*※":
            emit(5, 5, s); i += 1; continue
        if _ENUM.match(s):
            emit(6, 6, s); i += 1; continue
        emit(0, 0, s); i += 1
    if not first_done:
        sec.first_para(0, 0, "")


# ======================================================================
# 패키징
# ======================================================================
def pack(path: Path, header: str, section: str, hpf: str, prvtext: str):
    with ZipFile(path, "w") as z:
        z.writestr("mimetype", MIMETYPE, compress_type=ZIP_STORED)
        z.writestr("version.xml", VERSION_XML, compress_type=ZIP_DEFLATED)
        z.writestr("settings.xml", SETTINGS_XML, compress_type=ZIP_DEFLATED)
        z.writestr("META-INF/manifest.xml", MANIFEST, compress_type=ZIP_DEFLATED)
        z.writestr("META-INF/container.xml", CONTAINER_XML, compress_type=ZIP_DEFLATED)
        z.writestr("META-INF/container.rdf", CONTAINER_RDF, compress_type=ZIP_DEFLATED)
        z.writestr("Contents/content.hpf", hpf, compress_type=ZIP_DEFLATED)
        z.writestr("Contents/header.xml", header, compress_type=ZIP_DEFLATED)
        z.writestr("Contents/section0.xml", section, compress_type=ZIP_DEFLATED)
        z.writestr("Preview/PrvText.txt", prvtext, compress_type=ZIP_DEFLATED)


def main():
    ap = argparse.ArgumentParser(description="정부 업무추진계획(본문형) → HWPX (self-contained)")
    ap.add_argument("input", type=Path, help="아웃라인 텍스트(.txt/.md)")
    ap.add_argument("--title", help="문서 제목(메타). 미지정 시 첫 # 제목")
    ap.add_argument("--creator", default="", help="작성자(메타)")
    ap.add_argument("--output", "-o", type=Path, required=True, help="출력 .hwpx")
    args = ap.parse_args()
    if not args.input.is_file():
        raise SystemExit(f"입력 없음: {args.input}")

    md = args.input.read_text(encoding="utf-8")
    sec = Section()
    parse(md, sec)
    section_xml = sec.xml()
    header_xml = build_header()

    title = args.title
    if not title:
        mm = re.search(r"^#+\s+(.*)$", md, re.M)
        title = mm.group(1).strip() if mm else args.input.stem
    prvtext = re.sub(r"[#*|>-]", "", md)

    pack(args.output, header_xml, section_xml, content_hpf(title, args.creator), prvtext)
    print(f"WROTE: {args.output}")


if __name__ == "__main__":
    main()
