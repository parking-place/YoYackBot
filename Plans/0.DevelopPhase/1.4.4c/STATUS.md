# 1.4.4c 진행 상태

기준일: 2026-10-28. **2/2단계 완료, `v1.4.4c` 출시.** 기준은 `v1.4.4b`(`419764b`, `main` 병합 `62e1c4f`)이며 브랜치는 `develop/1.4.4c`이다.

| 단계 | 목표 | 상태 | 구현 C / 증거 E / 종료 D | 선행·제약 |
|---|---|---|---|---|
| [1.4.4c-P1](01-diet-effort.md) | 식단 호출 강도 고정 | DONE | C `fad6ddff3444bfcdb907d97edfa5494ddfbff200` / E [`0a78d8d`](https://github.com/parking-place/YoYackBot/commit/0a78d8de7f18bd7391403ad9fd26ed4720e5e3d6) | 기준 `v1.4.4b`, [C CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/40640214040), [E CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/40640393605), 종료 D push 확인 |
| [1.4.4c-P2](02-release.md) | 통합·배포·출시 | DONE | C `2e71278a9f2c7e561498b9f95236fd0a0104d164` / E [`f7a58b3`](https://github.com/parking-place/YoYackBot/commit/f7a58b388d33dbd1e9e0e9bee4a56483238a55be) | P1 D `8bcaa76`, [C CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/40640660254), 태그 `v1.4.4c`·[Release](https://github.com/parking-place/YoYackBot/releases/tag/v1.4.4c), 사용자 출시 지시 2026-10-28, [E CI 성공](https://github.com/parking-place/YoYackBot/actions/runs/40641657606), 종료 D push 확인 |

[버전 개요](README.md) · [공통 Git 규칙](../GIT_WORKFLOW.md)
