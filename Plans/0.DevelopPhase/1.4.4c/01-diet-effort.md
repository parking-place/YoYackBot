# 1.4.4c-P1 — 식단 호출 강도 고정

- 상태: **PLANNED** · 검사: `T144c-P1-A/B` · 환경: 개발 LXC, 합성 대역, 실제 모델(합성 자료)

## 작업

[계약](CONTRACT.md)대로 식단 평가·주간 훈수 호출의 추론 강도를 `medium`으로 고정한다.

## 검증·완료 기준

- `T144c-P1-A`: 서비스 설정이 low든 medium이든 식단 두 호출(Luna 대체 포함)은 medium이고, 평가 고르기·`!!말하자면` 고르기는 low, 안내 문구는 high, 나머지는 설정값이다. 전체 회귀.
- `T144c-P1-B`: 서비스 설정을 low로 둔 실제 실행에서 CLI 인자가 `--model gpt-6.1-terra`·`model_reasoning_effort=medium`이고 일간 정산·주간 훈수가 통과한다.

[버전 개요](README.md) · [다음 P2](02-release.md)
