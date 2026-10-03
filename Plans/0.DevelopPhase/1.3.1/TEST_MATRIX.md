# 1.3.1 검증 목록

총 **4단계·8검사**, 계획 게시 시점의 **모든 결과는 NOT_RUN**이다. 기준은 `v1.3.0`(`df159cc`)이다. 코드는 개발 LXC에서 검증하고, 실제 모델 확인은 P4, 시험 Discord 확인은 P4 배포 뒤 사용자가 한다.

| 검사 ID | 단계 | 환경 | 통과 기준 | 결과 |
|---|---|---|---|---|
| `T131-P1-A` | [P1](01-idiom-cooldown.md) | LXC 합성 | 시작 안내 없이 결과 한 줄, 다른 안내 문구 불변, 실패 시 쿨타임 없음 | PASS |
| `T131-P1-B` | [P1](01-idiom-cooldown.md) | LXC 합성 | 요약·`!!말하자면` 쿨타임 분리·재시작 유지·BUSY 공유, 정리·백업 제외, 회귀 | PASS |
| `T131-P2-A` | [P2](02-help-command.md) | LXC 합성 | `/도움말` 누구나·ephemeral·본문 동일·`/속도` 미표시 | NOT_RUN |
| `T131-P2-B` | [P2](02-help-command.md) | LXC 합성 | `!!요약좀 도움` 한 줄 안내, 비주시 채널, 안내 문구의 `/도움말`, 로그, 회귀 | NOT_RUN |
| `T131-P3-A` | [P3](03-speed-command.md) | LXC 합성 | 켠 서버의 모든 호출에만 `service_tier="priority"`, 다른 옵션 불변, 읽기 실패 시 보통 | NOT_RUN |
| `T131-P3-B` | [P3](03-speed-command.md) | LXC 합성 | 권한·소유·만료·문구, 기본 끔, 탈퇴 정리, 백업·복원, 로그·지표, 도움말 미표시, 회귀 | NOT_RUN |
| `T131-P4-A` | [P4](04-release.md) | LXC 실제 모델/CI | 보통/빠른 모드 요약·`!!말하자면` 성공·형식·소요 시간, 전체 회귀·버전·문서·4/8 집계 | NOT_RUN |
| `T131-P4-B` | [P4](04-release.md) | LXC/시험 Discord | 배포·1.3.0 복귀·재업그레이드·고아 정리, 사용자 확인, P1~P3 원격 증거, main CI | NOT_RUN |

각 단계의 A/B와 구현 C 검증, 증거 E의 GitHub 반영·CI 성공 후 [상태 문서](STATUS.md)에 DONE을 기록하는 종료 D를 만든다.
