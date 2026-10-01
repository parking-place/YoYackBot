# 1.1.2a 검증 목록

계획 게시 시점의 **모든 결과는 NOT_RUN**이다. 코드는 개발 LXC에서 검증한다. 실제 모델 호출은 P3에서만 계약의 건수 안에서 하며, 시험 Discord 확인은 P4 배포 뒤 사용자가 직접 한다.

| 검사 ID | 단계 | 환경 | 통과 기준 | 결과 |
|---|---|---|---|---|
| `T112a-P1-A` | [P1](01-command-permission.md) | LXC 합성 | 권한 플래그 없는 사용자도 열기·저장, DM 거절, 모든 명령어가 서버 전용·기본 권한 `use_application_commands` | NOT_RUN |
| `T112a-P1-B` | [P1](01-command-permission.md) | LXC 합성 | 다른 사람·다른 서버 조작 거절, 저장 검증·동시 수정·제한 시간 유지, 지표는 시각·채널 수만, 회귀 | NOT_RUN |
| `T112a-P2-A` | [P2](02-nickname-underline.md) | LXC 합성 | 이름 밑줄 정확히 한 번(조사·겹침·굵은 불릿·`사용자 (1)`), 인용·코드·한 글자 낱말 제외, 멱등 | NOT_RUN |
| `T112a-P2-B` | [P2](02-nickname-underline.md) | LXC 합성 | 추가 요청·평가 줄·검사·분할과 함께 동작, 회귀 | NOT_RUN |
| `T112a-P3-A` | [P3](03-help-evaluation.md) | LXC/CI | 도움말이 문안과 같음(설정값별), 2,000자 미만, 문서 갱신 | NOT_RUN |
| `T112a-P3-B` | [P3](03-help-evaluation.md) | LXC 실제 모델 | 6건 이름 밑줄·깨진 Markdown 0·1.1.2 형식 유지, 사용자 확인 | NOT_RUN |
| `T112a-P4-A` | [P4](04-release.md) | LXC/CI | 전체 회귀, 도움말·버전·문서·SHA 일치 | NOT_RUN |
| `T112a-P4-B` | [P4](04-release.md) | LXC/시험 Discord | 배포·복귀, 비관리자 `/채널 설정` 사용 확인, 밑줄·도움말 확인, 로그, 병합 후 `main` CI | NOT_RUN |

각 단계의 A/B 결과와 구현 C·증거 E·종료 D의 GitHub 반영, 필요한 CI 성공이 확인돼야 [상태 문서](STATUS.md)를 DONE으로 바꾼다.
