# 1.0.0a 진행 상태

2026-09-29 기준 **계획 5단계, 구현 완료 2단계**. P1·P2는 후보 검증을 완료했으며 제품 배포는 아직 아니다.

| 단계 | 목표 | 상태 | C/E/D 원격 증거 | 선행 |
|---|---|---|---|---|
| [P1](01-contract.md) | 설정·보존 계약 | DONE | [C `d0f6bd4`](https://github.com/parking-place/YoYackBot/commit/d0f6bd4d63f4a800d29684b75a1d9670802bcdbd) / [E `57546b7`](https://github.com/parking-place/YoYackBot/commit/57546b74e8f179161b7fe6718b2102240b55d3ce) / D 원격 확인 | 1.0.0 완료 |
| [P2](02-cache.md) | DB 정리·복원 | DONE | [C `e0f981d`](https://github.com/parking-place/YoYackBot/commit/e0f981dca10f51bc68208bf2e83d65e4bc7ff09e) / [E `1c2b49c`](https://github.com/parking-place/YoYackBot/commit/1c2b49c666aeefbb553844b57c12fa86761b469b) / D 원격 확인 | P1 DONE |
| [P3](03-collection.md) | 기간·개수 수집 | PUSH_PENDING | C `8ae9ae5` / [증거 E](../evidence/1.0.0a-P3.md) / D 대기 | P2 DONE |
| [P4](04-help.md) | 명령·도움말 | PLANNED | — | P3 DONE |
| [P5](05-release.md) | 운영 회귀·출시 | PLANNED | — | P4 DONE |

각 단계의 검증 결과·실행 SHA·원격 URL을 기록한다. IN_PROGRESS → VERIFIED/PUSH_PENDING → DONE은 [공통 Git 규칙](../GIT_WORKFLOW.md)에 따라 실제 원격 반영 뒤에만 진행한다.
