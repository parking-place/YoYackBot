# 1.1.3 검증 목록

계획 게시 시점의 **모든 결과는 NOT_RUN**이다. 코드는 개발 LXC에서 검증한다. 실제 모델 호출은 없으며, 시험 Discord 확인은 P3 배포 뒤 사용자가 직접 한다.

| 검사 ID | 단계 | 환경 | 통과 기준 | 결과 |
|---|---|---|---|---|
| `T113-P1-A` | [P1](01-manager-roles.md) | LXC 합성 | 판정 표 전 칸(관리자·채널 관리·관리 역할·없음·DM), 조작 중 역할 상실 거절, 모든 명령어가 공통 판정 | PASS — [증거](../evidence/1.1.3-P1.md) |
| `T113-P1-B` | [P1](01-manager-roles.md) | LXC 합성 | 서버별 저장·동시 수정, schema 5 유지·`v1.1.2a` 읽기, 백업·복원 왕복·이전 백업 호환, 운영 명령, 회귀 | PASS — [증거](../evidence/1.1.3-P1.md) |
| `T113-P2-A` | [P2](02-role-command.md) | LXC 합성 | 관리자·관리 역할이 역할 설정·저장, 저장된 역할 사용자의 `/채널 설정` 허용·제거 시 거절 | PASS — [증거](../evidence/1.1.3-P2.md) |
| `T113-P2-B` | [P2](02-role-command.md) | LXC 합성 | `@everyone`·managed·없는 역할 거절, 다른 사람·서버·동시 수정·만료, 로그 시각·역할 수만, 회귀 | PASS — [증거](../evidence/1.1.3-P2.md) |
| `T113-P3-A` | [P3](03-release.md) | LXC/CI | 전체 회귀, 도움말 새 줄(2,000자 미만), 버전·문서·SHA 일치 | NOT_RUN |
| `T113-P3-B` | [P3](03-release.md) | LXC/시험 Discord | 배포·복귀, 일반 계정 거절·역할 지정·역할 계정 허용 확인, 로그, 병합 후 `main` CI | NOT_RUN |

각 단계의 A/B 결과와 구현 C·증거 E·종료 D의 GitHub 반영, 필요한 CI 성공이 확인돼야 [상태 문서](STATUS.md)를 DONE으로 바꾼다.
