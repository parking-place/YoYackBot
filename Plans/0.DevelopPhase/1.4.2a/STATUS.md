# 1.4.2a 진행 상태

기준일: 2026-10-12. **3/3단계 완료, `v1.4.2a` 출시.** 기준은 `v1.4.2`(`109ce8b`, `main` 병합 `d127e75`)이며 브랜치는 `develop/1.4.2a`이다.

| 단계 | 목표 | 상태 | 구현 C / 증거 E / 종료 D | 선행·제약 |
|---|---|---|---|---|
| [1.4.2a-P1](01-more-presets.md) | 프리셋 6종 | DONE | C `8963cac9852cfad0e84154b61b9288dc6743eb9d` / E [`57d7d5e`](https://github.com/parking-place/YoYackBot/commit/57d7d5e3d374f8c65ba5e72c7f90890f6adcce4f) | 기준 `v1.4.2`, [C CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/38213117743), [E CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/38213273781), 종료 D push 확인 |
| [1.4.2a-P2](02-evaluation.md) | 실제 모델 평가 | DONE | C `8963cac9852cfad0e84154b61b9288dc6743eb9d` / E [`22137e5`](https://github.com/parking-place/YoYackBot/commit/22137e537e37973ae4c3e8e2f057792ed0d34105) | P1 D `c073356`, [C CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/38213117743), 사용자 예시 확인 2026-10-12, [E CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/38218115671), 종료 D push 확인 |
| [1.4.2a-P3](03-release.md) | 통합·배포·출시 | DONE | C `54b3fbc16f6487a61858497f4c94d245b4c0550c` / E [`3114b34`](https://github.com/parking-place/YoYackBot/commit/3114b3485adbb679dfb452e705c848f22bf82611) | P2 D `b5a6e01`, [C CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/38218380172), 태그 `v1.4.2a`·[Release](https://github.com/parking-place/YoYackBot/releases/tag/v1.4.2a), 사용자 Discord 확인 2026-10-14, [E CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/38488543381), 종료 D push 확인 |

[버전 개요](README.md) · [공통 Git 규칙](../GIT_WORKFLOW.md)
