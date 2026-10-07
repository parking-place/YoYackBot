# 1.4.0 검증 목록

총 **7단계·15검사**, 계획 게시 시점의 **모든 결과는 NOT_RUN**이다. 기준은 `v1.3.4`(`1491025`)이다.

| 검사 ID | 단계 | 환경 | 통과 기준 | 결과 |
|---|---|---|---|---|
| `T140-P1-A` | [P1](01-execution-settings.md) | LXC 합성 | 설정 권한·채널 하나·역할 선택·화면 규칙 | PASS |
| `T140-P1-B` | [P1](01-execution-settings.md) | LXC 합성 | 정리·백업·로그·회귀 | PASS |
| `T140-P2-A` | [P2](02-audit-log.md) | LXC 합성 | 적용·연장·해제 판별, 로그 형식·알림 없음, 미설정 0건 | PASS |
| `T140-P2-B` | [P2](02-audit-log.md) | LXC 합성 | 봇 실행분 처형자 대체·중복 없음, 실패 처리, 사유 비기록, 권한 없음, 회귀 | PASS |
| `T140-P3-A` | [P3](03-execute-command.md) | LXC 합성 | 기본값·시간 형식·허용 범위·성공 경로 | NOT_RUN |
| `T140-P3-B` | [P3](03-execute-command.md) | LXC 합성 | 권한 상승 방지·봇 권한·오류·로그 처형자, 회귀 | NOT_RUN |
| `T140-P4-A` | [P4](04-tone-split.md) | LXC 합성 | 고정 규칙·말투 단락 분리, 기본값 = 현행 | NOT_RUN |
| `T140-P4-B` | [P4](04-tone-split.md) | LXC 합성 | `/말투` 표시 범위, 저장 말투 호환, 격리, 회귀 | NOT_RUN |
| `T140-P5-A` | [P5](05-tone-notices.md) | LXC 합성 | 목록·생성·검증·저장·되돌리기 | NOT_RUN |
| `T140-P5-B` | [P5](05-tone-notices.md) | LXC 합성 | 전송 지점 적용·서버 분리·실패 시 기본·알림·로그·백업, 회귀 | NOT_RUN |
| `T140-P6-A` | [P6](06-evaluation.md) | LXC 실제 모델 | 기본 말투 품질 = `v1.3.4` 수준 | NOT_RUN |
| `T140-P6-B` | [P6](06-evaluation.md) | LXC 실제 모델 | 서버 말투 반영·고정 규칙 유지 | NOT_RUN |
| `T140-P6-C` | [P6](06-evaluation.md) | LXC 실제 모델 | 안내 문구 생성 품질·검증, 사용자 예시 확인 | NOT_RUN |
| `T140-P7-A` | [P7](07-release.md) | LXC/CI | 회귀·버전·문서·7/15 집계, 복귀 호환 | NOT_RUN |
| `T140-P7-B` | [P7](07-release.md) | LXC/시험 Discord | 배포·intent·사용자 확인, main CI, 태그·Release | NOT_RUN |
