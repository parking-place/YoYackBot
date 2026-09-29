# 1.0.1 검증 목록

계획 게시 시점에는 **모든 검사가 NOT_RUN**이다. 합성 대역, 실제 모델, 실제 Discord, 운영 반영을 서로 다른 증거로 기록한다. 코드·모델·DB·Discord를 실행하는 검사는 개발 LXC에서 수행한다. 8시간·24시간 연속 시험은 사용자 요청에 따라 이 버전의 검사 항목이 아니다.

| 검사 ID | 단계 | 환경 | 통과 기준 | 결과 |
|---|---|---|---|---|
| `T101-P1-A` | [P1](01-app-server-contract.md) | LXC 합성 | app-server JSON 버킷·창·남은 비율 경계와 누락/오류 처리의 결정성 | NOT_RUN |
| `T101-P1-B` | [P1](01-app-server-contract.md) | LXC 읽기 전용 | 실제 봇 계정 응답·고정 CLI 호환, 비밀 비노출·자식 정리·비게시 | NOT_RUN |
| `T101-P2-A` | [P2](02-usage-command.md) | LXC 합성 | 사용량 문구 74/82·74/9·10%·0%, 실패·미주시 라우팅 | NOT_RUN |
| `T101-P2-B` | [P2](02-usage-command.md) | LXC/시험 Discord | 진짜 한도 초과만 확정 안내, 일시 오류 분리, 실패 후 재시도, 실제 사용량 표시 | NOT_RUN |
| `T101-P3-A` | [P3](03-detailed-summary.md) | LXC 합성 | 기본 명령과 동일한 1시간 수집·권한·명령 제외 | NOT_RUN |
| `T101-P3-B` | [P3](03-detailed-summary.md) | LXC 실제 모델 | 화자·결정·미해결점 사실성 및 하오체의 사람 검토, 쿨타임 회귀 | NOT_RUN |
| `T101-P4-A` | [P4](04-short-summary.md) | LXC 합성 | 기본 명령과 동일한 1시간 수집, 잘못된 결합 입력 거부 | NOT_RUN |
| `T101-P4-B` | [P4](04-short-summary.md) | LXC 실제 모델 | 본문 4~6줄 목표·중요 사실 보존·화자 귀속의 사람 검토 | NOT_RUN |
| `T101-P5-A` | [P5](05-status-command.md) | LXC 격리 DB | 현재 Guild 수치·실제 설정·마지막 성공 시각·재시작 정확성 | NOT_RUN |
| `T101-P5-B` | [P5](05-status-command.md) | LXC/시험 Discord | 장애 시 허위 정상 없음, 읽기 전용, 비밀·타 Guild 비노출 | NOT_RUN |
| `T101-P6-A` | [P6](06-help-release.md) | LXC/CI | 도움말·명령 회귀·버전·문서·SHA 일치 | NOT_RUN |
| `T101-P6-B` | [P6](06-help-release.md) | LXC/시험 Discord/운영 | 같은 SHA의 짧은 기능 점검·배포/롤백 증거·이전 5단계 원격 증거 | NOT_RUN |

각 단계가 위 A/B 검사를 만족하고, [공통 Git 완료 규칙](../GIT_WORKFLOW.md)의 구현 C·증거 E·종료 D를 원격에서 확인해야 [1.0.1 상태](STATUS.md)를 DONE으로 바꿀 수 있다. 실제 계정 한도 소진은 고의로 유발하지 않으며 해당 오류 분류는 합성 실패 주입으로 확인한다. 실사용 한도 초과 관찰은 별도 `NOT_RUN` 한계로 기록한다.
