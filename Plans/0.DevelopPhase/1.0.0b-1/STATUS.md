# 1.0.0b-1 진행 상태

2026-09-29 기준 **6단계 계획, 완료 0단계**. 이전 `1.0.0b` P1의 DONE과 P2 후보 코드는 [과거 상태](../1.0.0b/STATUS.md)에만 기록한다. 새 계획은 구현·검증·출시 전이다.

| 단계 | 목표 | 상태 | C/E/D 원격 증거 | 선행 |
|---|---|---|---|---|
| [P1](01-large-input.md) | 대량 입력·모델 오류 | IN_PROGRESS | 후보 구현 중 | 1.0.0a 출시 |
| [P2](02-backfill.md) | 30일 초기 수집·실시간 DB | PLANNED | — | P1 DONE |
| [P3](03-readiness.md) | 준비 안내·요약 차단 | PLANNED | — | P2 DONE |
| [P4](04-queue.md) | 모델 대기열 시간 정책 | PLANNED | — | P3 DONE |
| [P5](05-recovery.md) | 장애·중단·롤백 처리 | PLANNED | — | P4 DONE |
| [P6](06-release.md) | 통합 검증·출시 | PLANNED | — | P5 DONE |

검증 결과·실행 SHA·원격 URL을 단계마다 기록한다. IN_PROGRESS → PUSH_PENDING → DONE은 [공통 Git 규칙](../GIT_WORKFLOW.md)에 따라 실제 원격 반영 뒤에만 진행한다. 미실행 또는 실패는 PASS가 아니다.
