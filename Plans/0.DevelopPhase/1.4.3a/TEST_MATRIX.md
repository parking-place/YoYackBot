# 1.4.3a 검증 목록

총 **2단계·4검사**, 모두 **PASS**다(계획 게시 시점에는 모두 NOT_RUN, P2-B의 운영 21:00·22:30 확인은 NOT_RUN으로 기록하고 합성 시험으로 갈음). 기준은 `v1.4.3`(`b267c00`)이다.

| 검사 ID | 단계 | 환경 | 통과 기준 | 결과 |
|---|---|---|---|---|
| `T143a-P1-A` | [P1](01-judge-everyone-and-ping.md) | LXC 합성 | 역할 밖 게시자 평가 포함, 개별 호출·안 올린 사람은 역할 인원만, 봇·명령 제외 | PASS |
| `T143a-P1-B` | [P1](01-judge-everyone-and-ping.md) | LXC 합성 | 21:00 역할+개별 멘션·상한, 멘션 허용 범위, 읽기 실패 대체, 회귀 | PASS |
| `T143a-P2-A` | [P2](02-release.md) | LXC/CI | 전체 회귀·버전·문서·2/4 집계, 복귀 호환 | PASS |
| `T143a-P2-B` | [P2](02-release.md) | LXC/시험 Discord | 배포, 사용자 확인, main CI, 태그·Release | PASS |
