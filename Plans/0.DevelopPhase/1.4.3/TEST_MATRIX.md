# 1.4.3 검증 목록

총 **5단계·10검사**, 계획 게시 시점의 **모든 결과는 NOT_RUN**이다. 기준은 `v1.4.2a`(`54b3fbc`)이다.

| 검사 ID | 단계 | 환경 | 통과 기준 | 결과 |
|---|---|---|---|---|
| `T143-P1-A` | [P1](01-diet-settings.md) | LXC 합성 | 명령·권한·고르기·해제·저장·연 사람·시간 제한·권한 경고 | PASS |
| `T143-P1-B` | [P1](01-diet-settings.md) | LXC 합성 | `members` intent, 테이블·백업·정리, 문구 목록, 회귀 | PASS |
| `T143-P2-A` | [P2](02-diet-schedule.md) | LXC 합성 | 시각(KST), 올림 판정, 개별 호출·생략, 멘션 허용 범위 | PASS |
| `T143-P2-B` | [P2](02-diet-schedule.md) | LXC 합성 | 한 번만·유예·건너뜀, 설정·권한·채널 문제, 로그, 회귀 | PASS |
| `T143-P3-A` | [P3](03-diet-judge.md) | LXC 합성 | 입력 제한, `--image`·읽기 전용 연결·삭제, 서버 말투 | PASS |
| `T143-P3-B` | [P3](03-diet-judge.md) | LXC 합성 | 해석·형식, 검사·재작성·실패, 아무도 안 올림, 멘션 없음, 로그, 회귀 | PASS |
| `T143-P4-A` | [P4](04-evaluation.md) | LXC 실제 모델 | 사진 반영·검사 통과·금지선 0·사람 수·시간, 말투 2종 | PASS |
| `T143-P4-B` | [P4](04-evaluation.md) | LXC 실제 모델 | 사용자 예시 확인 | 사용자 확인 대기 |
| `T143-P5-A` | [P5](05-release.md) | LXC/CI | 전체 회귀·버전·문서·5/10 집계, 복귀 호환 | NOT_RUN |
| `T143-P5-B` | [P5](05-release.md) | LXC/시험 Discord | 포털 intent·배포·명령 동기화, 사용자 확인, main CI, 태그·Release | NOT_RUN |
