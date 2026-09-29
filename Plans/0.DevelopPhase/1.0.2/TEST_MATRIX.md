# 1.0.2 검증 목록

계획 게시 시점의 **모든 결과는 NOT_RUN**이다. 구현 전 문서 검사와 실제 LXC·Discord 제품 검증을 섞어 기록하지 않는다. 코드는 개발 LXC에서 검증하며 시험 Discord 확인은 P5 배포 뒤 사용자가 직접 입력한다. 안내 기능은 프롬프트를 바꾸지 않으므로 실제 모델 평가는 필수가 아니다.

| 검사 ID | 단계 | 환경 | 통과 기준 | 결과 |
|---|---|---|---|---|
| `T102-P1-A` | [P1](01-range-contract.md) | LXC 합성 | 기본·모든 옵션 × 모드의 표시값·두 안내 문장, 10·30일 허용과 31일/낮은 설정 거부 회귀 | PASS — [증거](../evidence/1.0.2-P1.md) |
| `T102-P1-B` | [P1](01-range-contract.md) | LXC 격리 DB | 초기 수집·누락 재확인·완료 안내 미게시는 준비 중, 준비 완료만 입장 경로; 운영 실효 상한 기록 | PASS — [증거](../evidence/1.0.2-P1.md) |
| `T102-P2-A` | [P2](02-active-scope.md) | LXC 합성 | 원자적 입장·첫 요청 범위 스냅샷·동일 채널 20건/타 Guild 분리 | PASS — [증거](../evidence/1.0.2-P2.md) |
| `T102-P2-B` | [P2](02-active-scope.md) | LXC 합성 | 성공·빈 결과·실패·한도 초과·취소·재시작 후 범위 정리와 쿨타임 보존 | PASS — [증거](../evidence/1.0.2-P2.md) |
| `T102-P3-A` | [P3](03-collection-notice.md) | LXC 합성 | 준비 완료 채널의 모든 입장 요청에 조회 직전 정확히 한 번의 시작 안내, 후속 안내 순서 | PASS — [증거](../evidence/1.0.2-P3.md) |
| `T102-P3-B` | [P3](03-collection-notice.md) | LXC 합성 | 미주시·준비 중(초기 수집·재확인)·옵션 오류·쿨타임·종료·전송 실패에 허위 시작 안내·조회 없음 | PASS — [증거](../evidence/1.0.2-P3.md) |
| `T102-P4-A` | [P4](04-busy-notice.md) | LXC 합성 | `10일` 활성 중 `5분` 중복에 정확한 두 줄, 첫 안내 선행, 단일 작업 | NOT_RUN |
| `T102-P4-B` | [P4](04-busy-notice.md) | LXC 합성 | 시작 안내 전송·조회·대기·모델·게시·종료 경계의 활성 범위와 채널/Guild 분리 | NOT_RUN |
| `T102-P5-A` | [P5](05-integration-release.md) | LXC/CI | 전체 옵션·1.0.1 명령·준비 상태 경계·도움말·보안·쿨타임·패키지 회귀 | NOT_RUN |
| `T102-P5-B` | [P5](05-integration-release.md) | LXC/시험 Discord | 동일 SHA의 시작/진행 중 게시·순서(사용자 확인+로그), 배포/복구 및 원격 증거 | NOT_RUN |

각 단계의 A/B 결과, 구현 C·증거 E·종료 D의 GitHub 반영과 필요한 CI가 확인돼야 [상태 문서](STATUS.md)를 DONE으로 변경한다. 실제 Discord 게시가 미실행이면 해당 항목은 `NOT_RUN`이다. 사용자 요청에 따라 8시간·24시간 연속 관측은 이 버전의 필수 검사에 포함하지 않는다.
