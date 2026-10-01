# 1.1.2a 검증 목록

계획 게시 시점의 **모든 결과는 NOT_RUN**이다. 코드는 개발 LXC에서 검증한다. 실제 모델 호출은 없으며, 시험 Discord 확인은 P3 배포 뒤 사용자가 직접 한다.

| 검사 ID | 단계 | 환경 | 통과 기준 | 결과 |
|---|---|---|---|---|
| `T112a-P1-A` | [P1](01-command-permission.md) | LXC 합성 | 관리자·채널 관리·권한 플래그 없는 허용 사용자 모두 열기·저장 가능, DM 거절, 등록 기본 권한·`guild_only` 유지 | NOT_RUN |
| `T112a-P1-B` | [P1](01-command-permission.md) | LXC 합성 | 다른 사람·다른 서버 조작 거절, 저장 검증·동시 수정·제한 시간 유지, 지표에 사용자 ID 없음, 회귀 | NOT_RUN |
| `T112a-P2-A` | [P2](02-help-docs.md) | LXC 합성 | 도움말·빈 목록 안내 새 문구, “관리자가 `/채널 설정`” 문구 없음, 2,000자 미만 | NOT_RUN |
| `T112a-P2-B` | [P2](02-help-docs.md) | LXC/CI | 채널 설정 문서·저장소 검증·비밀 검사·회귀 | NOT_RUN |
| `T112a-P3-A` | [P3](03-release.md) | LXC/CI | 전체 회귀, 도움말·버전·문서·SHA 일치 | NOT_RUN |
| `T112a-P3-B` | [P3](03-release.md) | LXC/시험 Discord | 배포·복귀, 연동 설정으로 허용한 비관리자 사용 확인, 미허용자 비노출, 로그, 병합 후 `main` CI | NOT_RUN |

각 단계의 A/B 결과와 구현 C·증거 E·종료 D의 GitHub 반영, 필요한 CI 성공이 확인돼야 [상태 문서](STATUS.md)를 DONE으로 바꾼다.
