# 1.1.2a 검증 목록

계획 게시 시점의 **모든 결과는 NOT_RUN**이다. 코드는 개발 LXC에서 검증한다. 실제 모델 호출은 P4에서만 계약의 건수(6건) 안에서 하며, 시험 Discord 확인은 P5 배포 뒤 사용자가 직접 한다.

| 검사 ID | 단계 | 환경 | 통과 기준 | 결과 |
|---|---|---|---|---|
| `T112a-P1-A` | [P1](01-command-permission.md) | LXC 합성 | 권한 플래그 없는 사용자도 열기·저장, DM 거절, 모든 명령어가 서버 전용·기본 권한 `use_application_commands` | PASS — [증거](../evidence/1.1.2a-P1.md) |
| `T112a-P1-B` | [P1](01-command-permission.md) | LXC 합성 | 다른 사람·다른 서버 조작 거절, 저장 검증·동시 수정·제한 시간 유지, 지표는 시각·채널 수만, 회귀 | PASS — [증거](../evidence/1.1.2a-P1.md) |
| `T112a-P2-A` | [P2](02-markdown-prompt.md) | LXC 합성 | `###` 제목·인용 비평 `> ↳ _…_`·`__이름__`·굵게·취소선 규칙, 옛 형식 지시 없음, 합성 형식 예 | NOT_RUN |
| `T112a-P2-B` | [P2](02-markdown-prompt.md) | LXC 합성 | 1순위·추가 요청·진행 중·평가 줄·이모지 규칙 회귀 | NOT_RUN |
| `T112a-P3-A` | [P3](03-output-checks.md) | LXC 합성 | `> ↳` 비평 줄 검사, `###`·`> ↳` 주제 지표, `name_underline` 판정 | NOT_RUN |
| `T112a-P3-B` | [P3](03-output-checks.md) | LXC 합성 | 이모지 제거·평가 줄·거절 안내·분할이 마크다운을 깨지 않음, 지표 원문 비기록, 회귀 | NOT_RUN |
| `T112a-P4-A` | [P4](04-help-evaluation.md) | LXC/CI | 도움말이 문안과 같음(설정값별), 2,000자 미만, 도움말·빈 목록 안내에 “관리자” 문구 없음, 문서 갱신 | NOT_RUN |
| `T112a-P4-B` | [P4](04-help-evaluation.md) | LXC 실제 모델 | 6건 사실 오류 0, `###` 제목, 인용 비평, 이름 밑줄, 깨진 마크다운 0, 1.1.2 형식 유지, 사용자 확인 | NOT_RUN |
| `T112a-P5-A` | [P5](05-release.md) | LXC/CI | 전체 회귀, 도움말·버전·문서·SHA 일치 | NOT_RUN |
| `T112a-P5-B` | [P5](05-release.md) | LXC/시험 Discord | 배포·복귀, 비관리자 `/채널 설정` 사용 확인, 마크다운·밑줄·도움말 확인, 로그, 병합 후 `main` CI | NOT_RUN |

각 단계의 A/B 결과와 구현 C·증거 E·종료 D의 GitHub 반영, 필요한 CI 성공이 확인돼야 [상태 문서](STATUS.md)를 DONE으로 바꾼다.
