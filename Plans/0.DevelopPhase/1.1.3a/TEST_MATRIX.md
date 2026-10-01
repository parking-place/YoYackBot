# 1.1.3a 검증 목록

계획 게시 시점의 **모든 결과는 NOT_RUN**이다. 코드는 개발 LXC에서 검증한다. 실제 모델 호출은 없으며, 시험 Discord 확인은 P3 배포 뒤 사용자가 직접 한다.

| 검사 ID | 단계 | 환경 | 통과 기준 | 결과 |
|---|---|---|---|---|
| `T113a-P1-A` | [P1](01-command-replies.md) | LXC 합성 | 사용량·상태·채널 목록 출력이 계약 예와 글자 단위 일치(경우별) | PASS — [증거](../evidence/1.1.3a-P1.md) |
| `T113a-P1-B` | [P1](01-command-replies.md) | LXC 합성 | 메시지 나눔·이스케이프·멘션 차단 유지, 묶음 1~3 문구 목록 시험, 회귀 | PASS — [증거](../evidence/1.1.3a-P1.md) |
| `T113a-P2-A` | [P2](02-notices.md) | LXC 합성 | 묶음 4~13 문구 고정, 시작·진행 중 조합·쿨타임·요약 머리말 경우별, `/관리권한 설정` 거절 문구 수정 | NOT_RUN |
| `T113a-P2-B` | [P2](02-notices.md) | LXC 합성 | 문구 목록 시험 전체, 중복 문구 정리, 요약 나눔·평가 줄·멘션 차단 유지, 회귀 | NOT_RUN |
| `T113a-P3-A` | [P3](03-release.md) | LXC/CI | 전체 회귀, 버전·문서·SHA 일치 | NOT_RUN |
| `T113a-P3-B` | [P3](03-release.md) | LXC/시험 Discord | 배포·복귀, 사용자 확인+로그, P1~P2 원격 증거, 병합 후 `main` CI | NOT_RUN |

각 단계의 A/B 결과와 구현 C·증거 E·종료 D의 GitHub 반영, 필요한 CI 성공이 확인돼야 [상태 문서](STATUS.md)를 DONE으로 바꾼다.
