# 1.3.0 진행 상태

기준일: 2026-10-02. **계획 7단계·16검사 / 구현 완료 2단계.** 2026-10-02 사용자 지시(“1.3.0까지 바로 개발”)로 1.2.0의 Discord 확인·태그·`main` 통합을 기다리지 않고 `develop/1.3.0`을 1.2.0 후보 위에서 시작했다. 1.2.0 출시 마무리(P7-C/D)는 별도로 남아 있으며, 1.3.0 출시(P7)는 1.2.0 출시 뒤에만 한다. 사자성어 기능을 P5로 추가하고 기존 실제 평가·출시를 P6·P7로 이동했다. 이관 시점의 출시 코드 근거는 [`v1.1.3a`](../1.1.3a/STATUS.md)다. 1.3.0 착수는 새 [1.2.0](../1.2.0/STATUS.md)의 7단계 완료·출시·`main` 통합 뒤이며, 실행·복귀 대상의 정확한 SHA는 아직 미정이다. 이 문서의 GitHub 게시는 두 버전의 구현·검증 완료를 뜻하지 않는다.

| 단계 | 목표 | 상태 | 구현 C / 증거 E / 종료 D | 선행·제약 |
|---|---|---|---|---|
| [1.3.0-P1](01-rating-candidates.md) | 평가 후보 10개·금지 소재 | DONE | C `9e7036aaf5275f4d57e32e9b72972e03e2bc15f6` / E [`a7b5ea6`](https://github.com/parking-place/YoYackBot/commit/a7b5ea653d2d3e3a10450d2b1a701a398ff49db8) | 기준 1.2.0 후보 `613856e`, [E CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/37002470823), 종료 D push 확인 |
| [1.3.0-P2](02-rating-judge.md) | luna 심사로 1개 선택 | DONE | C `569dab421a811ff063d0c164f2604981cc7d16e6` / E [`a4c0c2b`](https://github.com/parking-place/YoYackBot/commit/a4c0c2b65523f5b5a71c386d7a2719756a9c17eb) | P1 D `bcd2ae3`, [E CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/37002941471), 종료 D push 확인 |
| [1.3.0-P3](03-reply-range.md) | 답장으로 범위 지정 | IN_PROGRESS | — | P2 종료 D `1d1829f` |
| [1.3.0-P4](04-tone-command.md) | `/말투` 명령 | PLANNED | — | P3 원격 완료 |
| [1.3.0-P5](05-idiom.md) | 최근 30개·후보 4개·사자성어 한마디 | PLANNED | — | P4 원격 완료, 서버 말투와 분리 |
| [1.3.0-P6](06-evaluation.md) | 기존 요약 16건 + 사자성어 4건 실제 평가 | PLANNED | — | P5 원격 완료, 계정 한도 확인 |
| [1.3.0-P7](07-release.md) | 도움말·통합·배포·출시 | PLANNED | — | P1~P6 원격 증거 선행 |

실행 시 [검증 목록](TEST_MATRIX.md)의 결과와 대상 SHA·환경·원격 URL·남은 공백을 단계마다 기록한다. 구현 C 검증과 증거 E의 원격 반영·CI 성공 후 DONE을 기록하는 종료 D를 만들고, D의 원격 반영·필요 CI까지 확인해야 완료다. 마지막 P7의 출시 전·후 증거 순서는 해당 단계 문서를 따른다.

[버전 개요](README.md) · [공통 Git 규칙](../GIT_WORKFLOW.md)
