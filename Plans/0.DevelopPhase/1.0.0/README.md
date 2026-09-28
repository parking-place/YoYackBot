# 1.0.0 — 정식 배포와 운영 인수

- 상태: **PLANNED**
- 단계 수: **5단계**

## 목표

검증한 후보를 재현 가능하게 배포하고 운영 관측·롤백·GitHub 릴리스까지 마친다.

## 진입 조건

이전 버전 [0.9.0](../0.9.0/README.md)의 마지막 단계와 원격 업로드 확인을 완료한다.

## 단계

| 순서 | 단계 | 검증 ID | 상태 |
|---|---|---|---|
| 1 | [1.0.0-P1 — 정식 출시 범위·증거 최종 검토](01-release-review.md) | `T100-P1-A/B` | PLANNED |
| 2 | [1.0.0-P2 — 버전·배포 산출물·설정 재현성](02-release-package.md) | `T100-P2-A/B` | PLANNED |
| 3 | [1.0.0-P3 — 업데이트·migration·롤백 리허설](03-rollback-rehearsal.md) | `T100-P3-A/B` | PLANNED |
| 4 | [1.0.0-P4 — 운영 배포·동일 SHA smoke·초기 관측](04-production-validation.md) | `T100-P4-A/B` | PLANNED |
| 5 | [1.0.0-P5 — GitHub 정식 릴리스·최종 인수](05-release-publish.md) | `T100-P5-A/B` | PLANNED |

## 버전 완료 조건

- 5단계의 고유 검증과 영향 범위 회귀 검사가 통과했다.
- 각 단계마다 commit → GitHub push → 원격 반영 확인이 완료되었고 STATUS에 증거가 있다.
- 버전 마지막 단계에서 기본 브랜치 통합 결과와 검증 대상 SHA 대응을 기록했다.
- 필수 항목의 FAIL/NOT_RUN 또는 선행 조건 누락을 완료로 계산하지 않는다.

[공통 Git 완료 규칙](../GIT_WORKFLOW.md) · [진행 상태](../STATUS.md) · [전체 로드맵](../README.md)
