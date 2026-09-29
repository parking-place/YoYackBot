# 1.0.0b 진행 상태

**폐기·대체(SUPERSEDED).** 후속 실행은 [1.0.0b-1 상태](../1.0.0b-1/STATUS.md)에서 추적한다. 2026-09-29 기준 이 계획은 6단계 중 P1만 실제 완료했고, P2는 후보 코드 push까지만 진행했다. 운영 집계의 이전 모델 오류 세부 원인은 미확인이다. 이 버전의 태그/출시는 없다.

| 단계 | 목표 | 상태 | C/E/D 원격 증거 | 선행 |
|---|---|---|---|---|
| [P1](01-diagnose.md) | 실패 분류·재현 | DONE | [C `d6c6040`](https://github.com/parking-place/YoYackBot/commit/d6c6040a2077106a94dbe8683a9623a474052272) / [E `ae783e6`](https://github.com/parking-place/YoYackBot/commit/ae783e68d19245a6e4c67f6abbe888a29ecf3d8d) / D 원격 확인 | 1.0.0a 완료 |
| [P2](02-input.md) | 대량 입력·모델 한도 | STOPPED | 후보 C `715148e`·`00ea16c`·`846f140` push, E/D 없음 | P1 DONE |
| [P3](03-backfill.md) | 최초 주시 채널 30일 초기 수집 | SUPERSEDED | — | 새 계획으로 이관 |
| [P4](04-queue.md) | 모델 대기열 시간 정책 | SUPERSEDED | — | 새 계획으로 이관 |
| [P5](05-recovery.md) | 실패 정리·재시도 | SUPERSEDED | — | 새 계획으로 이관 |
| [P6](06-release.md) | 대량 요청·초기 수집 통합·출시 | SUPERSEDED | — | 새 계획으로 이관 |

P2의 후보 코드가 새 브랜치에 포함되더라도 P2를 소급해 DONE으로 표시하지 않는다. 새 계획은 별도 C/E/D와 [공통 Git 규칙](../GIT_WORKFLOW.md)으로 완료 판정한다.
