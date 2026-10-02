# 1.2.0 진행 상태

기준일: 2026-10-02. **계획 6단계 / 구현 완료 0단계.** 현재 출시 코드는 [`v1.1.3a`](../1.1.3a/STATUS.md)다. 이 문서의 GitHub 게시는 1.2.0 구현·검증의 완료가 아니다.

| 단계 | 목표 | 상태 | 구현 C / 증거 E / 종료 D | 선행·제약 |
|---|---|---|---|---|
| [1.2.0-P1](01-rating-candidates.md) | 평가 후보 10개·금지 소재 | PLANNED | — | `v1.1.3a` 출시·`main` 통합 |
| [1.2.0-P2](02-rating-judge.md) | luna 심사로 1개 선택 | PLANNED | — | P1 원격 완료 |
| [1.2.0-P3](03-reply-range.md) | 답장으로 범위 지정 | PLANNED | — | P2 원격 완료 |
| [1.2.0-P4](04-tone-command.md) | `/말투` 명령 | PLANNED | — | P3 원격 완료 |
| [1.2.0-P5](05-evaluation.md) | 실제 모델 평가 | PLANNED | — | P4 원격 완료, 계정 한도 확인 |
| [1.2.0-P6](06-release.md) | 도움말·통합·배포·출시 | PLANNED | — | P1~P5 원격 증거 선행 |

실행 시 [검증 목록](TEST_MATRIX.md)의 결과와 대상 SHA·환경·원격 URL·남은 공백을 단계마다 기록한다. 구현 C·증거 E·종료 D가 모두 원격에서 확인되고 E의 CI가 성공한 뒤에만 DONE으로 바꾼다.

[버전 개요](README.md) · [공통 Git 규칙](../GIT_WORKFLOW.md)
