# 1.4.4b 진행 상태

기준일: 2026-10-28. **2/2단계 완료, `v1.4.4b` 출시.** 기준은 `v1.4.4a`(`cb928d8`, `main` 병합 `c99b698`)이며 브랜치는 `develop/1.4.4b`이다.

| 단계 | 목표 | 상태 | 구현 C / 증거 E / 종료 D | 선행·제약 |
|---|---|---|---|---|
| [1.4.4b-P1](01-diet-model.md) | 호출별 모델·실제 모델 평가 | DONE | C `69e4d9a0772b4ba8b21a87dbf2feab4b92fa8eb0` / E [`27ed1f5`](https://github.com/parking-place/YoYackBot/commit/27ed1f5e2b5ff4e70cce2b6abb83e6a6dfca9395) | 기준 `v1.4.4a`, [C CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/40632788378), [E CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/40632976775), 종료 D push 확인 |
| [1.4.4b-P2](02-release.md) | 통합·배포·출시 | DONE | C `419764b5f3d9245da528e2624f4697b6f4e0246a` / E [`ad693db`](https://github.com/parking-place/YoYackBot/commit/ad693db79ce05694263870d2348227d10ec47f57) | P1 D `b5cb63b`, [C CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/40633274578), 태그 `v1.4.4b`·[Release](https://github.com/parking-place/YoYackBot/releases/tag/v1.4.4b), 사용자 출시 지시 2026-10-28, [E CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/40633608290), 종료 D push 확인 |

[버전 개요](README.md) · [공통 Git 규칙](../GIT_WORKFLOW.md)
