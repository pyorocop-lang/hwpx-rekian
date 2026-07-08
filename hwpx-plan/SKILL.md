---
name: hwpx-plan
description: "정부 업무추진계획·기구설치계획 등 본문형 한글(HWPX) 문서를 아웃라인 텍스트로 작성. 계층(□/ㅇ/-/①)·글씨크기·문단간격이 참조 문서에서 도출된 self-contained 생성기. templates/ 오버레이에 의존하지 않음."
---

# hwpx-plan — 본문형 정부문서 작성 스킬 (self-contained)

정부 업무추진계획·기구 설치/운영계획처럼 **표지 없이 개요 계층(□/ㅇ/-/①)으로 이어지는
본문형 문서**를 아웃라인 텍스트 한 장으로 작성한다.

## 기존 hwpx 스킬과의 관계 — 의존성 절연

이 스킬은 `hwpx/templates/`(base·gonmun·report·minutes·proposal·govplan) **오버레이에
전혀 의존하지 않는다.** `plan_writer.py` 한 파일이 HWPX 패키지 전체를 직접 생성한다:

- 패키지 보일러플레이트(mimetype, META-INF/*, version.xml, settings.xml, content.hpf, Preview)
  → 스크립트 내 문자열 상수
- `header.xml`(스타일 정의) → `STYLE_SPEC`(charPr/paraPr 딕셔너리)에서 코드로 생성
- `section0.xml`(본문) → 아웃라인 파서가 생성

즉 `templates/`를 지우거나 옮겨도 이 스킬은 그대로 동작한다.

## 스타일 근거 — 참조 문서에서 도출

정부 기구설치·업무추진계획 원본(.hwp)의 CharShape/ParaShape를 분석해 아래 값을 채택:

| 요소 | 글씨 | 문단 |
|------|------|------|
| 제목 (`#`) | 16pt 볼드 함초롬돋움 | 가운데, 아래 여백 |
| □ 대항목 | 15pt 볼드 함초롬돋움, 색상(#C00000) | 내어쓰기, 위 여백 300 |
| ㅇ 중항목 | 15pt 함초롬바탕 | 좌여백 1400, 내어쓰기 -600 |
| - 세부 | 15pt 함초롬바탕 | 좌여백 2000, 내어쓰기 -600 |
| ①②③ 열거 | 15pt 함초롬바탕 | 좌여백 1400, 내어쓰기 -700 |
| * / ※ 각주 | 12pt 함초롬바탕 회색 | 좌여백 2600, 내어쓰기 -600 |
| 본문 기본 | 15pt 함초롬바탕 | JUSTIFY |

- **줄간격 160%**, A4·편집용지 여백 위15/아래10/좌우20/머리꼬리10mm (본문폭 48190)
- 하위 계층은 모두 **내어쓰기(hanging indent)** → 줄바꿈 시 둘째 줄이 기호 뒤에 정렬
- 색상 □·글씨크기·여백은 `plan_writer.py` 상단 `STYLE_SPEC`(CHARPR/PARAPR)에서 조정

## 입력 형식 (아웃라인 텍스트)

```
# 문서 제목
□ 대항목
ㅇ 중항목  ( (목적)/(근거) 등 라벨 그대로 사용 )
- 세부 설명
① 열거 항목   (①…⑳ / 1) / 가. / (1) 모두 인식)
* 각주 / 부연   (※ 도 동일)
| 헤더1 | 헤더2 |   ← GFM 표 (다음 줄 |---|---| 구분자)
| a | b |
**굵게**            ← 인라인 볼드
(빈 줄)             ← 빈 문단
```

## 사용법

```bash
python3 hwpx-plan/plan_writer.py outline.txt -o result.hwpx
python3 hwpx-plan/plan_writer.py outline.txt --title "제목" --creator "부서명" -o result.hwpx
```

의존성: Python 3 표준 라이브러리만 사용(lxml 불필요). 검증은 기존
`hwpx/scripts/validate.py`로 교차 확인 가능.

## 예시

`hwpx-plan/example.txt`는 「(자율기구) 계약분쟁조정과 설치 및 운영계획」을 재현한 샘플이다.

```bash
python3 hwpx-plan/plan_writer.py hwpx-plan/example.txt -o plan.hwpx
```

## 확장 포인트

- **새 계층/스타일**: `CHARPR`/`PARAPR`에 항목 추가 후 파서 `parse()`의 마커 분기에 연결.
- **색상 테마**: `COLOR_DAEHANG`(□ 색) 등 상단 상수만 바꾸면 전체 반영.
- **다른 문서군**: 표지형·성과지표형이 필요하면 STYLE_SPEC을 확장하거나, 시각 요소가 많은
  경우 기존 `hwpx` 스킬(templates/govplan)을 사용.
