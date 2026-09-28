# 0.1.0 — Discord 연결과 주시 채널 설정

- 상태: **PLANNED**
- 단계 수: **5단계**

## 목표

서버별로 허용된 텍스트 채널만 주시하며 설정을 재시작 후 복원한다.

## 진입 조건

이전 버전 [0.0.0](../0.0.0/README.md)의 마지막 단계와 원격 업로드 확인을 완료한다.

## 단계

| 순서 | 단계 | 검증 ID | 상태 |
|---|---|---|---|
| 1 | [0.1.0-P1 — Discord 연결·이벤트 경계 구현](01-gateway.md) | `T010-P1-A/B` | DONE |
| 2 | [0.1.0-P2 — 채널 설정 명령·관리 권한 구현](02-channel-selector.md) | `T010-P2-A/B` | DONE |
| 3 | [0.1.0-P3 — 주시 설정 영속화·서버 격리](03-settings-store.md) | `T010-P3-A/B` | PLANNED |
| 4 | [0.1.0-P4 — 주시 추가·해제·미주시 차단](04-watch-enforcement.md) | `T010-P4-A/B` | PLANNED |
| 5 | [0.1.0-P5 — 채널 설정 실환경 검증·버전 종료](05-channel-acceptance.md) | `T010-P5-A/B` | PLANNED |

## 버전 완료 조건

- 5단계의 고유 검증과 영향 범위 회귀 검사가 통과했다.
- 각 단계마다 commit → GitHub push → 원격 반영 확인이 완료되었고 STATUS에 증거가 있다.
- 버전 마지막 단계에서 기본 브랜치 통합 결과와 검증 대상 SHA 대응을 기록했다.
- 필수 항목의 FAIL/NOT_RUN 또는 선행 조건 누락을 완료로 계산하지 않는다.

[공통 Git 완료 규칙](../GIT_WORKFLOW.md) · [진행 상태](../STATUS.md) · [전체 로드맵](../README.md)
