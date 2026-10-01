# 1.1.2a 진행 상태

기준일: 2026-10-01. **계획 4단계 / 구현 완료 0단계.** 현재 출시 코드는 [`v1.1.2`](../1.1.2/STATUS.md)다. 이 문서의 GitHub 게시는 1.1.2a 구현·검증의 완료가 아니다.

| 단계 | 목표 | 상태 | 구현 C / 증거 E / 종료 D | 선행·제약 |
|---|---|---|---|---|
| [1.1.2a-P1](01-command-permission.md) | 슬래시 명령어 권한 | PLANNED | — | `v1.1.2` 출시·`main` 통합 |
| [1.1.2a-P2](02-nickname-underline.md) | 닉네임 밑줄 | PLANNED | — | P1 원격 완료 |
| [1.1.2a-P3](03-help-evaluation.md) | 짧은 도움말·실제 모델 확인 | PLANNED | — | P2 원격 완료, 계정 한도 확인 |
| [1.1.2a-P4](04-release.md) | 통합·배포·출시 | PLANNED | — | P1~P3 원격 증거 선행 |

실행 시 [검증 목록](TEST_MATRIX.md)의 결과와 대상 SHA·환경·원격 URL·남은 공백을 단계마다 기록한다. 구현 C·증거 E·종료 D가 모두 원격에서 확인되고 E의 CI가 성공한 뒤에만 DONE으로 바꾼다.

[버전 개요](README.md) · [공통 Git 규칙](../GIT_WORKFLOW.md)
