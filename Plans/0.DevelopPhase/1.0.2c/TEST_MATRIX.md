# 1.0.2c 검증 목록

계획 게시 시점에는 모든 결과가 NOT_RUN이었고, 아래 결과는 각 단계 증거를 따른다. 코드는 개발 LXC에서 검증한다. 실제 모델 호출은 P3에서만 계약의 건수 안에서 하며, 시험 Discord 확인은 P4 배포 뒤 사용자가 직접 입력한다.

| 검사 ID | 단계 | 환경 | 통과 기준 | 결과 |
|---|---|---|---|---|
| `T102c-P1-A` | [P1](01-cooldown.md) | LXC 합성 | 고정 시계로 1분 경계·환경 변수 존중·성공에만 쿨타임 | PASS — [증거](../evidence/1.0.2c-P1.md) |
| `T102c-P1-B` | [P1](01-cooldown.md) | LXC 격리 DB | 5분 기록의 남은 시간 60초 상한·재시작 후 동일·schema 불변 | PASS — [증거](../evidence/1.0.2c-P1.md) |
| `T102c-P2-A` | [P2](02-tone-prompt.md) | LXC 합성 | 세 모드·재시도 프롬프트의 말투·금지선·우선순위, 안내 문구 불변 | PASS — [증거](../evidence/1.0.2c-P2.md) |
| `T102c-P2-B` | [P2](02-tone-prompt.md) | LXC 합성 | 혐오 비하어 탐지 재시도·안전 실패, 허용 비속어·인용 오탐 없음, 쿨타임·상태 유지 | PASS — [증거](../evidence/1.0.2c-P2.md) |
| `T102c-P3-A` | [P3](03-tone-evaluation.md) | LXC 실제 모델 | 필수 사실·금지 사실·화자 귀속·지어낸 인용·둔갑 0 | PASS(v1 9건·v2 3건) — [증거](../evidence/1.0.2c-P3.md) |
| `T102c-P3-B` | [P3](03-tone-evaluation.md) | LXC 실제 모델 | 비속어 섞인 몸통·하오체 말끝, 사람 성적 묘사·혐오 비하어·인신공격 0, 짧게 줄 수, 사용자 확인 | v1 FAIL(모델 순화) → v2 PASS(사용자 수용 수준) — [증거](../evidence/1.0.2c-P3.md) |
| `T102c-P4-A` | [P4](04-release.md) | LXC/CI | 전체 회귀, 도움말·버전·문서·SHA 일치 | PASS — [증거](../evidence/1.0.2c-P4.md) |
| `T102c-P4-B` | [P4](04-release.md) | LXC/시험 Discord | 배포·복귀, 사용자 확인+로그 대조, P1~P3 원격 증거, 병합 후 `main` CI | PASS(사용자 확인+로그, 복귀는 격리; 1분 뒤 입장 실제 확인 NOT_RUN) — [증거](../evidence/1.0.2c-P4.md) |

각 단계의 A/B 결과와 구현 C·증거 E·종료 D의 GitHub 반영, 필요한 CI 성공이 확인돼야 [상태 문서](STATUS.md)를 DONE으로 바꾼다. 8시간·24시간 연속 관측은 필수 검사가 아니다.
