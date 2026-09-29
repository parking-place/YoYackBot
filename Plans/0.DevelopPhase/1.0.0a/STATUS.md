# 1.0.0a 진행 상태

2026-09-29 기준 **계획 5단계, 구현 완료 4단계**. P1~P4는 후보 검증을 완료했으며 버전 출시 판정은 P5에서 한다.

| 단계 | 목표 | 상태 | C/E/D 원격 증거 | 선행 |
|---|---|---|---|---|
| [P1](01-contract.md) | 설정·보존 계약 | DONE | [C `d0f6bd4`](https://github.com/parking-place/YoYackBot/commit/d0f6bd4d63f4a800d29684b75a1d9670802bcdbd) / [E `57546b7`](https://github.com/parking-place/YoYackBot/commit/57546b74e8f179161b7fe6718b2102240b55d3ce) / D 원격 확인 | 1.0.0 완료 |
| [P2](02-cache.md) | DB 정리·복원 | DONE | [C `e0f981d`](https://github.com/parking-place/YoYackBot/commit/e0f981dca10f51bc68208bf2e83d65e4bc7ff09e) / [E `1c2b49c`](https://github.com/parking-place/YoYackBot/commit/1c2b49c666aeefbb553844b57c12fa86761b469b) / D 원격 확인 | P1 DONE |
| [P3](03-collection.md) | 기간·개수 수집 | DONE | [C `8ae9ae5`](https://github.com/parking-place/YoYackBot/commit/8ae9ae5a534ed829161c028e1551188ccb752baf) / [E `422b9ea`](https://github.com/parking-place/YoYackBot/commit/422b9ea0ef7742be022b8f335d7b431bc8616490) / D 원격 확인 | P2 DONE |
| [P4](04-help.md) | 명령·도움말 | DONE | [C `4b967e4`](https://github.com/parking-place/YoYackBot/commit/4b967e4fff4c99ecc44d9c8b385b69769c4c9776) / [설치 절차 C `051d9cd`](https://github.com/parking-place/YoYackBot/commit/051d9cd67a10b5dfbf7020961a816f7cf63e9cfa) / [E `ee9abd2`](https://github.com/parking-place/YoYackBot/commit/ee9abd22b7dd229b1a24084f089d2c4592e70f2b) / D 원격 확인 | P3 DONE |
| [P5](05-release.md) | 운영 회귀·출시 | PUSH_PENDING | [C `ebacd11`](https://github.com/parking-place/YoYackBot/commit/ebacd1164510f31f5669c3e0b916ca589c4a7190) / [증거 E](../evidence/1.0.0a-P5.md) / D 대기 | P4 DONE |

각 단계의 검증 결과·실행 SHA·원격 URL을 기록한다. IN_PROGRESS → VERIFIED/PUSH_PENDING → DONE은 [공통 Git 규칙](../GIT_WORKFLOW.md)에 따라 실제 원격 반영 뒤에만 진행한다.
