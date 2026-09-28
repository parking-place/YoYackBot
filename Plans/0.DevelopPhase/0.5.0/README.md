# 0.5.0 — Codex CLI 안전 연동

- 상태: **PLANNED**
- 단계 수: **5단계**

## 목표

요청 전용 파일을 읽어 최종 요약을 반환하고 오류·timeout·잔여 데이터를 정리한다.

## 진입 조건

이전 버전 [0.4.0](../0.4.0/README.md)의 마지막 단계와 원격 업로드 확인을 완료한다.

## 단계

| 순서 | 단계 | 검증 ID | 상태 |
|---|---|---|---|
| 1 | [0.5.0-P1 — CLI·인증·GPT-6 Luna Light 확인](01-cli-model-contract.md) | `T050-P1-A/B` | DONE |
| 2 | [0.5.0-P2 — 요청 입력 파일·표시명 정규화](02-input-files.md) | `T050-P2-A/B` | DONE |
| 3 | [0.5.0-P3 — 비대화형 subprocess·파일/도구 격리](03-subprocess-isolation.md) | `T050-P3-A/B` | DONE |
| 4 | [0.5.0-P4 — 시간·입력 제한·취소·잔여 파일 정리](04-timeouts-cleanup.md) | `T050-P4-A/B` | DONE |
| 5 | [0.5.0-P5 — 실제 모델 연동·실패 회귀 게이트](05-engine-acceptance.md) | `T050-P5-A/B` | PLANNED |

## 버전 완료 조건

- 5단계의 고유 검증과 영향 범위 회귀 검사가 통과했다.
- 각 단계마다 commit → GitHub push → 원격 반영 확인이 완료되었고 STATUS에 증거가 있다.
- 버전 마지막 단계에서 기본 브랜치 통합 결과와 검증 대상 SHA 대응을 기록했다.
- 필수 항목의 FAIL/NOT_RUN 또는 선행 조건 누락을 완료로 계산하지 않는다.

[공통 Git 완료 규칙](../GIT_WORKFLOW.md) · [진행 상태](../STATUS.md) · [전체 로드맵](../README.md)
