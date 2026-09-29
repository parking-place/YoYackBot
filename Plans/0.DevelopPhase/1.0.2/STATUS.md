# 1.0.2 진행 상태

기준일: 2026-09-29. **계획 5단계 / 구현 완료 0단계.** 현재 출시 코드는 1.0.0이고 [1.0.1 상태](../1.0.1/STATUS.md)도 계획 단계다. 이 문서의 GitHub 게시는 1.0.2 구현·검증의 완료가 아니다.

| 단계 | 목표 | 상태 | 구현 C / 증거 E / 종료 D | 선행·제약 |
|---|---|---|---|---|
| [1.0.2-P1](01-range-contract.md) | 10일 허용·범위 라벨 | PLANNED | — | 1.0.1 완료 선행 |
| [1.0.2-P2](02-active-scope.md) | 활성 범위 원자적 보관 | PLANNED | — | P1 원격 완료 선행 |
| [1.0.2-P3](03-collection-notice.md) | 수집 시작 안내 | PLANNED | — | P2 원격 완료 선행 |
| [1.0.2-P4](04-busy-notice.md) | 중복 요청 안내 | PLANNED | — | P3 원격 완료 선행 |
| [1.0.2-P5](05-integration-release.md) | 통합·시험 Discord·출시 | PLANNED | — | P1~P4 원격 증거 선행 |

실행 시 [검증 목록](TEST_MATRIX.md)의 결과와 대상 SHA·환경·원격 URL·남은 공백을 단계마다 기록한다. `IN_PROGRESS`/`VERIFIED`/`PUSH_PENDING`을 거쳐 구현 C·증거 E·종료 D가 모두 원격에서 확인된 뒤에만 DONE으로 바꾼다. 현 단계의 `PLANNED`는 자동화 검사나 실제 채널 게시의 PASS를 뜻하지 않는다.

[버전 개요](README.md) · [공통 Git 규칙](../GIT_WORKFLOW.md)
