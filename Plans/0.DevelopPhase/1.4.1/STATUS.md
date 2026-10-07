# 1.4.1 진행 상태

기준일: 2026-10-07. **2/2단계 완료, `v1.4.1` 출시.** 기준은 `v1.4.0`(`312e5b0`, `main` 병합 `5fd6546`)이며 브랜치는 `develop/1.4.1`이다.

| 단계 | 목표 | 상태 | 구현 C / 증거 E / 종료 D | 선행·제약 |
|---|---|---|---|---|
| [1.4.1-P1](01-pardon.md) | `/사면` 명령 | DONE | C `70cae3f34f76c08ca8ab8e5f21b82630a94a6222` / E [`e5078d6`](https://github.com/parking-place/YoYackBot/commit/e5078d6e31df8625b28a6a2330f8e8b5d5ad05ee) | 기준 `v1.4.0`, [C CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/37613243867), [E CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/37613435440), 종료 D push 확인 |
| [1.4.1-P2](02-release.md) | 통합·배포·출시 | DONE | C `18ec31e9101d4309dd393b56ff39ac9b576b484d` / E [`38ee6be`](https://github.com/parking-place/YoYackBot/commit/38ee6bee94f6916c174b0790ce59ccadb326d1fb) | P1 D `a7eb231`, [C CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/37613767989), 태그 `v1.4.1`·[Release](https://github.com/parking-place/YoYackBot/releases/tag/v1.4.1), 사용자 Discord 확인 2026-10-07, [E CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/37614341160), 종료 D push 확인 |

[버전 개요](README.md) · [공통 Git 규칙](../GIT_WORKFLOW.md)
