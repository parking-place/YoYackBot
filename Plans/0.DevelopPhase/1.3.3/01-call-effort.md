# 1.3.3-P1 — 호출별 추론 강도·호출 계측

- 상태: **PUSH_PENDING** · 검사: `T133-P1-A/B` **PASS** ([증거](../evidence/1.3.3-P1.md)) · 환경: 개발 LXC, 합성 대역(모델 호출 없음)

## 작업

[계약](CONTRACT.md) 1절대로 엔진이 호출 이름별로 추론 강도를 정한다. `judge`·`idiom_select`는 `low`, 나머지는 설정값이며 설정값보다 높이지 않는다. 실행기는 그 요청 호출의 강도를 Codex 인자에 넣는다(빠른 등급과 같은 요청 단위 전달). `request_timing`의 호출 항목에 `effort`·`execs`·`tokens`를 더하고 `scripts/show_timings.py`·문서를 맞춘다.

## 검증·완료 기준

- `T133-P1-A`: 설정 `medium`에서 요약 5회 경로·사자성어 3회 경로의 호출별 `model_reasoning_effort` 인자가 계약대로다(`judge`·`idiom_select`만 `low`). 설정 `low`에서는 모두 `low`다. 빠른 등급 인자와 함께 써도 서로 섞이지 않고, 동시 요청끼리도 섞이지 않는다.
- `T133-P1-B`: `execs`·`tokens`를 CLI 진단 출력에서 숫자로만 읽고(되찍힌 프롬프트 안의 같은 모양 줄은 세지 않음) 실패·시간 초과 때는 비운다. 허용 목록·내용 없음, 표 스크립트 갱신, 기존 지표 불변, 전체 회귀 통과.

[버전 개요](README.md) · [다음 P2](02-idiom-inline.md)
