# 1.0.1 진행 상태

기준일: 2026-09-29. **계획 작성 6단계 / 구현 완료 2단계, P3 진행 중.** [1.0.0a~d](../README.md)의 실제 완료가 선행한다. 이 계획의 GitHub 게시는 P1~P6 구현·검증의 완료가 아니다. [1.0.0까지 완료된 55단계](../STATUS.md)는 별도 집계로 보존한다.

| 단계 | 목표 | 상태 | 구현 C / 증거 E / 종료 D | 제한·다음 작업 |
|---|---|---|---|---|
| [1.0.1-P1](01-app-server-contract.md) | app-server JSON 계약 | DONE | [C `a9cb8cb`](https://github.com/parking-place/YoYackBot/commit/a9cb8cbcfd3e8b02f5b852090792338ce05bc45e) / [C CI](https://github.com/parking-place/YoYackBot/actions/runs/36555209064) / [E `7b8b08d`](https://github.com/parking-place/YoYackBot/commit/7b8b08d10b0f626599b33d4a426478a35aa078ad) / [E CI](https://github.com/parking-place/YoYackBot/actions/runs/36555316652) / [증거](../evidence/1.0.1-P1.md); 원격 확인 | P1-A/B PASS(OpenJevLXC). 봇 계정은 주간 창만 반환 → 사용자 결정으로 있는 창만 표시 |
| [1.0.1-P2](02-usage-command.md) | 사용량·한도 초과 | DONE | [C `d477dd5`](https://github.com/parking-place/YoYackBot/commit/d477dd510feb82467126b449b3c9bc8b623a1cc6) / [C CI](https://github.com/parking-place/YoYackBot/actions/runs/36555779151) / [E `0033dc1`](https://github.com/parking-place/YoYackBot/commit/0033dc19a3363631c80e374c7cb057a724a72561) / [E CI](https://github.com/parking-place/YoYackBot/actions/runs/36555849157) / [증거](../evidence/1.0.1-P2.md); 원격 확인 | P2-A PASS, P2-B 합성·실제 조회 PASS; 시험 채널은 P6 사용자 확인 |
| [1.0.1-P3](03-detailed-summary.md) | 범위 지정 자세한 요약 | PUSH_PENDING | C `aec9bcb` / [증거](../evidence/1.0.1-P3.md) | P3-A PASS, P3-B 실제 모델 3건 PASS |
| [1.0.1-P4](04-short-summary.md) | 범위 지정 짧은 요약 | PLANNED | — | P3 선행 |
| [1.0.1-P5](05-status-command.md) | 실측 상태 응답 | PLANNED | — | P4 선행 |
| [1.0.1-P6](06-help-release.md) | 도움말·통합·출시 | PLANNED | — | P1~P5 원격 증거 선행 |

실행 시 각 단계 상태를 `IN_PROGRESS` → `VERIFIED`/`PUSH_PENDING` → `DONE`으로 갱신한다. DONE은 같은 단계의 검사 결과, C/E/D SHA와 원격 URL, 필요한 GitHub CI, 개발 LXC/Discord 검증 범위가 모두 확인된 뒤에만 쓴다. 문서에 적힌 샘플 수치·모델 이름은 운영 실측으로 간주하지 않는다.

[버전 개요](README.md) · [검증 목록](TEST_MATRIX.md) · [Git 완료 규칙](../GIT_WORKFLOW.md)
