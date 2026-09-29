# 1.0.1 진행 상태

기준일: 2026-09-29. **계획 작성 6단계 / 구현 완료 0단계, P1 원격 확인 중.** [1.0.0a~d](../README.md)의 실제 완료가 선행한다. 이 계획의 GitHub 게시는 P1~P6 구현·검증의 완료가 아니다. [1.0.0까지 완료된 55단계](../STATUS.md)는 별도 집계로 보존한다.

| 단계 | 목표 | 상태 | 구현 C / 증거 E / 종료 D | 제한·다음 작업 |
|---|---|---|---|---|
| [1.0.1-P1](01-app-server-contract.md) | app-server JSON 계약 | PUSH_PENDING | C `a9cb8cb` / [증거](../evidence/1.0.1-P1.md) | P1-A/B PASS(OpenJevLXC); E 원격·CI 확인 대기 |
| [1.0.1-P2](02-usage-command.md) | 사용량·한도 초과 | PLANNED | — | P1 선행 |
| [1.0.1-P3](03-detailed-summary.md) | 범위 지정 자세한 요약 | PLANNED | — | P2 선행 |
| [1.0.1-P4](04-short-summary.md) | 범위 지정 짧은 요약 | PLANNED | — | P3 선행 |
| [1.0.1-P5](05-status-command.md) | 실측 상태 응답 | PLANNED | — | P4 선행 |
| [1.0.1-P6](06-help-release.md) | 도움말·통합·출시 | PLANNED | — | P1~P5 원격 증거 선행 |

실행 시 각 단계 상태를 `IN_PROGRESS` → `VERIFIED`/`PUSH_PENDING` → `DONE`으로 갱신한다. DONE은 같은 단계의 검사 결과, C/E/D SHA와 원격 URL, 필요한 GitHub CI, 개발 LXC/Discord 검증 범위가 모두 확인된 뒤에만 쓴다. 문서에 적힌 샘플 수치·모델 이름은 운영 실측으로 간주하지 않는다.

[버전 개요](README.md) · [검증 목록](TEST_MATRIX.md) · [Git 완료 규칙](../GIT_WORKFLOW.md)
