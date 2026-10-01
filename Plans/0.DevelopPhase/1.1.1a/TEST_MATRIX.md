# 1.1.1a 검증 목록

계획 게시 시점에는 모든 결과가 NOT_RUN이었고, 아래 결과는 각 단계 증거를 따른다. 코드는 개발 LXC에서 검증한다. 실제 모델 호출은 P3에서만 계약의 건수 안에서 하며, 시험 Discord 확인은 P4 배포 뒤 사용자가 직접 입력한다.

| 검사 ID | 단계 | 환경 | 통과 기준 | 결과 |
|---|---|---|---|---|
| `T111a-P1-A` | [P1](01-ongoing-prompt.md) | LXC 합성 | 진행 중 원칙·새 묶음 이름·금지 소재 문장 존재, 옛 조롱 예·`아직 안 정해진 거`·`미정` 표시 없음 | PASS — [증거](../evidence/1.1.1a-P1.md) |
| `T111a-P1-B` | [P1](01-ongoing-prompt.md) | LXC 합성 | 1순위 규칙·추가 요청 우선·인용·평가 빼기·기존 검사 회귀 | PASS — [증거](../evidence/1.1.1a-P1.md) |
| `T111a-P2-A` | [P2](02-ongoing-check.md) | LXC 합성 | 미결 조롱 표현 감지, 인용·`>`·코드 제외, 평범한 문장 오탐 0 | PASS — [증거](../evidence/1.1.1a-P2.md) |
| `T111a-P2-B` | [P2](02-ongoing-check.md) | LXC 합성 | 본문·평가 줄 재생성 분기, `retried_left` 게시, 호출 3번 이하, 원문 비기록 | PASS — [증거](../evidence/1.1.1a-P2.md) |
| `T111a-P3-A` | [P3](03-evaluation.md) | LXC 실제 모델 | 12건 사실·화자·결정/진행 중 분류 오류 0, 지어낸 항목 0, 금지선 0 | PASS — [증거](../evidence/1.1.1a-P3.md) |
| `T111a-P3-B` | [P3](03-evaluation.md) | LXC 실제 모델 | 서술자 미결 조롱 0, 새 표시 이름, 비아냥·평가 줄·하오체 유지, 사용자 확인 | PASS — [증거](../evidence/1.1.1a-P3.md) |
| `T111a-P4-A` | [P4](04-release.md) | LXC/CI | 전체 회귀, 도움말·버전·문서·SHA 일치 | PASS — [증거](../evidence/1.1.1a-P4.md) |
| `T111a-P4-B` | [P4](04-release.md) | LXC/시험 Discord | 배포·복귀, 사용자 확인+로그, P1~P3 원격 증거, 병합 후 `main` CI | PASS(사용자 확인+로그, 복귀는 격리; 길게 실제 채널 NOT_RUN) — [증거](../evidence/1.1.1a-P4.md) |

각 단계의 A/B 결과와 구현 C·증거 E·종료 D의 GitHub 반영, 필요한 CI 성공이 확인돼야 [상태 문서](STATUS.md)를 DONE으로 바꾼다. 8시간·24시간 연속 관측은 필수 검사가 아니다.
