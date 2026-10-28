# 1.4.4a 진행 상태

기준일: 2026-10-27. **2/2단계 완료, `v1.4.4a` 출시.** 기준은 `v1.4.4`(`1034a3a`, `main` 병합 `8472d8b`)이며 브랜치는 `develop/1.4.4a`이다.

| 단계 | 목표 | 상태 | 구현 C / 증거 E / 종료 D | 선행·제약 |
|---|---|---|---|---|
| [1.4.4a-P1](01-cli-update.md) | CLI 고정값·호환 확인 | DONE | C `65e209b254302932fcc3cd7a4fd30f469c72d9b4` / E [`9819259`](https://github.com/parking-place/YoYackBot/commit/9819259e70a60b12d312c59322c0ea560b25372e) | 기준 `v1.4.4`, [C CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/40467153986), [E CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/40467373895), 종료 D push 확인 |
| [1.4.4a-P2](02-release.md) | 통합·배포·출시 | DONE | C `cb928d876409a4f83f688f9f68659d5706be60ff` / E [`607952a`](https://github.com/parking-place/YoYackBot/commit/607952a6825db969330062cf39a6c76feaa57232) | P1 D `d1ee215`, [C CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/40467681464), 태그 `v1.4.4a`·[Release](https://github.com/parking-place/YoYackBot/releases/tag/v1.4.4a), 사용자 출시 지시 2026-10-28, [E CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/40631722011), 종료 D push 확인 |

[버전 개요](README.md) · [공통 Git 규칙](../GIT_WORKFLOW.md)
