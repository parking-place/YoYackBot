# 1.0.2 검증 목록

계획 게시 시점의 **모든 결과는 NOT_RUN**이다. 구현 전 문서 검사와 실제 LXC·Discord 제품 검증을 섞어 기록하지 않는다. 코드는 개발 LXC에서 검증하며 시험 Discord에는 합성 대화만 쓴다.

| 검사 ID | 단계 | 환경 | 통과 기준 | 결과 |
|---|---|---|---|---|
| `T102-P1-A` | [P1](01-range-contract.md) | LXC 합성 | 10·28일 허용, 29일/낮은 설정 거부, 기본·모든 옵션의 안전한 표시값 | NOT_RUN |
| `T102-P1-B` | [P1](01-range-contract.md) | LXC 격리 DB | 10일 범위의 7일 초과 History 보충과 최대 7일 영속 보존 | NOT_RUN |
| `T102-P2-A` | [P2](02-active-scope.md) | LXC 합성 | 원자적 입장·첫 요청 범위 스냅샷·동일 채널 20건/타 Guild 분리 | NOT_RUN |
| `T102-P2-B` | [P2](02-active-scope.md) | LXC 합성 | 성공·빈 결과·실패·취소·재시작 후 범위 정리와 쿨타임 보존 | NOT_RUN |
| `T102-P3-A` | [P3](03-collection-notice.md) | LXC 합성 | 수집 직전 정확한 한 번의 시작 안내, 빈 결과·실패 시 후속 순서 | NOT_RUN |
| `T102-P3-B` | [P3](03-collection-notice.md) | LXC 합성 | 미주시·오류·대기·전송 실패에 허위 시작/실제 수집 없음 | NOT_RUN |
| `T102-P4-A` | [P4](04-busy-notice.md) | LXC 합성 | `10일` 활성 중 `5분` 중복에 정확한 두 줄, 첫 안내 선행, 단일 작업 | NOT_RUN |
| `T102-P4-B` | [P4](04-busy-notice.md) | LXC 합성 | 수집·대기·모델·게시·종료 경계의 활성 범위와 채널/Guild 분리 | NOT_RUN |
| `T102-P5-A` | [P5](05-integration-release.md) | LXC/CI | 전체 옵션·1.0.1 명령·도움말·보안·쿨타임·패키지 회귀 | NOT_RUN |
| `T102-P5-B` | [P5](05-integration-release.md) | LXC/시험 Discord | 동일 SHA의 실제 시작/중복 게시·순서, 배포/복구 및 원격 증거 | NOT_RUN |

각 단계의 A/B 결과, 구현 C·증거 E·종료 D의 GitHub 반영과 필요한 CI가 확인돼야 [상태 문서](STATUS.md)를 DONE으로 변경한다. 실제 Discord 게시가 미실행이면 해당 항목은 `NOT_RUN`이다. 사용자 요청에 따라 8시간·24시간 연속 관측은 이 버전의 필수 검사에 포함하지 않는다.
