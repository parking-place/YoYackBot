# 0.4.0 — Discord History와 캐시 보충

- 상태: **PLANNED**
- 단계 수: **5단계**

## 목표

시간·개수 요청의 누락분만 조회하고 7일 밖 요청과 캐시 장애도 명시한 정책대로 처리한다.

## 진입 조건

이전 버전 [0.3.0](../0.3.0/README.md)의 마지막 단계와 원격 업로드 확인을 완료한다.

## 단계

| 순서 | 단계 | 검증 ID | 상태 |
|---|---|---|---|
| 1 | [0.4.0-P1 — History 페이지 조회·현재 채널 제한](01-history-pages.md) | `T040-P1-A/B` | IN_PROGRESS |
| 2 | [0.4.0-P2 — 시간 범위 차집합 조회·완료 확정](02-cache-gaps.md) | `T040-P2-A/B` | PLANNED |
| 3 | [0.4.0-P3 — 7일 초과·최대 4주 요청 처리](03-older-than-retention.md) | `T040-P3-A/B` | PLANNED |
| 4 | [0.4.0-P4 — 최신 일반 사용자 X개 보충](04-recent-count.md) | `T040-P4-A/B` | PLANNED |
| 5 | [0.4.0-P5 — 캐시 fallback·빈 대화·수집 통합 게이트](05-collection-acceptance.md) | `T040-P5-A/B` | PLANNED |

## 버전 완료 조건

- 5단계의 고유 검증과 영향 범위 회귀 검사가 통과했다.
- 각 단계마다 commit → GitHub push → 원격 반영 확인이 완료되었고 STATUS에 증거가 있다.
- 버전 마지막 단계에서 기본 브랜치 통합 결과와 검증 대상 SHA 대응을 기록했다.
- 필수 항목의 FAIL/NOT_RUN 또는 선행 조건 누락을 완료로 계산하지 않는다.

[공통 Git 완료 규칙](../GIT_WORKFLOW.md) · [진행 상태](../STATUS.md) · [전체 로드맵](../README.md)
