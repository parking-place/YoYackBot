# 1.3.3 진행 상태

기준일: 2026-10-05. **1/6단계 완료.** 기준은 `v1.3.2`(`6604a61`, `main` 병합 `e22a6b1`)이며 브랜치는 `develop/1.3.3`이다.

| 단계 | 목표 | 상태 | 구현 C / 증거 E / 종료 D | 선행·제약 |
|---|---|---|---|---|
| [1.3.3-P1](01-call-effort.md) | 호출별 추론 강도·호출 계측 | DONE | C `27c5c4281e35ca7160f7249fd1df6c8f89e25f28` / E [`ebaa2da`](https://github.com/parking-place/YoYackBot/commit/ebaa2dab51c6395b891ced8e03a822c5e8694a0e) | 기준 `v1.3.2`, [C CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/37265698459), [E CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/37265856038), 종료 D push 확인 |
| [1.3.3-P2](02-idiom-inline.md) | `!!말하자면` 대화 직접 전달 | PUSH_PENDING | C `e520f4a1a48ddb3ee30ea435c33a9a2565aeaa08` / E 증거 push 뒤 기록 | P1 D `50eb47a`, [C CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/37266395233) |
| [1.3.3-P3](03-summary-inline.md) | 요약 대화 직접 전달·입력 상한 | PLANNED | — | P2 D |
| [1.3.3-P4](04-parallel-candidates.md) | 요약·평가 후보 동시 실행 | PLANNED | — | P3 D |
| [1.3.3-P5](05-evaluation.md) | 실제 모델 평가 | PLANNED | — | P4 D, 사용자 예시 확인 |
| [1.3.3-P6](06-release.md) | 통합·배포·출시 | PLANNED | — | P5 D, 사용자 Discord 확인 |

구현 C 검증과 증거 E의 원격 반영·CI 성공 후 DONE을 기록하는 종료 D를 만들고, D의 원격 반영·필요 CI까지 확인해야 완료다.

[버전 개요](README.md) · [공통 Git 규칙](../GIT_WORKFLOW.md)
