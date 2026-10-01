# 1.1.2 검증 목록

계획 게시 시점의 **모든 결과는 NOT_RUN**이다. 코드는 개발 LXC에서 검증한다. 실제 모델 호출은 P3에서만 계약의 건수 안에서 하며, 시험 Discord 확인은 P4 배포 뒤 사용자가 직접 입력한다.

| 검사 ID | 단계 | 환경 | 통과 기준 | 결과 |
|---|---|---|---|---|
| `T112-P1-A` | [P1](01-format-prompt.md) | LXC 합성 | 이모지 규칙, 주제 한줄 비평 정확히 1줄, 짧게만 내용 1~2줄 형식, 길게·자세히 화자 불릿 유지, `이모지 빼고`·`비평 빼줘` 해석 | PASS — [증거](../evidence/1.1.2-P1.md) |
| `T112-P1-B` | [P1](01-format-prompt.md) | LXC 합성 | 1순위 규칙·추가 요청 우선·진행 중 원칙 회귀, 이모지 평가 줄 분리 | PASS(LXC 일시 실패 1회 기록) — [증거](../evidence/1.1.2-P1.md) |
| `T112-P2-A` | [P2](02-format-check.md) | LXC 합성 | `topic_critique` all/partial/none/na 판정, 결정·진행 중 묶음 제외, 원문 비기록 | PASS — [증거](../evidence/1.1.2-P2.md) |
| `T112-P2-B` | [P2](02-format-check.md) | LXC 합성 | 이모지 섞인 출력 분할·멘션 차단·평가 줄 위치, 조롱·비하어 검사 회귀 | PASS — [증거](../evidence/1.1.2-P2.md) |
| `T112-P3-A` | [P3](03-evaluation.md) | LXC 실제 모델 | 16건 사실·화자·분류 오류 0, 미결 조롱 0, 금지선 0, 이모지가 사실 대신 0 | NOT_RUN |
| `T112-P3-B` | [P3](03-evaluation.md) | LXC 실제 모델 | 짧게 2줄 이하 80%+, 주제 비평 90%+, 소제목 이모지 100%, 추가 요청 4건 반영, 사용자 확인 | NOT_RUN |
| `T112-P4-A` | [P4](04-release.md) | LXC/CI | 전체 회귀, 도움말·버전·문서·SHA 일치 | NOT_RUN |
| `T112-P4-B` | [P4](04-release.md) | LXC/시험 Discord | 배포·복귀, 사용자 확인+로그, P1~P3 원격 증거, 병합 후 `main` CI | NOT_RUN |

각 단계의 A/B 결과와 구현 C·증거 E·종료 D의 GitHub 반영, 필요한 CI 성공이 확인돼야 [상태 문서](STATUS.md)를 DONE으로 바꾼다. 8시간·24시간 연속 관측은 필수 검사가 아니다.
