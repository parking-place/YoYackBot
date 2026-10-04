# 1.3.3 진행 상태

기준일: 2026-10-05. **6단계 모두 PLANNED.** 기준은 1.3.2 후보 `6604a61`(운영 배포됨, 출시 대기)이며 브랜치는 `develop/1.3.3`이다. 출시는 1.3.2 출시 뒤에만 한다.

| 단계 | 목표 | 상태 | 구현 C / 증거 E / 종료 D | 선행·제약 |
|---|---|---|---|---|
| [1.3.3-P1](01-call-effort.md) | 호출별 추론 강도·호출 계측 | PLANNED | — | 기준 1.3.2 후보 |
| [1.3.3-P2](02-idiom-inline.md) | `!!말하자면` 대화 직접 전달 | PLANNED | — | P1 D |
| [1.3.3-P3](03-summary-inline.md) | 요약 대화 직접 전달·입력 상한 | PLANNED | — | P2 D |
| [1.3.3-P4](04-parallel-candidates.md) | 요약·평가 후보 동시 실행 | PLANNED | — | P3 D |
| [1.3.3-P5](05-evaluation.md) | 실제 모델 평가 | PLANNED | — | P4 D, 사용자 예시 확인 |
| [1.3.3-P6](06-release.md) | 통합·배포·출시 | PLANNED | — | P5 D, 1.3.2 출시, 사용자 Discord 확인 |

구현 C 검증과 증거 E의 원격 반영·CI 성공 후 DONE을 기록하는 종료 D를 만들고, D의 원격 반영·필요 CI까지 확인해야 완료다.

[버전 개요](README.md) · [공통 Git 규칙](../GIT_WORKFLOW.md)
