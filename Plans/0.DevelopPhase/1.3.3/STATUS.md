# 1.3.3 진행 상태

기준일: 2026-10-05. **4/6단계 완료.** 기준은 `v1.3.2`(`6604a61`, `main` 병합 `e22a6b1`)이며 브랜치는 `develop/1.3.3`이다.

| 단계 | 목표 | 상태 | 구현 C / 증거 E / 종료 D | 선행·제약 |
|---|---|---|---|---|
| [1.3.3-P1](01-call-effort.md) | 호출별 추론 강도·호출 계측 | DONE | C `27c5c4281e35ca7160f7249fd1df6c8f89e25f28` / E [`ebaa2da`](https://github.com/parking-place/YoYackBot/commit/ebaa2dab51c6395b891ced8e03a822c5e8694a0e) | 기준 `v1.3.2`, [C CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/37265698459), [E CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/37265856038), 종료 D push 확인 |
| [1.3.3-P2](02-idiom-inline.md) | `!!말하자면` 대화 직접 전달 | DONE | C `e520f4a1a48ddb3ee30ea435c33a9a2565aeaa08` / E [`d6d60ba`](https://github.com/parking-place/YoYackBot/commit/d6d60ba2c3dfa382cd13604528f8375285347218) | P1 D `50eb47a`, [C CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/37266395233), [E CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/37266634766), 종료 D push 확인 |
| [1.3.3-P3](03-summary-inline.md) | 요약 대화 직접 전달·입력 상한 | DONE | C `36512c51aa134c67f2ee1144db896f2ecb44192b` / E [`4e43648`](https://github.com/parking-place/YoYackBot/commit/4e436483da2ea6d74bee0f217ad816da60b9ba1a) | P2 D `ce7988e`, [C CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/37267123093), [E CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/37267425463), 종료 D push 확인 |
| [1.3.3-P4](04-parallel-candidates.md) | 요약·평가 후보 동시 실행 | DONE | C `1046ee0b133de27a20fe7daa9819e036bf648714` / E [`a6dfeeb`](https://github.com/parking-place/YoYackBot/commit/a6dfeebf8e4e892051a11cb3b639a53a98ebba46) | P3 D `3de8bca`, [C CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/37267978273), [E CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/37268234482), 종료 D push 확인 |
| [1.3.3-P5](05-evaluation.md) | 실제 모델 평가 | PLANNED | — | P4 D, 사용자 예시 확인 |
| [1.3.3-P6](06-release.md) | 통합·배포·출시 | PLANNED | — | P5 D, 사용자 Discord 확인 |

구현 C 검증과 증거 E의 원격 반영·CI 성공 후 DONE을 기록하는 종료 D를 만들고, D의 원격 반영·필요 CI까지 확인해야 완료다.

[버전 개요](README.md) · [공통 Git 규칙](../GIT_WORKFLOW.md)
