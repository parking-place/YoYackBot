# 1.4.4 진행 상태

기준일: 2026-10-26. **3/5단계 완료.** 기준은 `v1.4.3a`(`4e4933d`, `main` 병합 `5d6120c`)이며 브랜치는 `develop/1.4.4`이다.

| 단계 | 목표 | 상태 | 구현 C / 증거 E / 종료 D | 선행·제약 |
|---|---|---|---|---|
| [1.4.4-P1](01-exercise-settings.md) | 운동 설정·기록 저장소 | DONE | C `27216315051a55129bd43eead12a81608293a1ca` / E [`5a75e10`](https://github.com/parking-place/YoYackBot/commit/5a75e10b5e8bf319659c05a55c86cdfec1bbdd21) | 기준 `v1.4.3a`, [C CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/40290674672), [E CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/40290925953), 종료 D push 확인 |
| [1.4.4-P2](02-daily-tally.md) | 일간 영양·운동 정산 | DONE | C `a83c88d376900efea3045c1d5a2276db35a27542` / E [`86ccc52`](https://github.com/parking-place/YoYackBot/commit/86ccc524aeb21fc42bb4818a56e83e2d7d2831dc) | P1 D, [C CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/40291995457), [E CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/40292238100), 종료 D push 확인 |
| [1.4.4-P3](03-weekly-advice.md) | 주간 훈수 | DONE | C `e40c6e390a82b7fe9cc7c90e2158747d2a79324b` / E [`d255024`](https://github.com/parking-place/YoYackBot/commit/d25502494b9fdeaafe3339a553a25d788b9bba0d) | P2 D, [C CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/40293391108), [E CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/40293687780), 종료 D push 확인 |
| [1.4.4-P4](04-evaluation.md) | 실제 모델 평가 | PLANNED | — | P3 D, 사용자 예시 확인 |
| [1.4.4-P5](05-release.md) | 통합·배포·출시 | PLANNED | — | P4 D, 사용자 Discord 확인 |

[버전 개요](README.md) · [공통 Git 규칙](../GIT_WORKFLOW.md)
