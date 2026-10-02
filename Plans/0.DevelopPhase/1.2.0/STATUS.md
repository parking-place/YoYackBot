# 1.2.0 진행 상태

기준일: 2026-10-02. **계획 7단계 / 구현 완료 2단계.** 현재 출시 코드는 [v1.1.3a](../1.1.3a/STATUS.md)다. 기존 1.2.0 계획은 [1.3.0](../1.3.0/README.md)으로 이동했고, 이 문서는 버그 수정과 F02/F10의 새 계획이다.

| 단계 | 목표 | 상태 | 구현 C / 증거 E / 종료 D | 선행·제약 |
|---|---|---|---|---|
| [1.2.0-P1](01-permissions-settings.md) | B01·B02·B09·B14 권한·설정 | DONE | C `1f47eff1e20a1b5bda770a9f0d22255555baf402` / E [`f26c60c`](https://github.com/parking-place/YoYackBot/commit/f26c60c75ae8f37cd56655fd675fc53c94ba9186) | PR #44 main 통합 `b987a17`, [E CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/36992669254), 종료 D push 확인 |
| [1.2.0-P2](02-cache-consistency.md) | B03·B04·B06·B07 캐시 정합성 | DONE | C `efefbeba2545dc651da5cf9347691d2cb6784eb5` / E [`5d3a4da`](https://github.com/parking-place/YoYackBot/commit/5d3a4da2fd98cf1105cc5c75cdd5193b63f69e12) | P1 D `3f3997a`, [E CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/36994154698), 종료 D push 확인 |
| [1.2.0-P3](03-worker-memory.md) | B05·B08 worker·메모리 | PLANNED | — | P2 원격 완료 |
| [1.2.0-P4](04-output-runtime.md) | B10~B13 출력·실행 | PLANNED | — | P3 원격 완료 |
| [1.2.0-P5](05-collection-progress.md) | F02 수집 진행·차단 원인 | PLANNED | — | P4 원격 완료 |
| [1.2.0-P6](06-reply-context.md) | F10 범위 안 답글 연결 | PLANNED | — | P5 원격 완료, 모델 8건 평가 |
| [1.2.0-P7](07-integration-release.md) | 통합·복귀·출시 | PLANNED | — | P1~P6 원격 증거, 사용자 Discord 확인 |

검사는 [TEST_MATRIX](TEST_MATRIX.md)의 28개이며 P1·P2 여덟 검사는 LXC에서 PASS이며 P3~P7은 NOT_RUN이다. 계획 파일 작성·이전 계획 머지·버전 디렉터리 이동·계획 PR의 CI 성공은 위 제품 구현 단계의 완료가 아니다.

구현 C → 동일 SHA 검증·증거 E → E CI 성공 확인 → 종료 D → 원격 반영을 단계마다 기록한다. [공통 Git 규칙](../GIT_WORKFLOW.md), [범위 추적](SCOPE_MAP.md), [버전 개요](README.md).
