# 0.6.0 — 화자 중심 요약과 Discord 출력

- 상태: **PLANNED**
- 단계 수: **5단계**

## 목표

원문에 충실한 한국어 하오체 요약을 길이 제한에 맞춰 같은 채널에 게시한다.

## 진입 조건

이전 버전 [0.5.0](../0.5.0/README.md)의 마지막 단계와 원격 업로드 확인을 완료한다.

## 단계

| 순서 | 단계 | 검증 ID | 상태 |
|---|---|---|---|
| 1 | [0.6.0-P1 — 화자·결정·미해결 중심 프롬프트](01-summary-prompt.md) | `T060-P1-A/B` | IN_PROGRESS |
| 2 | [0.6.0-P2 — 사실성·화자 귀속·하오체 평가](02-quality-evaluation.md) | `T060-P2-A/B` | PLANNED |
| 3 | [0.6.0-P3 — 머리말·실제 범위·긴 메시지 분할](03-format-split.md) | `T060-P3-A/B` | PLANNED |
| 4 | [0.6.0-P4 — 같은 채널 전송·부분 실패 처리](04-delivery.md) | `T060-P4-A/B` | PLANNED |
| 5 | [0.6.0-P5 — 수집부터 게시까지 출력 통합 게이트](05-output-acceptance.md) | `T060-P5-A/B` | PLANNED |

## 버전 완료 조건

- 5단계의 고유 검증과 영향 범위 회귀 검사가 통과했다.
- 각 단계마다 commit → GitHub push → 원격 반영 확인이 완료되었고 STATUS에 증거가 있다.
- 버전 마지막 단계에서 기본 브랜치 통합 결과와 검증 대상 SHA 대응을 기록했다.
- 필수 항목의 FAIL/NOT_RUN 또는 선행 조건 누락을 완료로 계산하지 않는다.

[공통 Git 완료 규칙](../GIT_WORKFLOW.md) · [진행 상태](../STATUS.md) · [전체 로드맵](../README.md)

[합성 대화 품질 평가 기준](QUALITY_RUBRIC.md)
