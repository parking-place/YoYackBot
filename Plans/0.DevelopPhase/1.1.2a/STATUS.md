# 1.1.2a 진행 상태

기준일: 2026-10-01. **계획 5단계 / 구현 완료 3단계, P4 진행 중.** 현재 출시 코드는 [`v1.1.2`](../1.1.2/STATUS.md)다. 이 문서의 GitHub 게시는 1.1.2a 구현·검증의 완료가 아니다.

| 단계 | 목표 | 상태 | 구현 C / 증거 E / 종료 D | 선행·제약 |
|---|---|---|---|---|
| [1.1.2a-P1](01-command-permission.md) | 슬래시 명령어 권한 | DONE | [C `4f4c3d7`](https://github.com/parking-place/YoYackBot/commit/4f4c3d7d8d8c798cff44206d335c7bbcf7ef0ec4) / [C CI](https://github.com/parking-place/YoYackBot/actions/runs/36829381007) / [E `2ed8518`](https://github.com/parking-place/YoYackBot/commit/2ed8518b187cdf308236d56e55d24df93bc125d1) / [E CI](https://github.com/parking-place/YoYackBot/actions/runs/36829490186) / [증거](../evidence/1.1.2a-P1.md); 원격 확인 | P1-A/B PASS |
| [1.1.2a-P2](02-markdown-prompt.md) | 마크다운·인용 비평·닉네임 밑줄 프롬프트 | DONE | [C `86fe206`](https://github.com/parking-place/YoYackBot/commit/86fe20653a3a845108cff45e6fa6a9fa83eda9f4) / [C CI](https://github.com/parking-place/YoYackBot/actions/runs/36829930674) / [E `a8daffc`](https://github.com/parking-place/YoYackBot/commit/a8daffcb968a8907a1928e3e8ab08bd68734c4e2) / [E CI](https://github.com/parking-place/YoYackBot/actions/runs/36830038597) / [증거](../evidence/1.1.2a-P2.md); 원격 확인 | P2-A/B PASS |
| [1.1.2a-P3](03-output-checks.md) | 새 형식에 맞춘 검사·지표 | DONE | [C `b28a725`](https://github.com/parking-place/YoYackBot/commit/b28a7257da4ae40d20a234c16a3cdab260552330) / [C CI](https://github.com/parking-place/YoYackBot/actions/runs/36830431157) / [E `7984ad1`](https://github.com/parking-place/YoYackBot/commit/7984ad1e1768d932d5ce55f99646f4814a9d092f) / [E CI](https://github.com/parking-place/YoYackBot/actions/runs/36830540955) / [증거](../evidence/1.1.2a-P3.md); 원격 확인 | P3-A/B PASS |
| [1.1.2a-P4](04-help-evaluation.md) | 짧은 도움말·실제 모델 확인 | IN_PROGRESS | — | P3 원격 완료, 계정 한도 확인 |
| [1.1.2a-P5](05-release.md) | 통합·배포·출시 | PLANNED | — | P1~P4 원격 증거 선행 |

실행 시 [검증 목록](TEST_MATRIX.md)의 결과와 대상 SHA·환경·원격 URL·남은 공백을 단계마다 기록한다. 구현 C·증거 E·종료 D가 모두 원격에서 확인되고 E의 CI가 성공한 뒤에만 DONE으로 바꾼다.

[버전 개요](README.md) · [공통 Git 규칙](../GIT_WORKFLOW.md)
