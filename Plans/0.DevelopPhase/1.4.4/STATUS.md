# 1.4.4 진행 상태

기준일: 2026-10-26. **진행 중.** 기준은 `v1.4.3a`(`4e4933d`, `main` 병합 `5d6120c`)이며 브랜치는 `develop/1.4.4`이다.

| 단계 | 목표 | 상태 | 구현 C / 증거 E / 종료 D | 선행·제약 |
|---|---|---|---|---|
| [1.4.4-P1](01-exercise-settings.md) | 운동 설정·기록 저장소 | PUSH_PENDING | C `2721631` / E 증거 push 뒤 기록 | 기준 `v1.4.3a`, [C CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/40290674672) |
| [1.4.4-P2](02-daily-tally.md) | 일간 영양·운동 정산 | PLANNED | — | P1 D |
| [1.4.4-P3](03-weekly-advice.md) | 주간 훈수 | PLANNED | — | P2 D |
| [1.4.4-P4](04-evaluation.md) | 실제 모델 평가 | PLANNED | — | P3 D, 사용자 예시 확인 |
| [1.4.4-P5](05-release.md) | 통합·배포·출시 | PLANNED | — | P4 D, 사용자 Discord 확인 |

[버전 개요](README.md) · [공통 Git 규칙](../GIT_WORKFLOW.md)
