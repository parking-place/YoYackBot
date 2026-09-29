# 1.0.0a 진행 상태

2026-09-29 기준 **계획 5단계, 구현 완료 0단계**. 1.0.0의 후속 계획 게시와 제품 배포는 별개다.

| 단계 | 목표 | 상태 | C/E/D 원격 증거 | 선행 |
|---|---|---|---|---|
| [P1](01-contract.md) | 설정·보존 계약 | PUSH_PENDING | C `d0f6bd4` / [증거 E](../evidence/1.0.0a-P1.md) / D 대기 | 1.0.0 완료 |
| [P2](02-cache.md) | DB 정리·복원 | PLANNED | — | P1 DONE |
| [P3](03-collection.md) | 기간·개수 수집 | PLANNED | — | P2 DONE |
| [P4](04-help.md) | 명령·도움말 | PLANNED | — | P3 DONE |
| [P5](05-release.md) | 운영 회귀·출시 | PLANNED | — | P4 DONE |

각 단계의 검증 결과·실행 SHA·원격 URL을 기록한다. IN_PROGRESS → VERIFIED/PUSH_PENDING → DONE은 [공통 Git 규칙](../GIT_WORKFLOW.md)에 따라 실제 원격 반영 뒤에만 진행한다.
