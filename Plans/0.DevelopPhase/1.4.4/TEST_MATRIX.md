# 1.4.4 검증 목록

총 **5단계·10검사**, 계획 게시 시점의 **모든 결과는 NOT_RUN**이다. 기준은 `v1.4.3a`(`4e4933d`)이다.

| 검사 ID | 단계 | 환경 | 통과 기준 | 결과 |
|---|---|---|---|---|
| `T144-P1-A` | [P1](01-exercise-settings.md) | LXC 합성 | 운동 명령·권한·저장·기본값·백업 | PASS |
| `T144-P1-B` | [P1](01-exercise-settings.md) | LXC 합성 | 일간 기록·주간 조회·정리, 주 1회 기록, 문구 목록, 회귀 | PASS |
| `T144-P2-A` | [P2](02-daily-tally.md) | LXC 합성 | 운동 입력(같은/다른 채널), JSON 해석·검사·재작성, 정산 줄 모양 | PASS |
| `T144-P2-B` | [P2](02-daily-tally.md) | LXC 합성 | 일간 기록 저장, 멘션 없음, 로그, 회귀 | PASS |
| `T144-P3-A` | [P3](03-weekly-advice.md) | LXC 합성 | 일요일·주 1회, 사람 목록, 평균·날 수, 텍스트만 | PASS |
| `T144-P3-B` | [P3](03-weekly-advice.md) | LXC 합성 | 훈수 해석·검사·실패, 게시 모양·멘션 없음, 기록 없는 사람, 회귀 | PASS |
| `T144-P4-A` | [P4](04-evaluation.md) | LXC 실제 모델 | 숫자 범위·방향, 운동 정산, 근거 있는 구체적 훈수, 금지선 0 | PASS |
| `T144-P4-B` | [P4](04-evaluation.md) | LXC 실제 모델 | 사용자 예시 확인 | PASS |
| `T144-P5-A` | [P5](05-release.md) | LXC/CI | 전체 회귀·버전·문서·5/10 집계, 복귀 호환 | PASS |
| `T144-P5-B` | [P5](05-release.md) | LXC/시험 Discord | 배포·명령 동기화, 사용자 확인, main CI, 태그·Release | PASS |
